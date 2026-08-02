"""Tests for scrinium.ingest.metadata abstract/doc helpers."""

from __future__ import annotations

import json

from scrinium.ingest.metadata._abstract import backfill_abstracts, extract_abstract_from_md
from scrinium.ingest.metadata._doc_extract import extract_document_metadata


class _NoKeyConfig:
    def resolved_api_key(self) -> str:
        return ""


def test_extract_abstract_from_md_heading_block(tmp_path):
    md = tmp_path / "paper.md"
    md.write_text(
        "# Title\n\n"
        "# Abstract\n\n"
        "This paper studies turbulent particle transport near the wall and "
        "shows that gravity changes the acceleration statistics in a clear way "
        "across a wide range of Stokes numbers.\n\n"
        "# 1 Introduction\n\n"
        "Body text.\n",
        encoding="utf-8",
    )

    abstract = extract_abstract_from_md(md)

    assert abstract is not None
    assert "turbulent particle transport" in abstract
    assert "Introduction" not in abstract


def test_backfill_abstracts_writes_missing_abstract(tmp_path):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "Smith-2024-Test"
    paper_dir.mkdir(parents=True)

    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "id": "uuid-1",
                "title": "Test Paper",
                "authors": ["John Smith"],
                "year": 2024,
                "doi": "",
                "journal": "",
                "abstract": "",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "paper.md").write_text(
        "# Test Paper\n\n"
        "# Abstract\n\n"
        "This paper provides a compact abstract long enough to pass the "
        "sanity checks and verify that backfill_abstracts writes the result "
        "back into meta json correctly for already ingested papers.\n",
        encoding="utf-8",
    )

    stats = backfill_abstracts(papers_dir)
    data = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))

    assert stats == {"filled": 1, "skipped": 0, "failed": 0, "updated": 0}
    assert "compact abstract" in data["abstract"]


def test_extract_document_metadata_fallback_without_api_key(tmp_path):
    md = tmp_path / "report.md"
    md.write_text(
        "# Internal CFD Report\n\n"
        "This report summarizes the solver setup, boundary conditions, mesh "
        "strategy, convergence checks, and validation notes for a turbulent "
        "channel-flow campaign. " * 20,
        encoding="utf-8",
    )

    meta = extract_document_metadata(md, _NoKeyConfig())

    assert meta.title == "Internal CFD Report"
    assert meta.paper_type == "document"
    assert meta.extraction_method == "fallback_document"
    assert len(meta.abstract.split()) >= 50
