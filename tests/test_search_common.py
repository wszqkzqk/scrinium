"""Unit tests for the shared FTS5/RRF helpers (scholaraio.search_common).

Also pins the delegation wiring: index.py and explore.py route query
sanitization, FTS schema generation, and RRF merging through search_common.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from scholaraio.explore import build_explore_fts, explore_search, explore_unified_search
from scholaraio.index import _safe_query, build_index, search
from scholaraio.search_common import RRF_K, fts_create_sql, rrf_merge, sanitize_fts_query


class TestSanitizeFtsQuery:
    def test_strips_special_characters(self):
        # Each special char becomes a space; inner spaces are not collapsed.
        assert sanitize_fts_query('CRISPR-Cas9 (review): "phase 2"') == "CRISPR Cas9  review    phase 2"

    def test_keeps_word_chars_digits_underscores(self):
        assert sanitize_fts_query("covid_19 2021") == "covid_19 2021"

    def test_keeps_unicode_words(self):
        assert sanitize_fts_query("湍流 边界层") == "湍流 边界层"

    def test_only_special_chars_returns_empty(self):
        assert sanitize_fts_query("!!! ***") == ""

    def test_trims_but_does_not_collapse_inner_spaces(self):
        assert sanitize_fts_query("  a-b  ") == "a b"

    def test_index_safe_query_alias_delegates(self):
        assert _safe_query('a "b" (c)') == sanitize_fts_query('a "b" (c)')


class TestFtsCreateSql:
    def test_generates_ordered_columns_with_unindexed_markers(self):
        sql = fts_create_sql("t", [("a", False), ("b", True), ("c", False)])
        assert sql.startswith("CREATE VIRTUAL TABLE IF NOT EXISTS t USING fts5(")
        assert "a UNINDEXED" in sql
        assert "c UNINDEXED" in sql
        assert "tokenize = 'unicode61'" in sql
        # Column order is preserved as given.
        assert sql.index("a UNINDEXED") < sql.index("\n    b,") < sql.index("c UNINDEXED")

    def test_roundtrip_indexed_vs_unindexed(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(fts_create_sql("t", [("pid", False), ("title", True)]))
            conn.execute("INSERT INTO t (pid, title) VALUES (?, ?)", ("secret-id", "hello world"))
            rows = conn.execute("SELECT pid FROM t WHERE t MATCH ?", ("hello",)).fetchall()
            assert rows == [("secret-id",)]
            # UNINDEXED column content is not searchable.
            assert conn.execute("SELECT pid FROM t WHERE t MATCH ?", ("secret",)).fetchall() == []
        finally:
            conn.close()


class TestRrfMerge:
    def test_single_leg_match_flags_and_scores(self):
        fts = [{"paper_id": "a"}, {"paper_id": "b"}]
        vec = [{"paper_id": "c"}]
        merged = rrf_merge(fts, vec)
        by_id = {r["paper_id"]: r for r in merged}
        assert by_id["a"]["match"] == "fts"
        assert by_id["a"]["score"] == pytest.approx(1.0 / (RRF_K + 1))
        assert by_id["b"]["score"] == pytest.approx(1.0 / (RRF_K + 2))
        assert by_id["c"]["match"] == "vec"
        assert by_id["c"]["score"] == pytest.approx(1.0 / (RRF_K + 1))

    def test_both_hit_sums_scores_and_ranks_first(self):
        fts = [{"paper_id": "x"}, {"paper_id": "a"}]
        vec = [{"paper_id": "x"}, {"paper_id": "b"}]
        merged = rrf_merge(fts, vec)
        assert merged[0]["paper_id"] == "x"
        assert merged[0]["match"] == "both"
        assert merged[0]["score"] == pytest.approx(2.0 / (RRF_K + 1))

    def test_ties_keep_fts_before_vec_order(self):
        merged = rrf_merge([{"paper_id": "a"}], [{"paper_id": "b"}])
        assert [r["paper_id"] for r in merged] == ["a", "b"]

    def test_custom_get_id_and_empty_ids_skipped(self):
        fts = [{"doi": "10.1/a"}, {"doi": ""}, {"title": "no id at all"}]
        merged = rrf_merge(fts, [], get_id=lambda r: r.get("doi") or r.get("openalex_id", ""))
        assert [r["doi"] for r in merged] == ["10.1/a"]

    def test_top_k_truncates(self):
        fts = [{"paper_id": str(i)} for i in range(10)]
        assert len(rrf_merge(fts, [], top_k=3)) == 3

    def test_custom_k(self):
        merged = rrf_merge([{"paper_id": "a"}], [], k=10)
        assert merged[0]["score"] == pytest.approx(1.0 / 11)

    def test_original_fields_preserved(self):
        merged = rrf_merge([{"paper_id": "a", "title": "T"}], [])
        assert merged[0]["title"] == "T"


class TestMainIndexDelegation:
    """The main library must sanitize queries via search_common."""

    def test_search_with_special_chars_does_not_raise(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        results = search('turbulence: "boundary" (layers)', tmp_db)
        assert any("Turbulence" in r["title"] for r in results)


def _make_explore_cfg(tmp_path) -> SimpleNamespace:
    """Create a minimal explore library (papers.jsonl) under a temp root."""
    lib = tmp_path / "data" / "explore" / "demo"
    lib.mkdir(parents=True)
    papers = [
        {
            "doi": "10.1/a",
            "openalex_id": "W1",
            "title": "Turbulence in boundary layers",
            "abstract": "Shear flow over a flat plate.",
            "authors": ["Smith"],
            "year": 2023,
        },
        {
            "doi": "10.1/b",
            "openalex_id": "W2",
            "title": "Deep learning for fluids",
            "abstract": "Neural surrogates.",
            "authors": ["Wang"],
            "year": 2024,
        },
    ]
    (lib / "papers.jsonl").write_text("".join(json.dumps(p) + "\n" for p in papers), encoding="utf-8")
    return SimpleNamespace(_root=tmp_path)


class TestExploreDelegation:
    """Explore FTS/unified search must use the shared helpers."""

    def test_build_fts_then_search(self, tmp_path):
        cfg = _make_explore_cfg(tmp_path)
        assert build_explore_fts("demo", cfg=cfg) == 2
        results = explore_search("demo", "turbulence", cfg=cfg)
        assert len(results) == 1
        assert results[0]["doi"] == "10.1/a"
        assert results[0]["match"] == "fts"

    def test_special_char_query_does_not_raise(self, tmp_path):
        cfg = _make_explore_cfg(tmp_path)
        build_explore_fts("demo", cfg=cfg)
        # Sanitized to plain terms; same hit as a plain query.
        results = explore_search("demo", 'turbulence: "boundary" (layers)', cfg=cfg)
        assert len(results) == 1
        assert results[0]["doi"] == "10.1/a"

    def test_query_without_terms_returns_empty(self, tmp_path):
        cfg = _make_explore_cfg(tmp_path)
        build_explore_fts("demo", cfg=cfg)
        assert explore_search("demo", "!!!", cfg=cfg) == []

    def test_unified_search_degrades_to_fts(self, tmp_path, monkeypatch):
        cfg = _make_explore_cfg(tmp_path)
        build_explore_fts("demo", cfg=cfg)

        def _no_vectors(*_args, **_kwargs):
            raise FileNotFoundError("no vectors")

        monkeypatch.setattr("scholaraio.explore.explore_vsearch", _no_vectors)
        results = explore_unified_search("demo", "turbulence", cfg=cfg)
        assert len(results) == 1
        assert results[0]["match"] == "fts"
        assert results[0]["score"] == pytest.approx(1.0 / (RRF_K + 1))

    def test_unified_search_marks_both_hits(self, tmp_path, monkeypatch):
        cfg = _make_explore_cfg(tmp_path)
        build_explore_fts("demo", cfg=cfg)
        monkeypatch.setattr(
            "scholaraio.explore.explore_vsearch",
            lambda *_a, **_k: [{"doi": "10.1/a", "title": "Turbulence in boundary layers", "score": 0.9}],
        )
        results = explore_unified_search("demo", "turbulence", cfg=cfg)
        assert len(results) == 1
        assert results[0]["match"] == "both"
        assert results[0]["score"] == pytest.approx(2.0 / (RRF_K + 1))
