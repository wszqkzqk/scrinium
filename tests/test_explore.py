"""Tests for explore filters, validation, and public helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scrinium.config import _build_config
from scrinium.explore import (
    _build_filter,
    build_explore_fts,
    explore_db_path,
    explore_unified_search,
    explore_vsearch,
    fetch_explore,
    validate_explore_name,
)


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


class TestExploreSearchWithoutVectors:
    """Regression: explore silo with FTS only (embed never ran) must not crash."""

    def test_unified_search_degrades_to_keyword(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SCRINIUM_EMBED_PROVIDER", raising=False)
        cfg = _build_config({}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        # explore.db has papers_fts but no paper_vectors table
        conn = sqlite3.connect(explore_db_path("demo", cfg))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "papers_fts" in tables
        assert "paper_vectors" not in tables

        results = explore_unified_search("demo", "turbulent drag", cfg=cfg)
        assert results
        assert results[0]["title"] == "Turbulent drag reduction"

    def test_vsearch_raises_clean_error_without_table(self, tmp_path, monkeypatch):
        pytest.importorskip("faiss", reason="embed extra not installed")
        monkeypatch.delenv("SCRINIUM_EMBED_PROVIDER", raising=False)
        cfg = _build_config({}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        with pytest.raises(FileNotFoundError, match="向量库为空"):
            explore_vsearch("demo", "turbulent drag", cfg=cfg)

    def test_vsearch_provider_none_reports_disabled(self, tmp_path):
        cfg = _build_config({"embed": {"provider": "none"}}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        with pytest.raises(FileNotFoundError, match="已禁用"):
            explore_vsearch("demo", "turbulent drag", cfg=cfg)

    def test_unified_search_provider_none_keyword_only(self, tmp_path):
        cfg = _build_config({"embed": {"provider": "none"}}, tmp_path)
        _make_explore_lib(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        results = explore_unified_search("demo", "boundary layer", cfg=cfg)
        assert results
        assert results[0]["title"] == "Boundary layer stability"
