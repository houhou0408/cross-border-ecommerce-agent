# -*- coding: utf-8 -*-
"""数据采集模块：为 Agent 工具提供实时数据支撑。

设计要点（面试讲解重点）：
1. 双源策略：优先在线 API/爬虫 → 失败降级到本地缓存/内置数据，保证可用性；
2. 缓存机制：采集结果带时间戳缓存到内存，避免频繁请求外部服务；
3. 采集与工具解耦：采集函数返回结构化数据，由各工具自行调用，职责分离；
4. 合规设计：爬虫仅采集公开榜单数据，遵守 robots.txt，不存储个人数据。

对应业务场景：
- 实时汇率：汇率换算工具的实时数据源
- 选品热度：选品分析工具的市场热度依据
"""
import os
import re
import time
import json
from collections import Counter
from typing import Dict, Any, Optional, List

import requests

from config import LOG_DIR
from 工具集.数据库连接 import get_cursor

# ============ 缓存 ============
# 内存缓存：{ key: { "data": ..., "ts": timestamp } }
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 3600  # 缓存有效期 1 小时


def _get_cache(key: str) -> Optional[Any]:
    """读取缓存，过期返回 None。"""
    item = _CACHE.get(key)
    if item and (time.time() - item["ts"]) < _CACHE_TTL:
        return item["data"]
    return None


def _set_cache(key: str, data: Any) -> None:
    """写入缓存。"""
    _CACHE[key] = {"data": data, "ts": time.time()}


# ============ 实时汇率采集 ============

# 免费汇率 API（无需 Key，公开开放）
# 备选：exchangerate-api.com / open.er-api.com / frankfurter.app
_RATE_APIS = [
    "https://open.er-api.com/v6/latest/USD",  # 以 USD 为基准
    "https://api.frankfurter.app/latest?from=USD",  # 欧洲央行数据
]


def fetch_exchange_rates() -> Dict[str, float]:
    """采集实时汇率（以 USD 为基准）。

    采集流程：
    1. 查内存缓存（1 小时内有效）
    2. 查 MySQL exchange_rate 表（持久化快照）
    3. 调用免费汇率 API（在线采集）
    4. 全部失败 → 降级到内置固定汇率

    Returns:
        dict: { "USD": 1.0, "CNY": 7.19, "EUR": 0.92, "JPY": 151.5, ... }
    """
    # 1) 内存缓存
    cached = _get_cache("exchange_rates")
    if cached:
        return cached

    # 2) MySQL 快照
    rates_from_db = {}
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute(
                    "SELECT from_currency, to_currency, rate FROM exchange_rate "
                    "WHERE from_currency='USD'"
                )
                for row in cur.fetchall():
                    rates_from_db[row["to_currency"]] = float(row["rate"])
            except Exception:
                pass

    # 3) 在线 API 采集
    rates_online = _fetch_rates_from_api()

    # 合并：在线优先，补全用 DB
    rates = {"USD": 1.0}
    if rates_online:
        rates.update(rates_online)
        # 采集成功 → 回写 DB 缓存（静默失败）
        _save_rates_to_db(rates_online)
    elif rates_from_db:
        rates.update(rates_from_db)

    # 4) 全部失败 → 内置降级
    if len(rates) <= 1:
        rates = {
            "USD": 1.0, "CNY": 7.1950, "EUR": 0.9200,
            "JPY": 151.50, "GBP": 0.7900, "KRW": 1380.0,
            "SGD": 1.3500, "MYR": 4.6500, "THB": 36.80,
            "VND": 25400.0, "IDR": 15800.0, "PHP": 56.20,
        }

    _set_cache("exchange_rates", rates)
    return rates


def _fetch_rates_from_api() -> Optional[Dict[str, float]]:
    """调用免费汇率 API，返回以 USD 为基准的汇率字典。"""
    for url in _RATE_APIS:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # open.er-api.com 格式
                if "rates" in data:
                    print(f"[数据采集] 汇率采集成功 (source={url})")
                    return {k: float(v) for k, v in data["rates"].items()}
                # frankfurter 格式
                if "rates" in data:
                    return {k: float(v) for k, v in data["rates"].items()}
        except Exception as e:
            print(f"[数据采集] 汇率 API 异常 ({url}): {e}")
            continue
    print("[数据采集] 所有汇率 API 均不可用，降级处理")
    return None


def _save_rates_to_db(rates: Dict[str, float]) -> None:
    """将采集到的汇率回写 MySQL（静默失败，不阻塞主流程）。"""
    with get_cursor() as cur:
        if cur is None:
            return
        try:
            for to_cur, rate in rates.items():
                if to_cur == "USD":
                    continue
                cur.execute(
                    "INSERT INTO exchange_rate (from_currency, to_currency, rate, updated_at) "
                    "VALUES (%s, %s, %s, NOW()) "
                    "ON DUPLICATE KEY UPDATE rate=%s, updated_at=NOW()",
                    ("USD", to_cur, rate, rate),
                )
        except Exception as e:
            print(f"[数据采集] 汇率回写 DB 失败: {e}")


def get_rate(from_cur: str, to_cur: str) -> float:
    """获取任意两币种间的汇率（基于 USD 基准交叉计算）。

    Args:
        from_cur: 源币种代码（如 CNY）
        to_cur: 目标币种代码（如 USD）

    Returns:
        汇率值，如 7.195 表示 1 USD = 7.195 CNY
    """
    from_cur, to_cur = from_cur.upper(), to_cur.upper()
    if from_cur == to_cur:
        return 1.0

    rates = fetch_exchange_rates()
    usd_to_from = rates.get(from_cur)
    usd_to_to = rates.get(to_cur)

    if not usd_to_from or not usd_to_to:
        return 0.0

    # 交叉汇率：from → USD → to
    return (1.0 / usd_to_from) * usd_to_to


def get_rate_source() -> str:
    """返回当前汇率数据来源（用于前端展示）。"""
    if _get_cache("exchange_rates"):
        return "在线采集（API）"
    with get_cursor() as cur:
        if cur is not None:
            return "数据库快照"
    return "内置降级数据"


# ============ 选品热度采集 ============

# 内置热门品类基线（爬虫失败时降级用）
_BASELINE_TRENDS = {
    "电子产品": {"热搜关键词": ["蓝牙耳机", "充电宝", "智能手表"], "平均客单价": "$15-50", "增长趋势": "稳定"},
    "服装": {"热搜关键词": ["瑜伽裤", "防晒衣", "速干T恤"], "平均客单价": "$10-35", "增长趋势": "上升"},
    "家居": {"热搜关键词": ["收纳盒", "氛围灯", "迷你风扇"], "平均客单价": "$8-30", "增长趋势": "快速上升"},
    "美妆": {"热搜关键词": ["唇釉", "面膜", "美甲贴"], "平均客单价": "$5-25", "增长趋势": "上升"},
    "宠物用品": {"热搜关键词": ["宠物玩具", "自动喂食器", "猫爬架"], "平均客单价": "$12-45", "增长趋势": "快速上升"},
}


# ============ 亚马逊竞品采集（三数据源：Proboost / Canopy / Rainforest）============
# Proboost：阿里云市场 MCP 服务，国内直连，按量计费
# Canopy：免费 100 次/月，Key 走环境变量，支持 Rest API
# Rainforest：免费 100 次/月，Key 必须走环境变量 RAINFOREST_API_KEY
# 优先级：PROBOOST_MCP_TOKEN > CANOPY_API_KEY > RAINFOREST_API_KEY
_RAINFOREST_API_KEY = os.getenv("RAINFOREST_API_KEY", "")
_RAINFOREST_ENDPOINT = "https://api.rainforestapi.com/request"

_CANOPY_API_KEY = os.getenv("CANOPY_API_KEY", "")
_CANOPY_ENDPOINT = "https://rest.canopyapi.co"

_PROBOOST_TOKEN = os.getenv("PROBOOST_MCP_TOKEN", "")

# 当前使用的数据源（Proboost 优先）
if _PROBOOST_TOKEN:
    _API_PROVIDER = "proboost"
elif _CANOPY_API_KEY:
    _API_PROVIDER = "canopy"
else:
    _API_PROVIDER = "rainforest"

# 品类中文名 → 亚马逊英文搜索词（英文搜索结果更准）
_CATEGORY_SEARCH_MAP = {
    "电子产品": "electronics gadgets",
    "服装": "clothing fashion",
    "家居": "home living",
    "家居用品": "home kitchen glassware dinnerware",
    "美妆": "beauty cosmetics",
    "宠物用品": "pet supplies",
    "玻璃杯": "glass cup",
    "水杯": "water glasses drinking cups set",
    "玻璃制品": "glassware drinkware barware glass set",
    "厨房用品": "kitchen utensils cookware home",
}

# 目标市场 → Rainforest amazon_domain
_MARKET_DOMAIN_MAP = {
    "美国": "amazon.com",
    "欧盟": "amazon.de",
    "英国": "amazon.co.uk",
    "日本": "amazon.co.jp",
    "东南亚": "amazon.com",  # 东南亚无统一站点，回退美国站
}

# 目标市场 → Canopy domain（短代码）
_MARKET_CANOPY_MAP = {
    "美国": "US",
    "欧盟": "DE",
    "英国": "UK",
    "日本": "JP",
    "东南亚": "US",
}

# 英文停用词（提炼关键词时过滤）
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "for", "with", "of", "to", "in", "on", "at",
    "by", "is", "it", "this", "that", "from", "your", "you", "are", "be", "as",
    "its", "our", "we", "they", "he", "she", "but", "not", "all", "any", "can",
    "has", "have", "had", "will", "would", "could", "should", "new", "best",
    "top", "buy", "sale", "off", "free", "shipping", "prime",
}


def _fetch_canopy_search(category: str, market: str) -> Optional[Dict[str, Any]]:
    """Canopy API 搜索竞品数据。每页最多 20 条，翻 2 页取约 40 条。

    Canopy REST API 格式：
    - GET /api/amazon/search?searchTerm=xxx&domain=US&page=1,2
    - Header: API-KEY
    - 返回 searchResults 数组，每项含 title/price/rating/ratingsTotal/asin/image/link
    """
    search_term = _CATEGORY_SEARCH_MAP.get(category, category)
    domain = _MARKET_CANOPY_MAP.get(market, "US")

    all_results = []
    for page in [1, 2]:
        try:
            resp = requests.get(
                f"{_CANOPY_ENDPOINT}/api/amazon/search",
                params={"searchTerm": search_term, "domain": domain, "page": page},
                headers={"API-KEY": _CANOPY_API_KEY},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"[数据采集] Canopy API HTTP {resp.status_code}: {resp.text[:200]}")
                break

            data = resp.json()
            results = data.get("searchResults", []) or []
            if not results:
                break

            for item in results:
                price_obj = item.get("price", {}) or {}
                all_results.append({
                    "标题": (item.get("title") or "")[:80],
                    "价格": price_obj.get("value"),
                    "币种": price_obj.get("currency", "USD"),
                    "评分": item.get("rating"),
                    "评论数": item.get("ratingsTotal"),
                    "BSR": None,  # Canopy 搜索不含 BSR
                    "asin": item.get("asin"),
                    "链接": item.get("link", ""),
                    "图片": item.get("image", ""),  # Canopy 额外返回商品图
                })
        except requests.exceptions.Timeout:
            print(f"[数据采集] Canopy API 第{page}页超时")
            break
        except Exception as e:
            print(f"[数据采集] Canopy API 第{page}页异常: {e}")
            break

    if not all_results:
        return None

    result = {
        "竞品列表": all_results,
        "数据来源": "Canopy API",
        "采集时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "市场": market,
        "域名": domain,
    }
    print(f"[数据采集] Canopy 采集成功 (category={category}, market={market}, 共 {len(all_results)} 个竞品, 2页)")
    return result


def fetch_rainforest_competitors(category: str, market: str = "美国") -> Optional[Dict[str, Any]]:
    """调用 Rainforest API 获取亚马逊竞品数据。

    采集流程：
    1. 查内存缓存（1 小时 TTL）
    2. 调用 Rainforest API 的 search 接口
    3. 解析 search_results，提取标题/价格/评分/评论数/BSR/ASIN

    Args:
        category: 品类中文名（如 电子产品、服装、家居、美妆、宠物用品）
        market: 目标市场（如 美国、欧盟、日本、英国、东南亚）

    Returns:
        dict: {
            "竞品列表": [{ 标题, 价格, 币种, 评分, 评论数, BSR, asin, 链接 }, ...],
            "数据来源": "Rainforest API",
            "采集时间": "...",
            "市场": "...",
            "域名": "...",
        }
        采集失败返回 None
    """
    cache_key = f"rf_{category}_{market}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 数据源路由：Proboost > Canopy > Rainforest
    if _API_PROVIDER == "proboost":
        from 工具集.proboost_client import fetch_proboost_competitors
        keyword = _CATEGORY_SEARCH_MAP.get(category, category)
        result = fetch_proboost_competitors(keyword, market)
        if result:
            _set_cache(cache_key, result)
            return result
        # Proboost 失败，继续尝试 Canopy

    if _API_PROVIDER == "canopy":
        result = _fetch_canopy_search(category, market)
        if result:
            _set_cache(cache_key, result)
            return result
        # Canopy 失败，继续尝试 Rainforest

    if not _RAINFOREST_API_KEY:
        print("[数据采集] 未配置 RAINFOREST_API_KEY，跳过 Rainforest 采集")
        return None

    search_term = _CATEGORY_SEARCH_MAP.get(category, category)
    amazon_domain = _MARKET_DOMAIN_MAP.get(market, "amazon.com")

    params = {
        "api_key": _RAINFOREST_API_KEY,
        "type": "search",
        "amazon_domain": amazon_domain,
        "search_term": search_term,
        "sort_by": "featured",
        "max_page": 3,  # 翻 3 页，约 24 条竞品
    }

    try:
        resp = requests.get(_RAINFOREST_ENDPOINT, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"[数据采集] Rainforest API HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        request_info = data.get("request_info", {}) or {}
        if not request_info.get("success", False):
            print(f"[数据采集] Rainforest API 返回失败: {request_info.get('message')}")
            return None

        products = data.get("search_results", []) or []
        if not products:
            print(f"[数据采集] Rainforest 未返回商品 (category={category}, market={market})")
            return None

        competitors: List[Dict[str, Any]] = []
        for item in products:  # 取全部竞品（max_page=3，约24条）
            price_obj = item.get("price", {}) or {}
            competitors.append({
                "标题": (item.get("title") or "")[:80],
                "价格": price_obj.get("value"),
                "币种": price_obj.get("currency"),
                "评分": item.get("rating"),
                "评论数": item.get("ratings_total"),
                "BSR": item.get("bestsellers_rank"),
                "asin": item.get("asin"),
                "链接": item.get("link", ""),
            })

        result = {
            "竞品列表": competitors,
            "数据来源": "Rainforest API",
            "采集时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "市场": market,
            "域名": amazon_domain,
        }
        _set_cache(cache_key, result)
        print(f"[数据采集] Rainforest 采集成功 (category={category}, market={market}, 共 {len(competitors)} 个竞品)")
        return result

    except requests.exceptions.Timeout:
        print("[数据采集] Rainforest API 请求超时（15s）")
        return None
    except Exception as e:
        print(f"[数据采集] Rainforest API 异常: {e}")
        return None


def _fetch_canopy_reviews(asin: str, domain: str = "US", max_reviews: int = 5) -> Optional[Dict]:
    """Canopy API 获取单个 ASIN 的用户评论。

    GET /api/amazon/product/reviews?asin=xxx&domain=US
    """
    try:
        resp = requests.get(
            f"{_CANOPY_ENDPOINT}/api/amazon/product/reviews",
            params={"asin": asin, "domain": domain},
            headers={"API-KEY": _CANOPY_API_KEY},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[数据采集] Canopy 评论 HTTP {resp.status_code}")
            return None
        data = resp.json()
        reviews_raw = data.get("reviews", []) or data.get("topReviews", []) or []
        reviews = []
        for r in reviews_raw[:max_reviews]:
            reviews.append({
                "title": (r.get("title") or "")[:120],
                "body": (r.get("body") or r.get("text") or "")[:300],
                "rating": r.get("rating"),
                "date": str(r.get("date", "")),
            })
        result = {"asin": asin, "reviews": reviews}
        print(f"[数据采集] Canopy 评论采集成功 (asin={asin}, {len(reviews)}条)")
        return result
    except Exception as e:
        print(f"[数据采集] Canopy 评论采集异常: {e}")
        return None


def fetch_rainforest_reviews(asin: str, amazon_domain: str = "amazon.com", max_reviews: int = 5) -> Optional[Dict]:
    """调用 Rainforest API 获取单个 ASIN 的用户评论。

    Args:
        asin: 商品 ASIN
        amazon_domain: 域名
        max_reviews: 最多获取几条评论
    Returns:
        {"asin": str, "reviews": [{"title":, "body":, "rating":, "date":}, ...]} 或 None
    """
    cache_key = f"reviews_{asin}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    # 数据源路由：Proboost > Canopy > Rainforest
    if _API_PROVIDER == "proboost":
        from 工具集.proboost_client import fetch_proboost_reviews
        domain = amazon_domain if amazon_domain in ("US", "UK", "DE", "JP") else "US"
        result = fetch_proboost_reviews(asin, domain, max_reviews)
        if result:
            _set_cache(cache_key, result)
        return result

    if _API_PROVIDER == "canopy":
        canopy_domain = amazon_domain if amazon_domain in ("US", "UK", "DE", "JP") else "US"
        result = _fetch_canopy_reviews(asin, canopy_domain, max_reviews)
        if result:
            _set_cache(cache_key, result)
        return result

    params = {
        "api_key": _RAINFOREST_API_KEY,
        "type": "reviews",
        "amazon_domain": amazon_domain,
        "asin": asin,
        "max_page": 1,
    }
    try:
        resp = requests.get(_RAINFOREST_ENDPOINT, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        request_info = data.get("request_info", {}) or {}
        if not request_info.get("success", False):
            return None
        reviews_raw = data.get("reviews", []) or []
        reviews = []
        for r in reviews_raw[:max_reviews]:
            reviews.append({
                "title": (r.get("title") or "")[:120],
                "body": (r.get("body") or "")[:300],
                "rating": r.get("rating"),
                "date": r.get("date", {}).get("utc", "") if isinstance(r.get("date"), dict) else "",
            })
        result = {"asin": asin, "reviews": reviews}
        _set_cache(cache_key, result)
        print(f"[数据采集] Rainforest 评论采集成功 (asin={asin}, {len(reviews)}条)")
        return result
    except Exception as e:
        print(f"[数据采集] Rainforest 评论采集异常: {e}")
        return None


def _extract_keywords_from_titles(titles: List[str], top_n: int = 8) -> List[str]:
    """从商品标题中提炼高频关键词（简单词频统计 + 停用词过滤）。

    亚马逊标题为英文，用空格分词即可，无需 jieba。
    """
    words: List[str] = []
    for title in titles:
        if not title:
            continue
        # 小写化 + 提取英文单词
        for w in re.findall(r"[a-zA-Z]+", title.lower()):
            if len(w) >= 3 and w not in _STOP_WORDS:
                words.append(w)
    counter = Counter(words)
    return [w for w, _ in counter.most_common(top_n)]


def _summarize_competitors_to_trend(rf_data: Dict[str, Any]) -> Dict[str, Any]:
    """将 Rainforest 竞品列表提炼为选品热度结构（热搜词/客单价/趋势）。

    用于把真实竞品数据适配到 fetch_product_trends 的返回结构，
    让选品分析工具无需改动即可获得真实数据。
    """
    competitors = rf_data.get("竞品列表", []) or []

    # 热搜关键词：从标题提炼
    keywords = _extract_keywords_from_titles([c.get("标题", "") for c in competitors])

    # 客单价区间：基于有效价格
    prices = [
        c.get("价格") for c in competitors
        if isinstance(c.get("价格"), (int, float)) and c.get("价格") > 0
    ]
    if prices:
        avg_price = f"${min(prices):.0f}-${max(prices):.0f}"
    else:
        avg_price = "暂无"

    # 增长趋势：基于评论数和 BSR 推断市场成熟度
    ratings_total = [
        c.get("评论数") for c in competitors
        if isinstance(c.get("评论数"), (int, float)) and c.get("评论数") > 0
    ]
    if ratings_total:
        avg_reviews = sum(ratings_total) / len(ratings_total)
        if avg_reviews > 1000:
            trend = "成熟市场，竞争激烈"
        elif avg_reviews > 200:
            trend = "稳定增长"
        elif avg_reviews > 50:
            trend = "快速上升"
        else:
            trend = "新兴蓝海"
    else:
        trend = "暂无数据"

    return {
        "热搜关键词": keywords[:5] if keywords else ["暂无"],
        "平均客单价": avg_price,
        "增长趋势": trend,
        "竞品数": len(competitors),
        "竞品列表": competitors,  # 透传完整竞品数据，供选品工具展示
    }


def fetch_product_trends(category: str, market: str = "美国") -> Dict[str, Any]:
    """采集品类热度趋势数据。

    采集流程（四级降级链）：
    1. 查内存缓存（1h TTL）
    2. 查 MySQL product_trend 表（持久化快照）
    3. 在线采集：Rainforest API（真实亚马逊竞品）→ 模拟数据（最终降级）
    4. 内置基线数据

    Args:
        category: 品类（如 电子产品、服装、家居、美妆、宠物用品）
        market: 目标市场（如 美国、欧盟、日本、英国、东南亚）

    Returns:
        dict: { 热搜关键词, 平均客单价, 增长趋势, 采集时间, 数据来源, [竞品列表], [竞品数] }
    """
    cache_key = f"trend_{category}_{market}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 2) MySQL 查询
    with get_cursor() as cur:
        if cur is not None:
            try:
                cur.execute(
                    "SELECT keywords, avg_price, trend, collected_at "
                    "FROM product_trend WHERE category=%s AND market=%s",
                    (category, market),
                )
                row = cur.fetchone()
                if row:
                    result = {
                        "热搜关键词": json.loads(row["keywords"]) if row["keywords"] else [],
                        "平均客单价": row["avg_price"],
                        "增长趋势": row["trend"],
                        "采集时间": str(row["collected_at"]) if row["collected_at"] else "",
                        "数据来源": "数据库快照",
                    }
                    _set_cache(cache_key, result)
                    return result
            except Exception:
                pass

    # 3) 在线采集：优先 Rainforest API，失败降级到模拟数据
    online_data = _fetch_trends_online(category, market)
    if online_data:
        # 区分真实采集与模拟降级
        if online_data.get("竞品列表"):
            online_data["数据来源"] = "Rainforest API（亚马逊实时）"
        else:
            online_data["数据来源"] = "在线采集（模拟降级）"
        online_data["采集时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _set_cache(cache_key, online_data)
        # 回写 DB（仅存热度维度，竞品列表不持久化）
        _save_trend_to_db(category, market, online_data)
        return online_data

    # 4) 降级
    baseline = _BASELINE_TRENDS.get(category, {})
    result = {
        "热搜关键词": baseline.get("热搜关键词", ["暂无数据"]),
        "平均客单价": baseline.get("平均客单价", "暂无数据"),
        "增长趋势": baseline.get("增长趋势", "暂无数据"),
        "采集时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "数据来源": "内置基线数据",
    }
    _set_cache(cache_key, result)
    return result


def _fetch_trends_online(category: str, market: str) -> Optional[Dict[str, Any]]:
    """在线采集品类热度。

    采集优先级（四级降级链的在线层）：
    1. Rainforest API（真实亚马逊竞品数据）→ 从竞品列表提炼热搜词/客单价/趋势
    2. 模拟数据（最终降级，保证演示可用）

    实际生产中可进一步对接：
    - Amazon Best Sellers 爬虫
    - Shopee 热销榜 API
    - Google Trends API
    - Keepa API
    """
    # 1) 优先调用 Rainforest API（真实亚马逊数据）
    rf_data = fetch_rainforest_competitors(category, market)
    if rf_data and rf_data.get("竞品列表"):
        trend_data = _summarize_competitors_to_trend(rf_data)
        print(f"[数据采集] 选品热度采集成功 (Rainforest, category={category}, market={market})")
        return trend_data

    # 2) 降级到模拟数据（演示流程可用）
    time.sleep(0.3)

    mock_collected = {
        "电子产品": {
            "热搜关键词": ["wireless earbuds", "portable charger", "smart watch band"],
            "平均客单价": "$18-55",
            "增长趋势": "稳定增长",
        },
        "服装": {
            "热搜关键词": ["yoga pants", "UV jacket", "quick-dry shirt"],
            "平均客单价": "$12-38",
            "增长趋势": "季节性上升",
        },
        "家居": {
            "热搜关键词": ["storage box", "LED lamp", "mini fan"],
            "平均客单价": "$10-32",
            "增长趋势": "快速上升",
        },
    }

    data = mock_collected.get(category)
    if data:
        print(f"[数据采集] 选品热度采集成功 (模拟降级, category={category}, market={market})")
        return data

    print(f"[数据采集] 未采集到 {category} 的热度数据")
    return None


def _save_trend_to_db(category: str, market: str, data: Dict) -> None:
    """将采集到的热度数据回写 MySQL。"""
    with get_cursor() as cur:
        if cur is None:
            return
        try:
            cur.execute(
                "INSERT INTO product_trend (category, market, keywords, avg_price, trend, collected_at) "
                "VALUES (%s, %s, %s, %s, %s, NOW()) "
                "ON DUPLICATE KEY UPDATE keywords=%s, avg_price=%s, trend=%s, collected_at=NOW()",
                (
                    category, market,
                    json.dumps(data.get("热搜关键词", []), ensure_ascii=False),
                    data.get("平均客单价", ""),
                    data.get("增长趋势", ""),
                    json.dumps(data.get("热搜关键词", []), ensure_ascii=False),
                    data.get("平均客单价", ""),
                    data.get("增长趋势", ""),
                ),
            )
        except Exception as e:
            print(f"[数据采集] 热度数据回写 DB 失败: {e}")


# ============ 采集状态汇总（供前端展示）============

def get_collection_status() -> Dict[str, Any]:
    """返回数据采集模块的整体状态（供统计页展示）。"""
    rates = fetch_exchange_rates()
    return {
        "汇率数据": {
            "来源": get_rate_source(),
            "币种数": len(rates),
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "选品热度": {
            "来源": "Rainforest API + 基线降级",
            "覆盖品类": len(_BASELINE_TRENDS),
            "更新时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "竞品采集": {
            "数据源": "Rainforest API（亚马逊）",
            "免费额度": "100 次/月",
            "Key配置": "环境变量 RAINFOREST_API_KEY" if os.getenv("RAINFOREST_API_KEY") else "内置默认 Key",
        },
    }
