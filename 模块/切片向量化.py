# -*- coding: utf-8 -*-
"""切片与向量化模块：把文档切片后写入 Chroma 向量库。

设计要点：
- 使用 RecursiveCharacterTextSplitter 按中文分隔符递归切分，保留语义完整；
- Embedding 支持 HuggingFace(BGE) 与 OpenAI 两种 provider，通过配置切换；
- 向量库持久化到本地，避免每次重启重新 embedding（省时省钱）；
- 提供 build / load 两个入口，构建一次多次复用。
"""
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import EMBEDDING_CONFIG, CHROMA_CONFIG, RETRIEVAL_CONFIG
from 基础设施.日志统计 import get_file_logger
logger = get_file_logger("切片向量化")

# 全局缓存，避免重复加载模型（embedding 模型加载较慢）
_embedding_model: Optional[Embeddings] = None


def get_embedding_model() -> Embeddings:
    """获取 Embedding 模型（单例缓存）。"""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    provider = EMBEDDING_CONFIG["provider"].lower()
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        _embedding_model = OpenAIEmbeddings(model=EMBEDDING_CONFIG["openai_model"])
    else:
        # 默认 HuggingFace + BGE（本地推理，无需密钥）
        from langchain_huggingface import HuggingFaceEmbeddings
        _embedding_model = HuggingFaceEmbeddings(
            model_name=EMBEDDING_CONFIG["hf_model"],
            encode_kwargs={"normalize_embeddings": True},  # 归一化便于余弦相似度
        )
    logger.info("[切片向量化] Embedding 模型已加载: provider=%s", provider)
    return _embedding_model


def split_documents(docs: List[Document]) -> List[Document]:
    """将文档递归切片。

    使用中文常用分隔符（句号、换行、逗号等）优先在语义边界切分，
    避免把一句话从中间截断，提升检索准确率。
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=RETRIEVAL_CONFIG["chunk_size"],
        chunk_overlap=RETRIEVAL_CONFIG["chunk_overlap"],
        separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    logger.info("[切片向量化] 切片完成: %s 文档 -> %s 块", len(docs), len(chunks))
    return chunks


def build_vectorstore(docs: List[Document] = None, force_rebuild: bool = False):
    """构建（或重建）Chroma 向量库。

    Args:
        docs: 待写入的文档；为空时自动从知识库目录加载。
        force_rebuild: True 时先清空旧库再重建。
    """
    from langchain_chroma import Chroma
    import shutil
    from pathlib import Path

    persist_dir = Path(CHROMA_CONFIG["persist_dir"])
    if force_rebuild and persist_dir.exists():
        shutil.rmtree(persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[切片向量化] 已清空旧向量库: %s", persist_dir)

    if docs is None:
        from 模块.文档加载 import load_documents
        docs = load_documents()

    chunks = split_documents(docs)
    embedding = get_embedding_model()

    vs = Chroma.from_documents(
        documents=chunks,
        embedding=embedding,
        collection_name=CHROMA_CONFIG["collection_name"],
        persist_directory=CHROMA_CONFIG["persist_dir"],
    )
    logger.info("[切片向量化] 向量库构建完成，共 %s 条向量", len(chunks))
    return vs


def load_vectorstore(collection_name: str = None):
    """加载已持久化的 Chroma 向量库。

    Args:
        collection_name: None=默认全量库(cross_border_kb),
                         或 "products"/"rules"/"listings"/"risks" 按分库加载。

    若向量库不存在则自动触发构建。
    """
    from langchain_chroma import Chroma
    from pathlib import Path

    # 解析实际 collection 名称
    collections = CHROMA_CONFIG.get("collections", {})
    if collection_name is None:
        actual_name = CHROMA_CONFIG["collection_name"]
    elif collection_name in collections:
        actual_name = collections[collection_name]
    else:
        actual_name = collection_name  # 兜底：直接用传入值

    persist_dir = Path(CHROMA_CONFIG["persist_dir"])
    embedding = get_embedding_model()

    if not persist_dir.exists() or not any(persist_dir.iterdir()):
        logger.info("[切片向量化] 未检测到向量库，开始自动构建...")
        return build_vectorstore()

    vs = Chroma(
        collection_name=actual_name,
        embedding_function=embedding,
        persist_directory=CHROMA_CONFIG["persist_dir"],
    )
    logger.info("[切片向量化] 已加载向量库: %s, collection=%s", persist_dir, actual_name)
    return vs


def add_documents(docs: List[Document]):
    """向已存在的向量库追加文档（动态入库，无需重建）。

    用于知识库管理页：用户上传文档 → 切片 → 增量写入 Chroma。
    返回写入的切片数。
    """
    chunks = split_documents(docs)
    vs = load_vectorstore()
    vs.add_documents(chunks)
    logger.info("[切片向量化] 增量入库 %s 条切片", len(chunks))
    return len(chunks)


def add_documents_to_library(documents: list, library: str = "products"):
    """将文档添加到指定知识库。

    Args:
        documents: LangChain Document 列表
        library: "products"/"rules"/"listings"/"risks"
    Returns:
        写入的切片数。
    """
    from langchain_chroma import Chroma

    collections = CHROMA_CONFIG.get("collections", {})
    if library in collections:
        collection_name = collections[library]
    else:
        collection_name = library  # 兜底：直接用传入值

    chunks = split_documents(documents)
    embedding = get_embedding_model()
    vs = Chroma(
        collection_name=collection_name,
        embedding_function=embedding,
        persist_directory=CHROMA_CONFIG["persist_dir"],
    )
    vs.add_documents(chunks)
    logger.info("[切片向量化] 增量入库 %s(%s): %s 条切片", library, collection_name, len(chunks))
    return len(chunks)


def list_documents() -> List[dict]:
    """列出向量库中所有文档的来源与切片统计。

    通过 Chroma 的 metadata 聚合 source 字段。
    """
    from langchain_chroma import Chroma

    vs = Chroma(
        collection_name=CHROMA_CONFIG["collection_name"],
        embedding_function=get_embedding_model(),
        persist_directory=CHROMA_CONFIG["persist_dir"],
    )
    collection = vs._collection
    all_meta = collection.get(include=["metadatas"])
    sources = {}
    for m in all_meta.get("metadatas", []):
        src = (m or {}).get("source", "未知")
        if src not in sources:
            sources[src] = {"source": src, "chunks": 0}
        sources[src]["chunks"] += 1
    return list(sources.values())


def delete_document(source: str) -> int:
    """按来源文件名删除向量库中对应的所有切片。返回删除数量。"""
    from langchain_chroma import Chroma

    vs = Chroma(
        collection_name=CHROMA_CONFIG["collection_name"],
        embedding_function=get_embedding_model(),
        persist_directory=CHROMA_CONFIG["persist_dir"],
    )
    collection = vs._collection
    before = collection.count()
    collection.delete(where={"source": source})
    after = collection.count()
    deleted = before - after
    logger.info("[切片向量化] 删除 %s: %s 条切片", source, deleted)
    return deleted


if __name__ == "__main__":
    # 直接运行可重建知识库
    build_vectorstore(force_rebuild=True)
