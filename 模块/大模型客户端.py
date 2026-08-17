# -*- coding: utf-8 -*-
"""大模型客户端工厂：统一构造 LangChain Chat 模型。

设计要点：
- 通过 OpenAI 兼容接口，可接 DeepSeek / 通义千问 / OpenAI / 本地 vLLM 等；
- 每次调用创建新实例，避免 httpx client 复用关闭导致的 "client has been closed" 错误；
- 幻觉治理需要低温度，这里默认 temperature 来自 config（已设为 0.2）。
"""
from langchain_openai import ChatOpenAI

from config import LLM_CONFIG


def get_chat_model(temperature: float = None) -> ChatOpenAI:
    """获取 LangChain Chat 模型（每次新建，避免连接复用问题）。

    Args:
        temperature: 可覆盖默认温度，如幻觉校验时用更低温度。
    """
    return ChatOpenAI(
        model=LLM_CONFIG["model"],
        api_key=LLM_CONFIG["api_key"],
        base_url=LLM_CONFIG["base_url"],
        temperature=LLM_CONFIG["temperature"] if temperature is None else temperature,
        max_tokens=LLM_CONFIG["max_tokens"],
        request_timeout=120,
    )
