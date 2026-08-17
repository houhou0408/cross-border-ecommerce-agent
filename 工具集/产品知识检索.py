# -*- coding: utf-8 -*-
"""产品知识检索工具：让 Agent 能够主动检索 RAG 知识库。

这是 RAG 与 Agent 的桥接：Agent 在 ReAct 推理中，
判断需要查阅跨境电商知识时调用本工具，获取检索增强上下文。

支持四库分立检索：
  - 全部 → 搜索全量知识库
  - 产品参数 → kb_products（尺寸/材质/功能）
  - 平台规则 → kb_rules（违禁词+合规红线）
  - 爆款文案 → kb_listings（公司优质范本）
  - 风险案例 → kb_risks（违规/翻车/差评案例）
"""
from langchain_core.tools import tool

from 模块.检索器 import 检索器

# 中文知识库名 → 内部 library key 映射
_KB_NAME_MAP = {
    "产品参数": "products",
    "平台规则": "rules",
    "爆款文案": "listings",
    "风险案例": "risks",
}

# 全局单例，避免重复加载向量库
_retriever_instance = None


def _get_retriever():
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = 检索器()
    return _retriever_instance


@tool("search_kb")
def 检索跨境电商知识(查询问题: str, 知识库: str = "全部") -> str:
    """检索跨境电商知识库（平台政策、选品指南、物流与关税规范），返回相关知识片段。

    当需要查询亚马逊/Shopee/Temu 平台规则、选品建议、物流关税政策等知识时调用本工具。
    支持按知识库类型精准检索：产品参数、平台规则、爆款文案、风险案例。

    Args:
        查询问题: 自然语言查询，如 "亚马逊Listing标题有什么要求"
        知识库: 可选 "全部"（默认）、"产品参数"、"平台规则"、"爆款文案"、"风险案例"

    Returns:
        检索到的知识片段（带来源与相关度），未命中时返回提示。
    """
    kb = 知识库.strip()
    if kb == "全部":
        retriever = _get_retriever()
        kb_label = "全量知识库"
    else:
        library_key = _KB_NAME_MAP.get(kb)
        if library_key is None:
            return f"未知知识库类型: {kb}，可选值: 全部、产品参数、平台规则、爆款文案、风险案例"
        retriever = 检索器(library=library_key)
        kb_label = kb

    results = retriever.search_with_scores(查询问题)
    if not results:
        return f"知识库「{kb_label}」未检索到相关内容，请基于通用知识谨慎回答，并提示用户该信息未在知识库中核实。"

    context = retriever.format_context(results)
    return f"[知识库来源: {kb_label}]\n{context}"
