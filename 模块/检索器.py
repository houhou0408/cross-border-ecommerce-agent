# -*- coding: utf-8 -*-
"""检索模块：在 Chroma 向量库上做向量检索 + 关键词重排的混合检索。

设计要点：
- 向量检索负责语义召回（用 BGE embedding 相似度）；
- 关键词匹配（jieba 分词）做加分重排，弥补向量检索对专有名词/型号的不敏感；
- 相似度阈值过滤，低于阈值的视为未命中，避免低质上下文诱发幻觉；
- 返回结构化结果（含分数与来源），供幻觉治理模块溯源。
"""
from typing import List, Dict, Any
from dataclasses import dataclass, field

import jieba

from config import RETRIEVAL_CONFIG
from 模块.切片向量化 import load_vectorstore


@dataclass
class RetrievalResult:
    """单条检索结果。"""
    content: str
    score: float                  # 归一化后的综合得分(0~1)
    source: str                   # 来源文件
    metadata: Dict[str, Any] = field(default_factory=dict)


class 检索器:
    """混合检索器：向量召回 + 关键词重排。"""

    def __init__(self, vectorstore=None):
        self.vectorstore = vectorstore or load_vectorstore()
        self.retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": RETRIEVAL_CONFIG["top_k"] * 2},  # 多召回再重排
        )

    @staticmethod
    def _keyword_overlap(query: str, doc_text: str) -> float:
        """关键词重排分：query 与 doc 的分词重叠率。"""
        q_tokens = set(jieba.lcut(query))
        d_tokens = set(jieba.lcut(doc_text))
        # 过滤单字与标点
        q_tokens = {t for t in q_tokens if len(t.strip()) > 1}
        d_tokens = {t for t in d_tokens if len(t.strip()) > 1}
        if not q_tokens:
            return 0.0
        overlap = len(q_tokens & d_tokens) / len(q_tokens)
        return overlap

    def search(self, query: str, top_k: int = None) -> List[RetrievalResult]:
        """混合检索主入口。

        步骤：
        1) 向量召回 top_k*2 候选；
        2) 计算每个候选的向量相似度与关键词重叠分，加权融合；
        3) 按融合分降序，过滤低于阈值的结果，取 top_k。
        """
        top_k = top_k or RETRIEVAL_CONFIG["top_k"]
        candidates = self.retriever.invoke(query)

        results: List[RetrievalResult] = []
        for doc in candidates:
            # Chroma 相似度近似（归一化向量内积即余弦，已在 embedding 归一化）
            vec_score = float(doc.metadata.get("score", 0.6))  # 兜底默认分
            # 若 retriever 未带 score，用一个温和的默认值
            kw_score = self._keyword_overlap(query, doc.page_content)
            # 融合：向量 0.7 + 关键词 0.3
            fusion = 0.7 * vec_score + 0.3 * kw_score
            results.append(RetrievalResult(
                content=doc.page_content,
                score=round(fusion, 4),
                source=doc.metadata.get("source", "未知"),
                metadata=doc.metadata,
            ))

        # 过滤低分 + 排序 + 截断
        threshold = RETRIEVAL_CONFIG["score_threshold"]
        results = [r for r in results if r.score >= threshold]
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]

        print(f"[检索器] query='{query[:30]}' 命中 {len(results)} 条")
        return results

    def search_with_scores(self, query: str, top_k: int = None) -> List[RetrievalResult]:
        """带相似度分数的检索（直接用 Chroma similarity_search_with_score）。"""
        top_k = top_k or RETRIEVAL_CONFIG["top_k"]
        # Chroma 返回 (doc, distance)，distance 越小越相似；余弦距离=1-cos
        raw = self.vectorstore.similarity_search_with_relevance_scores(query, k=top_k * 2)
        results: List[RetrievalResult] = []
        for doc, rel_score in raw:
            kw_score = self._keyword_overlap(query, doc.page_content)
            fusion = 0.7 * float(rel_score) + 0.3 * kw_score
            results.append(RetrievalResult(
                content=doc.page_content,
                score=round(fusion, 4),
                source=doc.metadata.get("source", "未知"),
                metadata=doc.metadata,
            ))
        threshold = RETRIEVAL_CONFIG["score_threshold"]
        results = [r for r in results if r.score >= threshold]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

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
        print(f"\n[{hit.score}] {hit.source}\n{hit.content[:100]}")
