# -*- coding: utf-8 -*-
"""Listing 生成工具：根据产品信息与目标平台生成电商 Listing（标题/五点/描述/关键词）。

设计要点：
- 先检索知识库获取平台合规要求（如字符数、禁用词），约束 LLM 输出，降低幻觉与违规；
- 用结构化 Prompt 保证输出格式稳定（便于落库与展示）；
- 生成结果可存档到 MySQL listing_archive 表。
"""
import json

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

from 模块.大模型客户端 import get_chat_model
from 模块.检索器 import 检索器
from 工具集.数据库连接 import get_cursor

# 平台规则提示词（与知识库一致，作为硬约束兜底）
PLATFORM_RULES = {
    "amazon": "标题≤200字符，首字母大写，禁用促销词(Best/Free Shipping)；五点≥3条、每条≤500字符；主图纯白背景。",
    "shopee": "标题≤60字符，前40字符为核心关键词；图片≥3张首图无水印；禁止刷单刷评。",
    "temu": "价格敏感需通过核价；全托管供货为主；电子产品需CE/FCC认证。",
}


@tool("generate_listing")
def 生成产品Listing(产品名称: str, 平台: str = "amazon", 语言: str = "en", 产品卖点: str = "") -> str:
    """根据产品信息生成跨境电商 Listing（标题、五点描述、详情、关键词）。

    Args:
        产品名称: 产品中英文名称，如 "无线蓝牙音箱 Bluetooth Speaker"
        平台: 目标平台 amazon / shopee / temu，默认 amazon
        语言: 输出语言 en / zh，默认 en
        产品卖点: 产品的核心卖点或参数，可选，如 "IPX7防水, 续航20小时, 蓝牙5.3"

    Returns:
        结构化 Listing 文本（标题/五点/描述/关键词）
    """
    平台 = 平台.lower()
    # 1) 检索知识库获取该平台合规要求，约束生成
    try:
        retriever = 检索器()
        kb_hits = retriever.search_with_scores(f"{平台} Listing 上架 合规要求", top_k=3)
        kb_context = retriever.format_context(kb_hits)
    except Exception:  # noqa: BLE001
        kb_context = "（知识库检索失败，使用内置规则）"

    rule = PLATFORM_RULES.get(平台, PLATFORM_RULES["amazon"])
    lang_name = "英文" if 语言 == "en" else "中文"

    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是跨境电商资深运营，精通 {platform} Listing 优化。"
                   "严格遵循以下平台规则与知识库内容，禁止编造不存在的认证或参数。"
                   "若知识库未提供某信息，请基于卖点如实撰写，不得虚构。"),
        ("human",
         "产品: {product}\n卖点: {features}\n语言: {lang}\n\n"
         "【平台硬规则】\n{rule}\n\n【知识库参考】\n{kb}\n\n"
         "请输出结构化 Listing，严格按以下 JSON 字段返回（不要输出 JSON 以外的内容）:\n"
         '{{"title": "...", "bullets": ["...","...","...","...","..."], '
         '"description": "...", "keywords": ["...","...","..."]}}'),
    ])

    llm = get_chat_model()
    chain = prompt | llm
    resp = chain.invoke({
        "platform": 平台,
        "product": 产品名称,
        "features": 产品卖点 or "（未提供，请基于产品名称合理撰写，不得虚构参数）",
        "lang": lang_name,
        "rule": rule,
        "kb": kb_context,
    })
    content = resp.content.strip()

    # 2) 尝试解析 JSON，解析失败则原样返回
    listing = None
    try:
        # 兼容 LLM 偶尔带 ```json 包裹的情况
        if content.startswith("```"):
            content = content.strip("`")
            content = content.split("json", 1)[-1].strip() if content.startswith("json") else content
        listing = json.loads(content)
    except Exception:  # noqa: BLE001
        listing = None

    # 3) 落库存档（库不可用则跳过）
    if listing:
        _archive_listing(产品名称, 平台, 语言, listing)
        return _format_listing(listing, 平台, 语言)
    return f"（LLM 输出未按 JSON 解析成功，原文如下）\n{content}"


def _format_listing(listing: dict, platform: str, lang: str) -> str:
    """格式化展示 Listing。"""
    bullets = "\n".join(f"• {b}" for b in listing.get("bullets", []))
    keywords = ", ".join(listing.get("keywords", []))
    return (
        f"=== 生成 Listing（平台:{platform} | 语言:{lang}）===\n"
        f"【标题】\n{listing.get('title','')}\n\n"
        f"【五点描述】\n{bullets}\n\n"
        f"【详情描述】\n{listing.get('description','')}\n\n"
        f"【搜索关键词】\n{keywords}"
    )


def _archive_listing(product: str, platform: str, lang: str, listing: dict):
    """把生成结果存入 MySQL（库不可用时静默跳过）。"""
    with get_cursor() as cur:
        if cur is None:
            return
        cur.execute(
            "INSERT INTO listing_archive (product_name, platform, language, title, bullets, description, keywords) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                product, platform, lang,
                listing.get("title", ""),
                json.dumps(listing.get("bullets", []), ensure_ascii=False),
                listing.get("description", ""),
                ",".join(listing.get("keywords", [])),
            ),
        )
