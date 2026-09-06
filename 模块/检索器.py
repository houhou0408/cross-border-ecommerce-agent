# -*- coding: utf-8 -*-
"""检索模块：在 Chroma 向量库上做向量检索 + 关键词重排的混合检索。

设计要点（按真实业务标准）：
- 向量检索负责语义召回（用 BGE embedding 相似度）；
- 关键词匹配（jieba 分词）做加分重排，弥补向量检索对专有名词/型号的不敏感；
- 融合前对向量分、关键词分各自做 min-max 归一化，统一量纲后再加权，避免
  "两种不同量纲的分数直接相加"导致权重失衡；
- 命中判定基于原始向量分阈值（保底语义相关性），归一化后的融合分只用于排序，
  防止归一化把低质候选放大进结果；
- 关键词重叠率计算前过滤高频泛词（停用词）与单字，避免"价格/美国"这类无区分度
  词白占分数；
- 融合权重默认 0.7/0.3（config 可配），并内置 tune_weights() 网格搜索，
  用标注集（query + 期望关键词）自动寻优，而不是拍脑袋定权重；
- 返回结构化结果（含分数与来源），供幻觉治理模块溯源。
"""
from typing import List, Dict, Any, Optional, Sequence
from dataclasses import dataclass, field

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    jieba = None
    _HAS_JIEBA = False

from config import RETRIEVAL_CONFIG
from 模块.切片向量化 import load_vectorstore
from 基础设施.日志统计 import get_file_logger
logger = get_file_logger("检索器")


# 高频泛词（无区分度，过滤后关键词重叠分更有意义）
# 保守清单：只放真正泛化的词，不放领域词（关税/价格/美国等保留）
_STOPWORDS = {
    "产品", "商品", "一个", "这个", "那个", "怎么", "如何", "什么",
    "需要", "请问", "帮我", "进行", "可以", "能够", "以及", "我们",
    "有", "是", "的", "了", "在", "和", "与", "或", "很", "都",
}


def _tokenize(text: str) -> List[str]:
    """分词：优先 jieba，未安装时退化为字符切分（保证可启动）。
    统一过滤单字、标点、高频泛词，让重叠率计算更有区分度。
    """
    if _HAS_JIEBA:
        tokens = list(jieba.cut(text))
    else:
        tokens = [c for c in text if c.strip()]
    return [t for t in tokens if len(t.strip()) > 1 and t not in _STOPWORDS]


@dataclass
class RetrievalResult:
    """单条检索结果。"""
    content: str
    score: float                  # 归一化后的综合得分(0~1)，仅用于排序
    source: str                   # 来源文件
    metadata: Dict[str, Any] = field(default_factory=dict)


def _minmax_normalize(scores: Sequence[float]) -> List[float]:
    """min-max 归一化：把一组分数映射到 0~1，统一量纲后再做加权融合。

    - 全相等时：若全为 0 则返回全 0，否则返回全 1（避免 0/0）。
    - 只依赖当前候选集内的相对大小，适合"同一查询内排序"的场景。
    """
    scores = list(scores)
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.0 if hi < 1e-9 else 1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


class 检索器:
    """混合检索器：向量召回 + 关键词重排（归一化融合）。"""

    def __init__(self, vectorstore=None, library: str = None):
        self.library = library
        if vectorstore is not None:
            self.vectorstore = vectorstore
        elif library is not None:
            self.vectorstore = load_vectorstore(collection_name=library)
        else:
            self.vectorstore = load_vectorstore()
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": RETRIEVAL_CONFIG["top_k"] * 2},  # 多召回再重排
        )

    @staticmethod
    def _keyword_overlap(query: str, doc_text: str) -> float:
        """关键词重排分：query 与 doc 的（去停用词后）分词重叠率。

        注意：仅按 query 长度归一化，文档越长越容易覆盖 query 词，
        属于已知偏差；对排序影响有限，暂未做文档长度惩罚。
        """
        q_tokens = set(_tokenize(query))
        d_tokens = set(_tokenize(doc_text))
        if not q_tokens:
            return 0.0
        return len(q_tokens & d_tokens) / len(q_tokens)

    def _rank(self, query: str, top_k: int, vec_w: float, kw_w: float) -> List[RetrievalResult]:
        """混合检索统一实现：真实评分召回 → 阈值粗滤 → 归一化融合 → 排序截断。

        所有检索入口（search / search_with_scores）都走这里，
        保证不会出现"拿不到分数就兜底默认值"的假分情况。
        """
        # 1) 用 relevance scores 拿真实向量分（Chroma 余弦距离换算，0~1）
        raw = self.vectorstore.similarity_search_with_relevance_scores(query, k=top_k * 2)
        if not raw:
            return []

        # 2) 粗滤：原始向量分低于阈值的不入候选（保底语义相关性）
        candidates = [(doc, float(rel)) for doc, rel in raw if float(rel) >= RETRIEVAL_CONFIG["score_threshold"]]
        if not candidates:
            return []

        # 3) 两个分数各自 min-max 归一化，统一量纲后加权融合
        vec_scores = [rel for _, rel in candidates]
        kw_scores = [self._keyword_overlap(query, doc.page_content) for doc, _ in candidates]
        vec_norm = _minmax_normalize(vec_scores)
        kw_norm = _minmax_normalize(kw_scores)

        results: List[RetrievalResult] = []
        for (doc, _), vec_n, kw_n in zip(candidates, vec_norm, kw_norm):
            fusion = vec_w * vec_n + kw_w * kw_n
            meta = dict(doc.metadata)
            if self.library:
                meta["library"] = self.library
            results.append(RetrievalResult(
                content=doc.page_content,
                score=round(fusion, 4),
                source=doc.metadata.get("source", "未知"),
                metadata=meta,
            ))

        # 4) 按融合分降序，取 top_k
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]

        logger.info("[检索器] query='%s' 命中 %s 条", query[:30], len(results))
        return results

    def search(self, query: str, top_k: int = None) -> List[RetrievalResult]:
        """混合检索（语义召回 + 关键词重排），使用配置默认权重。"""
        top_k = top_k or RETRIEVAL_CONFIG["top_k"]
        vec_w = RETRIEVAL_CONFIG.get("vec_weight", 0.7)
        kw_w = RETRIEVAL_CONFIG.get("kw_weight", 0.3)
        return self._rank(query, top_k, vec_w, kw_w)

    def search_with_scores(self, query: str, top_k: int = None,
                           weights: Optional[tuple] = None) -> List[RetrievalResult]:
        """带相似度分数的检索（生产链路入口，Listing生成/产品知识检索调用）。

        Args:
            query: 查询文本
            top_k: 返回条数
            weights: (vec_weight, kw_weight) 覆盖默认权重，权重搜索时使用
        """
        top_k = top_k or RETRIEVAL_CONFIG["top_k"]
        if weights is not None:
            vec_w, kw_w = weights
        else:
            vec_w = RETRIEVAL_CONFIG.get("vec_weight", 0.7)
            kw_w = RETRIEVAL_CONFIG.get("kw_weight", 0.3)
        return self._rank(query, top_k, vec_w, kw_w)

    def tune_weights(self, queries: List[str], keyword_sets: List[List[str]],
                     alphas: Sequence[float] = (0.5, 0.6, 0.7, 0.8, 0.9),
                     top_k: int = 3) -> Dict[str, Any]:
        """基于标注集网格搜索最优融合权重（不依赖 LLM，只跑本地向量库）。

        评价指标：每条 query 检索 top_k 结果后，期望关键词在结果内容中的
        命中率（query 维度平均），命中率最高的权重组合即为最优。

        说明：这是"用标注集证明权重选择有依据"的最小可行做法，
        指标粗糙但足以排除明显失衡的权重组合。
        """
        best = {"vec_weight": None, "kw_weight": None, "score": -1.0}
        per_alpha: Dict[str, float] = {}
        for a in alphas:
            kw_w = round(1.0 - a, 2)
            total_hit_rate = 0.0
            for q, kws in zip(queries, keyword_sets):
                if not kws:
                    continue
                results = self.search_with_scores(q, top_k=top_k, weights=(a, kw_w))
                hit = sum(1 for r in results for k in kws if k in r.content)
                total_hit_rate += hit / len(kws)
            score = total_hit_rate / len(queries) if queries else 0.0
            per_alpha[f"vec={a},kw={kw_w}"] = round(score, 4)
            if score > best["score"]:
                best.update(vec_weight=a, kw_weight=kw_w, score=round(score, 4))
        best["per_alpha"] = per_alpha
        return best

    def format_context(self, results: List[RetrievalResult]) -> str:
        """把检索结果拼成给 LLM 的上下文文本（带来源编号）。"""
        if not results:
            return "（未检索到相关知识）"
        blocks = []
        for i, r in enumerate(results, 1):
            blocks.append(f"[{i}] 来源:{r.source} | 相关度:{r.score}\n{r.content}")
        return "\n\n".join(blocks)


if __name__ == "__main__":
    r = 检索器()
    for hit in r.search_with_scores("亚马逊Listing标题有什么要求"):
        logger.info("\n[%s] %s\n%s", hit.score, hit.source, hit.content[:100])
