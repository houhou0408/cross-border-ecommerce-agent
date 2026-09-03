# -*- coding: utf-8 -*-
"""幻觉治理模块单测：逐项验证六项评分逻辑。"""
import pytest

from 模块.幻觉治理 import get_guard, _normalize_text


@pytest.fixture
def guard():
    return get_guard()


# ============ 归一化 ============

class Test归一化:
    def test_百分号与尾零统一(self):
        # 60% / 60.00 / 60.0 归一化后应视为同一数字
        assert _normalize_text("60%") == _normalize_text("60.00") == _normalize_text("60.0")

    def test_千分位逗号去除(self):
        assert _normalize_text("1,200") == _normalize_text("1200")

    def test_markdown符号去除(self):
        assert "*" not in _normalize_text("**加粗** | 表格 | # 标题")

    def test_列表序号删除(self):
        # 序号是排版编号，不应参与数字比对
        assert "1" not in _normalize_text("1. 第一条")


# ============ verify 六项评分 ============

class Test无支撑判定:
    def test_空答案(self, guard):
        r = guard.verify("", "任何上下文")
        assert r.grounded is False
        assert r.grounding_score == 0.0

    def test_无上下文判幻觉(self, guard):
        r = guard.verify("美国进口服装关税很高", "")
        assert r.grounded is False
        assert r.grounding_score == 0.2
        assert "疑似凭空" in r.reason

    def test_知识库未命中且无工具支撑(self, guard):
        r = guard.verify("物流时效7天", "未检索到相关知识")
        assert r.grounded is False
        assert r.grounding_score == 0.2


class Test支撑评分:
    def test_工具数字溯源加分(self, guard):
        # 答案引用了工具输出的数字 → num_support=1.0，得分应显著高于无溯源场景
        r = guard.verify(
            "美国服装关税为32%，应缴关税$339.20",
            "未检索到相关知识",
            tool_context="关税税率: 32.00% 应缴关税: 339.20",
        )
        assert r.grounding_score > 0.6
        assert any("可溯源" in s for s in r.suggestions)

    def test_数字格式差异不影响溯源(self, guard):
        # 答案写 32%，工具输出 32.00 —— 归一化后视为同一数字
        r = guard.verify("关税32%", "未检索到相关知识", tool_context="税率: 32.00%")
        assert any("可溯源" in s for s in r.suggestions)

    def test_关键词覆盖得分(self, guard):
        # 答案关键词大部分来自上下文 → 通过校验
        ctx = "跨境物流采用空运专线，预计7到15个自然日送达，偏远地区2到3周。"
        r = guard.verify("跨境物流预计7到15个自然日送达", ctx)
        assert r.grounded is True
        assert r.grounding_score >= 0.45

    def test_诚实降级加分(self, guard):
        # 同样的答案，标注"以官方为准"应获得更高置信度
        ctx = "跨境物流预计7到15个自然日送达。"
        base = guard.verify("跨境物流预计7到15个自然日送达", ctx)
        honest = guard.verify("跨境物流预计7到15个自然日送达，具体以官方为准", ctx)
        assert honest.grounding_score >= base.grounding_score

    def test_知识库未命中但有工具支撑_不判幻觉(self, guard):
        r = guard.verify("关税为32%", "未检索到相关知识", tool_context="关税税率: 32%")
        # 有工具支撑则不应走 0.2 强制低分分支
        assert r.grounding_score > 0.2


class Test惩罚项:
    def test_绝对化词惩罚(self, guard):
        ctx = "跨境物流时效通常为7到15个自然日。"
        normal = guard.verify("物流通常为7到15个自然日", ctx)
        absolute = guard.verify("物流保证一定7到15个自然日", ctx)
        assert absolute.grounding_score < normal.grounding_score
        assert any("绝对化" in s for s in absolute.suggestions)

    def test_合规语境不误伤(self, guard):
        # "避免绝对化表述" 属于合规提醒语境，不应惩罚
        ctx = "客服话术规范：避免使用绝对化表述，不得承诺100%效果。"
        r = guard.verify("话术规范要求避免使用绝对化表述", ctx)
        assert not any("绝对化表述[" in s and "建议改为" in s for s in r.suggestions)


class Test标注:
    def test_低置信追加风险提示(self, guard):
        r = guard.verify("随便编的答案", "")
        annotated = get_guard().annotate_answer("随便编的答案", r)
        assert "[注意]" in annotated

    def test_通过校验不加提示(self, guard):
        ctx = "跨境物流采用空运专线，预计7到15个自然日送达。"
        r = guard.verify("跨境物流预计7到15个自然日送达", ctx)
        annotated = get_guard().annotate_answer("跨境物流预计7到15个自然日送达", r)
        assert "[注意]" not in annotated
