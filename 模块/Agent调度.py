# -*- coding: utf-8 -*-
"""Agent 调度模块：跨境电商智能体的核心编排层。

架构说明（面试讲解重点）：
- 采用 ReAct（Reasoning + Acting）思路 + 模型原生 Function Call 双引擎：
  · 通过 system prompt 引导模型"先思考需要什么工具/知识，再行动"（ReAct）；
  · 通过 bind_tools 把工具注册为函数签名，由模型决定调用（Function Call）；
- 多任务编排：单次对话中可串联多个工具（如先查知识→再算关税→再换算汇率）；
- 幻觉治理：Agent 产出后由 幻觉治理器 校验，低置信度自动追加风险提示；
- 可观测性：记录工具链、召回数、耗时、grounded 标志，写入日志模块。
"""
import re
import time
import uuid
from typing import List, Dict, Any, Optional

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from 模块.大模型客户端 import get_chat_model
from 模块.幻觉治理 import get_guard
from 工具集.关税查询 import 查询关税
from 工具集.汇率转换 import 汇率换算
from 工具集.产品知识检索 import 检索跨境电商知识
from 工具集.Listing生成 import 生成产品Listing
from 工具集.选品分析 import 选品分析
from 工具集.利润计算 import 利润计算
from 工具集.物流时效 import 物流时效查询
from 工具集.视频生成 import 生成宣传视频


# 系统提示词：ReAct 思维链引导
SYSTEM_PROMPT = """你是一名跨境电商运营智能体，服务于中国跨境卖家。
你必须遵循 ReAct 工作方式：先思考(Thought)需要哪些信息或工具，再行动(Action)调用工具，观察结果(Observation)，最终给出答案。

可用工具：
- 检索跨境电商知识：查询平台政策/选品/物流关税知识库（涉及规则、政策、建议时优先调用）；
- 查询关税：按目的国+商品类别查关税税率与应缴关税；
- 汇率换算：多币种金额换算；
- 生成产品Listing：生成符合平台规范的 Listing；
- 选品分析：按品类+目标市场给出市场热度/竞争程度/利润空间/合规风险/推荐指数等选品建议；
- 利润计算：按售价/采购成本/运费/关税/平台费率计算毛利、毛利率、利润率并给出利润健康度评价；
- 物流时效查询：按发货地+目的国+物流方式（海运/空运/快递/铁路）查询预计时效、运费区间与适用场景；
- 生成宣传视频：根据产品描述生成宣传视频，返回视频链接供查看。

工作原则（重要，降低幻觉）：
1. 涉及平台政策、关税、物流等事实性内容，必须先调用【检索跨境电商知识】获取依据，禁止凭记忆编造；
2. 涉及具体数字(税率/汇率/金额)必须通过对应工具获取，不得自行估算；
3. 若知识库未命中，如实说明"知识库暂无此信息"，并给出通用建议，标注需以官方为准；
4. 多步骤任务请依次调用工具，例如"美国电子产品关税+换算人民币"应先查关税再换算；
5. 回答末尾请用【依据来源】列出参考的知识来源或工具结果。
"""


class 跨境Agent:
    """跨境电商智能体调度器。"""

    def __init__(self, verbose: bool = True):
        self.llm = get_chat_model()
        self.tools = [
            检索跨境电商知识,
            查询关税,
            汇率换算,
            生成产品Listing,
            选品分析,
            利润计算,
            物流时效查询,
            生成宣传视频,
        ]
        self.verbose = verbose
        self.guard = get_guard()
        self.executor = self._build_executor()

    def _build_executor(self):
        """构建 ReAct + Function Call Agent（langchain 1.x create_agent，基于 langgraph）。

        create_agent 内部完成 bind_tools + ReAct 循环（思考→调用工具→观察→收敛），
        返回一个可 invoke 的 CompiledStateGraph，输入输出均为 messages 列表。
        """
        return create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=SYSTEM_PROMPT,
        )

    def orchestrate(self, query: str, chat_history: list = None, session_id: str = None) -> Dict[str, Any]:
        """多任务编排主入口。

        Args:
            query: 用户自然语言任务
            chat_history: 对话历史（LangChain message 列表），用于多轮对话记忆
            session_id: 会话 ID（可选，用于关联记忆模块持久化）

        Returns:
            dict: answer(最终答案) / tools_used(工具链) / retrievals(召回数)
                  / grounded(是否通过幻觉校验) / score(置信度) / latency_ms / session_id
        """
        session_id = session_id or str(uuid.uuid4())[:8]
        start = time.time()

        try:
            # langgraph 风格输入：历史消息 + 当前 query（注入记忆实现多轮对话）
            messages = list(chat_history or [])
            messages.append(HumanMessage(content=query))
            result = self.executor.invoke({"messages": messages})
            result_msgs = result["messages"]
            # 取最后一条 AI 消息作为最终答案
            answer = result_msgs[-1].content or ""
            # 从消息流中提取工具调用链（展示用，按 tool_call_id 精确匹配，避免错位）
            tools_used = self._extract_tool_chain(result_msgs)
            # 幻觉治理用"完整"上下文（不截断，避免正常答案被误判幻觉）：
            # - kb_context: 知识库检索返回（用于溯源 + 未命中检测）
            # - tool_context: 所有工具返回（用于数字/事实支撑校验，含关税/汇率等工具结果）
            kb_context = self._collect_full_context(result_msgs)
            tool_context = self._collect_tool_context(result_msgs)
            # RAG 溯源：从检索返回中提取结构化来源（文件名+相关度+片段），供前端展示
            sources = self._extract_sources(result_msgs)
        except Exception as e:  # noqa: BLE001
            answer = f"Agent 执行出错: {e}"
            tools_used = []
            kb_context = ""
            tool_context = ""
            sources = []

        latency_ms = int((time.time() - start) * 1000)

        # ---- 幻觉治理：知识库上下文做未命中检测，工具上下文做事实支撑校验 ----
        verify = self.guard.verify(answer, kb_context, tool_context)
        final_answer = self.guard.annotate_answer(answer, verify)

        payload = {
            "session_id": session_id,
            "answer": final_answer,
            "raw_answer": answer,
            "tools_used": tools_used,
            "sources": sources,
            "retrievals": sum(1 for t in tools_used if t.get("tool") == "search_kb"),
            "grounded": verify.grounded,
            "score": verify.grounding_score,
            "reason": verify.reason,
            "suggestions": verify.suggestions,
            "latency_ms": latency_ms,
        }

        # ---- 写入日志统计 ----
        try:
            from 模块.日志统计 import get_logger
            get_logger().log_query(payload)
        except Exception:  # noqa: BLE001
            pass

        if self.verbose:
            print(f"\n[Agent] 耗时={latency_ms}ms 工具链={tools_used} 置信度={verify.grounding_score}")

        return payload

    @staticmethod
    def _extract_tool_chain(messages) -> List[Dict[str, str]]:
        """从 langgraph 消息流提取工具调用链（按 tool_call_id 精确匹配，避免连续调用错位）。

        消息流形如：[Human, AIMessage(tool_calls=[...]), ToolMessage, AIMessage, ...]
        每个 AIMessage 的 tool_calls 携带唯一 tool_call_id，对应 ToolMessage.tool_call_id。
        """
        # 第一遍：收集每个 tool_call_id -> (name, args)
        id_to_call = {}
        order = []  # 保持调用顺序
        for msg in messages:
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        tc_id = tc.get("id", "")
                        name = tc.get("name", "unknown")
                        args = tc.get("args", {})
                    else:
                        tc_id = getattr(tc, "id", "")
                        name = getattr(tc, "name", "unknown")
                        args = getattr(tc, "args", {})
                    id_to_call[tc_id] = (name, args)
                    order.append(tc_id)
        # 第二遍：用 tool_call_id 匹配 ToolMessage 的结果
        id_to_output = {}
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", "")
                id_to_output[tc_id] = str(msg.content)
        # 组装（展示用，input/output 截断到 200 字符）
        chain = []
        for tc_id in order:
            name, args = id_to_call.get(tc_id, ("unknown", {}))
            out = id_to_output.get(tc_id, "")
            chain.append({
                "tool": name,
                "input": str(args)[:200],
                "output": out[:200],
            })
        return chain

    @staticmethod
    def _collect_full_context(messages) -> str:
        """幻觉治理专用：从消息流收集 search_kb 工具的【完整】返回内容作为校验上下文。

        注意：不能截断，否则答案关键词覆盖率会虚低，导致正常答案被误判幻觉。
        """
        # 先建立 tool_call_id -> tool_name 映射
        id_to_name = {}
        for msg in messages:
            if isinstance(msg, AIMessage):
                for tc in (getattr(msg, "tool_calls", None) or []):
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                    name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    id_to_name[tc_id] = name
        # 收集 search_kb 工具的完整返回
        parts = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tc_id = getattr(msg, "tool_call_id", "")
                if id_to_name.get(tc_id) == "search_kb":
                    parts.append(str(msg.content))
        return "\n\n".join(parts)

    @staticmethod
    def _collect_tool_context(messages) -> str:
        """幻觉治理用：收集【所有工具】的完整返回，作为事实支撑校验上下文。

        与 _collect_full_context 的区别：
        - _collect_full_context 只收集 search_kb，用于溯源和未命中检测；
        - 本方法收集所有工具（query_tariff/convert_currency/generate_listing/search_kb
          /analyze_product/calc_profit/query_logistics），
          使答案中来自关税/汇率等工具的数字能被识别为"有支撑"，避免误判幻觉。
        """
        parts = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                parts.append(str(msg.content))
        return "\n\n".join(parts)

    @staticmethod
    def _extract_sources(messages) -> List[Dict[str, Any]]:
        """RAG 溯源：从 search_kb 工具返回文本中提取结构化来源，供前端可折叠溯源展示。

        检索器 format_context 输出格式：
            [1] 来源:平台政策.md | 相关度:0.85
            片段正文内容...

        本方法用正则解析每条来源的：序号/来源文件/相关度/片段预览。
        """
        # 复用 _collect_full_context 拿到检索返回全文
        ctx = 跨境Agent._collect_full_context(messages)
        if not ctx:
            return []
        sources = []
        # 匹配 [N] 来源:xxx | 相关度:0.xx 后面跟片段（到下一个 [N] 或文末）
        pattern = re.compile(
            r"\[(\d+)\]\s*来源:([^\|\n]+?)\s*\|\s*相关度:([\d.]+)\s*\n([\s\S]*?)(?=\n\[\d+\]|\Z)"
        )
        for m in pattern.finditer(ctx):
            idx, source, score, content = m.group(1), m.group(2).strip(), m.group(3), m.group(4).strip()
            sources.append({
                "index": int(idx),
                "source": source,
                "score": float(score),
                "snippet": content[:160] + ("…" if len(content) > 160 else ""),
            })
        return sources


# 模块级单例
_agent_instance: Optional[跨境Agent] = None


def get_agent() -> 跨境Agent:
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = 跨境Agent()
    return _agent_instance


if __name__ == "__main__":
    agent = get_agent()
    r = agent.orchestrate("我要把蓝牙音箱出口到美国，电子产品类别，货值500美元，请查关税并换算成人民币")
    print("\n===== 最终答案 =====")
    print(r["answer"])
