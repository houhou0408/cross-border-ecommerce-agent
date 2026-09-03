# -*- coding: utf-8 -*-
"""检索器单测：归一化边界 / 停用词过滤 / 混合融合排序，全程不加载 Chroma 与 BGE。"""
import pytest
from langchain_core.documents import Document

from 模块.检索器 import 检索器, _minmax_normalize, _tokenize, RETRIEVAL_CONFIG


# ============ 纯函数 ============

class Test归一化边界:
    def test_空列表(self):
        assert _minmax_normalize([]) == []

    def test_全零(self):
        assert _minmax_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]

    def test_全相等非零(self):
        # 避免 0/0：全相等且非零时返回全 1
        assert _minmax_normalize([0.5, 0.5]) == [1.0, 1.0]

    def test_线性映射(self):
        assert _minmax_normalize([1.0, 2.0, 3.0]) == pytest.approx([0.0, 0.5, 1.0])


class Test分词与停用词:
    def test_停用词被过滤(self):
        tokens = _tokenize("这个产品怎么清关")
        # "这个/怎么/产品" 是无区分度泛词，必须被过滤
        assert "这个" not in tokens
        assert "怎么" not in tokens
        assert "产品" not in tokens
        assert "清关" in tokens

    def test_单字被过滤(self):
        assert all(len(t) > 1 for t in _tokenize("如何退货退款流程"))


# ============ 混合检索融合（注入 FakeVectorstore，不触真实向量库） ============

class FakeVectorstore:
    """预设向量检索结果的假向量库。"""

    def __init__(self, hits):
        # hits: [(Document, score)]，score 为原始向量分
        self._hits = hits

    def similarity_search_with_relevance_scores(self, query, k):
        return self._hits[:k]

    def as_retriever(self, **kwargs):
        raise NotImplementedError("测试不应走 retriever 路径")


def _make_retriever(hits):
    r = 检索器.__new__(检索器)   # 跳过 __init__（避免加载向量库）
    r.vectorstore = FakeVectorstore(hits)
    r.library = None
    return r


class Test阈值粗滤:
    def test_低于阈值被过滤(self):
        # 默认 score_threshold=0.35，0.2 的候选必须被粗滤
        hits = [(Document(page_content="无关内容"), 0.2)]
        r = _make_retriever(hits)
        assert r.search("蓝牙耳机") == []

    def test_阈值内保留(self):
        hits = [(Document(page_content="蓝牙耳机防水户外"), 0.9)]
        r = _make_retriever(hits)
        results = r.search("蓝牙耳机 户外防水")
        assert len(results) == 1
        assert results[0].source == "未知"


class Test融合排序:
    """3 个候选：A 向量分最高但无关键词重叠；B 关键词全命中；C 双低。"""

    QUERY = "蓝牙耳机 户外防水"

    HITS = [
        (Document(page_content="陶瓷保温杯居家场景", metadata={"source": "docA"}), 0.9),
        (Document(page_content="蓝牙耳机户外防水运动", metadata={"source": "docB"}), 0.5),
        (Document(page_content="蓝牙耳机桌面支架", metadata={"source": "docC"}), 0.4),
    ]

    def test_高关键词权重时_B反超(self):
        # 权重 (0.3, 0.7)：B 关键词全命中，应排第一
        r = _make_retriever(self.HITS)
        results = r.search_with_scores(self.QUERY, weights=(0.3, 0.7))
        assert results[0].source == "docB"

    def test_纯向量权重时_A第一(self):
        # 权重 (1.0, 0.0)：退化为纯向量序，A 向量分最高排第一
        r = _make_retriever(self.HITS)
        results = r.search_with_scores(self.QUERY, weights=(1.0, 0.0))
        assert results[0].source == "docA"

    def test_默认权重配置存在(self):
        assert 0.0 < RETRIEVAL_CONFIG["vec_weight"] < 1.0
        assert RETRIEVAL_CONFIG["vec_weight"] + RETRIEVAL_CONFIG["kw_weight"] == pytest.approx(1.0)

    def test_top_k截断(self):
        r = _make_retriever(self.HITS)
        assert len(r.search(self.QUERY, top_k=2)) == 2
