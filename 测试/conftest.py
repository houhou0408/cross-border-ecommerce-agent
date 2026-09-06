# -*- coding: utf-8 -*-
"""共享测试夹具。

设计说明（面试讲解重点）：
1. 测试全程不依赖 MySQL / LLM Key / 外部网络 / embedding 模型；
2. 不用 sqlite 替身——项目 SQL 是 MySQL 方言（%s 占位符、ON DUPLICATE KEY UPDATE、
   REPLACE INTO、JSON 列），换 sqlite 等于重写所有 SQL，违背"不改行为"原则；
3. 各业务模块都是 `from 基础设施.数据库连接 import get_cursor` 的本地绑定，
   patch 源模块对已导入的模块无效，必须逐消费模块 patch；
4. FakeCursor 按 SQL 关键字预设返回行，并记录 execute 调用供断言。
"""
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ============ FakeCursor：模拟 mysql.connector dictionary=True 游标 ============

class FakeCursor:
    """可预设返回行的假游标。

    plan: [(SQL匹配子串, rows), ...]，execute 时按顺序匹配第一个命中片段；
    未命中返回空结果。executed 记录 (sql, params) 供测试断言。
    """

    def __init__(self, plan=None):
        self._plan = plan or []
        self.executed = []
        self._rows = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._rows = []
        for frag, rows in self._plan:
            if frag.lower() in sql.lower():
                self._rows = rows
                break

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


@contextmanager
def _fake_cursor_ctx(plan=None):
    yield FakeCursor(plan)


@contextmanager
def _offline_cursor_ctx():
    yield None


# ============ DB 消费模块清单与 patch 助手 ============

_DB_CONSUMERS = [
    "模块.记忆模块",
    "基础设施.日志统计",
    "模块.反馈闭环",
    "工具集.数据采集",
    "工具集.关税查询",
    "工具集.视频生成",
    "工具集.卖点图生成",
    "基础设施.用户认证",
]


def _iter_consumer_modules():
    """延迟导入所有 DB 消费模块（避免 conftest 导入期做重活）。

    只产出确实持有 get_cursor 本地绑定的模块——个别模块可能改用
    函数内延迟导入，patch 不存在的属性会直接 AttributeError。
    """
    import importlib
    for name in _DB_CONSUMERS:
        try:
            m = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(m, "get_cursor"):
            yield m


def patch_db(monkeypatch, plan=None, modules=None):
    """把指定模块的 get_cursor 本地绑定替换为 FakeCursor（带预设行）。

    Args:
        plan: [(SQL子串, rows)] 预设查询结果
        modules: 指定要 patch 的模块列表；默认全部消费模块
    """
    def _ctx():
        return _fake_cursor_ctx(plan)

    targets = modules if modules is not None else list(_iter_consumer_modules())
    for m in targets:
        monkeypatch.setattr(m, "get_cursor", _ctx)
    return targets


@pytest.fixture
def db_offline(monkeypatch):
    """所有消费模块的 get_cursor 一律 yield None（触发既有降级链）。"""
    def _ctx():
        return _offline_cursor_ctx()

    for m in _iter_consumer_modules():
        monkeypatch.setattr(m, "get_cursor", _ctx)


@pytest.fixture(autouse=True)
def _clear_rate_cache():
    """每个测试前清空数据采集内存缓存，避免用例间串味。"""
    import 工具集.数据采集 as 数据采集
    数据采集._CACHE.clear()
    yield
    数据采集._CACHE.clear()


def _no_network(requests_like):
    """构造一个所有请求都抛超时异常的假 requests 模块。"""
    def _raise(*args, **kwargs):
        raise TimeoutError("测试环境禁止外呼")

    return SimpleNamespace(get=_raise, post=_raise)


# ============ 路径隔离夹具（防测试污染真实数据文件） ============

@pytest.fixture
def tmp_auth_files(monkeypatch, tmp_path):
    """用户/Token 文件隔离到 tmp 目录。"""
    import 基础设施.用户认证 as auth
    monkeypatch.setattr(auth, "_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_TOKENS_FILE", tmp_path / "tokens.json")
    return auth


@pytest.fixture
def tmp_memory(monkeypatch, tmp_path):
    """记忆模块会话文件隔离到 tmp 目录 + 复位单例。"""
    import 模块.记忆模块 as mem
    monkeypatch.setattr(mem, "_SESSION_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(mem, "_memory_instance", None)
    yield mem
    mem._memory_instance = None


@pytest.fixture
def tmp_tasks(monkeypatch, tmp_path):
    """视频/卖点图任务文件隔离到 tmp 目录。"""
    import 工具集.视频生成 as video
    monkeypatch.setattr(video, "_TASK_DIR", tmp_path / "video_tasks.json")
    try:
        import 工具集.卖点图生成 as img
        for attr in ("_IMAGE_TASK_DIR", "_TASK_DIR"):
            if hasattr(img, attr):
                monkeypatch.setattr(img, attr, tmp_path / "image_tasks.json")
                break
    except ImportError:
        pass
    return tmp_path
