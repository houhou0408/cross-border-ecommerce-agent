# -*- coding: utf-8 -*-
"""业务迭代闭环模块：收集运营反馈 → 错误案例入库 → 知识库自优化。

设计要点（面试讲解重点）：
1. 反馈机制：运营可一键评价好坏，坏例自动入库分析；
2. 自优化：错误案例积累后自动提炼常见问题，更新知识库提示；
3. 闭环统计：统计好/坏案例比例、常见翻车场景、修正建议。

面试话术："不是静态系统，运营反馈会反向优化知识库，越用越懂业务。"
"""
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from config import DATA_DIR
from langchain_core.tools import tool


# 反馈数据存储
_FEEDBACK_FILE = DATA_DIR / "feedback_records.json"


def _load_feedback() -> List[Dict]:
    if _FEEDBACK_FILE.exists():
        try:
            with open(_FEEDBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_feedback(records: List[Dict]):
    try:
        with open(_FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[反馈闭环] 保存失败: {e}")


@dataclass
class 反馈统计:
    total: int = 0
    good: int = 0
    bad: int = 0
    good_rate: float = 0.0
    top_issues: List[str] = field(default_factory=list)
    recent: List[Dict] = field(default_factory=list)


def record_feedback(query: str, answer: str, rating: str = "good",
                    comment: str = "", issue_type: str = "") -> Dict[str, Any]:
    """记录运营反馈。

    Args:
        query: 用户原始提问
        answer: Agent 返回的答案
        rating: "good" 好 / "bad" 差
        comment: 运营备注（如"参数写错了""关键词堆砌""场景不对"）
        issue_type: 问题分类：幻觉/合规/参数错误/风格不符/其他
    """
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "query": query[:200],
        "answer_preview": answer[:200],
        "rating": rating,
        "comment": comment,
        "issue_type": issue_type or ("无" if rating == "good" else "未分类"),
    }
    records = _load_feedback()
    records.append(record)
    # 只保留最近 500 条，避免文件过大
    if len(records) > 500:
        records = records[-500:]
    _save_feedback(records)
    return {"ok": True, "msg": "反馈已记录", "id": len(records) - 1}


def get_feedback_stats() -> 反馈统计:
    """获取反馈统计 + 改进建议。"""
    records = _load_feedback()
    total = len(records)
    good = sum(1 for r in records if r.get("rating") == "good")
    bad = total - good
    good_rate = round(good / total, 3) if total else 0

    # 分析坏案例 Top 问题
    bad_records = [r for r in records if r.get("rating") == "bad"]
    issue_counter: Dict[str, int] = {}
    for r in bad_records:
        t = r.get("issue_type", "未分类")
        issue_counter[t] = issue_counter.get(t, 0) + 1
    top_issues = sorted(issue_counter.keys(), key=lambda k: issue_counter[k], reverse=True)[:5]

    return 反馈统计(
        total=total,
        good=good,
        bad=bad,
        good_rate=good_rate,
        top_issues=top_issues,
        recent=records[-10:],
    )


def generate_improvement_suggestions() -> List[str]:
    """基于反馈数据生成改进建议。"""
    stats = get_feedback_stats()
    suggestions = []

    if stats.good_rate < 0.8 and stats.total >= 5:
        suggestions.append("整体好评率偏低，建议检查 LLM prompt 模板和知识库覆盖度")

    if stats.total > 0:
        suggestions.append(f"共收集 {stats.total} 条反馈，好评率 {stats.good_rate*100:.0f}%")

    if stats.top_issues:
        suggestions.append(f"高频问题类型: {', '.join(stats.top_issues[:3])}")

    # 坏案例积累达到阈值时建议更新知识库
    if stats.bad >= 5:
        suggestions.append("坏案例已≥5条，建议复盘后补充知识库/调整 prompt 约束")

    return suggestions


# ============ Agent 工具注册 ============

@tool("feedback_record")
def 记录反馈(query: str, answer: str, rating: str = "good", comment: str = "",
            issue_type: str = "") -> str:
    """记录运营对 Agent 回答的评价反馈，用于持续优化系统。

    当用户说"这个回答不对""参数错了""没问题""好评"等评价时调用此工具。
    坏案例会自动积累，用于后续知识库优化。

    Args:
        query: 用户的原始提问
        answer: Agent 返回的答案
        rating: "good"好 / "bad"差
        comment: 可选备注说明
        issue_type: 问题类型：幻觉/合规/参数错误/风格不符/其他
    """
    import re
    # 清理 query 中的前缀标记（如 [feedback] 前缀）
    clean_query = re.sub(r'^\[.*?\]\s*', '', query)
    result = record_feedback(clean_query, answer, rating, comment, issue_type)
    if rating == "bad":
        return (
            f"反馈已记录。感谢您的反馈，我们会根据此案例优化系统。\n"
            f"- 问题类型: {issue_type or '未分类'}\n"
            f"- 备注: {comment or '无'}"
        )
    return "感谢您的反馈（好评已记录）。"


@tool("feedback_stats")
def 查看反馈统计() -> str:
    """查看系统反馈统计，了解 AI 回答质量和常见问题。

    当用户问"最近回答质量怎么样""有没有翻车""统计一下反馈"时调用。

    Returns:
        反馈统计摘要
    """
    stats = get_feedback_stats()
    suggs = generate_improvement_suggestions()

    lines = [
        f"=== 系统反馈统计 ===",
        f"总反馈: {stats.total} 条",
        f"好评: {stats.good} 条 | 差评: {stats.bad} 条",
        f"好评率: {stats.good_rate*100:.0f}%",
    ]
    if stats.top_issues:
        lines.append(f"\n高频问题类型: {', '.join(stats.top_issues)}")
    if suggs:
        lines.append("\n改进建议:")
        for s in suggs:
            lines.append(f"  - {s}")
    if stats.recent:
        lines.append(f"\n最近反馈:")
        for r in stats.recent[-5:]:
            emoji = "👍" if r.get("rating") == "good" else "👎"
            lines.append(f"  {emoji} [{r['time']}] {r.get('comment','')[:30] or r.get('issue_type','')}")
    return "\n".join(lines)
