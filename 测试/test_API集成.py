# -*- coding: utf-8 -*-
"""API 集成测试：TestClient 走真实 FastAPI 路由，仅 mock LLM/Agent 与外部 API。

覆盖点（面试讲解重点）：
1. /ask 端到端：鉴权 → 会话创建（归属当前用户）→ FakeAgent 编排 → 消息写回记忆；
2. 多轮记忆：第二轮请求注入第一轮的历史消息（验证 chat_history 传递）；
3. 客服 FAQ 链路：buyer_reply mock，会话归属 + 消息落库；
4. 图片上传：multipart 上传返回 /uploads/ 路径；
5. 视频任务全生命周期（降级模式）：无 Key → 直接降级示例视频 + 任务记录可查。
"""
import pytest
from fastapi.testclient import TestClient

import 接口.FastAPI服务 as svc
from 接口.FastAPI服务 import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def fake_agent(monkeypatch):
    """替换 get_agent：记录调用参数，返回固定答案。"""
    calls = []

    class FakeAgent:
        def orchestrate(self, query, chat_history=None, session_id=None):
            calls.append({"query": query, "chat_history": chat_history, "session_id": session_id})
            return {
                "answer": f"echo: {query}",
                "tools_used": ["fake_tool"],
                "grounded": True,
                "score": 0.9,
                "latency_ms": 12,
            }

    monkeypatch.setattr(svc, "get_agent", lambda: FakeAgent())
    return calls


def _login(auth, username="api_user"):
    auth.register(username, "pass123")
    r = auth.login(username, "pass123")
    assert r["ok"] is True
    return {"Authorization": f"Bearer {r['token']}"}


# ============ /ask 端到端 ============

class TestAsk端到端:
    def test_无session自动新建并归属当前用户(self, client, tmp_auth_files, tmp_memory,
                                          db_offline, fake_agent):
        headers = _login(tmp_auth_files, "ask_user1")
        r = client.post("/ask", json={"query": "蓝牙音箱卖美国怎么样"}, headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "echo: 蓝牙音箱卖美国怎么样"
        assert body["session_id"]

        # 会话归属当前用户且消息已写回
        sess = tmp_memory.记忆管理器().get_session(body["session_id"])
        assert sess["user_id"] is not None
        roles = [m["role"] for m in sess["messages"]]
        assert roles == ["user", "assistant"]

    def test_多轮记忆注入历史(self, client, tmp_auth_files, tmp_memory, db_offline, fake_agent):
        headers = _login(tmp_auth_files, "ask_user2")
        r1 = client.post("/ask", json={"query": "第一轮问题"}, headers=headers)
        sid = r1.json()["session_id"]
        r2 = client.post("/ask", json={"query": "第二轮问题", "session_id": sid}, headers=headers)
        assert r2.status_code == 200

        # 第二次 orchestrate 收到第一轮的 user/assistant 历史
        assert len(fake_agent) == 2
        history = fake_agent[1]["chat_history"]
        assert history, "第二轮应注入历史消息"

    def test_上传图片路径注入query(self, client, tmp_auth_files, tmp_memory, db_offline, fake_agent):
        headers = _login(tmp_auth_files, "ask_user3")
        r = client.post("/ask", json={"query": "帮我做卖点图", "image_path": "/uploads/x.jpg"},
                        headers=headers)
        assert r.status_code == 200
        # FakeAgent 收到的 query 前面带上传标记
        assert "【用户已上传商品图片：/uploads/x.jpg】" in fake_agent[0]["query"]


# ============ 客服链路 ============

class Test客服链路:
    def test_buyer问答与会话归属(self, client, tmp_auth_files, tmp_memory, db_offline, monkeypatch):
        import 模块.智能客服 as cs

        def fake_buyer_reply(query, history):
            return {"reply": f"客服回复: {query}", "type": "faq", "grounded": True}

        monkeypatch.setattr(cs, "buyer_reply", fake_buyer_reply)

        headers = _login(tmp_auth_files, "cs_user1")
        r = client.post("/support/ask", json={"query": "我的订单到哪了", "mode": "buyer"},
                        headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["reply"] == "客服回复: 我的订单到哪了"
        assert body["session_id"]

        # 会话归属 + 双消息落库
        sess = tmp_memory.记忆管理器().get_session(body["session_id"])
        assert sess["user_id"] is not None
        assert [m["role"] for m in sess["messages"]] == ["user", "assistant"]

    def test_客服异常降级不炸(self, client, tmp_auth_files, tmp_memory, db_offline, monkeypatch):
        import 模块.智能客服 as cs

        def boom(query, history):
            raise RuntimeError("LLM 挂了")

        monkeypatch.setattr(cs, "buyer_reply", boom)
        headers = _login(tmp_auth_files, "cs_user2")
        r = client.post("/support/ask", json={"query": "hi", "mode": "buyer"}, headers=headers)
        assert r.status_code == 200
        assert "暂时不可用" in r.json()["reply"]

    def test_Faq主题公开列表(self, client):
        # /support/faq/topics 需鉴权但不需要会话
        r = client.get("/support/faq/topics")
        assert r.status_code == 401  # 无 token 先被拦


# ============ 图片上传 ============

class Test图片上传:
    def test_上传返回uploads路径(self, client, tmp_auth_files, monkeypatch, tmp_path):
        import 工具集.视频生成 as 视频
        headers = _login(tmp_auth_files, "up_user1")
        saved = {}

        def fake_save(data, filename):
            saved["name"] = filename
            return "/uploads/product_fake.jpg"

        # 路由内是延迟导入，patch 源模块即可
        monkeypatch.setattr(视频, "_save_upload_image", fake_save)
        r = client.post(
            "/chat/upload-image",
            files={"file": ("photo.jpg", b"\xff\xd8fakejpg", "image/jpeg")},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["image_path"] == "/uploads/product_fake.jpg"
        assert saved["name"] == "photo.jpg"

    def test_空图片被拒(self, client, tmp_auth_files):
        headers = _login(tmp_auth_files, "up_user2")
        r = client.post(
            "/chat/upload-image",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
            headers=headers,
        )
        assert r.status_code == 200
        assert "error" in r.json()


# ============ 视频任务生命周期（降级模式） ============

class Test视频任务生命周期:
    def test_文生视频降级模式全链路(self, client, tmp_auth_files, tmp_tasks,
                                     db_offline, monkeypatch):
        import 工具集.视频生成 as 视频
        monkeypatch.setattr(视频, "_API_KEY", "")

        headers = _login(tmp_auth_files, "v_user1")
        # 创建（无 Key → 直接降级示例视频）
        r = client.post("/video/text-to-video", json={"prompt": "产品展示视频"},
                        headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["used_fallback"] is True
        assert body["video_url"]

        # 查询（本人可见）
        detail = client.get(f"/video/tasks/{body['task_id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["status"] == "completed"

        # 列表（归属当前用户）
        tasks = client.get("/video/tasks", headers=headers).json()["tasks"]
        assert any(t["id"] == body["task_id"] for t in tasks)

        # 删除
        assert client.delete(f"/video/tasks/{body['task_id']}",
                             headers=headers).json()["deleted"] is True
        # 再查 → 不存在
        again = client.get(f"/video/tasks/{body['task_id']}", headers=headers)
        assert "error" in again.json()
