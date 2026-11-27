"""
extractor.py — Paper metadata extractor
=======================================

Stage-1 metadata extraction (extracts title/authors/year/doi/journal from
MinerU markdown). Only RegexExtractor (regex only, zero model calls) is kept
in the framework; difficult files that fail rule-based extraction are routed
to the pending queue for agent/subagent review.

Usage
-----
    from scrinium.ingest.extractor import get_extractor

    extractor = get_extractor()
    meta = extractor.extract(Path("paper.md"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scrinium.ingest.metadata import PaperMetadata


# ============================================================================
#  Protocol
# ============================================================================


@runtime_checkable
class MetadataExtractor(Protocol):
    """Metadata extractor protocol; all extractors must implement this interface."""

    def extract(self, filepath: Path) -> PaperMetadata:
        """Extract paper metadata from a Markdown file.

        Args:
            filepath: Path to the ``.md`` file produced by MinerU.

        Returns:
            Populated :class:`~scrinium.ingest.metadata.PaperMetadata` instance.
        """
        ...


# ============================================================================
#  Regex extractor (wraps the regex logic in scrinium.ingest.metadata)
# ============================================================================


class RegexExtractor:
    """Regex-only metadata extractor.

    Wraps the regex extraction logic in ``scrinium.ingest.metadata`` without
    calling any LLM. Fast and model-free; works best on papers with clean OCR.
    """

    def extract(self, filepath: Path) -> PaperMetadata:
        from scrinium.ingest.metadata import extract_metadata_from_markdown

        # Read file once; pass text to both metadata extraction and patent check
        text = filepath.read_text(encoding="utf-8", errors="replace")
        meta = extract_metadata_from_markdown(filepath, text=text)
        _extract_patent_number(meta, text)
        return meta


# ============================================================================
#  Patent number extraction
# ============================================================================


def _extract_patent_number(meta, text: str) -> None:
    """Extract patent publication number from text and set paper_type if patent."""
    from scrinium.ingest.metadata._models import PATENT_NUMBER_RE

    m = PATENT_NUMBER_RE.search(text[:10000])
    if m and not meta.publication_number:
        meta.publication_number = m.group(1).upper()
    # Heuristic: if publication_number found and no DOI, likely a patent
    if meta.publication_number and not meta.doi:
        if not meta.paper_type or meta.paper_type in ("", "article"):
            meta.paper_type = "patent"


# ============================================================================
#  Factory
# ============================================================================


def get_extractor() -> MetadataExtractor:
    """Return a metadata extractor instance (always :class:`RegexExtractor`).

    Returns:
        A :class:`RegexExtractor` instance.
    """
    return RegexExtractor()
