# -*- coding: utf-8 -*-
"""意图路由层：确定性意图的规则化前置路由（关键词兜底）。

为什么存在（面试讲解重点）：
- ReAct Agent 依赖 LLM 自主决策是否调用工具，DeepSeek 等模型对模糊意图
  （如"这张图帮我看看能不能卖"）偶尔不触发 Function Call，导致功能漏触发；
- 对「确定性高、体验敏感」的意图做规则化前置路由：命中则直接 invoke 工具、
  完全绕过 LLM 推理，保证功能必达、结果稳定；
- 未命中的请求返回 None，由 Agent调度 回落到正常 ReAct 流程，两层互为兜底。

路由规则：
1. 图片上传 + 选品关键词 → 商品图选品分析（报告末尾追加素材生成引导）；
2. 选品报告后的序号输入（1/2/3/全部生成）→ 对应素材生成工具，
   所需上下文（识别品类/图片卖点/图片路径）从会话历史中正则提取。
"""
import re
import time
from typing import Any, Dict, List, Optional

from 基础设施.日志统计 import get_file_logger, get_logger
from 模块.多模型路由 import get_router
from 工具集.Listing生成 import 生成产品Listing
from 工具集.卖点图生成 import 生成卖点图
from 工具集.商品图选品 import 商品图选品分析
from 工具集.视频生成 import 文生视频, 生成宣传视频

logger = get_file_logger("意图路由")

# 选品报告末尾追加的素材生成选项（引导用户用序号继续）
_OFFER_SUFFIX = (
    "\n\n---\n\n"
    "需要我继续生成以下素材吗？\n\n"
    "1. 生成产品Listing（基于选品分析的品类和竞品关键词，可直接生成）\n\n"
    "2. 生成卖点图（基于您上传的商品图，可直接生成）\n\n"
    "3. 生成宣传视频（基于您上传的商品图，可直接生成）\n\n"
    "请回复序号（如 1、2、3）或输入「全部生成」。"
)

# 历史消息中提取素材生成上下文的正则
_RE_CATEGORY_IN_HISTORY = re.compile(r"识别品类[：:]\s*(.+)")
_RE_FEATURES_IN_HISTORY = re.compile(r"图片卖点[：:]\s*(.+)")
_RE_IMAGE_IN_HISTORY = re.compile(r"(/uploads/\S+\.(?:png|jpg|jpeg))")
_RE_CATEGORY_IN_QUERY = re.compile(r"品类[：:]\s*(.+)")
_RE_FEATURES_IN_QUERY = re.compile(r"(?:卖点|features)[：:]\s*(.+)")


def _finalize(
    final_answer: str,
    raw_answer: str,
    tools_used: List[Dict[str, str]],
    verify: Any,
    session_id: str,
    start: float,
    query: str,
    verbose: bool,
) -> Dict[str, Any]:
    """按 orchestrate 的 payload 口径收尾：统一字段 + 统计落库 + 日志。"""
    latency_ms = int((time.time() - start) * 1000)
    payload = {
        "session_id": session_id,
        "answer": final_answer,
        "raw_answer": raw_answer,
        "tools_used": tools_used,
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
        get_logger().log_query(payload)
    except Exception:  # noqa: BLE001
        pass
    if verbose:
        logger.info(
            "\n[Agent] 耗时=%sms 工具链=%s 置信度=%s",
            latency_ms, tools_used, verify.grounding_score,
        )
    return payload


def try_route(
    query: str,
    chat_history: list,
    *,
    guard: Any,
    session_id: str,
    start: float,
    verbose: bool = True,
) -> Optional[Dict[str, Any]]:
    """确定性意图前置路由入口。

    命中返回与 orchestrate 同构的 payload；未命中返回 None（回落 ReAct 流程）。
    """
    routed = _route_image_selection(query, guard, session_id, start, verbose)
    if routed is not None:
        return routed
    return _route_followup_generation(query, chat_history, guard, session_id, start, verbose)


def _route_image_selection(
    query: str, guard: Any, session_id: str, start: float, verbose: bool
) -> Optional[Dict[str, Any]]:
    """规则1：图片上传 + 选品关键词 → 强制走商品图选品分析。"""
    _image_prefix = "【用户已上传商品图片："
    if not query.startswith(_image_prefix):
        return None
    _has_intent = re.search(
        r"分析|选品|能不能做|可以(做|卖)|有市场|竞争|帮我看看|可不可以|怎么样|值得|好不好做|能(做|卖)吗",
        query,
    )
    _img_match = re.match(r"【用户已上传商品图片：([^\]]+)】\n用户问题：(.*)", query, re.DOTALL)
    if not (_has_intent and _img_match):
        return None

    _img_path = _img_match.group(1)
    _user_q = _img_match.group(2).strip()
    logger.info(
        "[Agent] 检测到图片+选品意图，强制路由到商品图选品分析 (image=%s, q=%s)",
        _img_path, _user_q[:60],
    )
    try:
        _result = 商品图选品分析.invoke({
            "image_path": _img_path,
            "选品要求": _user_q,
        })
        _answer = str(_result) if _result else "选品分析无结果"
        _answer += _OFFER_SUFFIX
        _tools_used = [{
            "tool": "product_image_selection",
            "input": f"query={_user_q[:50]}, image={_img_path}",
            "output": _answer[:200],
        }]
        verify = guard.verify(_answer, "", _answer)
        final_answer = guard.annotate_answer(_answer, verify)
        return _finalize(final_answer, _answer, _tools_used, verify, session_id, start, query, verbose)
    except Exception as _fe:  # noqa: BLE001
        logger.warning("[Agent] 商品图选品分析强制调用失败: %s，回退到正常 LLM 流程", _fe)
        return None


def _extract_generation_context(chat_history: list, query: str):
    """从会话历史与当前 query 中提取素材生成所需上下文。"""
    _ctx_category = ""
    _ctx_features = ""
    _ctx_image_path = ""
    if chat_history:
        for _msg in reversed(chat_history):
            _text = str(_msg.content) if hasattr(_msg, "content") else str(_msg)
            if not _ctx_category:
                _m = _RE_CATEGORY_IN_HISTORY.search(_text)
                if _m:
                    _ctx_category = _m.group(1).strip()
            if not _ctx_features:
                _m = _RE_FEATURES_IN_HISTORY.search(_text)
                if _m:
                    _ctx_features = _m.group(1).strip().replace(" | ", ",")
            if not _ctx_image_path:
                _m = _RE_IMAGE_IN_HISTORY.search(_text)
                if _m:
                    _ctx_image_path = _m.group(1)
            if _ctx_category and _ctx_features:
                break
    # 从 query 自身也尝试提取（兜底）
    if not _ctx_category:
        _m = _RE_CATEGORY_IN_QUERY.search(query)
        if _m:
            _ctx_category = _m.group(1).strip()
    if not _ctx_features:
        _m = _RE_FEATURES_IN_QUERY.search(query)
        if _m:
            _ctx_features = _m.group(1).strip().replace(" | ", ",")[:200]
    if not _ctx_category:
        _ctx_category = "玻璃杯"  # 兜底品类（上下文完全缺失时保证工具可调用）
    return _ctx_category, _ctx_features, _ctx_image_path


def _route_followup_generation(
    query: str, chat_history: list, guard: Any, session_id: str, start: float, verbose: bool
) -> Optional[Dict[str, Any]]:
    """规则2：选品报告后的序号输入（1/2/3/全部生成）→ 强制调用对应素材工具。"""
    _followup_match = re.match(r"^\s*(1|2|3|全部生成|全部)\s*$", query.strip())
    if not _followup_match:
        return None
    _choice = _followup_match.group(1)
    logger.info("[Agent] 检测到素材生成序号: %s", _choice)

    _ctx_category, _ctx_features, _ctx_image_path = _extract_generation_context(chat_history, query)
    logger.info(
        "[Agent] 检测到素材生成序号: %s (品类=%s, image=%s)",
        _choice, _ctx_category, _ctx_image_path[:40] if _ctx_image_path else "无",
    )

    _answer = ""
    _tools_used: List[Dict[str, str]] = []

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
        # 全部生成：依次调用三类素材工具
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

    if not _answer:
        return None

    verify = guard.verify(_answer, "", _answer)
    final_answer = guard.annotate_answer(_answer, verify)
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

    return _finalize(final_answer, _answer, _tools_used, verify, session_id, start, query, verbose)
