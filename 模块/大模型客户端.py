# -*- coding: utf-8 -*-
"""大模型客户端工厂：统一构造 LangChain Chat 模型。

设计要点：
- 通过 OpenAI 兼容接口，可接 DeepSeek / 通义千问 / OpenAI / 本地 vLLM 等；
- 单例缓存，避免重复实例化；
- 幻觉治理需要低温度，这里默认 temperature 来自 config（已设为 0.2）。
"""
from typing import Optional
from langchain_core.language_models.chat_models import BaseChatModel

from config import LLM_CONFIG

_chat_model: Optional[BaseChatModel] = None


def get_chat_model(temperature: float = None) -> BaseChatModel:
    """获取 LangChain Chat 模型（单例）。

    Args:
        temperature: 可覆盖默认温度，如幻觉校验时用更低温度。
    """
    global _chat_model
    if _chat_model is not None and temperature is None:
        return _chat_model

    from langchain_openai import ChatOpenAI
    model = ChatOpenAI(
        model=LLM_CONFIG["model"],
        api_key=LLM_CONFIG["api_key"],
        base_url=LLM_CONFIG["base_url"],
        temperature=LLM_CONFIG["temperature"] if temperature is None else temperature,
        max_tokens=LLM_CONFIG["max_tokens"],
    )
    if temperature is None:
        _chat_model = model
    return model
