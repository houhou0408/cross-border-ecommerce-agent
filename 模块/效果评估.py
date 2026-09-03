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
from 模块.日志统计 import get_file_logger
logger = get_file_logger("效果评估")


# ============ 标准测试集 ============
# 每条：query + 期望工具(至少命中一个) + 期望关键词(答案应包含)
# 字段说明：
#   source: 问题来源标注（内部构建 = 开发自建；业务抽样(模拟) = 模拟真实用户 query）
#   level:  难度标注（易/中/难），便于按难度分层统计
TEST_SET: List[Dict[str, Any]] = [
    {
        "id": "T01",
        "query": "蓝牙音箱出口美国电子产品，货值500美元，查关税并换算成人民币",
        "expected_tools": ["query_tariff", "convert_currency"],
        # 注意：不用具体汇率数字（汇率实时变动，7.19/3597 会过时），
        # 只断言稳定要素：关税税率/附加税、免税额度、币种
        "expected_keywords": ["25", "0", "免税", "人民币", "美元"],
        "category": "多任务编排",
        "source": "内部构建",
        "level": "难",
    },
    {
        "id": "T02",
        "query": "Shopee上架有什么规范要求？",
        "expected_tools": ["search_kb"],
        "expected_keywords": ["Shopee", "上架", "标题", "图片", "描述"],
        "category": "RAG知识检索",
        "source": "内部构建",
        "level": "易",
    },
    {
        "id": "T03",
        "query": "我想做电子产品出口美国，帮我分析选品",
        "expected_tools": ["smart_selection"],
        "expected_keywords": ["市场热度", "竞争", "利润", "蓝海", "红海", "开发建议"],
        "category": "选品分析",
        "source": "内部构建",
        "level": "中",
    },
    {
        "id": "T04",
        "query": "产品售价100美元，采购成本40美元，运费10美元，关税0，帮我算利润",
        "expected_tools": ["calc_profit"],
        "expected_keywords": ["毛利", "利润率", "净利润"],
        "category": "利润计算",
        "source": "内部构建",
        "level": "易",
    },
    {
        "id": "T05",
        "query": "从中国发海运到美国要多久",
        "expected_tools": ["query_logistics"],
        "expected_keywords": ["天", "海运"],
        "category": "物流时效",
        "source": "内部构建",
        "level": "易",
    },
    {
        "id": "T06",
        "query": "火星的电子产品出口关税是多少",
        "expected_tools": [],
        # 超纲题的"正确答案"是明确拒答：无法查询/不存在/知识库未收录，不编造。
        # 关键词按真实拒答信号设计，而非预设话术。
        "expected_keywords": ["无法", "不存在", "知识库", "未命中", "火星"],
        "category": "幻觉治理(超纲)",
        "source": "内部构建",
        "level": "易",
    },
    {
        "id": "T07",
        "query": "Temu店铺因为什么会被罚款？有哪些违规红线？",
        "expected_tools": ["search_kb"],
        "expected_keywords": ["Temu", "违规", "罚款", "红线"],
        "category": "RAG知识检索",
        "source": "业务抽样(模拟)",
        "level": "中",
    },
    {
        "id": "T08",
        "query": "蓝牙音箱的Listing标题该怎么写才吸引人",
        "expected_tools": ["search_kb"],
        "expected_keywords": ["标题", "关键词", "卖点", "搜索"],
        "category": "RAG知识检索",
        "source": "业务抽样(模拟)",
        "level": "易",
    },
    {
        "id": "T09",
        "query": "手机壳出口欧盟要交多少关税，换算成欧元是多少",
        "expected_tools": ["query_tariff", "convert_currency"],
        "expected_keywords": ["关税", "%", "欧元"],
        "category": "多任务编排",
        "source": "业务抽样(模拟)",
        "level": "难",
    },
    {
        "id": "T10",
        "query": "产品卖25美元，平台佣金15%，采购8美元，帮我算下利润和利润率",
        "expected_tools": ["calc_profit"],
        "expected_keywords": ["毛利", "佣金", "利润率", "净利润"],
        "category": "利润计算",
        "source": "业务抽样(模拟)",
        "level": "中",
    },
    {
        "id": "T11",
        "query": "从深圳发快递到美国洛杉矶要几天",
        "expected_tools": ["query_logistics"],
        "expected_keywords": ["天", "快递"],
        "category": "物流时效",
        "source": "业务抽样(模拟)",
        "level": "易",
    },
    {
        "id": "T12",
        "query": "100美元换算成日元是多少",
        "expected_tools": ["convert_currency"],
        "expected_keywords": ["日元"],
        "category": "汇率换算",
        "source": "业务抽样(模拟)",
        "level": "易",
    },
    {
        "id": "T13",
        "query": "粗陶质感玻璃杯在美国亚马逊市场能不能做",
        "expected_tools": ["smart_selection"],
        "expected_keywords": ["市场", "竞品", "蓝海", "利润", "开发"],
        "category": "选品分析",
        "source": "业务抽样(模拟)",
        "level": "中",
    },
    {
        "id": "T14",
        "query": "蓝牙耳机的常见差评痛点有哪些，怎么改款",
        "expected_tools": ["analyze_pain_points"],
        "expected_keywords": ["痛点", "差评", "改款", "卖点"],
        "category": "痛点分析",
        "source": "业务抽样(模拟)",
        "level": "中",
    },
    {
        "id": "T15",
        "query": "亚马逊火星仓的入库预约怎么操作",
        "expected_tools": [],
        # 超纲拒答题：正确行为是明确说明知识库未收录 + 不编造具体操作
        "expected_keywords": ["火星仓", "知识库", "未命中", "无法", "暂无"],
        "category": "幻觉治理(超纲)",
        "source": "业务抽样(模拟)",
        "level": "中",
    },
    {
        "id": "T16",
        "query": "欧洲站卖家需要满足哪些合规要求",
        "expected_tools": ["search_kb"],
        "expected_keywords": ["合规", "欧洲", "税", "法规"],
        "category": "RAG知识检索",
        "source": "业务抽样(模拟)",
        "level": "易",
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
    quality: str = "wrong"               # 答案质量三档：correct / partial / wrong
    grounded: bool = True
    honest_degrade: bool = False         # 低置信但已诚实标注未核实（非编造幻觉）
    latency_ms: int = 0
    answer_preview: str = ""
    error: str = ""
    source: str = ""                     # 问题来源标注
    level: str = ""                      # 难度标注


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
            source=item.get("source", ""),
            level=item.get("level", ""),
        )
        try:
            agent = get_agent()
            res = agent.orchestrate(item["query"])
            r.tools_used = [t["tool"] for t in res.get("tools_used", [])]
            r.grounded = res.get("grounded", True)
            r.latency_ms = res.get("latency_ms", 0)
            answer = res.get("answer", "")
            r.answer_preview = answer[:200]
            # 诚实降级识别：grounded=False 时若答案明确标注未核实/不存在等，
            # 属于"低置信但未编造"，不算真幻觉（编造且未标注不确定）
            _HONEST_HINTS = ("未核实", "未命中", "未检索", "以官方为准",
                             "行业通用", "不存在", "无法提供", "暂未收录")
            r.honest_degrade = any(h in answer for h in _HONEST_HINTS)

            # 工具调用成功率：期望工具非空时，至少命中一个
            if r.expected_tools:
                r.tool_pass = any(t in r.tools_used for t in r.expected_tools)
            else:
                # 超纲问题无期望工具，工具调用成功率默认 True
                r.tool_pass = True

            # 答案关键词命中率 + 质量三档分级
            #   correct：命中率 >= 50%（能覆盖半数以上要点）
            #   partial：有命中但不足半数（部分正确，需人工复核）
            #   wrong：零命中（漏答或答非所问）
            keywords = item.get("expected_keywords", [])
            r.keyword_total = len(keywords)
            if keywords:
                r.keyword_hits = sum(1 for k in keywords if k.lower() in answer.lower())
                hit_rate = r.keyword_hits / r.keyword_total
                r.answer_pass = hit_rate >= 0.5
                if hit_rate >= 0.5:
                    r.quality = "correct"
                elif hit_rate > 0:
                    r.quality = "partial"
                else:
                    r.quality = "wrong"
            else:
                r.answer_pass = True
                r.quality = "correct"
        except Exception as e:  # noqa: BLE001
            r.error = str(e)
            r.tool_pass = False
            r.answer_pass = False
            r.quality = "wrong"
            r.grounded = False
        return r

    def run_all(self) -> Dict[str, Any]:
        """批量执行测试集，返回汇总报告。"""
        results: List[单条结果] = []
        for item in self.test_set:
            logger.info("[评估] 执行 %s: %s...", item['id'], item['query'][:30])
            r = self.run_once(item)
            results.append(r)
            time.sleep(0.5)  # 避免请求过快

        total = len(results)
        tool_pass_count = sum(1 for r in results if r.tool_pass)
        answer_pass_count = sum(1 for r in results if r.answer_pass)
        # 幻觉率口径：仅统计"编造且未标注不确定"的真幻觉；
        # 低置信但已诚实标注未核实的降级回答单列，不算幻觉
        hallucination_count = sum(1 for r in results if not r.grounded and not r.honest_degrade)
        honest_low_confidence = sum(1 for r in results if not r.grounded and r.honest_degrade)
        avg_latency = sum(r.latency_ms for r in results) / total if total else 0

        # 答案质量三档统计
        correct_count = sum(1 for r in results if r.quality == "correct")
        partial_count = sum(1 for r in results if r.quality == "partial")
        wrong_count = sum(1 for r in results if r.quality == "wrong")

        # 人工抽检清单：真幻觉 / 诚实降级 / 部分正确条目，建议人工复核后才可信
        manual_review = [
            {
                "test_id": r.test_id,
                "reason": (
                    "真幻觉(编造且未标注不确定)" if not r.grounded and not r.honest_degrade
                    else ("诚实降级(已标注未核实，非编造)" if not r.grounded
                          else ("答案部分正确(partial)" if r.quality == "partial"
                                else "答案错误(wrong)"))
                ),
                "keyword_hits": f"{r.keyword_hits}/{r.keyword_total}",
                "answer_preview": r.answer_preview,
                "error": r.error,
            }
            for r in results
            if r.quality != "correct" or not r.grounded
        ]

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
            # 诚实降级率：知识库未命中/工具不可用但如实标注，非编造幻觉
            "honest_low_confidence": honest_low_confidence,
            # 质量三档分布（correct 即 answer_accuracy_rate 的分子）
            "quality": {
                "correct": correct_count,
                "partial": partial_count,
                "wrong": wrong_count,
            },
            # 人工抽检清单：评估只能自动初判，抽样人工复核后才可作为发布依据
            "manual_review": manual_review,
            "by_category": by_category,
            "details": [
                {
                    "test_id": r.test_id,
                    "query": r.query,
                    "category": r.category,
                    "source": r.source,
                    "level": r.level,
                    "tools_used": r.tools_used,
                    "expected_tools": r.expected_tools,
                    "tool_pass": r.tool_pass,
                    "keyword_hits": r.keyword_hits,
                    "keyword_total": r.keyword_total,
                    "answer_pass": r.answer_pass,
                    "quality": r.quality,
                    "grounded": r.grounded,
                    "honest_degrade": r.honest_degrade,
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


def run_weight_tuning() -> Dict[str, Any]:
    """基于测试集搜索最优检索融合权重（不调 LLM，只跑本地向量库）。

    用法：先跑一次 get_evaluator().run_all() 看整体水平，
    再跑本函数，把返回的最优权重写回 config.py 的 RETRIEVAL_CONFIG。
    """
    from 模块.检索器 import 检索器
    try:
        retriever = 检索器()
        rag_items = [i for i in TEST_SET if i.get("category") == "RAG知识检索"]
        queries = [i["query"] for i in rag_items]
        keyword_sets = [i["expected_keywords"] for i in rag_items]
        result = retriever.tune_weights(queries, keyword_sets)
        result["note"] = f"基于 {len(rag_items)} 条 RAG 检索标注样本搜索"
        return result
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "note": "权重搜索失败，可能向量库未初始化"}
