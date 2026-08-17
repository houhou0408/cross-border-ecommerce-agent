# -*- coding: utf-8 -*-
"""临时脚本：重跑效果评估（16 条测试集），打印汇总 + 人工抽检 + 明细。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from 模块.效果评估 import get_evaluator

rep = get_evaluator().run_all()

print("=== 汇总 ===")
summary_keys = [
    "total", "tool_success_rate", "answer_accuracy_rate",
    "hallucination_rate", "hallucination_count", "honest_low_confidence",
    "avg_latency_ms", "quality",
    "tool_pass_count", "answer_pass_count",
]
print(json.dumps({k: rep[k] for k in summary_keys}, ensure_ascii=False, indent=1))

print("\n=== 人工抽检清单 ===")
print(json.dumps(rep["manual_review"], ensure_ascii=False, indent=1))

print("\n=== 明细 ===")
for d in rep["details"]:
    print(
        f"{d['test_id']} [{d['level']}] {d['category']} | "
        f"tool={d['tool_pass']} | {d['quality']} | "
        f"kw={d['keyword_hits']}/{d['keyword_total']} | "
        f"grounded={d['grounded']} honest={d['honest_degrade']} | "
        f"{d['latency_ms']}ms | tools={d['tools_used']} | err={d['error']}"
    )
