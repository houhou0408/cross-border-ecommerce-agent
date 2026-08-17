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
    "collections": {
        "products": "kb_products",    # 产品参数库（尺寸/材质/功能真实数据）
        "rules": "kb_rules",          # 平台规则库（各站点违禁词+合规红线）
        "listings": "kb_listings",    # 爆款文案库（公司优质范本）
        "risks": "kb_risks",          # 风险案例库（过往违规、翻车、差评案例）
    },
}

# ============ MySQL 配置（用于日志统计与Listing存档）============
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "root"),
    "database": os.getenv("MYSQL_DATABASE", "cross_border_agent"),
}

# ============ 用户鉴权配置 ============
AUTH_CONFIG = {
    "token_expire_hours": int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "72")),  # token 有效期
    "users_file": str(Path(__file__).parent / "数据" / "users.json"),       # 用户数据文件
    "tokens_file": str(Path(__file__).parent / "数据" / "tokens.json"),     # token 映射文件
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

# 品类→场景描述映射（用于卖点图智能场景匹配）
_SCENE_MAP = {
    "电子产品": "modern tech workspace, clean desk setup, ambient LED lighting, "
                "glossy product surfaces, futuristic minimalist style",
    "服装": "fashion studio, natural daylight, model wearing on urban street, "
           "soft fabric flow, editorial magazine style",
    "家居": "bright cozy living room, warm sunlight through window, "
           "Scandinavian interior design, plants and natural textures",
    "美妆": "luxury vanity table, soft ring light, marble background, "
           "elegant gold accents, beauty editorial style",
    "宠物用品": "happy pet in bright home, natural outdoor grass, "
               "playful action shots, warm affectionate moments",
    "户外运动": "adventure outdoor landscape, golden hour sunlight, "
               "action in nature, rugged terrain, athletic lifestyle",
    "玩具": "colorful playful kids room, soft diffused light, "
           "cheerful bright colors, safe child-friendly setting",
    "厨房用品": "modern white kitchen, fresh ingredients, steam and motion, "
               "professional chef style, clean marble countertop",
}

# ============ 视频生成配置（阿里云百炼 HappyHorse I2V 图生视频）============
VIDEO_CONFIG = {
    "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
    "model": os.getenv("VIDEO_MODEL", "happyhorse-i2v"),
    "base_url": "https://dashscope.aliyuncs.com/api/v1",
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5,
    "poll_interval": 5,          # 轮询间隔（秒）
    "poll_timeout": 300,         # 轮询超时（秒）
}

# ============ 文生视频配置（通义万相 Wan2.1 T2V）============
# 文生视频：纯文字描述生成视频，无需参考图片
# 模型可选：wanx2.1-t2v-turbo（快速度）/ wanx2.1-t2v-plus（高质量）
VIDEO_T2V_CONFIG = {
    "model": os.getenv("VIDEO_T2V_MODEL", "wanx2.1-t2v-turbo"),
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5,
}

# ============ 图像生成配置（通义万相 Wan2.1 T2I）============
# 用于「商品卖点图」批量生成：上传商品图 + 描述，AI 生成全套电商营销图
# 模型可选：wanx2.1-t2i-turbo（快速度）/ wanx2.1-t2i-plus（高质量）
# 复用 DASHSCOPE_API_KEY，无需单独配置
IMAGE_T2I_CONFIG = {
    "api_key": os.getenv("DASHSCOPE_API_KEY", ""),
    # model: 精品模式 → wan2.7-image（高质量），铺货模式 → fast_model（快速低成本）
    "model": os.getenv("IMAGE_T2I_MODEL", "wan2.7-image"),  # 万相2.7（支持图生图参考）
    "fast_model": "wan2.2-t2i-flash",  # 铺货模式用更快更便宜的模型
    "base_url": "https://dashscope.aliyuncs.com/api/v1",
    "size": "1024*1024",          # 生成图尺寸（宽*高）
    "n": 1,                        # 每种类型生成几张
    "poll_interval": 3,            # 轮询间隔（秒）
    "poll_timeout": 180,           # 轮询超时（秒）
}

# 卖点图类型与 prompt 模板（4 种电商标准营销图）
# 变量 {product} 由用户描述填充，{features} 由卖点列表填充
# 重要：上传的商品图是唯一主体来源，prompt 只指定风格/排版，禁止 AI 自由发挥生成别的产品。
#       通义万相生成图片上的中文文字会乱码，主图/场景图强制 no text；
#       卖点标注图/详情长图允许少量英文标注（中文仍会乱码，故仅英文）。
_NO_TEXT = "no text, no words, no letters, no typography, no watermark, no captions, no labels, no writing"
_EN_TEXT_OK = "minimal English text labels allowed, no Chinese text, no watermark"
# 参考图强约束：必须严格基于参考图，禁止生成参考图中没有的产品
_KEEP_REF = ("Strictly based on the provided reference product image. "
             "Generate the EXACT same product shown in the reference image — same type, same shape, same color, same design. "
             "Do NOT generate a different product. Do NOT use the text description to change the product. "
             "The reference image is the only source of truth for what the product looks like. ")
IMAGE_TEMPLATES = {
    "main": {
        "name": "白底主图",
        "prompt": _KEEP_REF +
                  "Professional e-commerce product photography of the reference product, "
                  "centered composition, pure white background (#FFFFFF), "
                  "soft studio lighting, sharp focus, high detail, 8k quality, "
                  "clean and minimal, " + _NO_TEXT + ", 1:1 square format",
    },
    "scene": {
        "name": "场景应用图",
        "prompt": _KEEP_REF +
                  "Lifestyle product photography of the reference product, "
                  "{scene_desc}, "
                  "showing the reference product being used, cinematic composition, 8k quality, "
                  + _NO_TEXT,
    },
    "features": {
        "name": "卖点标注图",
        "prompt": _KEEP_REF +
                  "E-commerce product feature infographic of the reference product, "
                  "clean layout with English feature callouts: {features}, "
                  "modern flat design, accent color highlights on the reference product, "
                  "professional marketing style, high contrast, clear hierarchy, 8k quality, "
                  + _EN_TEXT_OK,
    },
    "detail": {
        "name": "详情长图",
        "prompt": _KEEP_REF +
                  "Vertical e-commerce product detail page design of the reference product, "
                  "showing the reference product from multiple angles with English labels: {features}, "
                  "layered sections with visual hierarchy, modern minimalist style, "
                  "soft gradient background, premium branding feel, "
                  "8k quality, vertical 3:4 format, " + _EN_TEXT_OK,
    },
}
