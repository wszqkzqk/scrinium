"""
_doc_extract.py — Metadata extraction for non-paper documents
=============================================================

For general documents lacking a title or abstract (technical reports,
lecture notes, standards, etc.), ingests minimal metadata built from the
first heading/filename plus the first 500 words (rule-based, zero model calls).
When extraction is poor, the pipeline emits a handoff hint so an agent can
write the proper title and abstract directly afterwards.
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
