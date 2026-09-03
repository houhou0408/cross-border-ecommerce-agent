# -*- coding: utf-8 -*-
"""用户数据隔离测试：会话 / 视频任务 / 卖点图任务，谁创建谁能看，防越权读写删。

覆盖点（面试讲解重点）：
1. 模块级：list 按 user_id 过滤、get/delete 校验归属（MySQL 与 JSON 降级双路径）；
2. ContextVar 用户上下文：任务创建自动带上归属，工具链无需层层传参；
3. API 级：两个真实注册用户，A 的会话/任务对 B 完全不可见、不可删；
4. 越权访问返回业务错误而非 500，且不泄露对方数据是否存在。
"""
import pytest
from fastapi.testclient import TestClient

import 工具集.视频生成 as 视频
import 工具集.卖点图生成 as 卖点图
from 接口.FastAPI服务 import app
from 工具集.用户认证 import set_current_user


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _reg_and_login(auth, username):
    auth.register(username, "pass123")
    r = auth.login(username, "pass123")
    assert r["ok"] is True
    return r["token"], r["user"]["id"]


# ============ 模块级：记忆模块（JSON 降级路径） ============

class Test记忆模块隔离:
    def test_会话列表按用户过滤(self, tmp_memory, db_offline):
        m = tmp_memory.记忆管理器()
        m.create_session("A的会话", user_id="u-a")
        m.create_session("B的会话", user_id="u-b")
        a_ids = [s["id"] for s in m.list_sessions(user_id="u-a")]
        b_ids = [s["id"] for s in m.list_sessions(user_id="u-b")]
        assert len(a_ids) == 1 and len(b_ids) == 1
        assert set(a_ids).isdisjoint(b_ids)

    def test_越权删除他人会话被拒(self, tmp_memory, db_offline):
        m = tmp_memory.记忆管理器()
        sess = m.create_session("A的会话", user_id="u-a")
        assert m.delete_session(sess["id"], user_id="u-b") is False
        # 会话仍在
        assert m.get_session(sess["id"]) is not None

    def test_本人删除成功(self, tmp_memory, db_offline):
        m = tmp_memory.记忆管理器()
        sess = m.create_session("A的会话", user_id="u-a")
        assert m.delete_session(sess["id"], user_id="u-a") is True
        assert m.get_session(sess["id"]) is None

    def test_遗留无主会话不展示(self, tmp_memory, db_offline):
        m = tmp_memory.记忆管理器()
        m.create_session("无主遗留会话", user_id=None)
        assert m.list_sessions(user_id="u-a") == []


# ============ 模块级：任务归属（ContextVar 自动带 user_id） ============

class Test任务归属ContextVar:
    def test_视频任务自动带归属(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-a", "username": "alice"})
        task = 视频._create_task_record("产品视频", "/uploads/a.jpg")
        set_current_user(None)
        assert task["user_id"] == "u-a"
        assert task["username"] == "alice"

    def test_卖点图任务自动带归属(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-b", "username": "bob"})
        task = 卖点图._create_task_record("音箱", "防水", "/uploads/b.jpg")
        set_current_user(None)
        assert task["user_id"] == "u-b"


class Test视频任务隔离:
    def test_列表按用户过滤(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-a", "username": "alice"})
        ta = 视频._create_task_record("A的任务", "/a.jpg")
        set_current_user({"id": "u-b", "username": "bob"})
        tb = 视频._create_task_record("B的任务", "/b.jpg")
        set_current_user(None)

        a_list = [t["id"] for t in 视频.list_video_tasks(user_id="u-a")]
        b_list = [t["id"] for t in 视频.list_video_tasks(user_id="u-b")]
        assert a_list == [ta["id"]]
        assert b_list == [tb["id"]]

    def test_查询他人任务返回None(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-a", "username": "alice"})
        ta = 视频._create_task_record("A的任务", "/a.jpg")
        set_current_user(None)
        assert 视频.get_video_task(ta["id"], user_id="u-a") is not None
        assert 视频.get_video_task(ta["id"], user_id="u-b") is None

    def test_越权删除被拒(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-a", "username": "alice"})
        ta = 视频._create_task_record("A的任务", "/a.jpg")
        set_current_user(None)
        assert 视频.delete_video_task(ta["id"], user_id="u-b") is False
        assert 视频.get_video_task(ta["id"]) is not None  # 仍在
        assert 视频.delete_video_task(ta["id"], user_id="u-a") is True


class Test卖点图任务隔离:
    def test_列表查询删除全链路隔离(self, tmp_tasks, db_offline):
        set_current_user({"id": "u-a", "username": "alice"})
        ta = 卖点图._create_task_record("音箱", "防水", "/a.jpg")
        set_current_user({"id": "u-b", "username": "bob"})
        tb = 卖点图._create_task_record("台灯", "调光", "/b.jpg")
        set_current_user(None)

        # 列表隔离
        a_list = [t["id"] for t in 卖点图.list_image_tasks(user_id="u-a")]
        b_list = [t["id"] for t in 卖点图.list_image_tasks(user_id="u-b")]
        assert a_list == [ta["id"]]
        assert b_list == [tb["id"]]

        # 查询隔离
        assert 卖点图.get_image_task(ta["id"], user_id="u-b") is None
        assert 卖点图.get_image_task(ta["id"], user_id="u-a") is not None

        # 删除隔离
        assert 卖点图.delete_image_task(ta["id"], user_id="u-b") is False
        assert 卖点图.delete_image_task(ta["id"], user_id="u-a") is True


# ============ DB 路径：校验 SQL 归属条件与越权拦截 ============

class TestDB路径归属SQL:
    def test_会话列表SQL带user_id条件(self, tmp_memory, monkeypatch):
        import 测试.conftest as c
        rows = [{"id": "s1", "title": "t", "user_id": "u-a",
                 "created_at": "x", "updated_at": "x"}]
        cursor_holder = {}

        @c.contextmanager
        def _ctx():
            cur = c.FakeCursor([("from chat_session", rows)])
            cursor_holder["cur"] = cur
            yield cur

        monkeypatch.setattr(tmp_memory, "get_cursor", _ctx)
        m = tmp_memory.记忆管理器()
        result = m.list_sessions(user_id="u-a")
        assert len(result) == 1
        sql, params = cursor_holder["cur"].executed[0]
        assert "user_id=%s" in sql.replace(" ", "") or "user_id = %s" in sql
        assert "u-a" in params

    def test_视频删除先校验属主(self, tmp_tasks, monkeypatch):
        import 测试.conftest as c
        cursor_holder = {}

        @c.contextmanager
        def _ctx():
            cur = c.FakeCursor([("select user_id", [{"user_id": "u-a"}])])
            cursor_holder["cur"] = cur
            yield cur

        monkeypatch.setattr(视频, "get_cursor", _ctx)
        # B 冒充删除 A 的任务 → SELECT 属主不匹配 → False
        assert 视频.delete_video_task("task-1", user_id="u-b") is False
        assert any("SELECT USER_ID" in s.upper() for s, _ in cursor_holder["cur"].executed)


# ============ API 级：双用户端到端 ============

class TestAPI级双用户隔离:
    def test_会话列表互不可见(self, client, tmp_auth_files, tmp_memory, db_offline):
        token_a, _ = _reg_and_login(tmp_auth_files, "iso_alice")
        token_b, _ = _reg_and_login(tmp_auth_files, "iso_bob")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        # A 建 2 个会话，B 建 1 个
        assert client.post("/sessions", headers=ha).status_code == 200
        assert client.post("/sessions", headers=ha).status_code == 200
        assert client.post("/sessions", headers=hb).status_code == 200

        a_sessions = client.get("/sessions", headers=ha).json()["sessions"]
        b_sessions = client.get("/sessions", headers=hb).json()["sessions"]
        assert len(a_sessions) == 2
        assert len(b_sessions) == 1
        assert {s["id"] for s in a_sessions}.isdisjoint({s["id"] for s in b_sessions})

    def test_读取他人会话返回错误(self, client, tmp_auth_files, tmp_memory, db_offline):
        token_a, _ = _reg_and_login(tmp_auth_files, "iso_alice2")
        token_b, _ = _reg_and_login(tmp_auth_files, "iso_bob2")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        sid = client.post("/sessions", headers=ha).json()["id"]
        # B 读 A 的会话 → 404（不泄露存在性）
        r = client.get(f"/sessions/{sid}", headers=hb)
        assert r.status_code == 404
        assert r.json()["detail"] == "会话不存在"
        # A 自己可读
        assert "messages" in client.get(f"/sessions/{sid}", headers=ha).json()

    def test_删除他人会话被拒(self, client, tmp_auth_files, tmp_memory, db_offline):
        token_a, _ = _reg_and_login(tmp_auth_files, "iso_alice3")
        token_b, _ = _reg_and_login(tmp_auth_files, "iso_bob3")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        sid = client.post("/sessions", headers=ha).json()["id"]
        assert client.delete(f"/sessions/{sid}", headers=hb).json()["deleted"] is False
        # A 的会话还在（读取返回 200 而非 404）
        assert client.get(f"/sessions/{sid}", headers=ha).status_code == 200
        assert client.delete(f"/sessions/{sid}", headers=ha).json()["deleted"] is True

    def test_ask携带他人会话被拒(self, client, tmp_auth_files, tmp_memory, db_offline, monkeypatch):
        token_a, _ = _reg_and_login(tmp_auth_files, "iso_alice4")
        token_b, _ = _reg_and_login(tmp_auth_files, "iso_bob4")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        sid = client.post("/sessions", headers=ha).json()["id"]
        # B 用 A 的 session_id 提问 → 拒绝，且不触发 Agent 编排
        r = client.post("/ask", json={"query": "hi", "session_id": sid}, headers=hb)
        assert r.status_code == 200
        assert "error" in r.json()

    def test_任务列表接口互不可见(self, client, tmp_auth_files, tmp_tasks, db_offline):
        token_a, uid_a = _reg_and_login(tmp_auth_files, "iso_alice5")
        token_b, _ = _reg_and_login(tmp_auth_files, "iso_bob5")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        # 模块层用 A 的上下文建任务（等价于 A 经接口创建）
        set_current_user({"id": uid_a, "username": "iso_alice5"})
        视频._create_task_record("A的视频", "/a.jpg")
        卖点图._create_task_record("A的图", "卖点", "/a.jpg")
        set_current_user(None)

        a_videos = client.get("/video/tasks", headers=ha).json()["tasks"]
        b_videos = client.get("/video/tasks", headers=hb).json()["tasks"]
        a_images = client.get("/image/tasks", headers=ha).json()["tasks"]
        b_images = client.get("/image/tasks", headers=hb).json()["tasks"]
        assert len(a_videos) == 1 and len(b_videos) == 0
        assert len(a_images) == 1 and len(b_images) == 0
