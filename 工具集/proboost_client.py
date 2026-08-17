# -*- coding: utf-8 -*-
"""Proboost MCP 客户端：封装异步 MCP 调用，提供同步接口供数据采集模块使用。

设计要点：
1. 连接复用：每次调用独立连接（MCP SSE 不支持长时间保持）
2. 同步包装：用 asyncio.run() 包裹异步调用，对上层透明
3. 字段映射：Proboost 下划线字段 → 项目中文命名字段
4. 解析适配：Proboost 返回 markdown + 内嵌转义 JSON，需特殊解析
"""
import asyncio
import time
import os
import json
import re
from typing import Dict, Any, Optional, List

# Proboost MCP 配置（优先环境变量）
_MCP_URL = os.getenv("PROBOOST_MCP_URL",
    "http://f9038a3cf3c84ecdb5e3107976b9ef84.mcp.market.alicloudapi.com/mcp-servers/ea98b07bb83c48e886549c28292388b8/mcp-servers/proboost-amazon-mcp/sse")
_MCP_TOKEN = os.getenv("PROBOOST_MCP_TOKEN", "")

# 目标市场 → Proboost site
_SITE_MAP = {
    "美国": "US", "欧盟": "DE", "英国": "UK",
    "日本": "JP", "东南亚": "US",
}


def _parse_price(raw: Any) -> Optional[float]:
    if raw is None: return None
    try: return float(raw)
    except (ValueError, TypeError): return None


def _run_async(coro):
    """在线程中安全运行 async 协程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=30)
        return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _parse_proboost_response(text: str) -> tuple:
    """解析 Proboost MCP 返回的混合格式（markdown + 内嵌转义JSON）。
    
    Proboost 返回格式：先是一大段 markdown 字段说明表格，末尾嵌入已转义 JSON 字符串。
    数据嵌在类似 `"data\":{\"records\":[{...}]}"` 的格式中。
    
    Returns:
        (records: list | None, total: int)
    """
    if not text:
        return None, 0

    # 方式1：找 JSON code fence
    m = re.search(r'```json\s*\n([\s\S]*?)\n```', text)
    if m:
        try:
            data = json.loads(m.group(1))
            records = data.get("data", {}).get("records", []) or []
            total = int(data.get("data", {}).get("total", 0) or 0)
            if records:
                return records, total
        except json.JSONDecodeError:
            pass

    # 方式2：数据嵌在转义文本中，找 \"data\": 并提取
    # 格式类似: "data\":{\"records\":[{...}],\"total\":\"5\"}
    m = re.search(r'"data\\":\s*\{', text)
    if m:
        start = m.start()
        # 从 start 开始向前找第一个 {
        brace_start = text.find('{', start)
        if brace_start < 0:
            return None, 0
        
        # 手动匹配花括号找完整 JSON
        depth = 0
        in_str = False
        escaped = False
        end_pos = brace_start
        for i in range(brace_start, len(text)):
            c = text[i]
            if escaped:
                escaped = False
                continue
            if c == '\\':
                escaped = True
                continue
            if c == '"' and not escaped:
                in_str = not in_str
                continue
            if not in_str:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break
        
        json_str = text[brace_start:end_pos]
        # 先尝试直接解析
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 可能是双重转义，先 unescape 再解析
            unescaped = json_str.replace('\\"', '"').replace('\\\\', '\\')
            try:
                data = json.loads(unescaped)
            except json.JSONDecodeError:
                # 最后尝试用 ast.literal_eval 或更宽松的解析
                try:
                    # JSON 里的转义问题，尝试 JSON 规范的转义处理
                    data = json.loads(json_str.encode().decode('unicode_escape'))
                except:
                    return None, 0
        
        records = data.get("records", []) if isinstance(data, dict) else []
        total = int(data.get("total", 0) or 0) if isinstance(data, dict) else 0
        return records, total

    return None, 0


def fetch_proboost_competitors(keyword: str, market: str = "美国", page_size: int = 20) -> Optional[Dict[str, Any]]:
    """通过 Proboost MCP 选品工具搜索竞品。"""
    site = _SITE_MAP.get(market, "US")

    async def _fetch():
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        headers = {"Authorization": _MCP_TOKEN}
        async with sse_client(_MCP_URL, headers=headers) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                all_records = []
                for page in [1, 2]:
                    result = await session.call_tool("amz_product_selection", arguments={
                        "site": site,
                        "keyword": keyword,
                        "page": page,
                        "pageSize": min(page_size, 40),
                    })
                    text = ""
                    for c in result.content:
                        if hasattr(c, 'text'):
                            text += c.text

                    records, total = _parse_proboost_response(text)
                    if records is None or not records:
                        break

                    all_records.extend(records)
                    if len(records) < page_size or total <= len(all_records):
                        break

                if not all_records:
                    return None

                competitors = []
                for item in all_records:
                    competitors.append({
                        "标题": (item.get("item_title") or "")[:80],
                        "价格": _parse_price(item.get("selling_price_dig")),
                        "币种": item.get("currency_type", "USD"),
                        "评分": _parse_price(item.get("reviews_stars")),
                        "评论数": int(item.get("reviews_ratings", 0)) if item.get("reviews_ratings") else None,
                        "BSR": None,
                        "asin": item.get("sku_id"),
                        "链接": item.get("item_link", ""),
                        "图片": item.get("main_image_url", ""),
                        "卖家": item.get("seller_name", ""),
                        "品牌": item.get("brand_name", ""),
                    })

                return {
                    "竞品列表": competitors,
                    "数据来源": "Proboost MCP（亚马逊实时）",
                    "采集时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "市场": market,
                    "域名": site,
                }

    try:
        result = _run_async(_fetch())
        if result:
            print(f"[数据采集] Proboost 采集成功 (keyword={keyword}, market={market}, 共 {len(result['竞品列表'])} 个竞品)")
        return result
    except Exception as e:
        print(f"[数据采集] Proboost MCP 异常: {e}")
        return None


def fetch_proboost_reviews(asin: str, site: str = "US", max_reviews: int = 5) -> Optional[Dict]:
    """通过 Proboost MCP 获取单个 ASIN 的用户评论。"""
    async def _fetch():
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        headers = {"Authorization": _MCP_TOKEN}
        async with sse_client(_MCP_URL, headers=headers) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()

                result = await session.call_tool("amz_review_query", arguments={
                    "site": site,
                    "skuId": asin,
                    "page": 1,
                    "pageSize": max_reviews,
                })

                text = ""
                for c in result.content:
                    if hasattr(c, 'text'):
                        text += c.text

                records, _ = _parse_proboost_response(text)
                if not records:
                    return None

                reviews = []
                for r in records[:max_reviews]:
                    reviews.append({
                        "title": (r.get("voiceTitle") or r.get("title") or "")[:120],
                        "body": (r.get("voiceContent") or r.get("content") or r.get("body") or r.get("text") or "")[:300],
                        "rating": r.get("voiceScore") or r.get("score"),
                        "date": str(r.get("gmtCreate", "")),
                    })

                return {"asin": asin, "reviews": reviews}

    try:
        result = _run_async(_fetch())
        if result:
            print(f"[数据采集] Proboost 评论采集成功 (asin={asin}, {len(result['reviews'])}条)")
        return result
    except Exception as e:
        print(f"[数据采集] Proboost 评论采集异常: {e}")
        return None
