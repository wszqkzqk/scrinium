"""Contract tests for the FTS5 search index.

Verifies: build_index creates a searchable database, search returns
matching results with expected structure.
Does NOT test: SQLite internals, exact ranking scores, hash logic.
"""

from __future__ import annotations

import json
import sqlite3

from scrinium.index import build_index, lookup_paper, search, unified_search


class TestBuildAndSearch:
    """End-to-end index contract: build → search → results."""

    def test_build_then_search_by_title(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        assert len(results) >= 1
        titles = [r["title"] for r in results]
        assert any("Turbulence" in t or "turbulence" in t for t in titles)

    def test_search_returns_expected_fields(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        assert len(results) >= 1
        r = results[0]
        # Contract: search results contain at minimum these keys
        for key in ("paper_id", "title", "authors", "year", "journal"):
            assert key in r, f"Missing key: {key}"

    def test_search_no_match_returns_empty(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("xyznonexistent", tmp_db)
        assert results == []

    def test_search_by_abstract_content(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search("novel turbulence model boundary", tmp_db)
        assert len(results) >= 1

    def test_rebuild_is_idempotent(self, tmp_papers, tmp_db):
        """Building twice should not duplicate entries."""
        build_index(tmp_papers, tmp_db)
        build_index(tmp_papers, tmp_db)
        results = search("turbulence", tmp_db)
        # Should still find exactly one match for this query, not duplicates
        turbulence_results = [r for r in results if "Turbulence" in r.get("title", "")]
        assert len(turbulence_results) == 1

    def test_build_index_accepts_reference_dicts(self, tmp_path, tmp_db):
        papers_dir = tmp_path / "papers"
        paper_dir = papers_dir / "Smith-2023-Turbulence"
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(
            json.dumps(
                {
                    "id": "aaaa-1111",
                    "title": "Turbulence modeling in boundary layers",
                    "authors": ["Smith, John"],
                    "first_author_lastname": "Smith",
                    "year": 2023,
                    "journal": "Journal of Fluid Mechanics",
                    "doi": "10.1234/jfm.2023.001",
                    "abstract": "We propose a novel turbulence model for boundary layers.",
                    "paper_type": "journal-article",
                    "references": [
                        {"doi": "10.1000/classic"},
                        {"externalIds": {"DOI": "10.1000/second"}},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (paper_dir / "paper.md").write_text("# Turbulence\n\nFull text.", encoding="utf-8")

        build_index(papers_dir, tmp_db)

        with sqlite3.connect(tmp_db) as conn:
            rows = conn.execute(
                "SELECT target_doi FROM citations WHERE source_id = ? ORDER BY target_doi",
                ("aaaa-1111",),
            ).fetchall()
        assert [row[0] for row in rows] == ["10.1000/classic", "10.1000/second"]

    def test_unified_search_degrades_to_fts_when_vector_search_runtime_fails(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)

        def boom(*_args, **_kwargs):
            raise RuntimeError("proxy unavailable")

        monkeypatch.setattr("scrinium.vectors.vsearch", boom)

        results = unified_search("turbulence", tmp_db)

        assert len(results) >= 1
        assert all(r["match"] == "fts" for r in results)


class TestLookupPaper:
    """lookup_paper contract: find by UUID, dir_name, DOI, or publication_number."""

    def test_lookup_by_uuid(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        result = lookup_paper(tmp_db, "aaaa-1111")
        assert result is not None
        assert result["id"] == "aaaa-1111"

    def test_lookup_by_doi(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        result = lookup_paper(tmp_db, "10.1234/jfm.2023.001")
        assert result is not None
        assert result["doi"] == "10.1234/jfm.2023.001"

    def test_lookup_by_doi_is_backward_compatible_with_legacy_uppercase_registry(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            conn.execute("UPDATE papers_registry SET doi = UPPER(doi) WHERE doi != ''")
            conn.commit()

        result = lookup_paper(tmp_db, "10.1234/jfm.2023.001")
        assert result is not None
        assert result["id"] == "aaaa-1111"

    def test_lookup_by_publication_number(self, tmp_path, tmp_db):
        """Patent lookup normalizes to uppercase for matching."""
        papers_dir = tmp_path / "papers"
        pa = papers_dir / "Inventor-2023-Patent"
        pa.mkdir(parents=True)
        (pa / "meta.json").write_text(
            json.dumps(
                {
                    "id": "patent-001",
                    "title": "A patent invention",
                    "authors": ["Inventor"],
                    "first_author_lastname": "Inventor",
                    "year": 2023,
                    "journal": "",
                    "doi": "",
                    "abstract": "Patent abstract.",
                    "paper_type": "patent",
                    "ids": {"patent_publication_number": "CN112345678A"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (pa / "paper.md").write_text("# Patent\n\nContent.", encoding="utf-8")
        build_index(papers_dir, tmp_db)
        # Lookup with lowercase should still match (normalization)
        result = lookup_paper(tmp_db, "cn112345678a")
        assert result is not None
        assert result["id"] == "patent-001"

    def test_lookup_nonexistent_returns_none(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        assert lookup_paper(tmp_db, "nonexistent-id") is None
