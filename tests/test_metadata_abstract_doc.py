"""Tests for scrinium.ingest.metadata abstract/doc helpers (rule-based only)."""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from scrinium import cli
from scrinium.cli import ingest as cli_ingest
from scrinium.ingest.metadata._abstract import backfill_abstracts, extract_abstract_from_md
from scrinium.ingest.metadata._doc_extract import extract_document_metadata
from scrinium.ingest.pipeline import HINT_ABSTRACT_MISS


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

    assert stats["filled"] == 1
    assert stats["skipped"] == 0
    assert stats["failed"] == 0
    assert stats["updated"] == 0
    assert "compact abstract" in data["abstract"]


def test_backfill_abstracts_reports_regex_misses_in_failed_dirs(tmp_path):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "NoAbstract-2024-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(json.dumps({"id": "uuid-2", "abstract": ""}), encoding="utf-8")
    (paper_dir / "paper.md").write_text("# No Abstract Here\n\nBody without an abstract heading.\n", encoding="utf-8")

    stats = backfill_abstracts(papers_dir)

    assert stats["filled"] == 0
    assert stats["failed_dirs"] == ["NoAbstract-2024-Test"]


def test_cmd_backfill_abstract_emits_handoff_hint_on_regex_miss(tmp_path, monkeypatch):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "NoAbstract-2024-Test"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(json.dumps({"id": "uuid-2", "abstract": ""}), encoding="utf-8")
    (paper_dir / "paper.md").write_text("# No Abstract Here\n\nBody without an abstract heading.\n", encoding="utf-8")

    messages: list[str] = []
    monkeypatch.setattr(cli_ingest, "ui", lambda msg="": messages.append(msg))
    cfg = SimpleNamespace(papers_dir=papers_dir)

    cli.cmd_backfill_abstract(Namespace(dry_run=False, doi_fetch=False), cfg)

    hints = [m for m in messages if m.startswith("hint:")]
    assert len(hints) == 1
    assert "NoAbstract-2024-Test" in hints[0]
    assert HINT_ABSTRACT_MISS in hints[0]


def test_extract_document_metadata_fallback(tmp_path):
    md = tmp_path / "report.md"
    md.write_text(
        "# Internal CFD Report\n\n"
        "This report summarizes the solver setup, boundary conditions, mesh "
        "strategy, convergence checks, and validation notes for a turbulent "
        "channel-flow campaign. " * 20,
        encoding="utf-8",
    )

    meta = extract_document_metadata(md)

    assert meta.title == "Internal CFD Report"
    assert meta.paper_type == "document"
    assert meta.extraction_method == "fallback_document"
    assert len(meta.abstract.split()) >= 50
