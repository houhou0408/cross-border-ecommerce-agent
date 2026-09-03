# -*- coding: utf-8 -*-
"""命令行演示：交互式跨境电商 Agent，面试现场演示主入口。

用法:
    python 演示/命令行演示.py

功能:
- 支持自然语言多任务问答（走完整 Agent 链路）；
- 支持快捷指令:
  /listing  生成Listing   /tariff  查关税   /currency 换算汇率
  /stats    运行统计      /rebuild 重建知识库   /help    帮助   /exit 退出
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 项目自带第三方依赖目录 libs/ 兜底，保证直接启动不缺包
_libs_dir = Path(__file__).resolve().parent.parent / "libs"
if _libs_dir.exists():
    sys.path.insert(0, str(_libs_dir))

from 模块.Agent调度 import get_agent
from 模块.日志统计 import get_logger
from 工具集.关税查询 import 查询关税
from 工具集.汇率转换 import 汇率换算
from 工具集.Listing生成 import 生成产品Listing
from 模块.切片向量化 import build_vectorstore


BANNER = r"""
========================================================
   跨境电商 AI Agent  (ReAct + RAG + Function Call)
   技术栈: Python · LangChain · Chroma · MySQL · FastAPI
========================================================
输入自然语言任务，或输入 /help 查看快捷指令，/exit 退出
"""


def print_help():
    print("""
快捷指令:
  /listing <产品> [平台] [语言]   生成 Listing   例: /listing 蓝牙音箱 amazon en
  /tariff <国> <类别> [货值]       查关税         例: /tariff 美国 电子产品 500
  /currency <金额> <源> <目标>     换算汇率       例: /currency 500 USD CNY
  /stats                           运行统计
  /rebuild                         重建向量知识库
  /help                            帮助
  /exit                            退出

自然语言示例:
  1) 蓝牙音箱出口美国电子产品，货值500美元，查关税并换算成人民币
  2) 帮我写一个亚马逊的无线蓝牙音箱Listing，卖点IPX7防水续航20小时
  3) 欧盟电子产品需要哪些认证？
""")


def handle_shortcut(cmd: str) -> bool:
    """处理快捷指令，返回 True 表示已处理。"""
    parts = cmd.strip().split()
    if not parts:
        return False
    key = parts[0].lower()

    if key == "/help":
        print_help()
        return True
    if key == "/exit":
        print("再见！")
        sys.exit(0)
    if key == "/stats":
        print(get_logger().stats())
        return True
    if key == "/rebuild":
        print("重建知识库中（首次会下载 embedding 模型，请稍候）...")
        build_vectorstore(force_rebuild=True)
        print("知识库重建完成。")
        return True
    if key == "/currency" and len(parts) >= 4:
        amt = float(parts[1])
        text = 汇率换算.invoke({"金额": amt, "源币种": parts[2], "目标币种": parts[3]})
        print("\n" + text)
        return True
    if key == "/tariff" and len(parts) >= 3:
        country, category = parts[1], parts[2]
        value = float(parts[3]) if len(parts) >= 4 else 0.0
        text = 查询关税.invoke({"目的国": country, "商品类别": category, "货值": value})
        print("\n" + text)
        return True
    if key == "/listing" and len(parts) >= 2:
        product = parts[1]
        platform = parts[2] if len(parts) >= 3 else "amazon"
        lang = parts[3] if len(parts) >= 4 else "en"
        text = 生成产品Listing.invoke({"产品名称": product, "平台": platform, "语言": lang})
        print("\n" + text)
        return True
    return False


def main():
    print(BANNER)
    agent = get_agent()
    print_help()

    while True:
        try:
            user_input = input("\n🧑 你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user_input:
            continue

        # 快捷指令
        if user_input.startswith("/"):
            if not handle_shortcut(user_input):
                print("未知指令，输入 /help 查看帮助。")
            continue

        # 自然语言 -> Agent
        print("\n🤖 Agent 思考中...\n" + "-" * 50)
        try:
            result = agent.orchestrate(user_input)
            print("-" * 50)
            print("🤖 回答:")
            print(result["answer"])
            print("\n📋 元信息:")
            print(f"  会话ID: {result['session_id']}")
            print(f"  耗时: {result['latency_ms']}ms")
            print(f"  工具链: {[t['tool'] for t in result['tools_used']]}")
            print(f"  幻觉校验: grounded={result['grounded']} score={result['score']} | {result['reason']}")
        except Exception as e:  # noqa: BLE001
            print(f"❌ 执行失败: {e}")


if __name__ == "__main__":
    main()
