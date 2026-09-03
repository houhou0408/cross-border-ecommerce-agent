#!/bin/sh
# ===== 跨境电商 AI Agent 容器启动入口 =====
# 1) 等待 MySQL 就绪（可选，失败则工具自动降级）
# 2) 首次启动时自动构建向量知识库（需要下载 BGE embedding 模型）
# 3) 交给 CMD 启动 uvicorn

set -e

echo "[容器] 启动跨境电商 AI Agent ..."

# ---- 1. 等待 MySQL（最多 60s；slim 镜像无 nc，用 python socket 探测） ----
if [ -n "$MYSQL_HOST" ] && [ "$MYSQL_HOST" != "127.0.0.1" ]; then
  echo "[容器] 等待 MySQL ${MYSQL_HOST}:${MYSQL_PORT} 就绪 ..."
  python - <<'PYEOF'
import os, socket, time, sys
host = os.environ.get("MYSQL_HOST", "mysql")
port = int(os.environ.get("MYSQL_PORT", "3306"))
for i in range(30):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[容器] MySQL {host}:{port} 已就绪。")
            sys.exit(0)
    except OSError:
        time.sleep(2)
print("[容器] MySQL 暂不可用，将以内置数据降级启动。")
PYEOF
fi

# ---- 2. 首次启动自动构建向量库（失败不阻塞服务启动，服务可在无库状态降级） ----
if [ ! -d "/app/向量库存储" ] || [ -z "$(ls -A /app/向量库存储 2>/dev/null)" ]; then
  echo "[容器] 检测到空向量库，首次构建知识库（将下载 BGE embedding 模型，约 100MB，耐心等待）..."
  if python -c "from 模块.切片向量化 import build_vectorstore; build_vectorstore()"; then
    echo "[容器] 向量库构建完成。"
  else
    echo "[容器] 向量库构建失败（网络原因？），服务仍将启动，RAG 检索将自动降级。"
  fi
else
  echo "[容器] 检测到已有向量库，跳过构建。"
fi

echo "[容器] 启动 FastAPI 服务 ..."
exec "$@"