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
from 模块.多模型路由 import get_router
from 工具集.关税查询 import 查询关税
from 工具集.汇率转换 import 汇率换算
from 工具集.产品知识检索 import 检索跨境电商知识
from 工具集.Listing生成 import 生成产品Listing
from 工具集.利润计算 import 利润计算
from 工具集.物流时效 import 物流时效查询
from 工具集.视频生成 import 生成宣传视频, 文生视频
from 工具集.卖点图生成 import 生成卖点图
from 工具集.智能筛品 import 智能选品分析
from 工具集.痛点拆解 import 痛点分析
from 工具集.商品图选品 import 商品图选品分析
from 模块.反馈闭环 import 记录反馈, 查看反馈统计


# 系统提示词：ReAct 思维链引导
SYSTEM_PROMPT = """你是一名跨境电商运营智能体，服务于中国跨境卖家。
你必须遵循 ReAct 工作方式：先思考(Thought)需要哪些信息或工具，再行动(Action)调用工具，观察结果(Observation)，最终给出答案。

可用工具：
- 检索跨境电商知识：查询平台政策/选品/物流关税知识库（涉及规则、政策、建议时优先调用）；
- 查询关税：按目的国+商品类别查关税税率与应缴关税（支持：电子产品/服装/家居用品/玻璃制品/美妆/宠物用品/玩具/鞋类/灯具）；
- 汇率换算：多币种金额换算；
- 生成产品Listing：生成符合平台规范的 Listing（支持精品/铺货双模式+SEO关键词分层+痛点差异化+合规双检）；
- 智能选品分析：全套深度选品（Rainforest API真实竞品+自有成本利润核算+多层筛品+蓝海/红海分级+四级开发建议）；
- 利润计算：按售价/采购成本/运费/关税/平台费率计算毛利、毛利率、利润率并给出利润健康度评价；
- 物流时效查询：按发货地+目的国+物流方式（海运/空运/快递/铁路）查询预计时效、运费区间与适用场景；
- 生成宣传视频：根据产品描述生成宣传视频（图生视频），返回视频链接供查看；
- 文生视频：根据纯文字描述生成视频（无需图片），适合创意短片、场景演示；
- 生成卖点图：上传商品图后生成全套电商卖点图（白底主图/场景图/卖点标注图/详情长图），返回4张图片链接；
- 记录反馈：记录运营对回答的评价（好/差），用于系统自优化；
- 查看反馈统计：查看系统反馈统计与改进建议；
- 痛点分析：深度分析竞品用户痛点（评分/评论分布→问题模式→改款建议→差异化卖点）。
- 商品图选品分析：上传商品图后 AI 自动识别品类/材质/风格/卖点，再跑完整选品分析+痛点拆解。当用户上传商品图并提到"选品""分析""能不能做"时优先调用，避免用户手动描述产品。

工作原则（重要，降低幻觉）：
1. 涉及平台政策、关税、物流等事实性内容，必须先调用【检索跨境电商知识】获取依据，禁止凭记忆编造；
2. 涉及具体数字(税率/汇率/金额)必须通过对应工具获取，不得自行估算；
3. 若知识库未命中，如实说明"知识库暂无此信息"，并给出通用建议，标注需以官方为准；
4. 若问题涉及不存在的主题（如"火星"等不存在的国家/地区/仓库/平台/商品），必须明确拒答：
   直接说明"该主题不存在，无法查询/无法提供可靠信息"，不得编造数据、流程或猜测性内容；
5. 多步骤任务请依次调用工具，例如"美国电子产品关税+换算人民币"应先查关税再换算；
6. 回答末尾请用【依据来源】列出参考的知识来源或工具结果。

输出风格（强制）：
6. 禁止使用任何 emoji 表情符号（如 🚀📊✅❌💰🏆🥛🟢等），全部用纯文字替代；
7. 使用简洁专业的 B 端系统风格，段落清晰、层次分明，用 markdown 表格而非装饰性符号表达对比数据；
8. 不要用"～""！""✨"等口语化/装饰性标点，保持商务报告式的克制语气；
9. 数据结论优先于铺陈，先给结论再用数据支撑，避免冗长的铺垫性描述。

图片上传说明（重要）：
- 若用户消息开头出现【用户已上传商品图片：/uploads/xxx.jpg】，表示用户在对话中上传了商品图；
- 若用户要求做选品分析，优先调用【商品图选品分析】工具，image_path 填入图片路径，让视觉模型自动识别品类代替手动输入；
- 若用户要求生成视频或卖点图，调用【生成宣传视频】或【生成卖点图】工具，把图片路径作为 image_path 参数传入；
- 未上传图片时，image_path 留空，工具将走文生视频/纯文生图模式或降级。

全业务闭环联动（重要，面试亮点）：
- 选品→文案闭环：当用户要求"先分析选品再写Listing"时，先调用【智能选品分析】获取竞品分析结果，
  再从结果中提取热点关键词/差异化方向/用户痛点，作为"产品卖点"和"竞品痛点"参数传入【生成产品Listing】；
- 选品→图片闭环：智能选品分析输出的核心卖点和用户使用场景，传入【生成卖点图】的features和品类参数，
  实现「调研到素材」全链路自动化；
- 痛点→文案闭环：若调用了【痛点分析】，将其输出的改款建议和差异化卖点，
  作为"竞品痛点"参数传入【生成产品Listing】，实现痛点驱动的Listing差异化写作；
- 关税→利润闭环：先用【查询关税】获取税率，再将结果传入【利润计算】算净利润；
- 多工具串联时，上一环的输出摘要自动成为下一环的输入，无需用户重复描述。

选品→素材联动（重要，面试亮点）：
- 当用户完成选品分析后，不要在当轮自动调用素材生成工具；
- 你应根据用户已提供的信息，在回答末尾判断哪些素材可以生成、哪些缺条件，
  用简洁的列表告知用户，例如：
  ---
  需要我继续生成以下素材吗？
  1. 生成产品Listing（基于选品分析的品类和竞品关键词，可直接生成）
  2. 生成卖点图（需上传商品实拍图，纯文生图效果较差）
  3. 生成宣传视频（需上传商品实拍图，无图只能走文生视频，产品外观不可控）
  请回复序号或"全部生成"，若需要我生成卖点图/视频，请先上传商品图。
  ---
- 关键规则：
  a) 若用户未上传商品图，卖点图和视频选项应标注"需上传商品图"，不要直接调用；
  b) 若用户未上传图却回复了"2"或"3"，应先提示"请先上传商品图"而非直接调工具；
  c) 若用户已上传商品图，则列表注明"基于您上传的商品图生成"，可以直接调用；
  d) 产品Listing无需图片，无论有无上传图都应列在第一项；
- 只有当用户明确确认且所需信息齐全后，才调用对应素材工具；
- 调用素材工具时，从之前选品分析结果中提取卖点/品类/关键词作为参数，无需用户重复输入；
- 生成的图片链接用 markdown 图片格式 ![](url) 输出，
  视频链接用 markdown 链接格式 [点击下载/播放](url) 输出。"""


class 跨境Agent:
    """跨境电商智能体调度器。"""

    def __init__(self, verbose: bool = True):
        self.llm = None  # 每次 _build_executor 重新创建
        self.tools = [
            检索跨境电商知识,
            查询关税,
            汇率换算,
            生成产品Listing,
            智能选品分析,
            利润计算,
            物流时效查询,
            生成宣传视频,
            文生视频,
            生成卖点图,
            商品图选品分析,
            记录反馈,
            查看反馈统计,
            痛点分析,
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
            model=get_chat_model(),
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

        # ---- 前置意图检测：图片上传 + 选品关键词 → 强制走商品图选品分析 ----
        # DeepSeek 等模型对模糊意图有时不调用工具，这里做关键词兜底
        _image_prefix = "【用户已上传商品图片："
        if query.startswith(_image_prefix):
            _has_intent = re.search(
                r'分析|选品|能不能做|可以(做|卖)|有市场|竞争|帮我看看|可不可以|怎么样|值得|好不好做|能(做|卖)吗',
                query
            )
            _img_match = re.match(
                r'【用户已上传商品图片：([^\]]+)】\n用户问题：(.*)',
                query, re.DOTALL
            )
            if _has_intent and _img_match:
                _img_path = _img_match.group(1)
                _user_q = _img_match.group(2).strip()
                print(f"[Agent] 检测到图片+选品意图，强制路由到商品图选品分析 "
                      f"(image={_img_path}, q={_user_q[:60]})")
                try:
                    _result = 商品图选品分析.invoke({
                        "image_path": _img_path,
                        "选品要求": _user_q,
                    })
                    _answer = str(_result) if _result else "选品分析无结果"
                    # 在选品报告末尾追加素材生成选项
                    _offer = (
                        "\n\n---\n\n"
                        "需要我继续生成以下素材吗？\n\n"
                        "1. 生成产品Listing（基于选品分析的品类和竞品关键词，可直接生成）\n\n"
                        f"2. 生成卖点图（基于您上传的商品图，可直接生成）\n\n"
                        f"3. 生成宣传视频（基于您上传的商品图，可直接生成）\n\n"
                        "请回复序号（如 1、2、3）或输入「全部生成」。"
                    )
                    _answer += _offer
                    _tools_used = [{
                        "tool": "product_image_selection",
                        "input": f"query={_user_q[:50]}, image={_img_path}",
                        "output": _answer[:200],
                    }]
                    latency_ms = int((time.time() - start) * 1000)
                    verify = self.guard.verify(_answer, "", _answer)
                    final_answer = self.guard.annotate_answer(_answer, verify)
                    payload = {
                        "session_id": session_id,
                        "answer": final_answer,
                        "raw_answer": _answer,
                        "tools_used": _tools_used,
                        "sources": [],
                        "retrievals": 0,
                        "grounded": verify.grounded,
                        "score": verify.grounding_score,
                        "reason": verify.reason,
                        "suggestions": verify.suggestions,
                        "latency_ms": latency_ms,
                        "route": get_router().get_route_info(query),
                    }
                    try:
                        from 模块.日志统计 import get_logger
                        get_logger().log_query(payload)
                    except Exception:
                        pass
                    if self.verbose:
                        print(f"\n[Agent] 耗时={latency_ms}ms 工具链={_tools_used} 置信度={verify.grounding_score}")
                    return payload
                except Exception as _fe:
                    print(f"[Agent] 商品图选品分析强制调用失败: {_fe}，回退到正常 LLM 流程")

        # ---- 前置意图检测2：选品后的素材生成序号输入 ----
        # 用户在选品报告后输入 "1" / "2" / "3" / "全部生成" → 强制调用对应工具
        _followup_match = re.match(r'^\s*(1|2|3|全部生成|全部)\s*$', query.strip())
        if _followup_match:
            _choice = _followup_match.group(1)
            print(f"[Agent] 检测到素材生成序号: {_choice}")

            # 从对话历史中提取上下文
            _ctx_category = ""
            _ctx_features = ""
            _ctx_image_path = ""
            if chat_history:
                for _msg in reversed(chat_history):
                    _text = str(_msg.content) if hasattr(_msg, 'content') else str(_msg)
                    if not _ctx_category:
                        _m = re.search(r'识别品类[：:]\s*(.+)', _text)
                        if _m: _ctx_category = _m.group(1).strip()
                    if not _ctx_features:
                        _m = re.search(r'图片卖点[：:]\s*(.+)', _text)
                        if _m: _ctx_features = _m.group(1).strip().replace(' | ', ',')
                    if not _ctx_image_path:
                        _m = re.search(r'(/uploads/\S+\.(?:png|jpg|jpeg))', _text)
                        if _m: _ctx_image_path = _m.group(1)
                    if _ctx_category and _ctx_features:
                        break
            # 从 query 自身也尝试提取（兜底）
            if not _ctx_category:
                _m = re.search(r'品类[：:]\s*(.+)', query)
                if _m: _ctx_category = _m.group(1).strip()
            if not _ctx_features:
                _m = re.search(r'(?:卖点|features)[：:]\s*(.+)', query)
                if _m: _ctx_features = _m.group(1).strip().replace(' | ', ',')[:200]

            if not _ctx_category:
                _ctx_category = "玻璃杯"  # fallback

            print(f"[Agent] 检测到素材生成序号: {_choice} (品类={_ctx_category}, image={_ctx_image_path[:40] if _ctx_image_path else '无'})")

            if _choice in ("1",):
                _tool_result = 生成产品Listing.invoke({
                    "product": _ctx_category,
                    "platform": "amazon",
                    "language": "en",
                    "features": _ctx_features,
                })
                _tools_used = [{"tool": "generate_listing", "input": f"product={_ctx_category}", "output": str(_tool_result)[:200]}]
                _answer = str(_tool_result)
            elif _choice in ("2",):
                _tool_result = 生成卖点图.invoke({
                    "product": _ctx_category,
                    "features": _ctx_features,
                    "image_path": _ctx_image_path,
                    "品类": _ctx_category,
                    "画质": "精品",
                })
                _tools_used = [{"tool": "generate_selling_images", "input": f"product={_ctx_category}", "output": str(_tool_result)[:200]}]
                _answer = str(_tool_result)
            elif _choice in ("3",):
                _video_prompt = f"{_ctx_category}产品宣传，{_ctx_features}，自然光线下展示产品质感"
                if _ctx_image_path:
                    _tool_result = 生成宣传视频.invoke({
                        "prompt": _video_prompt,
                        "image_path": _ctx_image_path,
                    })
                else:
                    _tool_result = 文生视频.invoke({"prompt": _video_prompt})
                _tools_used = [{"tool": "generate_promo_video", "input": f"prompt={_video_prompt[:50]}", "output": str(_tool_result)[:200]}]
                _answer = str(_tool_result)
            elif _choice in ("全部生成", "全部"):
                # 全部生成：依次调用
                _answers = []
                _all_tools = []
                # 1. Listing
                _r1 = 生成产品Listing.invoke({"product": _ctx_category, "platform": "amazon", "language": "en", "features": _ctx_features})
                _answers.append("### 1. 产品Listing\n\n" + str(_r1))
                _all_tools.append({"tool": "generate_listing", "input": f"product={_ctx_category}", "output": str(_r1)[:80]})
                # 2. 卖点图
                _r2 = 生成卖点图.invoke({"product": _ctx_category, "features": _ctx_features, "image_path": _ctx_image_path, "品类": _ctx_category, "画质": "精品"})
                _answers.append("### 2. 卖点图\n\n" + str(_r2))
                _all_tools.append({"tool": "generate_selling_images", "input": f"product={_ctx_category}", "output": str(_r2)[:80]})
                # 3. 视频
                _video_prompt = f"{_ctx_category}产品宣传，{_ctx_features}，自然光线下展示产品质感"
                if _ctx_image_path:
                    _r3 = 生成宣传视频.invoke({"prompt": _video_prompt, "image_path": _ctx_image_path})
                else:
                    _r3 = 文生视频.invoke({"prompt": _video_prompt})
                _answers.append("### 3. 宣传视频\n\n" + str(_r3))
                _all_tools.append({"tool": "generate_promo_video", "input": f"prompt={_video_prompt[:50]}", "output": str(_r3)[:80]})
                _answer = "\n\n---\n\n".join(_answers)
                _tools_used = _all_tools
            else:
                _answer = ""
                _tools_used = []

            if _answer:
                latency_ms = int((time.time() - start) * 1000)
                verify = self.guard.verify(_answer, "", _answer)
                final_answer = self.guard.annotate_answer(_answer, verify)
                # 追加后续选项（如果还有未生成的）
                _remaining = []
                if _choice == "1":
                    _remaining = ["2. 生成卖点图", "3. 生成宣传视频"]
                elif _choice == "2":
                    _remaining = ["1. 生成产品Listing", "3. 生成宣传视频"]
                elif _choice == "3":
                    _remaining = ["1. 生成产品Listing", "2. 生成卖点图"]
                if _remaining:
                    final_answer += "\n\n---\n\n还可以继续生成：\n" + "\n".join(_remaining)
                payload = {
                    "session_id": session_id,
                    "answer": final_answer,
                    "raw_answer": _answer,
                    "tools_used": _tools_used,
                    "sources": [],
                    "retrievals": 0,
                    "grounded": verify.grounded,
                    "score": verify.grounding_score,
                    "reason": verify.reason,
                    "suggestions": verify.suggestions,
                    "latency_ms": latency_ms,
                    "route": get_router().get_route_info(query),
                }
                try:
                    from 模块.日志统计 import get_logger
                    get_logger().log_query(payload)
                except Exception:
                    pass
                if self.verbose:
                    print(f"\n[Agent] 耗时={latency_ms}ms 工具链={_tools_used} 置信度={verify.grounding_score}")
                return payload

        # 每次请求重建 executor，避免 httpx client 复用关闭问题
        executor = self._build_executor()

        try:
            # langgraph 风格输入：历史消息 + 当前 query（注入记忆实现多轮对话）
            messages = list(chat_history or [])
            messages.append(HumanMessage(content=query))
            result = executor.invoke({"messages": messages})
            result_msgs = result["messages"]
            # 取最后一条 AI 消息作为最终答案
            answer = result_msgs[-1].content or ""
            # 从消息流中提取工具调用链（展示用，按 tool_call_id 精确匹配，避免错位）
            tools_used = self._extract_tool_chain(result_msgs)
            kb_context = self._collect_full_context(result_msgs)
            tool_context = self._collect_tool_context(result_msgs)
            sources = self._extract_sources(result_msgs)
        except Exception as e:
            # 重试一次（常见问题：httpx client closed / langgraph bindings stale）
            try:
                executor2 = self._build_executor()
                messages2 = list(chat_history or [])
                messages2.append(HumanMessage(content=query))
                result2 = executor2.invoke({"messages": messages2})
                answer = result2["messages"][-1].content or ""
                tools_used = self._extract_tool_chain(result2["messages"])
                kb_context = self._collect_full_context(result2["messages"])
                tool_context = self._collect_tool_context(result2["messages"])
                sources = self._extract_sources(result2["messages"])
            except Exception as e2:
                answer = f"Agent 执行出错: {e2}"
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
            "route": get_router().get_route_info(query),
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
          /smart_selection/calc_profit/query_logistics），
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
