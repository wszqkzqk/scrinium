"""Tests for citation extraction and local citation verification."""

from __future__ import annotations

import json
from pathlib import Path

from scrinium.citation_check import check_citations, extract_citations
from scrinium.index import build_index


def _write_paper(
    papers_dir: Path,
    *,
    pid: str,
    title: str,
    authors: list[str],
    year: int,
    doi: str,
) -> None:
    pdir = papers_dir / title.replace(" ", "-")
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "meta.json").write_text(
        json.dumps(
            {
                "id": pid,
                "title": title,
                "authors": authors,
                "first_author_lastname": authors[0].split()[-1] if authors else "",
                "year": year,
                "journal": "Test Journal",
                "doi": doi,
                "abstract": "test",
                "paper_type": "journal-article",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pdir / "paper.md").write_text("# test\n", encoding="utf-8")


class TestExtractCitations:
    def test_extract_narrative_parenthetical_and_deduplicate(self):
        text = "Smith (2023) demonstrated X. Related work also includes (Smith, 2023; Wang et al., 2024)."
        cites = extract_citations(text)

        got = {(c["author"], c["year"]) for c in cites}
        assert ("Smith", "2023") in got
        assert ("Wang et al.", "2024") in got
        # Smith 2023 appears twice in text but should be deduplicated.
        assert len([c for c in cites if c["author"] == "Smith" and c["year"] == "2023"]) == 1

    def test_extract_author_connector_pattern(self):
        text = "As shown by Smith & Doe (2023), the model is stable."
        cites = extract_citations(text)
        assert len(cites) == 1
        assert cites[0]["author"] == "Smith & Doe"
        assert cites[0]["year"] == "2023"


class TestCheckCitations:
    def test_verified_match(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        citations = [{"author": "Smith", "year": "2023", "raw": "(Smith, 2023)"}]

        results = check_citations(citations, tmp_db)
        assert len(results) == 1
        assert results[0]["status"] == "VERIFIED"
        assert len(results[0]["matches"]) == 1
        assert results[0]["matches"][0]["paper_id"] == "aaaa-1111"

    def test_not_in_library(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        citations = [{"author": "Nonexistent", "year": "2030", "raw": "(Nonexistent, 2030)"}]

        results = check_citations(citations, tmp_db)
        assert results[0]["status"] == "NOT_IN_LIBRARY"
        assert results[0]["matches"] == []

    def test_ambiguous_match(self, tmp_path, tmp_db):
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir(parents=True)
        _write_paper(
            papers_dir,
            pid="id-1",
            title="Smith Study One",
            authors=["John Smith"],
            year=2023,
            doi="10.1000/a",
        )
        _write_paper(
            papers_dir,
            pid="id-2",
            title="Smith Study Two",
            authors=["Alice Smith"],
            year=2023,
            doi="10.1000/b",
        )
        build_index(papers_dir, tmp_db)
        citations = [{"author": "Smith", "year": "2023", "raw": "(Smith, 2023)"}]

        results = check_citations(citations, tmp_db)
        assert results[0]["status"] == "AMBIGUOUS"
        assert len(results[0]["matches"]) == 2

    def test_workspace_scope_filter_applied(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        citations = [{"author": "Smith", "year": "2023", "raw": "(Smith, 2023)"}]

        # Restrict search to a workspace that does not include Smith-2023 paper.
        results = check_citations(citations, tmp_db, paper_ids={"bbbb-2222"})
        assert results[0]["status"] == "NOT_IN_LIBRARY"
        assert results[0]["matches"] == []

    def test_missing_index_file_graceful(self, tmp_path):
        missing_db = tmp_path / "missing.db"
        citations = [{"author": "Smith", "year": "2023", "raw": "(Smith, 2023)"}]

        results = check_citations(citations, missing_db)
        assert results[0]["status"] == "NOT_IN_LIBRARY"
        assert results[0]["matches"] == []
