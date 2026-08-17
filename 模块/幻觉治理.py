# -*- coding: utf-8 -*-
"""幻觉治理模块：校验 Agent 答案是否"有据可依"，降低大模型编造内容的风险。

核心策略（面试讲解重点）：
1. 溯源校验(Grounding)：检查答案中的关键事实是否能在检索上下文中找到支撑；
   - 用关键词重叠率 + LLM 判定双重校验；
2. 置信度评分：综合检索相关度、关键词覆盖、答案长度给出 grounding_score；
3. 兜底拦截：低于阈值时追加"未在知识库中核实"提示，或触发重答；
4. 长度与禁忌词检查：过长/绝对化表述(如100%、永远)降权。

这样即使 LLM 出现幻觉，也能在产出层被识别并提示用户。
"""
import re
from typing import List, Optional
from dataclasses import dataclass

from config import HALLUCINATION_CONFIG


# 绝对化/夸大词，出现则降低置信度
_ABSOLUTE_WORDS = ["100%", "绝对", "永远", "一定", "保证", "百分百", "guaranteed", "always", "never"]


def _normalize_text(text: str) -> str:
    """归一化文本，用于答案与支撑上下文的比对（不影响最终展示）。

    解决两类误判根源：
    1. markdown 排版符号（|、**、# 等）干扰分词重合；
    2. 数字格式不一致：答案写 60%、60.00，工具输出写 60.0%、60.00，
       归一化后统一为纯数字（去千分位逗号、去尾零、去百分号），
       让"答案引用了工具输出中的数字"能被正确识别为有支撑。
    """
    t = re.sub(r"[|*#`_>\[\]()]", "", text)
    t = re.sub(r"-{3,}", " ", t)

    def _fmt(m):
        s = m.group(0)
        s = s.replace(",", "").replace("%", "")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"

    return re.sub(r"\d[\d,]*\.?\d*%?", _fmt, t)


@dataclass
class 校验结果:
    """幻觉校验结果。"""
    grounded: bool                # 是否通过校验
    grounding_score: float        # 置信度 0~1
    reason: str                   # 判定理由
    suggestions: List[str]        # 改进建议


class 幻觉治理器:
    """答案幻觉校验器。"""

    def __init__(self):
        self.config = HALLUCINATION_CONFIG

    def verify(self, answer: str, context: str, tool_context: str = "") -> 校验结果:
        """校验答案是否被上下文支撑。

        Args:
            answer: Agent 生成的最终答案
            context: 知识库检索上下文（search_kb 返回，用于溯源 + 未命中检测）
            tool_context: 所有工具返回（含关税/汇率等，用于事实支撑校验，避免工具结果被误判幻觉）

        Returns:
            校验结果
        """
        if not self.config["enabled"]:
            return 校验结果(True, 1.0, "幻觉治理已关闭", [])

        if not answer.strip():
            return 校验结果(False, 0.0, "答案为空", ["请提供有效回答"])

        suggestions = []
        score = 0.0

        # ---- 1) 知识库未命中检测 ----
        # 检索工具对超纲问题会返回"未命中/未检索到/暂无"等文本；
        # 但此时若其他工具（关税/汇率）有返回，仍可作答，不应直接判幻觉。
        _MISS_HINTS = ("未检索到", "未命中", "暂无", "未找到", "没有找到", "无相关", "(未检索到")
        kb_miss = (not context) or any(h in context for h in _MISS_HINTS)

        # 综合支撑上下文 = 知识库 + 工具返回（工具结果同样能支撑答案中的事实）
        support_context = "\n\n".join([c for c in [context, tool_context] if c])

        # 既无知识库支撑，又无工具结果支撑 → 强制低分
        if not support_context.strip() or kb_miss and not tool_context.strip():
            score = 0.2
            suggestions.append("知识库无相关内容，回答需明确标注'未在知识库核实'")
            return 校验结果(False, score, "无知识库/工具支撑，疑似凭空生成", suggestions)

        # ---- 2) 关键词覆盖分：答案分词在【综合上下文】中的覆盖率 ----
        # 用归一化文本比对：markdown 符号与数字格式差异不再干扰分词重合
        import jieba
        ans_norm = _normalize_text(answer)
        ctx_norm = _normalize_text(support_context)
        ans_tokens = {t for t in jieba.lcut(ans_norm) if len(t.strip()) > 1}
        ctx_tokens = set(jieba.lcut(ctx_norm))
        if ans_tokens:
            coverage = len(ans_tokens & ctx_tokens) / len(ans_tokens)
        else:
            coverage = 0.3
        score += 0.5 * coverage

        # ---- 3) 绝对化词惩罚 ----
        abs_hits = [w for w in _ABSOLUTE_WORDS if w.lower() in answer.lower()]
        if abs_hits:
            score -= 0.15
            suggestions.append(f"检测到绝对化表述{abs_hits}，建议改为留有余地的说法")

        # ---- 4) 长度检查：过长易发散 ----
        if len(answer) > 1200:
            score -= 0.1
            suggestions.append("答案过长，建议精简聚焦")

        # ---- 5) 数字/百分比核查：答案数字是否在【综合上下文】中出现 ----
        # 数字统一归一化后比对（60% / 60.00 / 60.0 视为同一个数字）
        ans_nums = set(re.findall(r"\d+\.?\d*%?", _normalize_text(answer)))
        ctx_nums = set(re.findall(r"\d+\.?\d*%?", _normalize_text(support_context)))
        unsupported_nums = ans_nums - ctx_nums - {"0"}  # 允许 0
        # 仅当"大量数字无支撑"才扣分，避免个别格式差异/衍生数字导致整体误判
        if unsupported_nums and len(ans_nums) > 2 and len(unsupported_nums) / len(ans_nums) > 0.3:
            score -= 0.1
            suggestions.append(f"答案含上下文未出现的数字{list(unsupported_nums)[:5]}，请核实")

        # ---- 6) 归一化 ----
        score = max(0.0, min(1.0, score + 0.3))  # 基础分 0.3 + 覆盖加权

        # 知识库未命中但有工具结果支撑：标注提示但不判幻觉
        if kb_miss and tool_context.strip():
            suggestions.append("知识库未命中，部分信息来自工具结果，建议以官方政策为准")

        grounded = score >= self.config["min_grounding_score"]
        if not grounded:
            reason = f"置信度{score:.2f}低于阈值{self.config['min_grounding_score']}，存在幻觉风险"
            suggestions.append("建议重新检索或明确告知用户信息未核实")
        else:
            reason = f"置信度{score:.2f}达标，答案基本有据可依"

        return 校验结果(grounded, round(score, 3), reason, suggestions)

    def llm_judge(self, answer: str, context: str) -> Optional[bool]:
        """用 LLM 做更细粒度的幻觉判定（可选，消耗额外 token）。

        返回 True=有据, False=幻觉, None=判定失败。
        """
        try:
            from 模块.大模型客户端 import get_chat_model
            from langchain_core.prompts import ChatPromptTemplate
            llm = get_chat_model(temperature=0.0)
            prompt = ChatPromptTemplate.from_messages([
                ("system", "你是事实核查员。判断【答案】中的事实是否都能在【上下文】中找到支撑。"
                           "只回答 JSON: {{\"grounded\": true/false, \"reason\": \"...\"}}"),
                ("human", "【上下文】\n{ctx}\n\n【答案】\n{ans}"),
            ])
            import json
            resp = (prompt | llm).invoke({"ctx": context, "ans": answer})
            txt = resp.content.strip().strip("`")
            data = json.loads(txt.split("json")[-1] if "json" in txt else txt)
            return bool(data.get("grounded"))
        except Exception:  # noqa: BLE001
            return None

    def annotate_answer(self, answer: str, result: 校验结果) -> str:
        """在答案末尾追加幻觉治理标注（用于最终展示）。"""
        if result.grounded:
            # 即使通过校验，若建议里有"知识库未命中"提示，也追加提醒（更严谨）
            kb_miss_tip = [s for s in result.suggestions if "知识库未命中" in s]
            if kb_miss_tip:
                return answer + "\n\n[提示] 部分信息来自工具结果，建议以官方政策为准。"
            return answer
        tag = "\n\n[注意] 本回答置信度较低，相关数据未在知识库中完全核实，请以官方政策为准。"
        return answer + tag


# 模块级单例
_治理器实例: Optional[幻觉治理器] = None


def get_guard() -> 幻觉治理器:
    global _治理器实例
    if _治理器实例 is None:
        _治理器实例 = 幻觉治理器()
    return _治理器实例
