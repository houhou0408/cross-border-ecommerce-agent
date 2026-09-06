# -*- coding: utf-8 -*-
"""文档加载模块：从知识库目录读取 .md/.txt/.pdf 文档并转为 LangChain Document。

设计要点：
- 支持多种格式，按扩展名分发到对应 Loader；
- 自动补充 source/标题等元数据，便于检索溯源；
- 容错：单文件解析失败不影响整体流程。
"""
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import TextLoader, PyPDFLoader

from config import KNOWLEDGE_DIR
from 基础设施.日志统计 import get_file_logger
logger = get_file_logger("文档加载")


# 扩展名 -> Loader 映射（.md 用 TextLoader，避免装重量级 unstructured）
_LOADER_MAP = {
    ".md": TextLoader,
    ".txt": TextLoader,
    ".pdf": PyPDFLoader,
}


def load_single_file(file_path: Path) -> List[Document]:
    """加载单个文件为 Document 列表。"""
    ext = file_path.suffix.lower()
    loader_cls = _LOADER_MAP.get(ext)
    if loader_cls is None:
        return []
    try:
        docs = loader_cls(str(file_path)).load()
        # 补充元数据：文件名、标题，便于后续溯源引用
        for d in docs:
            d.metadata.setdefault("source", file_path.name)
            d.metadata.setdefault("title", file_path.stem)
        return docs
    except Exception as e:  # noqa: BLE001
        logger.warning("[文档加载] 解析失败 %s: %s", file_path.name, e)
        return []


def load_documents(directory: Path = None) -> List[Document]:
    """加载目录下全部知识文档。

    Args:
        directory: 知识库目录，默认取 config.KNOWLEDGE_DIR

    Returns:
        合并后的 Document 列表
    """
    directory = directory or KNOWLEDGE_DIR
    all_docs: List[Document] = []
    files = sorted(
        [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in _LOADER_MAP]
    )
    if not files:
        logger.warning("[文档加载] 目录 %s 下未发现可加载文档", directory)
        return all_docs

    for fp in files:
        docs = load_single_file(fp)
        all_docs.extend(docs)
        logger.info("[文档加载] %s -> %s 个文档块", fp.name, len(docs))
    logger.info("[文档加载] 完成，共加载 %s 个文档", len(all_docs))
    return all_docs


if __name__ == "__main__":
    docs = load_documents()
    for d in docs[:2]:
        logger.info("\n--- %s ---\n%s", d.metadata, d.page_content[:120])
