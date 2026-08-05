# -*- coding: utf-8 -*-
"""Agent 效果评估模块：基于预设测试集，批量评估 Agent 的准确率/幻觉率/工具调用成功率。

设计要点（面试讲解重点）：
1. 标准测试集：预设 N 条 query + 期望工具/期望关键词，形成可复现的评估基准；
2. 三大指标：
   - 工具调用成功率：是否调用了期望工具（Function Call 准确性）
   - 答案命中率：答案是否包含期望关键词（回答准确性）
   - 幻觉率：grounded=False 的占比（幻觉治理效果）
3. 批量执行 + 结果汇总，输出可视化评估报告。

对应 JD 职责 6 的"智能体效果评估、简单数据统计，输出测试记录"。
"""
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from 模块.Agent调度 import get_agent


# ============ 标准测试集 ============
# 每条：query + 期望工具(至少命中一个) + 期望关键词(答案应包含)
TEST_SET: List[Dict[str, Any]] = [
    {
        "id": "T01",
        "query": "蓝牙音箱出口美国电子产品，货值500美元，查关税并换算成人民币",
        "expected_tools": ["query_tariff", "convert_currency"],
        "expected_keywords": ["25", "7.19", "3597", "0", "免税"],
        "category": "多任务编排",
    },
    {
        "id": "T02",
        "query": "Shopee上架有什么规范要求？",
        "expected_tools": ["search_kb"],
        "expected_keywords": ["Shopee", "上架", "标题", "图片", "描述"],
        "category": "RAG知识检索",
    },
    {
        "id": "T03",
        "query": "我想做电子产品出口美国，帮我分析选品",
        "expected_tools": ["analyze_product"],
        "expected_keywords": ["市场热度", "竞争", "利润", "推荐"],
        "category": "选品分析",
    },
    {
        "id": "T04",
        "query": "产品售价100美元，采购成本40美元，运费10美元，关税0，帮我算利润",
        "expected_tools": ["calc_profit"],
        "expected_keywords": ["毛利", "利润率", "净利润"],
        "category": "利润计算",
    },
    {
        "id": "T05",
        "query": "从中国发海运到美国要多久",
        "expected_tools": ["query_logistics"],
        "expected_keywords": ["天", "海运"],
        "category": "物流时效",
    },
    {
        "id": "T06",
        "query": "火星的电子产品出口关税是多少",
        "expected_tools": [],
        "expected_keywords": ["未命中", "暂无", "未检索", "无相关", "知识库"],
        "category": "幻觉治理(超纲)",
    },
]


@dataclass
class 单条结果:
    """单条测试结果。"""
    test_id: str
    query: str
    category: str
    tools_used: List[str] = field(default_factory=list)
    expected_tools: List[str] = field(default_factory=list)
    tool_pass: bool = False              # 是否调用了期望工具
    keyword_hits: int = 0                # 命中期望关键词数
    keyword_total: int = 0
    answer_pass: bool = False            # 关键词命中率达标
    grounded: bool = True
    latency_ms: int = 0
    answer_preview: str = ""
    error: str = ""


class 评估器:
    """Agent 效果评估器。"""

    def __init__(self, test_set: List[Dict] = None):
        self.test_set = test_set or TEST_SET

    def run_once(self, item: Dict) -> 单条结果:
        """执行单条测试。"""
        r = 单条结果(
            test_id=item["id"],
            query=item["query"],
            category=item.get("category", ""),
            expected_tools=item.get("expected_tools", []),
        )
        try:
            agent = get_agent()
            res = agent.orchestrate(item["query"])
            r.tools_used = [t["tool"] for t in res.get("tools_used", [])]
            r.grounded = res.get("grounded", True)
            r.latency_ms = res.get("latency_ms", 0)
            answer = res.get("answer", "")
            r.answer_preview = answer[:200]

            # 工具调用成功率：期望工具非空时，至少命中一个
            if r.expected_tools:
                r.tool_pass = any(t in r.tools_used for t in r.expected_tools)
            else:
                # 超纲问题无期望工具，工具调用成功率默认 True
                r.tool_pass = True

            # 答案关键词命中率
            keywords = item.get("expected_keywords", [])
            r.keyword_total = len(keywords)
            if keywords:
                r.keyword_hits = sum(1 for k in keywords if k.lower() in answer.lower())
                # 命中率 >= 50% 视为通过
                r.answer_pass = (r.keyword_hits / r.keyword_total) >= 0.5
            else:
                r.answer_pass = True
        except Exception as e:  # noqa: BLE001
            r.error = str(e)
            r.tool_pass = False
            r.answer_pass = False
            r.grounded = False
        return r

    def run_all(self) -> Dict[str, Any]:
        """批量执行测试集，返回汇总报告。"""
        results: List[单条结果] = []
        for item in self.test_set:
            print(f"[评估] 执行 {item['id']}: {item['query'][:30]}...")
            r = self.run_once(item)
            results.append(r)
            time.sleep(0.5)  # 避免请求过快

        total = len(results)
        tool_pass_count = sum(1 for r in results if r.tool_pass)
        answer_pass_count = sum(1 for r in results if r.answer_pass)
        hallucination_count = sum(1 for r in results if not r.grounded)
        avg_latency = sum(r.latency_ms for r in results) / total if total else 0

        # 分类统计
        by_category: Dict[str, Dict] = {}
        for r in results:
            cat = r.category or "其他"
            if cat not in by_category:
                by_category[cat] = {"total": 0, "tool_pass": 0, "answer_pass": 0}
            by_category[cat]["total"] += 1
            if r.tool_pass:
                by_category[cat]["tool_pass"] += 1
            if r.answer_pass:
                by_category[cat]["answer_pass"] += 1

        return {
            "total": total,
            "tool_success_rate": round(tool_pass_count / total, 3) if total else 0,
            "answer_accuracy_rate": round(answer_pass_count / total, 3) if total else 0,
            "hallucination_rate": round(hallucination_count / total, 3) if total else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "tool_pass_count": tool_pass_count,
            "answer_pass_count": answer_pass_count,
            "hallucination_count": hallucination_count,
            "by_category": by_category,
            "details": [
                {
                    "test_id": r.test_id,
                    "query": r.query,
                    "category": r.category,
                    "tools_used": r.tools_used,
                    "expected_tools": r.expected_tools,
                    "tool_pass": r.tool_pass,
                    "keyword_hits": r.keyword_hits,
                    "keyword_total": r.keyword_total,
                    "answer_pass": r.answer_pass,
                    "grounded": r.grounded,
                    "latency_ms": r.latency_ms,
                    "answer_preview": r.answer_preview,
                    "error": r.error,
                }
                for r in results
            ],
        }


# 模块级单例
_evaluator_instance: Optional[评估器] = None


def get_evaluator() -> 评估器:
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = 评估器()
    return _evaluator_instance
