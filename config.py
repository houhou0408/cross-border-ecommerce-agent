# -*- coding: utf-8 -*-
"""全局配置：模型、向量库、数据库、路径等集中管理。
说明：所有可调参数集中在此，方便面试演示时切换模型/数据源。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 加载项目根目录的 .env 文件（必须在读取 os.getenv 之前执行）
load_dotenv(Path(__file__).resolve().parent / ".env")

# ============ 路径配置 ============
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "数据"
KNOWLEDGE_DIR = DATA_DIR / "知识库文档"
CHROMA_DIR = PROJECT_ROOT / "向量库存储"
LOG_DIR = PROJECT_ROOT / "日志"

for _d in (DATA_DIR, KNOWLEDGE_DIR, CHROMA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ============ LLM 配置（OpenAI 兼容接口，可接 DeepSeek/通义千问/OpenAI）============
# 通过环境变量覆盖，避免硬编码密钥
LLM_CONFIG = {
    "model": os.getenv("LLM_MODEL", "deepseek-chat"),
    "api_key": os.getenv("LLM_API_KEY", "sk-your-api-key"),
    "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
    "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
}

# ============ Embedding 配置 ============
# 默认使用 BGE 中文小模型（本地运行，无需密钥），也可切换为 OpenAI 在线 Embedding
EMBEDDING_CONFIG = {
    "provider": os.getenv("EMBEDDING_PROVIDER", "huggingface"),  # huggingface | openai
    # HuggingFace 本地模型（推荐 BAAI/bge-small-zh-v1.5，体积小、中文效果好）
    "hf_model": os.getenv("HF_EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
    # OpenAI 在线 Embedding
    "openai_model": os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
}

# ============ Chroma 向量库配置 ============
CHROMA_CONFIG = {
    "persist_dir": str(CHROMA_DIR),
    "collection_name": "cross_border_kb",
}

# ============ MySQL 配置（用于日志统计与Listing存档）============
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "root"),
    "database": os.getenv("MYSQL_DATABASE", "cross_border_agent"),
}

# ============ 检索配置 ============
RETRIEVAL_CONFIG = {
    "chunk_size": 500,            # 切片字符数
    "chunk_overlap": 80,          # 切片重叠
    "top_k": 4,                   # 检索召回数
    "score_threshold": 0.35,      # 相似度阈值（低于则判为未命中）
}

# ============ 幻觉治理配置 ============
HALLUCINATION_CONFIG = {
    "enabled": True,              # 是否开启幻觉校验
    "min_grounding_score": 0.45,  # 答案-上下文最低对齐分
    "max_answer_tokens": 800,     # 答案长度上限，过长易发散
}

# ============ 视频生成配置（阿里云百炼 HappyHorse 1.1 R2V）============
VIDEO_CONFIG = {
    "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
    "model": os.getenv("VIDEO_MODEL", "happyhorse-1.1-r2v"),
    "base_url": "https://dashscope.aliyuncs.com/api/v1",
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5,
    "poll_interval": 5,          # 轮询间隔（秒）
    "poll_timeout": 300,         # 轮询超时（秒）
}
