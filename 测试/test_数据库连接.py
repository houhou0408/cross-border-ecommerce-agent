# -*- coding: utf-8 -*-
"""数据库连接测试：get_cursor 修复后的契约行为。

覆盖点（面试讲解重点）：
1. 连接失败 → yield None 降级，不抛异常；首次 WARNING、后续 DEBUG（防刷屏）；
2. 连接成功后 with 体内的 SQL 异常【正常上抛】，不再被吞（旧 bug）；
3. 成功路径 commit；SQL 异常路径 rollback。
"""
import logging
import sys
from types import SimpleNamespace

import pytest

import 基础设施.数据库连接 as db


# ============ 假 mysql.connector ============

class FakeCursor:
    def __init__(self, conn, fail_on_execute=False):
        self._conn = conn
        self._fail = fail_on_execute
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._fail:
            raise RuntimeError("SQL语法错误")

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, fail_on_execute=False):
        self.committed = 0
        self.rolled_back = 0
        self.closed = False
        self._fail_on_execute = fail_on_execute

    def cursor(self, dictionary=True):
        return FakeCursor(self, fail_on_execute=self._fail_on_execute)

    def is_connected(self):
        return not self.closed

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


def _install_fake_mysql(monkeypatch, connect_impl):
    """替换 get_cursor 内部 `import mysql.connector` 的解析结果。"""
    fake_pkg = SimpleNamespace(
        connector=SimpleNamespace(connect=lambda **kw: connect_impl(kw))
    )
    monkeypatch.setitem(sys.modules, "mysql", fake_pkg)
    # `import mysql.connector` 会先找 sys.modules["mysql.connector"]
    monkeypatch.setitem(sys.modules, "mysql.connector", fake_pkg.connector)
    # 复位失败去重状态，保证用例间独立
    monkeypatch.setattr(db, "_db_fail_logged", False)


# ============ 降级行为 ============

class Test连接失败降级:
    @pytest.fixture(autouse=True)
    def _allow_log_propagation(self, monkeypatch):
        """放开父 logger 日志传播，保证 caplog 能捕获记录。

        生产日志体系（基础设施.日志统计）会给父 logger "跨境Agent" 挂自有
        handler 并设 propagate=False，而 caplog 的捕获 handler 挂在根
        logger——不放开传播记录到不了根，caplog 为空（pytest 8.x 表现，
        9.x 行为不同），测试必须显式放开以跨版本稳定。
        """
        monkeypatch.setattr(logging.getLogger("跨境Agent"), "propagate", True)

    def test_连接失败yield_None不抛异常(self, monkeypatch):
        def _fail(kw):
            raise ConnectionRefusedError("MySQL 未启动")
        _install_fake_mysql(monkeypatch, _fail)
        with db.get_cursor() as cur:
            assert cur is None

    def test_连接失败首次WARNING后续DEBUG(self, monkeypatch, caplog):
        def _fail(kw):
            raise ConnectionRefusedError("MySQL 未启动")
        _install_fake_mysql(monkeypatch, _fail)

        with caplog.at_level(logging.DEBUG, logger="跨境Agent.数据库连接"):
            for _ in range(3):
                with db.get_cursor() as cur:
                    assert cur is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(warnings) == 1   # 只 WARNING 一次，防刷屏
        assert len(debugs) == 2     # 后续降为 DEBUG

    def test_恢复后复位并记INFO(self, monkeypatch, caplog):
        state = {"fail": True}
        def _maybe_fail(kw):
            if state["fail"]:
                raise ConnectionRefusedError("down")
            return FakeConn()
        _install_fake_mysql(monkeypatch, _maybe_fail)

        with caplog.at_level(logging.DEBUG, logger="跨境Agent.数据库连接"):
            with db.get_cursor() as cur:
                assert cur is None
            state["fail"] = False
            with db.get_cursor() as cur:
                assert cur is not None
            state["fail"] = True
            with db.get_cursor() as cur:
                assert cur is None

        # 第二次失败又是一次新 WARNING（恢复已复位去重状态）
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        infos = [r for r in caplog.records if "连接已恢复" in r.getMessage()]
        assert len(warnings) == 2
        assert len(infos) == 1


# ============ SQL 异常传播（核心 bug 修复） ============

class TestSQL异常上抛:
    def test_异常不被吞正常上抛(self, monkeypatch):
        _install_fake_mysql(monkeypatch, lambda kw: FakeConn(fail_on_execute=True))
        with pytest.raises(RuntimeError, match="SQL语法错误"):
            with db.get_cursor() as cur:
                cur.execute("SELECT * FROM 不存在的表")

    def test_异常路径rollback且不commit(self, monkeypatch):
        conn_holder = {}
        def _connect(kw):
            conn_holder["conn"] = FakeConn(fail_on_execute=True)
            return conn_holder["conn"]
        _install_fake_mysql(monkeypatch, _connect)

        with pytest.raises(RuntimeError):
            with db.get_cursor() as cur:
                cur.execute("BAD SQL")

        conn = conn_holder["conn"]
        assert conn.rolled_back == 1
        assert conn.committed == 0
        assert conn.closed is True


# ============ 成功路径 ============

class Test成功路径:
    def test_成功commit并关闭(self, monkeypatch):
        conn_holder = {}
        def _connect(kw):
            conn_holder["conn"] = FakeConn()
            return conn_holder["conn"]
        _install_fake_mysql(monkeypatch, _connect)

        with db.get_cursor() as cur:
            cur.execute("SELECT 1")
        conn = conn_holder["conn"]
        assert conn.committed == 1
        assert conn.closed is True

    def test_连接带3秒超时(self, monkeypatch):
        seen = {}
        def _connect(kw):
            seen.update(kw)
            return FakeConn()
        _install_fake_mysql(monkeypatch, _connect)
        with db.get_cursor() as cur:
            assert cur is not None
        assert seen.get("connection_timeout") == 3

    def test_is_db_available(self, monkeypatch):
        _install_fake_mysql(monkeypatch, lambda kw: FakeConn())
        assert db.is_db_available() is True

        def _fail(kw):
            raise ConnectionRefusedError("down")
        _install_fake_mysql(monkeypatch, _fail)
        assert db.is_db_available() is False
