# -*- coding: utf-8 -*-
"""产品知识检索工具：让 Agent 能够主动检索 RAG 知识库。

这是 RAG 与 Agent 的桥接：Agent 在 ReAct 推理中，
判断需要查阅跨境电商知识时调用本工具，获取检索增强上下文。
"""
from langchain_core.tools import tool

from 模块.检索器 import 检索器

# 全局单例，避免重复加载向量库
_retriever_instance = None


def _get_retriever():
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = 检索器()
    return _retriever_instance


@tool("search_kb")
def 检索跨境电商知识(查询问题: str) -> str:
    """检索跨境电商知识库（平台政策、选品指南、物流与关税规范），返回相关知识片段。

    当需要查询亚马逊/Shopee/Temu 平台规则、选品建议、物流关税政策等知识时调用本工具。

    Args:
        查询问题: 自然语言查询，如 "亚马逊Listing标题有什么要求"

    Returns:
        检索到的知识片段（带来源与相关度），未命中时返回提示。
    """
    retriever = _get_retriever()
    results = retriever.search_with_scores(查询问题)
    if not results:
        return "知识库未检索到相关内容，请基于通用知识谨慎回答，并提示用户该信息未在知识库中核实。"
    return retriever.format_context(results)
