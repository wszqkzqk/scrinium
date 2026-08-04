"""Contract tests for the FTS5 search index.

Verifies: build_index creates a searchable database, search returns
matching results with expected structure.
Does NOT test: SQLite internals, exact ranking scores, hash logic.
"""

from __future__ import annotations

import json
import sqlite3

from scrinium.index import _SCHEMA_VERSION, build_index, lookup_paper, search


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

    def test_deleted_paper_is_garbage_collected(self, tmp_papers, tmp_db):
        """Removing a paper directory must purge it from all index tables."""
        import shutil
        import sqlite3 as _sqlite3

        build_index(tmp_papers, tmp_db)
        victim = next(d for d in tmp_papers.iterdir() if d.is_dir())
        import json as _json

        paper_id = _json.loads((victim / "meta.json").read_text())["id"]
        shutil.rmtree(victim)
        build_index(tmp_papers, tmp_db)

        with _sqlite3.connect(tmp_db) as conn:
            for table, col in (
                ("papers", "paper_id"),
                ("papers_hash", "paper_id"),
                ("papers_registry", "id"),
                ("paper_tags", "paper_id"),
                ("citations", "source_id"),
            ):
                n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (paper_id,)).fetchone()[0]
                assert n == 0, f"stale row in {table}"
        results = search("turbulence", tmp_db)
        assert all(r["paper_id"] != paper_id for r in results)

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


class TestSchemaV2Migration:
    """v1 → v2 migration drops legacy embedding storage and is idempotent."""

    @staticmethod
    def _create_v1_db(db_path):
        """Build a v1 index DB that still carries vector tables + FAISS files."""
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE papers (paper_id TEXT, title TEXT)")
        conn.execute("CREATE TABLE papers_hash (paper_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL)")
        conn.execute("CREATE TABLE paper_vectors (paper_id TEXT PRIMARY KEY, vector BLOB)")
        conn.execute("CREATE TABLE vector_metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO paper_vectors VALUES ('p1', X'00')")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        (db_path.parent / "faiss.index").write_bytes(b"fake")
        (db_path.parent / "faiss_ids.json").write_text("[]", encoding="utf-8")

    @staticmethod
    def _table_names(db_path):
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row[0] for row in rows}

    def test_migration_drops_vector_storage(self, tmp_papers, tmp_db):
        self._create_v1_db(tmp_db)
        build_index(tmp_papers, tmp_db)

        tables = self._table_names(tmp_db)
        assert "paper_vectors" not in tables
        assert "vector_metadata" not in tables
        assert not (tmp_db.parent / "faiss.index").exists()
        assert not (tmp_db.parent / "faiss_ids.json").exists()
        with sqlite3.connect(tmp_db) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION

    def test_migration_is_idempotent(self, tmp_papers, tmp_db):
        self._create_v1_db(tmp_db)
        build_index(tmp_papers, tmp_db)
        # Second build sees user_version == _SCHEMA_VERSION: no migration, no error.
        build_index(tmp_papers, tmp_db)
        assert "paper_vectors" not in self._table_names(tmp_db)
        results = search("turbulence", tmp_db)
        assert len(results) >= 1

    def test_fresh_db_has_no_vector_tables(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        tables = self._table_names(tmp_db)
        assert "paper_vectors" not in tables
        assert "vector_metadata" not in tables


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


class TestBm25FieldWeights:
    """Field-weighted BM25: title/tags hits must outrank body-text hits."""

    @staticmethod
    def _write_paper(papers_dir, name, meta):
        d = papers_dir / name
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        (d / "paper.md").write_text("# paper\n", encoding="utf-8")

    def _build_weighted_corpus(self, tmp_path, tmp_db, a_extra):
        """Index a corpus where paper A carries 'quixotic' via ``a_extra``
        and paper B only repeats it in the abstract.

        Four filler papers keep the term's document frequency below half the
        corpus so the BM25 IDF stays positive and ranking is meaningful.
        """
        papers_dir = tmp_path / "papers"
        papers_dir.mkdir()
        base = {"authors": ["T Tester"], "year": 2023, "journal": "", "doi": "", "paper_type": "journal-article"}
        self._write_paper(
            papers_dir,
            "A-2023-Signal",
            {
                **base,
                "id": "aaaa-0001",
                "title": "A study of fluid flow",
                "abstract": "Nothing special here.",
                **a_extra,
            },
        )
        self._write_paper(
            papers_dir,
            "B-2023-Body",
            {
                **base,
                "id": "bbbb-0002",
                "title": "Ordinary results",
                "abstract": "The quixotic quixotic quixotic results are discussed in this quixotic paper.",
            },
        )
        for i in range(4):
            self._write_paper(
                papers_dir,
                f"Filler{i}-2023-Noise",
                {**base, "id": f"ffff-000{i}", "title": f"Filler paper {i}", "abstract": "Unrelated filler text."},
            )
        build_index(papers_dir, tmp_db)

    def test_title_hit_outranks_abstract_hit(self, tmp_path, tmp_db):
        self._build_weighted_corpus(tmp_path, tmp_db, {"title": "Quixotic methods for fluid flow"})
        ids = [r["paper_id"] for r in search("quixotic", tmp_db)]
        assert "bbbb-0002" in ids
        assert ids[0] == "aaaa-0001"

    def test_tag_hit_outranks_abstract_hit(self, tmp_path, tmp_db):
        self._build_weighted_corpus(tmp_path, tmp_db, {"tags": ["quixotic"]})
        ids = [r["paper_id"] for r in search("quixotic", tmp_db)]
        assert "bbbb-0002" in ids
        assert ids[0] == "aaaa-0001"

    def test_weights_match_papers_schema(self, tmp_papers, tmp_db):
        from scrinium.index import _BM25_WEIGHTS

        build_index(tmp_papers, tmp_db)
        with sqlite3.connect(tmp_db) as conn:
            col_count = len(conn.execute("PRAGMA table_info(papers)").fetchall())
        assert len(_BM25_WEIGHTS) == col_count
        assert all(isinstance(w, float) for w in _BM25_WEIGHTS)
        # title (col 1) is the dominant weight, curated tags (col 7) second
        assert _BM25_WEIGHTS[1] == max(_BM25_WEIGHTS)
        assert _BM25_WEIGHTS[7] == sorted(_BM25_WEIGHTS, reverse=True)[1]

    def test_explore_weights_match_fts_schema(self):
        from scrinium.explore import _FTS_BM25_WEIGHTS, _FTS_SCHEMA

        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(_FTS_SCHEMA)
            col_count = len(conn.execute("PRAGMA table_info(papers_fts)").fetchall())
        finally:
            conn.close()
        assert len(_FTS_BM25_WEIGHTS) == col_count
        assert all(isinstance(w, float) for w in _FTS_BM25_WEIGHTS)
        # title (col 1) dominates, abstract (col 3) next among indexed fields
        assert _FTS_BM25_WEIGHTS[1] == max(_FTS_BM25_WEIGHTS)
        assert _FTS_BM25_WEIGHTS[3] > 0.0
