# -*- coding: utf-8 -*-
"""桌面端启动器：双击运行，本地拉起 FastAPI 服务 + 桌面窗口。

用法:
    python 桌面端启动.py

行为:
- 自动在空闲端口启动后端服务（避免与已运行的 8000 端口实例冲突）；
- 用 pywebview 弹出桌面窗口加载 Web 界面；
- 关闭窗口后服务自动退出，不残留后台进程。
"""
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# 项目自带第三方依赖目录 libs/ 兜底
_libs_dir = _ROOT / "libs"
if _libs_dir.exists():
    sys.path.insert(0, str(_libs_dir))

# 国内镜像加速 embedding 模型访问（若未在 .env 配置）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


def _free_port() -> int:
    """获取一个空闲端口。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ready(url: str, timeout: float = 20.0) -> bool:
    """等待后端服务就绪（/health 返回 200）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def main():
    import uvicorn
    import webview

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    # 复用 接口/FastAPI服务.py 的 app（含静态前端挂载）
    from 接口.FastAPI服务 import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    if not _wait_ready(f"{base_url}/health"):
        print(f"[桌面端] 后端服务启动失败（{base_url}），请检查依赖与端口占用。")
        server.should_exit = True
        sys.exit(1)

    print(f"[桌面端] 后端就绪: {base_url}")
    window = webview.create_window(
        "跨境电商 AI 助手",
        f"{base_url}/",
        width=1360,
        height=860,
        min_size=(1080, 720),
        confirm_close=True,  # 关闭时二次确认，防止误关丢数据
    )
    webview.start()

    # 窗口关闭 → 停止后端
    server.should_exit = True
    print("[桌面端] 窗口已关闭，服务已停止。")


if __name__ == "__main__":
    main()
