# ===== 跨境电商 AI Agent Dockerfile（多阶段构建） =====
# 阶段一：用 Node 构建 React 前端 → 产物 前端/dist/
# 阶段二：用 Python 运行 FastAPI 后端，并拷贝前端产物

# ---------- Stage 1: 前端构建 ----------
FROM node:20-alpine AS frontend
WORKDIR /build/前端/react-app
# 先拷贝 package 文件利用缓存（npm ci 严格按 lock 安装，保证可复现）
COPY 前端/react-app/package*.json ./
RUN npm ci
COPY 前端/react-app/ ./
RUN npm run build
# 产物位于 /build/前端/dist（vite.config 输出到 dist，位于 react-app 同级的前端/ 下）

# ---------- Stage 2: 后端运行 ----------
FROM python:3.11-slim

# 国内 pip 镜像（可注释取消）与 HF 国内镜像加速 embedding 下载
ENV HF_ENDPOINT=https://hf-mirror.com \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先装依赖（利用 docker layer 缓存，避免每次改代码重装）
# 说明：BGE embedding 用 CPU 跑即可，因此先装 CPU 版 torch（避免默认拉取 ~2GB 的 CUDA 依赖），
# 再安装其余 requirements（torch 已满足 langchain/sentence-transformers 的 torch>=1.11.0 约束）。
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝后端代码（仅运行时所需；测试/演示/桌面端启动器不进生产镜像）
COPY config.py ./
COPY 基础设施/ ./基础设施/
COPY 模块/ ./模块/
COPY 工具集/ ./工具集/
COPY 接口/ ./接口/
COPY 数据/ ./数据/
COPY 前端/index.html ./前端/

# 从前端构建阶段拷贝 React 产物（FastAPI 挂载 前端/dist）
COPY --from=frontend /build/前端/dist ./前端/dist

# 容器启动脚本
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# 数据卷：向量库、上传素材、日志、用户/token 数据均持久化
VOLUME ["/app/向量库存储", "/app/静态资源", "/app/日志", "/app/数据"]

EXPOSE 8000

# 服务健康探针：/health 在鉴权白名单内，无需 token（start-period 覆盖首启建模时间）
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "接口.FastAPI服务:app", "--host", "0.0.0.0", "--port", "8000"]