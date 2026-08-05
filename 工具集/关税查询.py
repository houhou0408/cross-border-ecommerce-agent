# -*- coding: utf-8 -*-
"""关税查询工具：按目的国+商品类别查询关税税率，并计算应缴关税。

对接方式：
- 优先查 MySQL tariff_rule 表；
- 数据库不可用时降级到内置 MOCK_TARIFF；
- 支持 CIF 完税价格计算：应缴关税 = CIF × 税率。
"""
from langchain_core.tools import tool

from 工具集.数据库连接 import get_cursor

# 内置降级数据（与 SQL 预置数据保持一致）
MOCK_TARIFF = {
    ("美国", "电子产品"): {"hs_code": "8543.70", "tariff_rate": 0.25, "note": "部分品类加征301关税"},
    ("美国", "服装"):     {"hs_code": "6109.10", "tariff_rate": 0.163, "note": "棉制T恤"},
    ("美国", "家居用品"): {"hs_code": "3924.10", "tariff_rate": 0.035, "note": "塑料制品"},
    ("欧盟", "电子产品"): {"hs_code": "8543.70", "tariff_rate": 0.14, "note": "需CE认证"},
    ("欧盟", "服装"):     {"hs_code": "6109.10", "tariff_rate": 0.12, "note": "棉制T恤"},
    ("日本", "电子产品"): {"hs_code": "8543.70", "tariff_rate": 0.0, "note": "多数电子零关税"},
    ("日本", "服装"):     {"hs_code": "6109.10", "tariff_rate": 0.091, "note": "棉制T恤"},
}

# 简化的免税额度（de minimis）
DE_MINIMIS = {
    "美国": 800.0,
    "欧盟": 0.0,    # 2021起取消
    "日本": 10000.0,
    "英国": 135.0,
}


@tool("query_tariff")
def 查询关税(目的国: str, 商品类别: str, 货值: float = 0.0, 运费: float = 0.0, 保险费: float = 0.0) -> str:
    """查询指定目的国与商品类别的关税税率，并计算应缴关税金额。

    Args:
        目的国: 目的国/地区，如 美国、欧盟、日本、英国
        商品类别: 商品类别，如 电子产品、服装、家居用品
        货值: 商品货值（本币或美元），用于计算关税，默认0表示只查税率
        运费: 国际运费，默认0
        保险费: 保险费，默认0

    Returns:
        关税税率、HS编码、备注及应缴关税的说明文本
    """
    rule = None
    # 1) 优先查库
    with get_cursor() as cur:
        if cur is not None:
            cur.execute(
                "SELECT hs_code, tariff_rate, note FROM tariff_rule WHERE country=%s AND category=%s",
                (目的国, 商品类别),
            )
            row = cur.fetchone()
            if row:
                rule = {
                    "hs_code": row["hs_code"],
                    "tariff_rate": float(row["tariff_rate"]),
                    "note": row.get("note", ""),
                }

    # 2) 降级到内置数据
    if rule is None:
        rule = MOCK_TARIFF.get((目的国, 商品类别))

    if rule is None:
        return f"未查询到【{目的国}-{商品类别}】的关税规则，建议核实 HS 编码后补充规则。"

    rate = rule["tariff_rate"]
    # 3) 计算应缴关税
    cif = 货值 + 运费 + 保险费
    de_min = DE_MINIMIS.get(目的国, 0.0)

    lines = [
        f"目的国: {目的国}",
        f"商品类别: {商品类别}",
        f"HS编码: {rule['hs_code']}",
        f"关税税率: {rate*100:.2f}%",
        f"备注: {rule['note']}",
        f"免税额度(de minimis): {de_min} {'（按当地货币计）' if de_min else '（无免税）'}",
    ]
    if 货值 > 0:
        lines.append(f"完税价格(CIF): {cif:.2f}（货值{货值}+运费{运费}+保险{保险费}）")
        if cif <= de_min and de_min > 0:
            lines.append(f"应缴关税: 0（低于免税额度，免征）")
        else:
            duty = cif * rate
            lines.append(f"应缴关税: {duty:.2f}（CIF × {rate*100:.2f}%）")
    return "\n".join(lines)
