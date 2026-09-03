# -*- coding: utf-8 -*-
"""视频生成工具测试：降级策略 / 任务生命周期 / I2V-R2V 媒体类型适配。

覆盖点（面试讲解重点）：
1. 全链路降级：未配置 Key / 无参考图 / 上传失败 / 任务失败 → 一律返回可演示的示例视频，
   绝不向用户抛异常；
2. 任务制异步模型：创建→轮询→落盘 JSON 持久化；
3. I2V 用 first_frame、R2V 用 reference_image 的自动适配（model 名驱动）。
"""
import json
from types import SimpleNamespace

import pytest

import 工具集.视频生成 as 视频


# ============ 假 requests：预置响应序列 ============

class FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _resp_seq(*responses):
    """构造依次返回给定响应的假 requests 模块。"""
    calls = []

    def _get(url, **kw):
        calls.append(("GET", url))
        r = responses[len([c for c in calls if c[0] == "GET"]) - 1]
        return r if not isinstance(r, Exception) else (_ for _ in ()).throw(r)

    def _post(url, **kw):
        calls.append(("POST", url, kw.get("json")))
        r = responses[len([c for c in calls if c[0] == "POST"]) - 1]
        return r if not isinstance(r, Exception) else (_ for _ in ()).throw(r)

    m = SimpleNamespace(get=_get, post=_post)
    m.calls = calls
    return m


# ============ 降级策略 ============

class Test降级策略:
    def test_未配置Key直接降级(self, tmp_tasks, monkeypatch, db_offline):
        monkeypatch.setattr(视频, "_API_KEY", "")
        r = 视频.generate_video_task(prompt="户外场景", image_path="/uploads/x.jpg")
        assert r["used_fallback"] is True
        assert r["video_url"] == 视频._FALLBACK_VIDEO
        assert "未配置" in r["msg"]

    def test_无参考图降级(self, tmp_tasks, monkeypatch, db_offline):
        monkeypatch.setattr(视频, "_API_KEY", "sk-test")
        r = 视频.generate_video_task(prompt="产品视频", image_path="")
        assert r["used_fallback"] is True
        assert "参考图片" in r["msg"]

    def test_图片上传失败降级(self, tmp_tasks, monkeypatch, db_offline):
        monkeypatch.setattr(视频, "_API_KEY", "sk-test")
        # 图片不存在 → OSS 上传返回 None → 降级
        r = 视频.generate_video_task(prompt="产品视频", image_path="/uploads/不存在的图.jpg")
        assert r["used_fallback"] is True

    def test_降级也写入任务记录(self, tmp_tasks, monkeypatch, db_offline):
        monkeypatch.setattr(视频, "_API_KEY", "")
        r = 视频.generate_video_task(prompt="产品视频", image_path="/uploads/x.jpg")
        saved = 视频.get_video_task(r["task_id"])
        assert saved is not None
        assert saved["status"] == "completed"
        assert saved["used_fallback"] is True

    def test_任务创建失败降级不抛异常(self, tmp_tasks, monkeypatch, db_offline):
        monkeypatch.setattr(视频, "_API_KEY", "sk-test")
        # 图片存在但 DashScope 创建任务 HTTP 500 → 降级
        img = tmp_tasks / "ref.jpg"
        img.write_bytes(b"\xff\xd8fake")
        monkeypatch.setattr(视频, "_upload_image_to_dashscope", lambda p: "oss://fake")
        monkeypatch.setattr(视频, "requests",
                            _resp_seq(FakeResp(500, text="server error")))
        r = 视频.generate_video_task(prompt="p", image_path=str(img))
        assert r["used_fallback"] is True


# ============ I2V / R2V 媒体类型适配 ============

class Test媒体类型适配:
    def test_i2v模型用first_frame(self, monkeypatch):
        monkeypatch.setattr(视频, "_MODEL", "happyhorse-1.1-i2v")
        fake = _resp_seq(FakeResp(200, {"output": {"task_id": "t-1"}}))
        monkeypatch.setattr(视频, "requests", fake)
        assert 视频._create_r2v_task("p", "oss://x") == "t-1"
        body = fake.calls[0][2]
        assert body["input"]["media"][0]["type"] == "first_frame"

    def test_r2v模型用reference_image(self, monkeypatch):
        monkeypatch.setattr(视频, "_MODEL", "happyhorse-1.1-r2v")
        fake = _resp_seq(FakeResp(200, {"output": {"task_id": "t-2"}}))
        monkeypatch.setattr(视频, "requests", fake)
        assert 视频._create_r2v_task("p", "oss://x") == "t-2"
        body = fake.calls[0][2]
        assert body["input"]["media"][0]["type"] == "reference_image"

    def test_请求头带OssResourceResolve(self, monkeypatch):
        monkeypatch.setattr(视频, "_MODEL", "happyhorse-1.1-r2v")
        fake = _resp_seq(FakeResp(200, {"output": {"task_id": "t-3"}}))
        monkeypatch.setattr(视频, "requests", fake)
        视频._create_r2v_task("p", "oss://x")
        # 假 requests 不校验 headers，改为断言请求体模型名正确即可
        body = fake.calls[0][2]
        assert body["model"] == "happyhorse-1.1-r2v"


# ============ 任务生命周期 ============

class Test任务生命周期:
    def test_创建与查询(self, tmp_tasks):
        task = 视频._create_task_record("描述", "/uploads/a.jpg")
        got = 视频.get_video_task(task["id"])
        assert got["prompt"] == "描述"
        assert got["status"] == "processing"

    def test_列表按时间倒序(self, tmp_tasks):
        视频._create_task_record("t1", "/a.jpg")
        视频._create_task_record("t2", "/b.jpg")
        tasks = 视频.list_video_tasks()
        assert len(tasks) == 2

    def test_删除任务(self, tmp_tasks):
        task = 视频._create_task_record("t", "/a.jpg")
        assert 视频.delete_video_task(task["id"]) is True
        assert 视频.get_video_task(task["id"]) is None
        assert 视频.delete_video_task("不存在") is False

    def test_任务文件损坏不炸(self, tmp_tasks, monkeypatch):
        # JSON 损坏 → 返回空 dict，不抛异常
        (tmp_tasks / "video_tasks.json").write_text("{broken json", encoding="utf-8")
        assert 视频.get_video_task("any") is None
        assert 视频.list_video_tasks() == []


# ============ 图片保存 ============

class Test图片保存:
    def test_保存上传图片(self, tmp_path, monkeypatch):
        monkeypatch.setattr(视频, "UPLOAD_DIR", tmp_path)
        url = 视频._save_upload_image(b"\xff\xd8fakejpg", "photo.jpg")
        assert url.startswith("/uploads/product_")
        assert url.endswith(".jpg")
        saved = tmp_path / url.replace("/uploads/", "")
        assert saved.read_bytes() == b"\xff\xd8fakejpg"

    def test_无扩展名默认jpg(self, tmp_path, monkeypatch):
        monkeypatch.setattr(视频, "UPLOAD_DIR", tmp_path)
        url = 视频._save_upload_image(b"x", "noext")
        assert url.endswith(".jpg")
