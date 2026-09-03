# -*- coding: utf-8 -*-
"""智能客服模块：为跨境电商系统提供「买家售前售后接待」与「卖家客服话术助手」两大场景。

设计要点（面试讲解重点）：
1. 双场景分工：
   - 买家模式 (buyer)：面向终端消费者，处理售前/售后咨询，内置 FAQ 知识库 + 示例订单查询，
     回答附带"转人工 / 人工评价"能力；
   - 卖家模式 (seller)：面向跨境卖家，输入买家提问，生成专业、合规、带安抚语气的话术建议。
2. 降级链（沿用项目既有惯例）：
   - 订单查询：内置示例订单（可直接演示） → 预留真实订单/物流 API 替换位（仅需实现 _query_order_real）；
   - 意图识别：正则/关键词快速命中（快、确定、不耗 token） → LLM 兜底生成（灵活）；
3. 多轮会话：复用 记忆模块 持久化，跨轮次记录买家上下文；
4. 幻觉治理：买家/卖家的 LLM 生成结果都过 幻觉治理器，低置信自动追加风险提示；
5. 人工评价：复用 反馈闭环 的 record_feedback，买家可对回答给好评/差评，反向优化系统。

对应 JD 职责"客服流程/工单系统"与"面向用户的服务体验"。
"""
import re
import time
from typing import Dict, Any, List, Optional

from config import KNOWLEDGE_DIR
from 模块.大模型客户端 import get_chat_model
from 模块.幻觉治理 import get_guard
from 模块.反馈闭环 import record_feedback
from 模块.日志统计 import get_file_logger
logger = get_file_logger("智能客服")


# ============ 买家模式：FAQ 知识库（内置基线） ============
# 命中即返回确定答案（不耗 token、不编造）；未命中才走 LLM 生成。
_FAQ_KB: List[Dict[str, Any]] = [
    {
        "keys": ["物流", "发货", "多久", "到货", "时效", "配送", "快递", "几天"],
        "answer": (
            "您好，跨境商品通常采用空运或专线小包配送，预计 7~15 个自然日送达（偏远地区约 2~3 周）。\n"
            "具体时效以您订单详情页显示的物流轨迹为准。若超时未收到，可随时发我订单号帮您核查，或转人工跟进。"
        ),
    },
    {
        "keys": ["退", "换货", "退款", "退货", "7天", "14天", "售后", "不满意"],
        "answer": (
            "我们支持收货后 15 天内无理由退换货（商品需保持完好未使用）。\n"
            "退款将在收到退回商品并验货后的 3~5 个工作日内原路返回。\n"
            "如商品有质量问题，可提供照片/视频，我们将为您优先处理换货或退款，运费由我们承担。"
        ),
    },
    {
        "keys": ["尺码", "尺寸", "大小", "合身", "多大", "身高", "体重"],
        "answer": (
            "商品的详细尺寸表在详情页「规格参数」中可见。\n"
            "建议下单前对照自己的日常尺码选择。如果拿不准，可把您的身高体重发我，我帮您推荐最合适的尺码。"
        ),
    },
    {
        "keys": ["材质", "面料", "成分", "什么做的", "环保", "过敏", "安全"],
        "answer": (
            "商品使用的材质、成分均在详情页标注，且符合出口目的国的环保与安全标准。\n"
            "如您对特定材质过敏，建议下单前先确认成分表，也可告诉我您的顾虑，我为您进一步核实。"
        ),
    },
    {
        "keys": ["支付", "付款", "能不能", "方式", "信用卡", "支付宝", "paypal", "分期"],
        "answer": (
            "我们支持的支付方式以结算页为准，通常包含主流信用卡（Visa/Mastercard）、PayPal 及部分地区本地支付。\n"
            "所有支付均为加密处理，交易安全有保障。"
        ),
    },
    {
        "keys": ["关税", "税", "增值税", "额外收费", "运费"],
        "answer": (
            "跨境订单在结算页会包含商品价格与运费；是否产生目的国关税/增值税取决于当地政策与商品价值，"
            "以海关实际的清关结果为准，通常下单时即可在物流详情中查看。"
            "如您对税费有疑问，可提供订单号，我协助您核实或转人工专员处理。"
        ),
    },
    {
        "keys": ["保修", "质保", "坏了", "故障", "不能用", "维修", "一年"],
        "answer": (
            "本商品享受 12 个月质保。外观不影响使用的细微瑕疵不属保修范围；\n"
            "若出现非人为损坏的质量问题，可提供故障描述和照片，我们将按情况提供换新或维修服务。"
        ),
    },
    {
        "keys": ["客服", "人工", "转人工", "投诉", "电话"],
        "answer": (
            "收到，我这就为您转接人工客服。请稍候，人工客服将在数分钟内接入，"
            "并会带着我们本次沟通的记录继续为您服务，无需重复说明。"
        ),
    },
    {
        "keys": ["优惠", "折扣", "优惠券", "促销", "活动", "减"],
        "answer": (
            "店铺现有限时优惠与满减活动可查看商品页与首页 banner。\n"
            "部分商品支持叠加优惠券，下单前可先领取。如您对某款商品有意向，我也可以帮您确认当前是否有专属优惠。"
        ),
    },
]

# ============ 买家模式：示例订单数据（可直接演示） ============
# 每条含各阶段物流轨迹；真实业务中应整体替换为 _query_order_real 的 API 返回。
_ORDERS: Dict[str, Dict[str, Any]] = {
    "ORD2026053010": {
        "order_no": "ORD2026053010",
        "product": "便携蓝牙音箱",
        "qty": 1,
        "created": "2026-05-28",
        "status": "已签收",
        "track": [
            {"t": "2026-05-28 10:12", "desc": "商家已确认订单，进入备货"},
            {"t": "2026-05-30 09:00", "desc": "包裹已揽收，发往目的国"},
            {"t": "2026-06-08 14:22", "desc": "到达目的国海关，清关中"},
            {"t": "2026-06-11 11:05", "desc": "海关放行，转国内末端派送"},
            {"t": "2026-06-13 16:40", "desc": "已签收，签收人：王先生"},
        ],
    },
    "ORD2026071803": {
        "order_no": "ORD2026071803",
        "product": "陶瓷保温杯",
        "qty": 2,
        "created": "2026-07-16",
        "status": "运输中",
        "track": [
            {"t": "2026-07-16 15:30", "desc": "商家已确认订单，进入备货"},
            {"t": "2026-07-18 08:45", "desc": "包裹已揽收，发往目的国"},
        ],
    },
    "ORD2026081008": {
        "order_no": "ORD2026081008",
        "product": "大容量旅行充电宝",
        "qty": 1,
        "created": "2026-08-10",
        "status": "清关中",
        "track": [
            {"t": "2026-08-10 12:00", "desc": "商家已确认订单，进入备货"},
            {"t": "2026-08-12 10:20", "desc": "包裹已揽收，发往目的国"},
            {"t": "2026-08-16 09:35", "desc": "到达目的国海关，清关中"},
        ],
    },
}

# 从买家提问中提取订单号
_ORDER_RE = re.compile(r"[Oo][Rr][Dd][-]?\d{9,}", )


def _extract_order_no(query: str) -> Optional[str]:
    """从买家提问中提取订单号（如 ORD2026053010）。"""
    m = _ORDER_RE.search(query)
    if m:
        return m.group(0).upper().replace("-", "")
    # 兼容：连续 10 位以上的纯数字
    m = re.search(r"\d{10,}", query)
    return m.group(0) if m else None


def _query_order(order_no: str) -> Optional[Dict[str, Any]]:
    """查询订单详情。降级链：内置示例 → 预留真实 API 替换位。

    真实接入时：实现 _query_order_real(order_no) 返回与 _ORDERS 同结构的数据，
    并把下方 `return _query_order_real(...)` 取消注释、删除基线分支即可。
    """
    if order_no in _ORDERS:
        return _ORDERS[order_no]
    # ---- 预留真实订单/物流 API 替换位（默认关闭，未接入则返回 None）----
    # real = _query_order_real(order_no)
    # if real:
    #     return real
    return None


def _has_faq_hit(query: str) -> Optional[str]:
    """FAQ 关键词命中：返回确定答案；未命中返回 None。"""
    for faq in _FAQ_KB:
        if any(k in query for k in faq["keys"]):
            return faq["answer"]
    return None


def _format_order(order: Dict[str, Any]) -> str:
    """把订单数据渲染成给买家的文本。"""
    track = "\n".join(f"  · {t['t']}  {t['desc']}" for t in order["track"][-4:])
    return (
        f"■ 订单 {order['order_no']}：{order['product']} ×{order['qty']}\n"
        f"■ 当前状态：{order['status']}\n"
        f"■ 下单时间：{order['created']}\n"
        f"■ 物流轨迹：\n{track}\n"
        f"如需进一步核实，我可为您转人工专员跟进。"
    )


# ============ LLM 生成（买家/卖家共用） ============
def _llm_chat(system: str, history: List[Dict[str, str]]) -> str:
    """调用大模型生成回答。history 为 [{role, content}]，末条通常为用户当前问题。"""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    llm = get_chat_model(temperature=0.3)
    msgs: List[Any] = [SystemMessage(content=system)]
    for m in history[-6:]:  # 近几轮记忆，控制 token
        if m["role"] == "user":
            msgs.append(HumanMessage(content=m["content"]))
        else:
            msgs.append(AIMessage(content=m["content"]))
    # 确保以一条用户消息结尾（前端已 append，此处兜底）
    if not msgs or not isinstance(msgs[-1], HumanMessage):
        msgs.append(HumanMessage(content=history[-1]["content"] if history else "请继续"))
    return llm.invoke(msgs).content


# 买家回复的 system prompt：亲切、简洁、克制、不编造
_BUYER_SYSTEM = (
    "你是跨境电商店铺的智能客服，服务对象是海外买家或其咨询通道。\n"
    "回复要求：\n"
    "1. 语气亲切有耐心，使用中文，回复简洁专业；\n"
    "2. 只回答与商品、物流、售后、支付、尺码材质等售前售后相关问题；\n"
    "3. 涉及具体政策/时效/费用时，若无法确认必须如实说明，不得编造数字或承诺；\n"
    "4. 买家要求转人工/投诉时，应同意转接并安抚，不与其争辩；\n"
    "5. 若问题超出客服范围，礼貌引导并提供转人工建议；\n"
    "6. 禁止使用 emoji，用纯文字表达。"
)


def buyer_reply(query: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """买家客服统一入口：订单查询 / FAQ命中 / LLM生成，返回 {reply, type, grounded}。

    - type: order=订单查询, faq=FAQ命中, llm=大模型生成, suggest_transfer=建议转人工
    """
    # 1) 订单号查询（确定性优先）
    order_no = _extract_order_no(query)
    if order_no:
        order = _query_order(order_no)
        if order:
            return {"reply": _format_order(order), "type": "order", "grounded": True, "order_no": order_no}
        return {
            "reply": f"抱歉，未查询到订单 {order_no} 的信息。请核对订单号是否正确；如确认无误，我可为您转人工专员核实。",
            "type": "order", "grounded": True, "order_no": order_no, "not_found": True,
        }

    # 2) FAQ 关键词命中（确定答案，不耗 token）
    faq = _has_faq_hit(query)
    if faq:
        return {"reply": faq, "type": "faq", "grounded": True}

    # 3) 订单/物流状态类但没带单号 → 引导提供订单号
    if any(k in query for k in ["我的订单", "订单状态", "物流到哪", "我的快递", "查订单"]):
        return {
            "reply": "请把您的订单号发给我（例如：ORD2026053010），我立即帮您查询物流与配送状态。",
            "type": "guide", "grounded": True,
        }

    # 4) LLM 兜底生成（过幻觉治理）
    try:
        # 注：history 末尾已是当前问题（前端/服务层已 append），此处复用最近一轮即可
        answer = _llm_chat(_BUYER_SYSTEM, history + [{"role": "user", "content": query}])
    except Exception as e:  # noqa: BLE001
        # 降级：不回显原始异常，给买家一个客服兜底
        return {
            "reply": "抱歉，我暂时无法连接智能服务，请稍后再试或直接转人工客服为您处理。",
            "type": "error", "grounded": False, "error": str(e)[:120],
        }

    guard = get_guard()
    result = guard.verify(answer, "", tool_context="")
    reply = guard.annotate_answer(answer, result)
    return {"reply": reply, "type": "llm", "grounded": result.grounded,
            "score": result.grounding_score}


# ============ 卖家模式：客服话术助手 ============
_SELLER_SYSTEM = (
    "你是跨境电商卖家的资深客服话术顾问。用户会给你一段『买家咨询』（可能是原文或场景描述），"
    "请你生成一段可直接复制发给买家的回复话术。\n"
    "话术要求：\n"
    "1. 亲和专业、安抚买家情绪，让买家感到被重视；\n"
    "2. 对政策/时效/费用等事实性内容只做通用表述或引导确认，不编造具体承诺；\n"
    "3. 包含：共情开场 → 明确答复/引导 → 提供后续动作（如补发/退款/转专员）；\n"
    "4. 配一段『要点解析』：说明这样回复的处理逻辑和店铺话术技巧；\n"
    "5. 输出格式：\n"
    "   【建议话术】\n"
    "    ...（可直接复制的回复）...\n"
    "   【要点解析】\n"
    "   · ...\n"
    "6. 禁止使用 emoji。"
)


def seller_reply(query: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """卖家话术助手：生成可复制话术 + 要点解析。"""
    try:
        answer = _llm_chat(_SELLER_SYSTEM, history + [{"role": "user", "content": query}])
    except Exception as e:  # noqa: BLE001
        return {"reply": "话术生成失败，请稍后再试。", "type": "error",
                "grounded": False, "error": str(e)[:120]}

    guard = get_guard()
    result = guard.verify(answer, "", tool_context="")
    return {"reply": guard.annotate_answer(answer, result), "type": "seller",
            "grounded": result.grounded, "score": result.grounding_score}


# ============ 转人工 ============
def build_transfer_summary(history: List[Dict[str, str]]) -> Dict[str, Any]:
    """生成本次会话摘要，供转人工时交接给坐席，避免买家重复说明。"""
    user_msgs = [m["content"] for m in history if m["role"] == "user"][-3:]
    summary = {
        "topic": user_msgs[0][:30] if user_msgs else "未说明",
        "messages": len(history),
        "user_last": user_msgs[-1] if user_msgs else "",
    }
    return summary


# ============ 人工评价（复用反馈闭环） ============
def record_review(query: str, answer: str, rating: str = "good",
                  comment: str = "") -> Dict[str, Any]:
    """买家/运营对客服回答的评价，写入反馈闭环数据库。"""
    return record_feedback(query, answer, rating, comment or ("客服好评" if rating == "good" else "客服差评"))


# ============ 知识库文档目录（供前端展示客服FAQ来源说明） ============
def list_faq_topics() -> List[str]:
    """返回客服可覆盖的 FAQ 主题列表（前端引导用）。"""
    return ["物流时效", "退换货政策", "尺码选择", "材质成分", "支付方式", "售后质保", "优惠活动", "人工客服"]


if __name__ == "__main__":
    logger.info("%s", buyer_reply("查一下我的订单 ORD2026071803", [])["reply"])
    logger.info("----")
    logger.info("%s", buyer_reply("物流一般多久能到", [])["reply"])