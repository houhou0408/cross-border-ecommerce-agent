# -*- coding: utf-8 -*-
"""汇率转换工具：按币种查询实时汇率并换算金额。

数据来源（三级降级）：
1. 在线汇率 API（open.er-api.com，实时采集）→ 回写 MySQL 缓存
2. MySQL exchange_rate 表（持久化快照）
3. 内置固定汇率（兜底）

采集逻辑由「数据采集」模块统一管理，本工具只负责调用与展示。
"""
from langchain_core.tools import tool

from 工具集.数据采集 import get_rate, get_rate_source


@tool("convert_currency")
def 汇率换算(金额: float, 源币种: str, 目标币种: str) -> str:
    """将金额从源币种换算为目标币种，并返回实时汇率与换算结果。

    支持 USD/CNY/EUR/JPY/GBP/KRW/SGD/MYR/THB 等主流币种，
    汇率通过在线 API 实时采集（带 1 小时缓存）。

    Args:
        金额: 需换算的金额
        源币种: 源货币代码，如 CNY、USD、EUR、JPY
        目标币种: 目标货币代码，如 CNY、USD、EUR、JPY

    Returns:
        汇率、换算结果、数据来源及更新时间
    """
    源币种, 目标币种 = 源币种.upper(), 目标币种.upper()
    rate = get_rate(源币种, 目标币种)
    if rate == 0.0:
        return f"暂不支持 {源币种}->{目标币种} 的汇率，请确认币种代码。"
    result = 金额 * rate
    source = get_rate_source()
    return (
        f"汇率: 1 {源币种} = {rate:.4f} {目标币种}\n"
        f"换算结果: {金额} {源币种} = {result:.2f} {目标币种}\n"
        f"数据来源: {source}（1 小时缓存）\n"
        f"说明: 实际交易以银行实时牌价为准。"
    )
