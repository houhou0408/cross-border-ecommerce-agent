"""直接测试 Agent 能否调用工具"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("测试 1: Agent 模块导入")
print("=" * 60)
try:
    from 模块 import Agent调度
    print("✓ Agent调度 模块导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

print()
print("=" * 60)
print("测试 2: 创建 Agent 实例")
print("=" * 60)
try:
    agent = Agent调度.get_agent()
    print(f"✓ Agent 创建成功: {type(agent).__name__}")
except Exception as e:
    print(f"✗ 创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 60)
print("测试 3: 简单查询 - 美国电子产品关税")
print("=" * 60)
try:
    result = agent.orchestrate("美国电子产品关税税率是多少", session_id="test_001")
    print(f"✓ 查询完成")
    print(f"  答案: {result.get('answer', '')[:200]}...")
    print(f"  工具: {result.get('tools_used', [])}")
    print(f"  grounded: {result.get('grounded')} (score={result.get('score')})")
    print(f"  耗时: {result.get('latency_ms')} ms")
except Exception as e:
    print(f"✗ 查询失败: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
print("测试完成")
print("=" * 60)
