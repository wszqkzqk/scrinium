"""Tests for explore filters, validation, and public helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scrinium.config import _build_config
from scrinium.explore import (
    _build_filter,
    _resolve_sort,
    build_explore_fts,
    explore_db_path,
    explore_search,
    fetch_explore,
    validate_explore_name,
)


class TestResolveSort:
    def test_keyword_defaults_to_relevance(self):
        assert _resolve_sort(None, "milestoning kinetics") == "relevance_score:desc"

    def test_filter_only_defaults_to_year_asc(self):
        assert _resolve_sort(None, None) == "publication_year:asc"

    def test_explicit_option_name_mapped(self):
        assert _resolve_sort("citations", None) == "cited_by_count:desc"
        assert _resolve_sort("year_desc", "kw") == "publication_year:desc"

    def test_raw_openalex_expression_passes_through(self):
        assert _resolve_sort("cited_by_count:asc", None) == "cited_by_count:asc"


class TestBuildFilter:
    def test_min_citations_positive_adds_filter(self):
        filt, _ = _build_filter(min_citations=10)
        assert "cited_by_count:>9" in filt

    def test_min_citations_zero_or_negative_ignored(self):
        filt_zero, _ = _build_filter(min_citations=0)
        filt_negative, _ = _build_filter(min_citations=-3)
        assert "cited_by_count" not in filt_zero
        assert "cited_by_count" not in filt_negative


class TestFetchExploreLimit:
    def test_limit_must_be_positive(self):
        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=0)

        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=-1)


class TestExploreNameValidation:
    def test_validate_explore_name_rejects_path_traversal(self):
        assert validate_explore_name("jfm-2026")
        assert not validate_explore_name("")
        assert not validate_explore_name("../escape")
        assert not validate_explore_name("nested/name")


class TestExploreDbPath:
    def test_explore_db_path_uses_default_layout(self):
        assert explore_db_path("demo") == Path("data/explore/demo/explore.db")


def _make_explore_lib(tmp_path: Path, name: str = "demo") -> Path:
    """Create a minimal explore silo (papers.jsonl only) under tmp_path."""
    lib_dir = tmp_path / "data" / "explore" / name
    lib_dir.mkdir(parents=True)
    papers = [
        {
            "openalex_id": "W1",
            "doi": "10.1/a",
            "title": "Turbulent drag reduction",
            "authors": ["Alice"],
            "year": 2023,
            "abstract": "We study turbulent drag reduction in pipe flows.",
            "cited_by_count": 5,
        },
        {
            "openalex_id": "W2",
            "doi": "",
            "title": "Boundary layer stability",
            "authors": ["Bob"],
            "year": 2024,
            "abstract": "Stability analysis of laminar boundary layers.",
            "cited_by_count": 1,
        },
    ]
    (lib_dir / "papers.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in papers) + "\n",
        encoding="utf-8",
    )
    return lib_dir


class TestExploreKeywordSearch:
    """Explore silo search is FTS5 keyword-only (vectors were removed)."""

    def test_fts_schema_has_no_vector_tables(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        conn = sqlite3.connect(explore_db_path("demo", cfg))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "papers_fts" in tables
        assert "paper_vectors" not in tables

    def test_keyword_search_hits(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        results = explore_search("demo", "turbulent drag", cfg=cfg)
        assert results
        assert results[0]["title"] == "Turbulent drag reduction"

    def test_keyword_search_second_hit(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        results = explore_search("demo", "boundary layer", cfg=cfg)
        assert results
        assert results[0]["title"] == "Boundary layer stability"
