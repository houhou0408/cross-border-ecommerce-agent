# -*- coding: utf-8 -*-
"""多模型分层智能路由：按任务复杂度分配合适模型，控成本、保质量、防泄露。

设计要点（面试讲解重点）：
1. 批量铺货轻任务 → 低价国产模型（DeepSeek，控成本）
2. 精品高转化任务 → 高精度模型（保证输出质量）
3. 内部敏感数据 → 本地私有化模型（防止数据泄露）
4. 路由规则：根据 query 关键词 + 工具调用链自动判断任务级别

面试话术："不是所有任务都用最好的模型，铺货型走轻量模型控成本，精品型走高质量模型保转化。"
"""
import os
from typing import Optional

from config import LLM_CONFIG as _LLM
from langchain_core.language_models.chat_models import BaseChatModel


# ============ 多模型配置 ============
# 环境变量配置，不硬编码密钥

# 模型A：主力模型（精品任务）
PREMIUM_CONFIG = {
    "model": os.getenv("PREMIUM_MODEL", _LLM.get("model", "deepseek-chat")),
    "api_key": os.getenv("PREMIUM_API_KEY", _LLM.get("api_key", "")),
    "base_url": os.getenv("PREMIUM_BASE_URL", _LLM.get("base_url", "")),
    "temperature": 0.2,
    "max_tokens": 1024,
}

# 模型B：轻量模型（批量铺货，控成本）
LITE_CONFIG = {
    "model": os.getenv("LITE_MODEL", "deepseek-chat"),
    "api_key": os.getenv("LITE_API_KEY", _LLM.get("api_key", "")),
    "base_url": os.getenv("LITE_BASE_URL", _LLM.get("base_url", "")),
    "temperature": 0.3,
    "max_tokens": 512,
}

# 模型C：本地模型（敏感数据，默认回退到主力模型）
LOCAL_CONFIG = {
    "model": os.getenv("LOCAL_MODEL", _LLM.get("model", "deepseek-chat")),
    "api_key": os.getenv("LOCAL_API_KEY", _LLM.get("api_key", "")),
    "base_url": os.getenv("LOCAL_BASE_URL", _LLM.get("base_url", "")),
    "temperature": 0.1,
    "max_tokens": 512,
}


# ============ 任务分级关键词 ============
# 轻量任务（走 LITE 模型）
_LITE_TASKS = [
    "铺货", "批量", "快速", "简单", "翻译", "检查",
    "批量生成", "格式转换", "关键词提取",
]

# 敏感任务（走 LOCAL 模型）
_SENSITIVE_TASKS = [
    "内部", "保密", "财务", "人事", "工资", "供应商",
    "成本价", "底价", "配方", "工艺",
]

# 精品任务（走 PREMIUM 模型）— 默认
_PREMIUM_TASKS = [
    "Listing", "文案", "优化", "推广", "广告", "转化",
    "选品", "分析", "调研", "报告", "方案",
]


class 模型路由器:
    """多模型智能路由器：根据任务内容自动选择最优模型。"""

    def __init__(self):
        self._premium: Optional[BaseChatModel] = None
        self._lite: Optional[BaseChatModel] = None
        self._local: Optional[BaseChatModel] = None

    def classify(self, query: str, tools_being_used: list = None) -> str:
        """对任务分级：返回 "premium" / "lite" / "local"。

        Args:
            query: 用户当前提问
            tools_being_used: 当前任务即将调用的工具列表（用于更精准判断）
        """
        query_lower = query.lower()
        tools = [t.get("tool", "") for t in (tools_being_used or [])]

        # 1) 敏感数据 → LOCAL
        for kw in _SENSITIVE_TASKS:
            if kw in query_lower:
                return "local"

        # 2) 批量/铺货 → LITE
        for kw in _LITE_TASKS:
            if kw in query_lower:
                return "lite"
        # 铺货模式 + generate_listing → LITE
        if "generate_listing" in tools and "铺货" in query:
            return "lite"

        # 3) 精品任务 → PREMIUM（默认）
        for kw in _PREMIUM_TASKS:
            if kw in query_lower:
                return "premium"

        return "premium"  # 默认为精品

    def get_model(self, tier: str = "premium") -> BaseChatModel:
        """获取对应级别的 Chat 模型（每次新建，避免连接复用问题）。

        Args:
            tier: "premium" | "lite" | "local"
        """
        from langchain_openai import ChatOpenAI

        if tier == "lite":
            return ChatOpenAI(
                model=LITE_CONFIG["model"], api_key=LITE_CONFIG["api_key"],
                base_url=LITE_CONFIG["base_url"], temperature=LITE_CONFIG["temperature"],
                max_tokens=LITE_CONFIG["max_tokens"], request_timeout=120,
            )
        if tier == "local":
            return ChatOpenAI(
                model=LOCAL_CONFIG["model"], api_key=LOCAL_CONFIG["api_key"],
                base_url=LOCAL_CONFIG["base_url"], temperature=LOCAL_CONFIG["temperature"],
                max_tokens=LOCAL_CONFIG["max_tokens"], request_timeout=120,
            )
        return ChatOpenAI(
            model=PREMIUM_CONFIG["model"], api_key=PREMIUM_CONFIG["api_key"],
            base_url=PREMIUM_CONFIG["base_url"], temperature=PREMIUM_CONFIG["temperature"],
            max_tokens=PREMIUM_CONFIG["max_tokens"], request_timeout=120,
        )

    def get_route_info(self, query: str) -> dict:
        """获取当前请求的路由信息（供日志/前端展示）。"""
        tier = self.classify(query)
        config_map = {"premium": PREMIUM_CONFIG, "lite": LITE_CONFIG, "local": LOCAL_CONFIG}
        cfg = config_map.get(tier, PREMIUM_CONFIG)
        return {
            "tier": tier,
            "model": cfg["model"],
            "reason": f"任务级别: {tier}（基于关键词匹配）",
        }


# 模块级单例
_router: Optional[模型路由器] = None


def get_router() -> 模型路由器:
    global _router
    if _router is None:
        _router = 模型路由器()
    return _router
