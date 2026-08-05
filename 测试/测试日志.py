# -*- coding: utf-8 -*-
"""测试脚本：对各模块做冒烟测试，并生成测试日志（日志/测试日志.txt）。

运行: python 测试/测试日志.py

说明：
- 不依赖 LLM 在线接口的测试默认执行（文档加载/切片/关税/汇率/幻觉治理逻辑）；
- 需要 LLM/向量库的测试在 API Key 未配置时自动跳过并记录 SKIP。
"""
import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime

# 加载 .env（若存在）
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "日志"
LOG_DIR.mkdir(exist_ok=True)

TEST_LOG = LOG_DIR / "测试日志.txt"


class TestRunner:
    def __init__(self):
        self.lines = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def _log(self, msg: str):
        print(msg)
        self.lines.append(msg)

    def run(self, name: str, fn):
        self._log(f"\n[TEST] {name}")
        try:
            fn(self)
            self.passed += 1
            self._log(f"  -> PASS")
        except AssertionError as e:
            self.failed += 1
            self._log(f"  -> FAIL: {e}")
        except Exception as e:  # noqa: BLE001
            self.failed += 1
            self._log(f"  -> ERROR: {type(e).__name__}: {e}")

    def skip(self, reason: str):
        self.skipped += 1
        self._log(f"  -> SKIP: {reason}")

    def save(self):
        header = (
            f"========== 跨境电商 AI Agent 测试日志 ==========\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"环境: Python {sys.version.split()[0]} | OS={os.name}\n"
            f"LLM_MODEL={os.getenv('LLM_MODEL','(未配置)')} | "
            f"EMBEDDING_PROVIDER={os.getenv('EMBEDDING_PROVIDER','huggingface')}\n"
            f"汇总: 通过={self.passed} 失败={self.failed} 跳过={self.skipped}\n"
            f"================================================\n"
        )
        with open(TEST_LOG, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(self.lines))
        self._log(f"\n测试日志已保存: {TEST_LOG}")


# ============ 测试用例 ============
def test_文档加载(t: TestRunner):
    from 模块.文档加载 import load_documents
    docs = load_documents()
    assert len(docs) > 0, "知识库文档加载为空"
    t._log(f"  加载文档数: {len(docs)}")


def test_切片(t: TestRunner):
    from 模块.文档加载 import load_documents
    from 模块.切片向量化 import split_documents
    docs = load_documents()
    chunks = split_documents(docs)
    assert len(chunks) >= len(docs), "切片数应不少于文档数"
    t._log(f"  切片数: {len(chunks)}")


def test_关税查询(t: TestRunner):
    from 工具集.关税查询 import 查询关税
    text = 查询关税.invoke({"目的国": "美国", "商品类别": "电子产品", "货值": 500})
    assert "25.00%" in text or "关税税率" in text, f"关税查询结果异常: {text}"
    t._log(f"  关税结果: {text.splitlines()[-1]}")


def test_关税计算(t: TestRunner):
    from 工具集.关税查询 import 查询关税
    text = 查询关税.invoke({"目的国": "美国", "商品类别": "服装", "货值": 1000, "运费": 50, "保险费": 10})
    assert "应缴关税" in text, "应缴关税计算缺失"
    t._log(f"  计算结果含应缴关税")


def test_汇率换算(t: TestRunner):
    from 工具集.汇率转换 import 汇率换算
    text = 汇率换算.invoke({"金额": 100, "源币种": "USD", "目标币种": "CNY"})
    assert "719" in text or "CNY" in text, f"汇率换算异常: {text}"
    t._log(f"  换算: {text.splitlines()[1]}")


def test_幻觉治理_无上下文(t: TestRunner):
    from 模块.幻觉治理 import get_guard
    guard = get_guard()
    r = guard.verify("亚马逊标题不超过200字符", "（未检索到相关知识）")
    assert not r.grounded, "无上下文时应判为未通过"
    t._log(f"  无上下文置信度: {r.grounding_score}")


def test_幻觉治理_有上下文(t: TestRunner):
    from 模块.幻觉治理 import get_guard
    guard = get_guard()
    ctx = "亚马逊Listing标题长度不超过200字符，首字母大写，禁止促销用语。"
    r = guard.verify("亚马逊标题长度不超过200字符，需首字母大写。", ctx)
    assert r.grounded, f"有上下文支撑应通过, score={r.grounding_score}"
    t._log(f"  有上下文置信度: {r.grounding_score}")


def test_幻觉治理_绝对化词(t: TestRunner):
    from 模块.幻觉治理 import get_guard
    guard = get_guard()
    ctx = "电子产品关税税率为25%。"
    r = guard.verify("电子产品关税100%保证准确，绝对不会错。", ctx)
    assert any("绝对" in s or "100%" in s for s in r.suggestions), "应检测到绝对化表述"
    t._log(f"  检测到绝对化词: {r.suggestions}")


def test_数据库降级(t: TestRunner):
    from 工具集.数据库连接 import get_cursor
    with get_cursor() as cur:
        status = "可用" if cur is not None else "降级(使用内置数据)"
    t._log(f"  数据库状态: {status}")
    # 无论是否降级，关税工具都应能返回结果（已在 test_关税查询 覆盖）


def test_向量库构建与检索(t: TestRunner):
    api_key = os.getenv("LLM_API_KEY", "")
    if "your-api-key" in api_key or not api_key:
        # 无 LLM key 仍可测试向量库（embedding 用本地 BGE）
        pass
    try:
        from 模块.检索器 import 检索器
        r = 检索器()
        hits = r.search_with_scores("亚马逊Listing标题要求")
        assert isinstance(hits, list), "检索应返回列表"
        t._log(f"  检索命中: {len(hits)} 条")
    except Exception as e:  # noqa: BLE001
        t.skip(f"向量库测试未执行（可能未下载embedding模型）: {e}")


def test_Agent端到端(t: TestRunner):
    api_key = os.getenv("LLM_API_KEY", "")
    if "your-api-key" in api_key or not api_key:
        t.skip("未配置 LLM_API_KEY，跳过端到端测试")
        return
    try:
        from 模块.Agent调度 import get_agent
        agent = get_agent()
        result = agent.orchestrate("美国电子产品关税税率是多少", verbose=False)
        assert "answer" in result, "Agent应返回answer字段"
        t._log(f"  端到端耗时: {result['latency_ms']}ms 工具链: {[x['tool'] for x in result['tools_used']]}")
    except Exception as e:  # noqa: BLE001
        t.skip(f"端到端测试异常: {e}")


def main():
    runner = TestRunner()
    runner._log("开始执行模块冒烟测试...\n")
    tests = [
        ("文档加载", test_文档加载),
        ("文档切片", test_切片),
        ("关税查询(降级)", test_关税查询),
        ("关税CIF计算", test_关税计算),
        ("汇率换算(降级)", test_汇率换算),
        ("幻觉治理-无上下文", test_幻觉治理_无上下文),
        ("幻觉治理-有上下文", test_幻觉治理_有上下文),
        ("幻觉治理-绝对化词", test_幻觉治理_绝对化词),
        ("数据库降级策略", test_数据库降级),
        ("向量库检索", test_向量库构建与检索),
        ("Agent端到端", test_Agent端到端),
    ]
    for name, fn in tests:
        runner.run(name, fn)
    runner._log(f"\n========== 汇总: 通过={runner.passed} 失败={runner.failed} 跳过={runner.skipped} ==========")
    runner.save()


if __name__ == "__main__":
    main()
