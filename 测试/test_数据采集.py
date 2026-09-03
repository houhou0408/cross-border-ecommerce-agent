# -*- coding: utf-8 -*-
"""数据采集单测：内存缓存 TTL + 汇率四级降级链（全程 mock，零外呼）。"""
import time
from types import SimpleNamespace

import pytest

import 工具集.数据采集 as 采集
from 测试.conftest import patch_db


# ============ 内存缓存 ============

class Test缓存TTL:
    def test_缓存命中(self):
        采集._set_cache("k", {"v": 1})
        assert 采集._get_cache("k") == {"v": 1}

    def test_过期返回None(self):
        采集._set_cache("k", {"v": 1})
        # 把时间戳拨回 TTL 之外
        采集._CACHE["k"]["ts"] -= 采集._CACHE_TTL + 1
        assert 采集._get_cache("k") is None

    def test_不存在返回None(self):
        assert 采集._get_cache("no_such_key") is None


# ============ 假 requests（禁止外呼） ============

def _api_timeout():
    def _raise(*args, **kwargs):
        raise TimeoutError("测试禁止外呼")
    return SimpleNamespace(get=_raise, post=_raise)


def _api_ok(rates):
    class _Resp:
        status_code = 200
        def json(self):
            return {"rates": rates}
    def _get(url, timeout=10):
        return _Resp()
    return SimpleNamespace(get=_get, post=_api_timeout().post)


# ============ 汇率四级降级链 ============

class Test汇率降级链:
    def test_链1_缓存命中不外呼(self, monkeypatch):
        采集._set_cache("exchange_rates", {"USD": 1.0, "CNY": 7.2})
        calls = []
        def _get(url, timeout=10):
            calls.append(url)
            raise AssertionError("缓存命中时不应外呼")
        monkeypatch.setattr(采集, "requests", SimpleNamespace(get=_get))
        rates = 采集.fetch_exchange_rates()
        assert rates["CNY"] == 7.2
        assert calls == []

    def test_链2_API成功并回写缓存(self, monkeypatch, db_offline):
        monkeypatch.setattr(采集, "requests", _api_ok({"CNY": 7.15, "JPY": 149.0}))
        rates = 采集.fetch_exchange_rates()
        assert rates["CNY"] == 7.15
        assert rates["JPY"] == 149.0
        # 成功结果应写回内存缓存
        assert 采集._get_cache("exchange_rates")["CNY"] == 7.15

    def test_链3_API失败走DB快照(self, monkeypatch):
        rows = [
            {"from_currency": "USD", "to_currency": "CNY", "rate": "7.10"},
            {"from_currency": "USD", "to_currency": "EUR", "rate": "0.93"},
        ]
        patch_db(monkeypatch, plan=[("exchange_rate", rows)])
        monkeypatch.setattr(采集, "requests", _api_timeout())
        rates = 采集.fetch_exchange_rates()
        assert rates["CNY"] == 7.10
        assert rates["EUR"] == 0.93

    def test_链4_全失败走内置基线(self, monkeypatch, db_offline):
        monkeypatch.setattr(采集, "requests", _api_timeout())
        rates = 采集.fetch_exchange_rates()
        # 内置基线 12 个币种
        assert rates["USD"] == 1.0
        assert rates["CNY"] == 7.1950
        assert len(rates) == 12

    def test_链2成功后回写DB(self, monkeypatch):
        captured = []
        class CaptureCursor:
            def execute(self, sql, params=None):
                captured.append((sql, params))
            def close(self): pass
        import contextlib
        @contextlib.contextmanager
        def _cur():
            yield CaptureCursor()
        monkeypatch.setattr(采集, "get_cursor", _cur)
        monkeypatch.setattr(采集, "requests", _api_ok({"CNY": 7.15}))
        采集.fetch_exchange_rates()
        # 应有 INSERT ... ON DUPLICATE KEY UPDATE 回写
        inserts = [c for c in captured if "ON DUPLICATE KEY" in c[0]]
        assert inserts, "在线采集成功后必须回写 DB 快照"


class Test交叉汇率:
    def test_USD直转(self):
        采集._set_cache("exchange_rates", {"USD": 1.0, "CNY": 7.2, "JPY": 150.0})
        assert 采集.get_rate("USD", "CNY") == pytest.approx(7.2)

    def test_交叉计算(self):
        # CNY → JPY = (1/7.2) * 150
        采集._set_cache("exchange_rates", {"USD": 1.0, "CNY": 7.2, "JPY": 150.0})
        assert 采集.get_rate("CNY", "JPY") == pytest.approx(150.0 / 7.2)

    def test_同币种为1(self):
        assert 采集.get_rate("USD", "usd") == 1.0

    def test_未知币种返回0(self):
        采集._set_cache("exchange_rates", {"USD": 1.0})
        assert 采集.get_rate("USD", "XXX") == 0.0
