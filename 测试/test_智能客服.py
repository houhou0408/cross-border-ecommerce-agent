# -*- coding: utf-8 -*-
"""智能客服单测：订单号提取 / FAQ 命中 / 引导 / LLM 异常降级（确定性路径不耗 token）。"""
import pytest

from 模块.智能客服 import (
    _extract_order_no, _has_faq_hit, _query_order, buyer_reply,
)


class Test订单号提取:
    def test_标准格式(self):
        assert _extract_order_no("查一下 ORD2026053010") == "ORD2026053010"

    def test_小写与横线归一(self):
        assert _extract_order_no("订单号 ord-2026053010") == "ORD2026053010"

    def test_纯数字兼容(self):
        assert _extract_order_no("单号 1234567890123") == "1234567890123"

    def test_无订单号返回None(self):
        assert _extract_order_no("我的包裹到哪了") is None


class Test订单查询:
    def test_命中内置订单(self):
        r = buyer_reply("查一下 ORD2026071803 的物流", [])
        assert r["type"] == "order"
        assert r["grounded"] is True
        assert "运输中" in r["reply"]

    def test_未命中订单_引导核对(self):
        r = buyer_reply("ORD9999999999 到哪了", [])
        assert r["type"] == "order"
        assert r.get("not_found") is True
        assert "未查询到" in r["reply"]

    def test_查询函数降级链预留位(self):
        # 内置无此单且未接真实 API → None
        assert _query_order("ORD0000000000") is None


class TestFAQ命中:
    def test_退货类(self):
        r = buyer_reply("退货运费谁出", [])
        assert r["type"] == "faq"
        assert r["grounded"] is True
        assert "退换货" in r["reply"]

    def test_物流时效类(self):
        r = buyer_reply("多久能到货", [])
        assert r["type"] == "faq"

    def test_转人工类(self):
        r = buyer_reply("我要转人工投诉", [])
        assert r["type"] == "faq"
        assert "人工" in r["reply"]

    def test_FAQ不耗LLM(self, monkeypatch):
        # FAQ 命中时绝不应触发 LLM
        def _no_llm(*a, **kw):
            raise AssertionError("FAQ 命中不应调用 LLM")
        monkeypatch.setattr("模块.智能客服._llm_chat", _no_llm)
        r = buyer_reply("支持七天无理由退货吗", [])
        assert r["type"] == "faq"

    def test_命中函数返回确定答案(self):
        assert _has_faq_hit("尺码怎么选") is not None
        assert _has_faq_hit("今天天气如何") is None


class Test引导与降级:
    def test_物流类无单号引导(self):
        r = buyer_reply("我的订单状态怎么样了", [])
        assert r["type"] == "guide"
        assert "订单号" in r["reply"]

    def test_LLM异常不裸奔(self, monkeypatch):
        # LLM 挂了返回兜底话术，绝不把原始异常抛给买家
        def _broken(*a, **kw):
            raise RuntimeError("LLM 服务不可用")
        monkeypatch.setattr("模块.智能客服._llm_chat", _broken)
        r = buyer_reply("你们公司总部在哪里", [])
        assert r["type"] == "error"
        assert "转人工" in r["reply"]
