# -*- coding: utf-8 -*-
"""汇率转换工具：按币种查询汇率并换算金额。

对接方式：
- 优先查 MySQL exchange_rate 表（缓存快照）；
- 数据库不可用时降级到内置 MOCK_RATE；
- 生产环境可扩展为调用实时汇率 API 并回写缓存。
"""
from langchain_core.tools import tool

from 工具集.数据库连接 import get_cursor

# 内置降级汇率（演示用，与 SQL 预置一致）
MOCK_RATE = {
    ("CNY", "USD"): 0.1390,
    ("USD", "CNY"): 7.1950,
    ("CNY", "EUR"): 0.1280,
    ("USD", "EUR"): 0.9200,
    ("CNY", "JPY"): 21.4000,
    ("EUR", "USD"): 1.0870,
    ("JPY", "CNY"): 0.0467,
    ("USD", "JPY"): 151.50,
}


def _get_rate(from_cur: str, to_cur: str) -> float:
    """获取汇率，库优先，降级内置。"""
    from_cur, to_cur = from_cur.upper(), to_cur.upper()
    if from_cur == to_cur:
        return 1.0
    with get_cursor() as cur:
        if cur is not None:
            cur.execute(
                "SELECT rate FROM exchange_rate WHERE from_currency=%s AND to_currency=%s",
                (from_cur, to_cur),
            )
            row = cur.fetchone()
            if row:
                return float(row["rate"])
    return MOCK_RATE.get((from_cur, to_cur), 0.0)


@tool("convert_currency")
def 汇率换算(金额: float, 源币种: str, 目标币种: str) -> str:
    """将金额从源币种换算为目标币种，并返回汇率与换算结果。

    Args:
        金额: 需换算的金额
        源币种: 源货币代码，如 CNY、USD、EUR、JPY
        目标币种: 目标货币代码，如 CNY、USD、EUR、JPY

    Returns:
        汇率、换算结果及币种说明文本
    """
    源币种, 目标币种 = 源币种.upper(), 目标币种.upper()
    rate = _get_rate(源币种, 目标币种)
    if rate == 0.0:
        return f"暂不支持 {源币种}->{目标币种} 的汇率，请确认币种代码。"
    result = 金额 * rate
    return (
        f"汇率: 1 {源币种} = {rate:.4f} {目标币种}\n"
        f"换算结果: {金额} {源币种} = {result:.2f} {目标币种}\n"
        f"说明: 汇率来自缓存快照，实际交易以银行实时牌价为准。"
    )
