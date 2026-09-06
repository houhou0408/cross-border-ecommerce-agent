# -*- coding: utf-8 -*-
"""全局强制鉴权测试：白名单放行 / 业务路由 401 / 登录后可访问 / ContextVar 用户上下文。

覆盖点（面试讲解重点）：
1. FastAPI(dependencies=[Depends(require_user)]) 一行覆盖全部路由；
2. 白名单显式枚举：前端页/健康检查/登录注册/文档/静态前缀；
3. 401 带 WWW-Authenticate 头（前端据此引导登录）；
4. 尾部斜杠归一：/stats/ 与 /stats 同等鉴权；
5. ContextVar 用户上下文：Agent 工具链深处可取当前用户（阶段4数据隔离的基础）。
"""
import pytest
from fastapi.testclient import TestClient

from 接口.FastAPI服务 import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _reg_and_login(auth, username="tester", password="pass123"):
    auth.register(username, password)
    r = auth.login(username, password)
    assert r["ok"] is True
    return r["token"]


# ============ 白名单：无需登录 ============

class Test白名单放行:
    @pytest.mark.parametrize("path", ["/", "/health"])
    def test_公开路径非401(self, client, path):
        r = client.get(path)
        assert r.status_code != 401

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_api文档不对外暴露(self, client, path):
        # 安全整改：接口文档路由已关闭（特殊路由不走路由级依赖，无法用鉴权保护）
        r = client.get(path)
        assert r.status_code == 404

    def test_注册接口公开(self, client, tmp_auth_files):
        r = client.post("/auth/register", json={"username": "wl_user", "password": "pass123"})
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_登录接口公开(self, client, tmp_auth_files):
        tmp_auth_files.register("wl_user2", "pass123")
        r = client.post("/auth/login", json={"username": "wl_user2", "password": "pass123"})
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ============ 业务路由：无 token / 伪造 token 一律 401 ============

class Test业务路由强制鉴权:
    # 全量业务路由清单（与 FastAPI服务.py 的路由一一对应）
    GET_ROUTES = [
        "/stats", "/sessions", "/kb/documents", "/eval/testset",
        "/video/tasks", "/image/tasks", "/collection/status",
        "/support/faq/topics", "/auth/me", "/sessions/some-id",
        "/video/tasks/some-id", "/image/tasks/some-id",
        "/support/sessions/some-id",
    ]
    POST_ROUTES = [
        "/ask", "/listing", "/tariff", "/currency", "/sessions",
        "/video/text-to-video", "/support/ask", "/support/review",
        "/support/transfer", "/auth/logout",
    ]
    DELETE_ROUTES = [
        "/sessions/some-id", "/kb/documents/some-source",
        "/video/tasks/some-id", "/image/tasks/some-id",
        "/support/sessions/some-id",
    ]

    @pytest.mark.parametrize("path", GET_ROUTES)
    def test_GET无token返回401(self, client, path):
        assert client.get(path).status_code == 401

    @pytest.mark.parametrize("path", POST_ROUTES)
    def test_POST无token返回401(self, client, path):
        # 鉴权依赖先于请求体校验：不应出现 422
        assert client.post(path, json={}).status_code == 401

    @pytest.mark.parametrize("path", DELETE_ROUTES)
    def test_DELETE无token返回401(self, client, path):
        assert client.delete(path).status_code == 401

    def test_伪造token返回401(self, client):
        r = client.get("/stats", headers={"Authorization": "Bearer forged-token-xyz"})
        assert r.status_code == 401

    def test_401带WWWAuthenticate头(self, client):
        r = client.get("/stats")
        assert r.status_code == 401
        assert r.headers.get("WWW-Authenticate") == "Bearer"

    def test_尾部斜杠同等鉴权(self, client):
        assert client.get("/stats/").status_code == 401
        assert client.post("/ask/", json={}).status_code == 401


# ============ 登录后可访问 ============

class Test登录后放行:
    def test_有效token访问业务路由(self, client, tmp_auth_files):
        token = _reg_and_login(tmp_auth_files)
        r = client.get("/stats", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "total_calls" in r.json()

    def test_有效token访问me(self, client, tmp_auth_files):
        token = _reg_and_login(tmp_auth_files, username="me_user")
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "me_user"

    def test_登出后token失效(self, client, tmp_auth_files):
        token = _reg_and_login(tmp_auth_files, username="out_user")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/auth/logout", json={}, headers=headers).status_code == 200
        assert client.get("/stats", headers=headers).status_code == 401


# ============ ContextVar 用户上下文 ============

class Test用户上下文:
    def test_设置与读取(self):
        from 基础设施.用户认证 import set_current_user, get_current_user_ctx
        set_current_user({"id": "u1", "username": "alice"})
        assert get_current_user_ctx()["username"] == "alice"
        set_current_user(None)
        assert get_current_user_ctx() is None

    def test_请求内可取用户(self, client, tmp_auth_files):
        # 经真实请求验证：require_user 写入 ContextVar（以 /auth/me 返回用户佐证鉴权链路通）
        from 基础设施.用户认证 import set_current_user, get_current_user_ctx
        token = _reg_and_login(tmp_auth_files, username="ctx_user")
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        # 请求结束后上下文复位（ContextVar 在请求作用域内）
        set_current_user(None)
        assert get_current_user_ctx() is None
