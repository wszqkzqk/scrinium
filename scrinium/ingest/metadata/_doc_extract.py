"""
_doc_extract.py — 非论文文档的元数据提取
==========================================

对于缺少标题/摘要的普通文档（技术报告、课程讲义、标准文档等），
以首标题/文件名 + 前 500 词最小元数据入库（纯规则，零模型调用）。
提取结果不理想时由 pipeline 输出 handoff hint，agent 后处理直写
正式标题/摘要。
"""

from __future__ import annotations

import logging
from pathlib import Path

from scrinium.ingest.metadata._models import PaperMetadata

_log = logging.getLogger(__name__)


def extract_document_metadata(
    md_path: Path,
    *,
    existing_meta: PaperMetadata | None = None,
) -> PaperMetadata:
    """Extract metadata for a non-paper document (rule-based only).

    Flow:
    1. Try regex extraction (may get title, authors, etc.)
    2. Fill any gaps with fallback metadata (first heading / filename
       as title, first 500 words as abstract)

    Args:
        md_path: Markdown file path.
        existing_meta: Pre-existing metadata (if any).

    Returns:
        PaperMetadata with at least title and abstract filled.
    """
    from scrinium.ingest.extractor import RegexExtractor

    # Step 1: try regex extraction
    if existing_meta:
        meta = existing_meta
    else:
        try:
            extractor = RegexExtractor()
            meta = extractor.extract(md_path)
        except Exception as e:
            _log.debug("regex extraction failed for doc: %s", e)
            meta = PaperMetadata()

    # Step 2: fill gaps with minimal fallback metadata
    return _fallback_document_metadata(md_path, meta)


def _fallback_document_metadata(
    md_path: Path,
    meta: PaperMetadata | None = None,
) -> PaperMetadata:
    """Minimal metadata extraction without LLM."""
    if meta is None:
        meta = PaperMetadata()

    text = md_path.read_text(encoding="utf-8", errors="replace")

    # Title: first markdown heading or filename
    if not (meta.title or "").strip():
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("# ") and not line.startswith("## "):
                meta.title = line.lstrip("# ").strip()
                break
        if not (meta.title or "").strip():
            meta.title = md_path.stem.replace("-", " ").replace("_", " ")

    # Abstract: first 500 words as summary
    if not (meta.abstract or "").strip():
        words = text.split()[:500]
        meta.abstract = " ".join(words)

    meta.paper_type = meta.paper_type or "document"
    meta.extraction_method = "fallback_document"
    return meta
