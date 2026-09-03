# -*- coding: utf-8 -*-
"""根 conftest：确保项目根目录在 sys.path，并设置测试环境变量占位。

设计说明：
- 测试全程不依赖 MySQL / LLM Key / 外部网络 / embedding 模型；
- LLM_API_KEY 设占位值防止 config.py 读取 .env 失败告警；
- 必须在 import 项目模块【之前】设置环境变量。
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# 环境变量占位（在 sys.path 注入和模块导入前生效）
os.environ.setdefault("LLM_API_KEY", "sk-test-dummy")

sys.path.insert(0, str(_ROOT))

# 项目自带第三方依赖目录 libs/ 兜底（与 桌面端启动.py 的处理保持一致）
_libs_dir = _ROOT / "libs"
if _libs_dir.exists():
    sys.path.insert(0, str(_libs_dir))
