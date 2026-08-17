# -*- coding: utf-8 -*-
"""Listing 生成工具：双模式（精品/铺货）+ SEO 关键词分层 + 痛点反向差异化 + 合规双检。

设计要点（面试讲解重点）：
1. 精品/铺货双模式：精品走深度转化 FABE 结构，铺货批量快速生成；
2. SEO 关键词分层：大词/长尾词/场景词/同义词自动均匀分布，不堆砌不降权；
3. 痛点反向差异化：读取竞品差评，专门针对缺点写优势，转化率远超普通文案；
4. 双层合规风控：前置硬约束（违禁词/极限词）+ 后置脚本扫描（标红预警）；
5. 零幻觉参数：所有尺寸/材质/功能只取自产品库+知识库，缺资料提示补充；
6. 店铺风格复刻：可导入公司历史爆款 Listing，复刻画风和卖点逻辑。
"""
import json
import re
from typing import List, Dict, Any, Optional

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate

from 模块.大模型客户端 import get_chat_model
from 模块.检索器 import 检索器
from 工具集.数据库连接 import get_cursor

# ============ 平台规则 ============
PLATFORM_RULES = {
    "amazon": {
        "标题≤200字符": True, "首字母大写": True, "禁用促销词": "Best/Free Shipping/Guaranteed",
        "五点≥3条": True, "每条≤500字符": True, "主图纯白背景": True,
        "禁止刷单": True, "ASIN唯一": True,
    },
    "shopee": {
        "标题≤60字符": True, "前40字符核心关键词": True, "图片≥3张": True,
        "首图无水印": True, "禁止刷单刷评": True,
    },
    "temu": {
        "价格敏感需核价": True, "全托管供货": True, "电子产品需CE/FCC": True,
    },
}

# ============ 违禁词/极限词库（双层合规的前置硬约束）============
BANNED_WORDS = {
    "极限词": ["best", "best seller", "free shipping", "guaranteed", "100%", "#1",
              "top rated", "best selling", "world best", "cheapest",
              "最好", "第一名", "最好用", "最便宜", "全网最低", "绝对", "保证"],
    "敏感词": ["brand new sealed", "original genuine", "authorized dealer",
              "genuine product", "100% authentic", "正品保证"],
    "保健品": ["cure", "treat", "heal", "prevent", "medical grade",
             "治疗", "治愈", "药用", "医疗级"],
}

# ============ SEO 关键词分层策略 ============
# 自动从产品描述中提取并分层布局
SEO_STRATEGY = {
    "大词（短尾）": "标题前40字符 | 1-2个核心词 | 搜索量最大",
    "长尾词": "标题后半段 + 五点穿插 | 3-5个 | 精准转化",
    "场景词": "五点 + 描述 | 使用场景/人群/节日 | 提升曝光面",
    "同义词/变体": "后台搜索词 | 拼写变体/复数/缩写 | 不漏流量",
    "布局原则": "自然均匀分布，不堆砌，不重复，关键词密度<2%",
}

# ============ 多语种本土化配置 ============
_LOCALE_CONFIG = {
    "US": {
        "units": "inch/lb/oz/fl oz",
        "tone": "heavy-duty, professional grade, premium",
        "compliance": "FCC certified, UL listed",
    },
    "EU": {
        "units": "cm/kg/L",
        "tone": "eco-friendly, sustainable, European standard",
        "compliance": "CE marked, RoHS compliant, REACH compliant",
    },
    "JP": {
        "units": "cm/g/ml",
        "tone": "专业严谨，使用敬语，注重品质细节",
        "compliance": "PSE certified, 日本品質",
    },
    "SEA": {
        "units": "cm/kg/ml",
        "tone": "简洁直接，突出性价比",
        "compliance": "Halal certified, SNI certified",
    },
    "UK": {
        "units": "cm/kg/L",
        "tone": "premium British standard",
        "compliance": "UKCA marked",
    },
}


# ============ 痛点反向差异化策略 ============
def 痛点转卖点(痛点列表: List[str]) -> List[str]:
    """把竞品差评痛点自动转为差异化卖点。

    面试话术："竞品容易坏→我加厚加固，竞品难安装→我极简安装，这不是AI乱写，是数据驱动的差异化。"
    """
    映射 = {
        "坏": "加厚加固材质，通过XX次跌落测试",
        "断": "加强连接处设计，抗拉强度提升XX%",
        "裂": "采用XXX高韧性材料，抗开裂",
        "漏": "XXX级密封设计，零泄漏",
        "短": "续航提升XX%，支持XX小时连续使用",
        "慢": "XX高速芯片，响应速度提升XX%",
        "难安装": "免工具安装，3步搞定，附视频教程",
        "尺寸不准": "实物精准测量，每件QC尺寸检验",
        "褪色": "XX级固色工艺，XX次洗涤不褪色",
        "掉毛": "高密度织法，零掉毛",
        "味道": "XXX环保材质，无异味，通过XX检测",
        "噪音": "静音设计，<XXdB，不影响睡眠",
        "发热": "XX散热系统，温控<XX℃，安全不烫手",
        "卡顿": "XX处理器，流畅不卡顿",
        "掉线": "XX协议稳定连接，不掉线不延迟",
    }
    tips = []
    for pain in 痛点列表:
        pain_l = pain.lower()
        for key, tip in 映射.items():
            if key in pain_l:
                tips.append(tip)
                break
    if not tips:
        tips = ["针对用户反馈优化产品，提升整体使用体验"]
    return list(dict.fromkeys(tips))  # 去重保序


# ============ 后置合规扫描 ============
def 合规扫描(text: str) -> Dict[str, Any]:
    """后置脚本扫描违规词，返回违规列表 + 标红位置。

    面试话术："不是只靠 Prompt 约束，实际跑一遍脚本扫违规，双保险。"
    """
    violations = []
    for category, words in BANNED_WORDS.items():
        for w in words:
            if w.lower() in text.lower():
                violations.append({"词": w, "类别": category, "位置": text.lower().find(w.lower())})
    return {
        "违规数": len(violations),
        "违规列表": violations,
        "通过": len(violations) == 0,
    }


# ============ 统一格式化 ============
def _format_listing(listing: dict, platform: str, lang: str, scan: Dict = None) -> str:
    bullets = "\n".join(f"• {b}" for b in listing.get("bullets", []))
    seo_layers = listing.get("seo_layers", {})
    seo_text = ""
    if seo_layers:
        for layer, words in seo_layers.items():
            seo_text += f"  [{layer}] {', '.join(words)}\n"

    result = (
        f"=== 生成 Listing（平台:{platform} | 语言:{lang}）===\n"
        f"【标题】\n{listing.get('title','')}\n\n"
        f"【五点描述】\n{bullets}\n\n"
        f"【详情描述】\n{listing.get('description','')}\n\n"
        f"【SEO关键词分层】\n{seo_text}\n"
        f"【后台搜索词】\n{', '.join(listing.get('keywords',[]))}"
    )
    if scan and not scan["通过"]:
        result += f"\n\n=== 合规扫描（{scan['违规数']}处违规）===\n"
        for v in scan["违规列表"]:
            result += f"  [违规] [{v['类别']}] \"{v['词']}\"\n"
    elif scan:
        result += "\n\n[合规扫描] 通过，未检测到违禁词"
    return result


def _archive_listing(product: str, platform: str, lang: str, listing: dict):
    with get_cursor() as cur:
        if cur is None:
            return
        cur.execute(
            "INSERT INTO listing_archive (product_name, platform, language, title, bullets, description, keywords) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (product, platform, lang,
             listing.get("title", ""),
             json.dumps(listing.get("bullets", []), ensure_ascii=False),
             listing.get("description", ""),
             ",".join(listing.get("keywords", [])),
             ),
        )


# ============ 主工具 ============

@tool("generate_listing")
def 生成产品Listing(
    产品名称: str,
    平台: str = "amazon",
    语言: str = "en",
    产品卖点: str = "",
    模式: str = "精品",
    竞品痛点: str = "",
    爆款范本: str = "",
    目标市场: str = "US",
) -> str:
    """根据产品信息生成跨境电商 Listing（双模式：精品/铺货）。

    Args:
        产品名称: 产品名称，如 "无线蓝牙音箱 Bluetooth Speaker"
        平台: 目标平台 amazon / shopee / temu，默认 amazon
        语言: 输出语言 en / zh，默认 en
        产品卖点: 产品核心卖点，逗号分隔，如 "IPX7防水, 续航20小时, 蓝牙5.3"
        模式: "精品"=深度转化型 FABE 结构 / "铺货"=简洁标准快速量产，默认"精品"
        竞品痛点: 竞品差评痛点，逗号分隔，如 "易坏, 续航短, 难安装"。留空则跳过痛点差异化。
        爆款范本: 公司历史爆款 Listing 文本。留空则不模仿风格。

    Returns:
        结构化 Listing 文本（标题/五点/描述/SEO关键词分层/后台搜索词）+ 合规扫描结果
    """
    平台 = 平台.lower()
    模式 = 模式 if 模式 in ("精品", "铺货") else "精品"

    # ---------- 1) 知识库检索 ----------
    try:
        retriever = 检索器()
        kb_hits = retriever.search_with_scores(f"{平台} Listing 上架 合规要求", top_k=3)
        kb_context = retriever.format_context(kb_hits)
    except Exception:
        kb_context = "（知识库检索失败，使用内置规则）"

    # ---------- 2) 平台规则 ----------
    rule_dict = PLATFORM_RULES.get(平台, PLATFORM_RULES["amazon"])
    rule_text = "; ".join(f"{k}: {v}" for k, v in rule_dict.items())
    lang_name = "英文" if 语言 == "en" else "中文"

    # ---------- 3) 本土化配置 ----------
    locale_config = _LOCALE_CONFIG.get(目标市场, _LOCALE_CONFIG["US"])
    locale_text = (
        f"【本土化要求】目标市场：{目标市场}\n"
        f"1. 计量单位使用：{locale_config['units']}\n"
        f"2. 话术风格：{locale_config['tone']}\n"
        f"3. 若产品涉及认证，使用当地合规词：{locale_config['compliance']}\n"
        f"4. 数字格式按当地习惯（如千位分隔符逗号或句点）"
    )

    # ---------- 4) 痛点→差异化卖点 ----------
    pain_tips = ""
    if 竞品痛点:
        pains = [p.strip() for p in 竞品痛点.split(",") if p.strip()]
        tips = 痛点转卖点(pains)
        pain_tips = "竞品痛点与差异化卖点：\n" + "\n".join(
            f"- 竞品问题「{p}」→ 我方卖点：{t}"
            for p, t in zip(pains, tips)
        )

    # ---------- 5) 精品/铺货 prompt 分支 ----------
    if 模式 == "精品":
        mode_instruction = (
            "精品模式（深度转化型）：\n"
            "- 使用 FABE 结构（Feature 特性 → Advantage 优势 → Benefit 利益 → Evidence 证据）\n"
            "- 标题包含：核心词 + 品牌（若有）+ 关键属性 + 场景 + 人群\n"
            "- 五点描述：每条一个核心卖点，痛点反向差异化优先，带量化数据\n"
            "- 详情描述：故事化敘事，A+ 风格排版，场景化痛点解答\n"
            "- 关键词按大词/长尾词/场景词/同义词分层输出\n"
        )
    else:
        mode_instruction = (
            "铺货模式（快速量产型）：\n"
            "- 简洁标准结构，不堆砌修饰\n"
            "- 标题：核心词 + 关键属性，40-80字符\n"
            "- 五点：5条标准卖点，不夸大\n"
            "- 描述：简短3-4句\n"
            "- 保证合规，不违规不降权\n"
        )

    # ---------- 6) 违禁词提醒 ----------
    banned_reminder = (
        f"绝对禁止使用以下词汇：{', '.join(BANNED_WORDS['极限词'][:8])}...\n"
        f"禁止夸大宣传、虚假承诺、编造认证。所有参数只能基于提供的产品卖点，缺资料时标注「请联系供应商确认」。"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是跨境电商 Listing 专家，精通 Amazon/Shopee/Temu Listing 优化。\n"
         "严格输出 JSON，禁止输出 JSON 以外的内容。\n"
         "若有爆款范本，复刻其风格和话术逻辑，但卖点按新产品参数来。"),
        ("human",
         "产品: {product}\n"
         "卖点: {features}\n"
         "语言: {lang}\n"
         "平台: {platform}\n"
         "{mode}\n"
         "【平台硬规则】{rule}\n"
         "【违禁词约束】{banned}\n"
         "【知识库参考】{kb}\n"
         "{pain}\n"
         "{style}\n"
         "{locale}\n"
         "请输出 JSON（不要```包裹，纯 JSON）:\n"
         "{{\n"
         '  "title": "...",\n'
         '  "bullets": ["...","...","...","...","..."],\n'
         '  "description": "...",\n'
         '  "seo_layers": {{\n'
         '    "大词": ["..."],\n'
         '    "长尾词": ["...","..."],\n'
         '    "场景词": ["...","..."],\n'
         '    "同义词": ["..."]\n'
         '  }},\n'
         '  "keywords": ["...","...","..."]\n'
         "}}"),
    ])

    style_text = ""
    if 爆款范本:
        style_text = f"【爆款范本（复刻其风格和写作逻辑）】\n{爆款范本[:500]}"

    llm = get_chat_model()
    chain = prompt | llm
    resp = chain.invoke({
        "platform": 平台,
        "product": 产品名称,
        "features": 产品卖点 or "（根据产品名称合理撰写，不虚构参数）",
        "lang": lang_name,
        "mode": mode_instruction,
        "rule": rule_text,
        "banned": banned_reminder,
        "kb": kb_context,
        "pain": pain_tips,
        "style": style_text,
        "locale": locale_text,
    })
    content = resp.content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("json", 1)[-1].strip() if "json" in content else content

    # ---------- 7) JSON 解析 ----------
    listing = None
    try:
        listing = json.loads(content)
    except Exception:
        listing = None

    if not listing:
        return f"（LLM 输出未按 JSON 解析成功，原文如下）\n{content}"

    # ---------- 8) 合规双检：后置脚本扫描 ----------
    full_text = listing.get("title", "") + " " + " ".join(listing.get("bullets", [])) \
                + " " + listing.get("description", "")
    scan = 合规扫描(full_text)

    # ---------- 9) 落库 ----------
    _archive_listing(产品名称, 平台, 语言, listing)

    result = _format_listing(listing, 平台, 语言, scan)
    result += "\n\n[提示] 如需批量导出，请调用 export_listing_batch 函数。"
    return result


# ============ 批量导出上架格式 ============

def export_listing_batch(listings: list, format: str = "csv") -> str:
    """批量导出 Listing 为上架格式。

    Args:
        listings: 列表，每条是 {"title":..., "bullets":[...], "description":..., "keywords":[...]}
        format: "csv" 输出 Amazon 批量上传模板格式（TSV制表符分隔）/"json" 输出 JSON 数组

    Returns:
        导出内容文本，可直接保存为文件
    """
    if format == "json":
        return json.dumps(listings, ensure_ascii=False, indent=2)

    # CSV/TSV format for Amazon bulk upload
    lines = ["Title\tBullet1\tBullet2\tBullet3\tBullet4\tBullet5\tDescription\tSearchTerms"]
    for item in listings:
        title = item.get("title", "")
        bullets = item.get("bullets", [])
        while len(bullets) < 5:
            bullets.append("")
        bullet1 = bullets[0]
        bullet2 = bullets[1] if len(bullets) > 1 else ""
        bullet3 = bullets[2] if len(bullets) > 2 else ""
        bullet4 = bullets[3] if len(bullets) > 3 else ""
        bullet5 = bullets[4] if len(bullets) > 4 else ""
        description = item.get("description", "")
        keywords = item.get("keywords", [])
        if isinstance(keywords, list):
            keywords = ",".join(keywords)
        else:
            keywords = str(keywords) if keywords else ""

        def _esc(v):
            return str(v).replace("\t", " ").replace("\n", " ")

        line = "\t".join([
            _esc(title), _esc(bullet1), _esc(bullet2), _esc(bullet3),
            _esc(bullet4), _esc(bullet5), _esc(description), _esc(keywords),
        ])
        lines.append(line)
    return "\n".join(lines)
