"""
index.py — SQLite FTS5 full-text search index
=============================================

Indexed fields: title + abstract + conclusion + tags + si (all searchable).
Other fields (paper_id, authors, year, journal, doi, paper_type, citation_count,
md_path) are stored but not indexed.

The FTS schema version is recorded in ``PRAGMA user_version`` (currently
``_SCHEMA_VERSION``); when an older version is detected, the FTS table is
automatically dropped/recreated and a full reindex is triggered.

Usage:
    from scrinium.index import build_index, search
    build_index(papers_dir, db_path)
    results = search("turbulent boundary layer", db_path)
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from scrinium.papers import best_citation, parse_year_range
from scrinium.search_common import fts_create_sql, sanitize_fts_query

if TYPE_CHECKING:
    from scrinium.config import Config

#: FTS schema version recorded in ``PRAGMA user_version``; bump when the
#: ``papers`` FTS table layout changes (v1 = tags column added,
#: v2 = embedding/vector storage removed, v3 = si column added).
_SCHEMA_VERSION = 3

_SCHEMA = fts_create_sql(
    "papers",
    [
        ("paper_id", False),
        ("title", True),
        ("authors", True),
        ("year", True),
        ("journal", True),
        ("abstract", True),
        ("conclusion", True),
        ("tags", True),
        ("doi", False),
        ("paper_type", False),
        ("citation_count", False),
        ("md_path", False),
        ("si", True),
    ],
)

_PROCEEDINGS_SCHEMA = fts_create_sql(
    "proceedings_fts",
    [
        ("paper_id", False),
        ("title", True),
        ("authors", True),
        ("year", True),
        ("journal", True),
        ("abstract", True),
        ("conclusion", True),
        ("doi", False),
        ("paper_type", False),
        ("citation_count", False),
        ("md_path", False),
        ("dir_name", False),
        ("proceeding_id", False),
        ("proceeding_dir", False),
        ("proceeding_title", False),
    ],
)


_HASH_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers_hash (
    paper_id     TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL
);
"""

_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers_registry (
    id                   TEXT PRIMARY KEY,
    dir_name             TEXT NOT NULL UNIQUE,
    title                TEXT,
    doi                  TEXT,
    publication_number   TEXT,
    year                 INTEGER,
    first_author         TEXT
);
"""

_REGISTRY_DOI_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_doi
    ON papers_registry(doi) WHERE doi IS NOT NULL AND doi != '';
"""

_REGISTRY_PUBNUM_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_publication_number
    ON papers_registry(publication_number) WHERE publication_number IS NOT NULL AND publication_number != '';
"""

_CITATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS citations (
    source_id   TEXT NOT NULL,
    target_doi  TEXT NOT NULL,
    target_id   TEXT,
    PRIMARY KEY (source_id, target_doi)
);
"""
_CITATIONS_IDX_TARGET_DOI = "CREATE INDEX IF NOT EXISTS idx_cit_target_doi ON citations(target_doi);"
_CITATIONS_IDX_TARGET_ID = (
    "CREATE INDEX IF NOT EXISTS idx_cit_target_id ON citations(target_id) WHERE target_id IS NOT NULL;"
)

_PAPER_TAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id TEXT NOT NULL,
    tag      TEXT NOT NULL,
    UNIQUE(paper_id, tag)
);
"""
_PAPER_TAGS_TAG_INDEX = "CREATE INDEX IF NOT EXISTS idx_paper_tags_tag ON paper_tags(tag);"


def _index_hash(meta: dict) -> str:
    """Compute a short hash of the fields indexed in FTS5."""
    parts = [
        meta.get("title") or "",
        ", ".join(meta.get("authors") or []),
        str(meta.get("year") or ""),
        meta.get("journal") or "",
        meta.get("abstract") or "",
        meta.get("l3_conclusion") or "",
        " ".join(meta.get("tags") or []),
        meta.get("doi") or "",
        meta.get("paper_type") or "",
        ((meta.get("ids") or {}).get("patent_publication_number", "") or ""),
    ]
    cc = meta.get("citation_count")
    if cc and isinstance(cc, dict):
        vals = [v for v in cc.values() if isinstance(v, (int, float))]
        parts.append(str(max(vals)) if vals else "")
    parts.append(json.dumps(meta.get("references", []), sort_keys=True))
    parts.append(json.dumps(meta.get("si") or {}, sort_keys=True))
    text = "\n".join(parts)
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


_best_citation = best_citation  # backward compat alias


def _load_si_text(pdir: Path) -> str:
    """Read all converted Markdown under a paper's ``si/`` and join for FTS indexing (capped at 300 KB)."""
    si_dir = pdir / "si"
    if not si_dir.is_dir():
        return ""
    parts: list[str] = []
    for smd in sorted(si_dir.glob("*.md")):
        try:
            parts.append(smd.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n\n".join(parts)[:300_000]


def _ensure_schema(conn: sqlite3.Connection) -> bool:
    """Migrate the FTS schema when ``PRAGMA user_version`` is outdated.

    Drops and recreates the ``papers`` FTS table with the current schema and
    clears ``papers_hash``/``paper_tags`` so the next ``build_index`` run
    reindexes everything. Migration to v2 additionally drops the removed
    embedding storage (``paper_vectors`` / ``vector_metadata`` tables and the
    FAISS sidecar files next to the database); the ``citations`` and
    ``papers_registry`` tables are left untouched.

    Returns:
        ``True`` when a migration was performed.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == _SCHEMA_VERSION:
        return False
    conn.execute("DROP TABLE IF EXISTS papers")
    conn.execute(_SCHEMA)
    conn.execute(_HASH_SCHEMA)
    conn.execute("DELETE FROM papers_hash")  # force full reindex
    conn.execute("DROP TABLE IF EXISTS paper_tags")
    conn.execute(_PAPER_TAGS_SCHEMA)
    if version < 2:
        _drop_vector_storage(conn)
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    return True


def _drop_vector_storage(conn: sqlite3.Connection) -> None:
    """Remove legacy embedding storage: vector tables and FAISS sidecar files."""
    conn.execute("DROP TABLE IF EXISTS paper_vectors")
    conn.execute("DROP TABLE IF EXISTS vector_metadata")
    db_files = [row[2] for row in conn.execute("PRAGMA database_list") if row[2]]
    for db_file in db_files:
        db_dir = Path(db_file).parent
        for name in ("faiss.index", "faiss_ids.json"):
            try:
                (db_dir / name).unlink(missing_ok=True)
            except OSError:
                import logging

                logging.getLogger(__name__).warning("failed to remove legacy vector file %s", db_dir / name)


def build_index(papers_dir: Path, db_path: Path, rebuild: bool = False) -> int:
    """Build or incrementally update the SQLite FTS5 full-text search index.

    Indexed fields: ``title`` + ``abstract`` + ``conclusion`` + ``tags`` are all
    full-text searchable. Other fields (``paper_id``, ``authors``, etc.) are
    stored only. Tags are also synced to the ``paper_tags`` filter table for
    exact ``--tag`` filtering.

    Args:
        papers_dir: Ingested papers directory; scans ``*.json`` inside it.
        db_path: SQLite database path (created if missing).
        rebuild: Clear old data and rebuild from scratch when ``True``.

    Returns:
        Number of papers indexed in this run.
    """
    from scrinium.papers import iter_paper_dirs
    from scrinium.papers import read_meta as _read_meta

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.execute(_HASH_SCHEMA)
        conn.execute(_REGISTRY_SCHEMA)
        conn.execute(_CITATIONS_SCHEMA)
        _ensure_schema(conn)  # migrate pre-tags FTS layout if needed
        conn.execute(_PAPER_TAGS_SCHEMA)
        try:
            conn.execute(_PAPER_TAGS_TAG_INDEX)
        except sqlite3.OperationalError:
            pass  # index already exists
        try:
            conn.execute(_REGISTRY_DOI_INDEX)
        except sqlite3.OperationalError:
            pass  # index already exists
        # Migrate: add publication_number column if missing (pre-existing DB)
        try:
            conn.execute("SELECT publication_number FROM papers_registry LIMIT 0")
        except sqlite3.OperationalError:
            try:
                conn.execute("ALTER TABLE papers_registry ADD COLUMN publication_number TEXT")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(_REGISTRY_PUBNUM_INDEX)
        except sqlite3.OperationalError:
            pass
        except sqlite3.IntegrityError:
            import logging

            logging.getLogger(__name__).warning(
                "cannot create UNIQUE index on publication_number: duplicate values exist; "
                "falling back to non-unique index"
            )
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_registry_publication_number "
                    "ON papers_registry(publication_number) "
                    "WHERE publication_number IS NOT NULL AND publication_number != ''"
                )
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_DOI)
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(_CITATIONS_IDX_TARGET_ID)
        except sqlite3.OperationalError:
            pass

        if rebuild:
            conn.execute("DROP TABLE IF EXISTS papers")
            conn.execute(_SCHEMA)
            conn.execute("DELETE FROM papers_hash")
            conn.execute("DELETE FROM papers_registry")
            conn.execute("DELETE FROM citations")
            conn.execute("DELETE FROM paper_tags")

        # Load existing hashes for incremental change detection
        existing_hashes: dict[str, str] = {}
        if not rebuild:
            for row in conn.execute("SELECT paper_id, content_hash FROM papers_hash").fetchall():
                existing_hashes[row[0]] = row[1]

        count = 0
        seen: set[str] = set()
        for pdir in iter_paper_dirs(papers_dir):
            try:
                meta = _read_meta(pdir)
            except (ValueError, FileNotFoundError):
                continue
            paper_id = meta.get("id") or pdir.name
            seen.add(paper_id)
            h = _index_hash(meta)
            if not rebuild and existing_hashes.get(paper_id) == h:
                continue  # unchanged, skip

            if not rebuild:
                conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))

            best_cite = _best_citation(meta)
            md_file = pdir / "paper.md"
            tags = [t for t in (meta.get("tags") or []) if isinstance(t, str)]
            conn.execute(
                """
                INSERT INTO papers
                    (paper_id, title, authors, year, journal, abstract, conclusion,
                     tags, doi, paper_type, citation_count, md_path, si)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    meta.get("title") or "",
                    ", ".join(meta.get("authors") or []),
                    str(meta.get("year") or ""),
                    meta.get("journal") or "",
                    meta.get("abstract") or "",
                    meta.get("l3_conclusion") or "",
                    " ".join(tags),
                    meta.get("doi") or "",
                    meta.get("paper_type") or "",
                    str(best_cite) if best_cite is not None else "",
                    str(md_file) if md_file.exists() else "",
                    _load_si_text(pdir),
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO papers_hash (paper_id, content_hash) VALUES (?, ?)",
                (paper_id, h),
            )

            # Sync the paper_tags filter table from meta tags
            conn.execute("DELETE FROM paper_tags WHERE paper_id = ?", (paper_id,))
            if tags:
                conn.executemany(
                    "INSERT OR IGNORE INTO paper_tags (paper_id, tag) VALUES (?, ?)",
                    [(paper_id, t) for t in dict.fromkeys(tags)],
                )

            # Update papers_registry — use ON CONFLICT(id) DO UPDATE so that
            # a publication_number UNIQUE violation is surfaced rather than
            # silently deleting a different paper's row (which INSERT OR REPLACE
            # would do when the new pub_num collides with another id's row).
            dir_name = pdir.name
            pub_num = ((meta.get("ids") or {}).get("patent_publication_number", "") or "").upper().strip()
            try:
                doi_norm = (meta.get("doi") or "").lower().strip()
                conn.execute(
                    """INSERT INTO papers_registry
                       (id, dir_name, title, doi, publication_number, year, first_author)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           dir_name=excluded.dir_name,
                           title=excluded.title,
                           doi=excluded.doi,
                           publication_number=excluded.publication_number,
                           year=excluded.year,
                           first_author=excluded.first_author""",
                    (
                        paper_id,
                        dir_name,
                        meta.get("title") or "",
                        doi_norm,
                        pub_num,
                        meta.get("year"),
                        meta.get("first_author_lastname") or "",
                    ),
                )
            except sqlite3.IntegrityError as exc:
                import logging

                _idx_log = logging.getLogger(__name__)
                err_msg = str(exc).lower()
                if "publication_number" in err_msg and pub_num:
                    _idx_log.warning(
                        "publication_number %r for paper %s conflicts with another paper; "
                        "storing without publication_number",
                        pub_num,
                        paper_id,
                    )
                    conn.execute(
                        """INSERT INTO papers_registry
                           (id, dir_name, title, doi, publication_number, year, first_author)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET
                               dir_name=excluded.dir_name,
                               title=excluded.title,
                               doi=excluded.doi,
                               publication_number=excluded.publication_number,
                               year=excluded.year,
                               first_author=excluded.first_author""",
                        (
                            paper_id,
                            dir_name,
                            meta.get("title") or "",
                            doi_norm,
                            "",  # clear conflicting pub_num
                            meta.get("year"),
                            meta.get("first_author_lastname") or "",
                        ),
                    )
                else:
                    _idx_log.warning(
                        "IntegrityError for paper %s: %s; skipping registry update",
                        paper_id,
                        exc,
                    )

            # Insert references into citations table
            refs = _reference_dois(meta.get("references") or [])
            if refs:
                conn.execute("DELETE FROM citations WHERE source_id = ?", (paper_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO citations (source_id, target_doi, target_id) VALUES (?, ?, NULL)",
                    [(paper_id, doi) for doi in refs],
                )

            count += 1

        # Garbage-collect entries whose paper directory no longer exists
        if not rebuild:
            stale = set(existing_hashes) - seen
            for pid in stale:
                conn.execute("DELETE FROM papers WHERE paper_id = ?", (pid,))
                conn.execute("DELETE FROM papers_hash WHERE paper_id = ?", (pid,))
                conn.execute("DELETE FROM papers_registry WHERE id = ?", (pid,))
                conn.execute("DELETE FROM paper_tags WHERE paper_id = ?", (pid,))
                conn.execute("DELETE FROM citations WHERE source_id = ?", (pid,))
            if stale:
                import logging

                logging.getLogger(__name__).info("removed %d stale index entries", len(stale))
            # Drop citation links pointing at papers that no longer exist
            conn.execute("""
                UPDATE citations SET target_id = NULL
                WHERE target_id IS NOT NULL AND target_id NOT IN (SELECT id FROM papers_registry)
            """)

        # Bulk resolve target_id for citations where target paper is in library
        conn.execute("""
            UPDATE citations SET target_id = (
                SELECT pr.id FROM papers_registry pr
                WHERE LOWER(pr.doi) = LOWER(citations.target_doi)
            ) WHERE target_id IS NULL
        """)

        conn.commit()
    finally:
        conn.close()
    return count


_SEARCH_COLS = "paper_id, title, authors, year, journal, doi, paper_type, citation_count, tags"
_PROCEEDINGS_SEARCH_COLS = (
    "paper_id, title, authors, year, journal, doi, paper_type, citation_count, "
    "dir_name, proceeding_id, proceeding_dir, proceeding_title"
)

#: Per-column BM25 weights for the ``papers`` FTS table, in ``_SCHEMA``
#: column order. bm25() weights are multiplicative factors: a query-term hit
#: in a higher-weighted column contributes proportionally more to the final
#: score (bm25 returns negative values, so ascending order = best first).
#: Tuning rationale: a hit in the title or in curated tags is the strongest
#: topicality signal and must dominate body-text hits; authors and journal
#: carry provenance signal; abstract/conclusion are long body text where
#: incidental term mentions are common; year is nearly noise. UNINDEXED
#: columns never match, so their weight is irrelevant (pinned to 0.0).
_BM25_WEIGHTS = (
    0.0,  # paper_id (UNINDEXED)
    10.0,  # title
    5.0,  # authors
    0.5,  # year
    3.0,  # journal
    2.0,  # abstract
    1.5,  # conclusion
    8.0,  # tags (curated)
    0.0,  # doi (UNINDEXED)
    0.0,  # paper_type (UNINDEXED)
    0.0,  # citation_count (UNINDEXED)
    0.0,  # md_path (UNINDEXED)
    1.0,  # si (long attachment text; incidental mentions are common)
)

#: Pre-rendered ``bm25(papers, ...)`` rank expression for ORDER BY clauses.
_BM25_EXPR = f"bm25(papers, {', '.join(str(w) for w in _BM25_WEIGHTS)})"


def _reference_dois(refs: list) -> list[str]:
    """Extract DOI strings from heterogeneous reference entries.

    Supports both the canonical list[str] shape and dict entries that may
    come from manually curated metadata or external APIs.
    """
    dois: list[str] = []
    for ref in refs:
        doi = ""
        if isinstance(ref, str):
            doi = ref
        elif isinstance(ref, dict):
            external_ids = ref.get("externalIds")
            if not isinstance(external_ids, dict):
                external_ids = {}
            external_ids_alt = ref.get("external_ids")
            if not isinstance(external_ids_alt, dict):
                external_ids_alt = {}
            doi = (
                str(ref.get("doi") or "")
                or str(ref.get("DOI") or "")
                or str(external_ids.get("DOI") or "")
                or str(external_ids_alt.get("DOI") or "")
            )
        doi = (doi or "").strip().lower()
        if doi:
            dois.append(doi)
    return dois


def _ensure_fts_table(conn: sqlite3.Connection) -> None:
    """Raise FileNotFoundError if the FTS5 papers table does not exist.

    When the table exists but was created by an older schema version, migrate
    it in place (drops and recreates the FTS table; rerun ``scrinium index``
    to repopulate).
    """
    has_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'").fetchone()
    if not has_table:
        raise FileNotFoundError("FTS5 index table does not exist; run `scrinium index` first")
    if _ensure_schema(conn):
        conn.commit()


def _ensure_proceedings_fts_table(conn: sqlite3.Connection) -> None:
    has_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='proceedings_fts'").fetchone()
    if not has_table:
        raise FileNotFoundError("Proceedings FTS5 index table does not exist; build the proceedings index first")


def build_proceedings_index(proceedings_root: Path, db_path: Path, rebuild: bool = False) -> int:
    """Build a keyword index for proceedings child papers."""
    from scrinium.proceedings import iter_proceedings_papers

    rows = list(iter_proceedings_papers(proceedings_root))
    current_proceeding_ids = {str(row["proceeding_id"]) for row in rows}
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_PROCEEDINGS_SCHEMA)
        if rebuild:
            conn.execute("DELETE FROM proceedings_fts")
        else:
            existing_proceeding_ids = {
                str(row[0])
                for row in conn.execute(
                    "SELECT DISTINCT proceeding_id FROM proceedings_fts WHERE proceeding_id IS NOT NULL AND proceeding_id != ''"
                )
            }
            stale_proceeding_ids = existing_proceeding_ids - current_proceeding_ids
            if stale_proceeding_ids:
                conn.executemany(
                    "DELETE FROM proceedings_fts WHERE proceeding_id = ?",
                    [(proceeding_id,) for proceeding_id in stale_proceeding_ids],
                )

        count = 0
        cleared_proceedings: set[str] = set()
        for row in rows:
            if not rebuild:
                proceeding_id = row["proceeding_id"]
                if proceeding_id not in cleared_proceedings:
                    conn.execute(
                        """
                        DELETE FROM proceedings_fts
                        WHERE proceeding_id = ?
                        """,
                        (proceeding_id,),
                    )
                    cleared_proceedings.add(proceeding_id)
            conn.execute(
                """
                INSERT INTO proceedings_fts
                    (paper_id, title, authors, year, journal, abstract, conclusion,
                     doi, paper_type, citation_count, md_path, dir_name,
                     proceeding_id, proceeding_dir, proceeding_title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["paper_id"],
                    row["title"],
                    row["authors"],
                    row["year"],
                    row["journal"],
                    row["abstract"],
                    row["conclusion"],
                    row["doi"],
                    row["paper_type"],
                    row["citation_count"],
                    row["md_path"],
                    row["dir_name"],
                    row["proceeding_id"],
                    row["proceeding_dir"],
                    row["proceeding_title"],
                ),
            )
            count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def search_proceedings(
    query: str,
    db_path: Path,
    top_k: int = 20,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
) -> list[dict]:
    """Keyword search over proceedings child papers."""
    if not db_path.exists():
        raise FileNotFoundError(f"Index file does not exist: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_proceedings_fts_table(conn)
        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)
        rows = conn.execute(
            f"""
            SELECT {_PROCEEDINGS_SEARCH_COLS}
            FROM proceedings_fts
            WHERE proceedings_fts MATCH ?{filter_sql}
            ORDER BY rank
            LIMIT ?
            """,
            [_safe_query(query), *filter_params, top_k],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg: Config | None = None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
    tags: list[str] | None = None,
) -> list[dict]:
    """FTS5 keyword full-text search.

    Runs an FTS5 MATCH across ``title``, ``abstract``, ``conclusion``, and
    ``tags``, returning results ranked by BM25 relevance. BM25 is weighted per
    column (see ``_BM25_WEIGHTS``): title and curated-tag hits weigh significantly
    more than body-text hits.

    Args:
        query: Search terms (space-separated, FTS5 syntax).
        db_path: SQLite index database path.
        top_k: Maximum results to return; read from ``cfg.search.top_k`` when ``None``.
        cfg: Optional :class:`~scrinium.config.Config` instance.
        year: Year filter (``"2023"`` / ``"2020-2024"`` / ``"2020-"``).
        journal: Journal name filter (LIKE fuzzy match).
        paper_type: Paper type filter (e.g. ``"review"``, ``"journal-article"``).
        paper_ids: Paper UUID whitelist; returns only results in this set.
        tags: List of curated tags (canonical names) for exact AND filtering.

    Returns:
        List of matching paper dicts, each with ``paper_id``, ``title``,
        ``authors``, ``year``, ``journal``, ``doi``, ``paper_type``,
        ``citation_count``, and ``tags`` (list of tags).

    Raises:
        FileNotFoundError: Index file or FTS5 table does not exist.
    """
    if top_k is None:
        top_k = cfg.search.top_k if cfg is not None else 20

    if not db_path.exists():
        raise FileNotFoundError(f"Index file does not exist: {db_path}\nRun `scrinium index` first")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type, tags=tags)

        # Over-fetch when post-filtering by paper_ids to avoid empty results
        fetch_k = top_k * 5 if paper_ids else top_k

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE papers MATCH ?{filter_sql}
            ORDER BY {_BM25_EXPR}
            LIMIT ?
            """,
            [_safe_query(query), *filter_params, fetch_k],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
        _normalize_result_tags(results)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def search_author(
    query: str,
    db_path: Path,
    top_k: int | None = None,
    cfg: Config | None = None,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Search papers by author name (LIKE fuzzy match).

    Args:
        query: Author name (or partial name), case-insensitive.
        db_path: SQLite index database path.
        top_k: Maximum results to return; read from ``cfg.search.top_k`` when ``None``.
        cfg: Optional :class:`~scrinium.config.Config` instance.
        year: Year filter (``"2023"`` / ``"2020-2024"`` / ``"2020-"``).
        journal: Journal name filter (LIKE fuzzy match).
        paper_type: Paper type filter (e.g. ``"review"``, ``"journal-article"``).
        paper_ids: Paper UUID whitelist; returns only results in this set.

    Returns:
        List of matching paper dicts.
    """
    if top_k is None:
        top_k = cfg.search.top_k if cfg is not None else 20

    if not db_path.exists():
        raise FileNotFoundError(f"Index file does not exist: {db_path}\nRun `scrinium index` first")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)

        # Over-fetch when post-filtering by paper_ids to avoid empty results
        fetch_k = top_k * 5 if paper_ids else top_k

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE authors LIKE ?{filter_sql}
            ORDER BY year DESC
            LIMIT ?
            """,
            [f"%{query}%", *filter_params, fetch_k],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
        _normalize_result_tags(results)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def top_cited(
    db_path: Path,
    top_k: int = 10,
    *,
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Return papers sorted by citation count descending.

    Args:
        db_path: SQLite index database path.
        top_k: Maximum results to return.
        year: Year filter (``"2023"`` / ``"2020-2024"`` / ``"2020-"``).
        journal: Journal name filter (LIKE fuzzy match).
        paper_type: Paper type filter (e.g. ``"review"``, ``"journal-article"``).
        paper_ids: Paper UUID whitelist; returns only results in this set.

    Returns:
        List of paper dicts ordered by ``citation_count`` descending.

    Raises:
        FileNotFoundError: Index file or FTS5 table does not exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Index file does not exist: {db_path}\nRun `scrinium index` first")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_fts_table(conn)

        conn.row_factory = sqlite3.Row
        filter_sql, filter_params = _build_filter_clause(year=year, journal=journal, paper_type=paper_type)

        # Skip SQL LIMIT when post-filtering by paper_ids (workspace scope)
        limit_clause = "" if paper_ids else "LIMIT ?"
        limit_params = [] if paper_ids else [top_k]

        rows = conn.execute(
            f"""
            SELECT {_SEARCH_COLS}
            FROM papers
            WHERE citation_count != ''{filter_sql}
            ORDER BY CAST(citation_count AS INTEGER) DESC
            {limit_clause}
            """,
            [*filter_params, *limit_params],
        ).fetchall()
        results = [dict(r) for r in rows]
        _enrich_dir_names(results, conn)
        _normalize_result_tags(results)
    finally:
        conn.close()
    if paper_ids is not None:
        results = [r for r in results if r["paper_id"] in paper_ids]
    return results[:top_k]


def _parse_year_filter(year: str) -> tuple[str, list[str]]:
    """Parse a year filter expression and return a SQL WHERE fragment and parameters.

    Supported formats: ``"2023"`` (single year), ``"2020-2024"`` (range),
    ``"2020-"`` (from start year onward).

    Args:
        year: Year filter expression.

    Returns:
        ``(where_clause, params)`` tuple.
    """
    start, end = parse_year_range(year)
    if start is not None and end is not None:
        if start == end:
            return "year = ?", [str(start)]
        return "year >= ? AND year <= ?", [str(start), str(end)]
    elif start is not None:
        return "year >= ?", [str(start)]
    elif end is not None:
        return "year <= ?", [str(end)]
    return "1=1", []


def _build_filter_clause(
    year: str | None = None,
    journal: str | None = None,
    paper_type: str | None = None,
    tags: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Build a filter WHERE clause (without a leading AND/WHERE).

    Args:
        year: Year filter expression; no filtering when ``None``.
        journal: Journal name (LIKE fuzzy match); no filtering when ``None``.
        paper_type: Paper type (LIKE fuzzy match, e.g. ``review``,
            ``journal-article``); no filtering when ``None``.
        tags: List of curated tags (canonical names) with AND semantics (the
            paper must have all of them); no filtering when ``None``.

    Returns:
        ``(clauses_str, params)`` where each condition in clauses_str is prefixed with ``AND``.
    """
    clauses: list[str] = []
    params: list[str] = []
    if year:
        yc, yp = _parse_year_filter(year)
        clauses.append(yc)
        params.extend(yp)
    if journal:
        clauses.append("journal LIKE ?")
        params.append(f"%{journal}%")
    if paper_type:
        clauses.append("paper_type LIKE ?")
        params.append(f"%{paper_type}%")
    if tags:
        for tag in tags:
            clauses.append("paper_id IN (SELECT paper_id FROM paper_tags WHERE tag = ?)")
            params.append(tag)
    sql = "".join(f" AND {c}" for c in clauses)
    return sql, params


def paper_ids_for_tags(db_path: Path, tags: list[str]) -> set[str]:
    """Return the set of paper UUIDs that carry all given tags (AND semantics).

    Args:
        db_path: SQLite index database path.
        tags: List of curated tags (canonical names).

    Returns:
        Matching paper UUID set; empty if the database or ``paper_tags`` table does not exist.
    """
    if not tags or not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_tags'").fetchone()
        if not has_table:
            return set()
        ids: set[str] | None = None
        for tag in tags:
            rows = conn.execute("SELECT paper_id FROM paper_tags WHERE tag = ?", (tag,)).fetchall()
            current = {row[0] for row in rows}
            ids = current if ids is None else ids & current
        return ids if ids is not None else set()
    finally:
        conn.close()


_safe_query = sanitize_fts_query  # backward compat alias


def _enrich_dir_names(results: list[dict], conn: sqlite3.Connection) -> list[dict]:
    """Enrich search results with dir_name from papers_registry."""
    has_reg = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'").fetchone()
    if not has_reg:
        return results
    id_to_dir: dict[str, str] = {}
    for row in conn.execute("SELECT id, dir_name FROM papers_registry").fetchall():
        id_to_dir[row[0]] = row[1]
    for r in results:
        r["dir_name"] = id_to_dir.get(r["paper_id"], "")
    return results


def _normalize_result_tags(results: list[dict]) -> list[dict]:
    """Convert the space-joined FTS ``tags`` column into a list of strings."""
    for r in results:
        raw = r.get("tags")
        r["tags"] = raw.split() if isinstance(raw, str) and raw else []
    return results


def lookup_paper(db_path: Path, user_input: str) -> dict | None:
    """Look up a paper by UUID, dir_name, DOI, or patent publication number.

    Tries matching in this order: UUID -> dir_name -> DOI -> publication_number.
    Publication number lookups are normalized to uppercase automatically.

    Args:
        db_path: SQLite database path.
        user_input: UUID, directory name, DOI, or patent publication number.

    Returns:
        ``papers_registry`` row dict, or ``None`` if not found.
    """
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='papers_registry'"
        ).fetchone()
        if not has_table:
            return None
        conn.row_factory = sqlite3.Row
        # Try UUID
        row = conn.execute("SELECT * FROM papers_registry WHERE id = ?", (user_input,)).fetchone()
        if row:
            return dict(row)
        # Try dir_name
        row = conn.execute("SELECT * FROM papers_registry WHERE dir_name = ?", (user_input,)).fetchone()
        if row:
            return dict(row)
        # Try DOI (new DBs store lowercase DOI; old DBs may still contain mixed case)
        normalized_doi = user_input.strip().lower()
        row = conn.execute(
            "SELECT * FROM papers_registry WHERE doi = ?",
            (normalized_doi,),
        ).fetchone()
        if not row:
            # Backward compatibility for pre-normalization registries.
            row = conn.execute(
                "SELECT * FROM papers_registry WHERE LOWER(doi) = ?",
                (normalized_doi,),
            ).fetchone()
        if row:
            return dict(row)
        # Try patent publication number (normalize to uppercase)
        try:
            row = conn.execute(
                "SELECT * FROM papers_registry WHERE publication_number = ?",
                (user_input.upper().strip(),),
            ).fetchone()
            if row:
                return dict(row)
        except sqlite3.OperationalError:
            pass  # column may not exist in old DB
    finally:
        conn.close()
    return None


# ============================================================================
#  Citation graph queries
# ============================================================================


def get_references(
    paper_id: str,
    db_path: Path,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Query the reference list of a paper.

    Args:
        paper_id: Paper UUID.
        db_path: SQLite database path.
        paper_ids: Paper UUID whitelist (filters only in-library results).

    Returns:
        List of references, each with ``target_doi`` and ``target_id``;
        in-library papers also include ``title``, ``dir_name``, ``year``, ``first_author``.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT c.target_doi, c.target_id,
                      pr.title, pr.dir_name, pr.year, pr.first_author
               FROM citations c
               LEFT JOIN papers_registry pr ON c.target_id = pr.id
               WHERE c.source_id = ?
               ORDER BY pr.year DESC NULLS LAST, c.target_doi""",
            (paper_id,),
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r.get("target_id") is None or r["target_id"] in paper_ids]
    return results


def get_citing_papers(
    paper_id: str,
    db_path: Path,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Query which local papers cite the given paper (reverse lookup within the library).

    Args:
        paper_id: UUID of the cited paper.
        db_path: SQLite database path.
        paper_ids: Paper UUID whitelist.

    Returns:
        List of citing papers, each with ``source_id``, ``dir_name``, ``title``, ``year``.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        # Get DOI of target paper
        row = conn.execute("SELECT doi FROM papers_registry WHERE id = ?", (paper_id,)).fetchone()
        target_doi = row["doi"] if row else ""

        # Find papers that cite this paper (by target_id or target_doi)
        params: list = [paper_id]
        doi_clause = ""
        if target_doi:
            doi_clause = " OR LOWER(c.target_doi) = LOWER(?)"
            params.append(target_doi)

        rows = conn.execute(
            f"""SELECT DISTINCT c.source_id,
                       pr.dir_name, pr.title, pr.year, pr.first_author
                FROM citations c
                JOIN papers_registry pr ON c.source_id = pr.id
                WHERE (c.target_id = ?{doi_clause})
                ORDER BY pr.year DESC""",
            params,
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r["source_id"] in paper_ids]
    return results


def get_shared_references(
    paper_id_list: list[str],
    db_path: Path,
    min_shared: int = 2,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Query shared references across multiple papers.

    Args:
        paper_id_list: List of paper UUIDs.
        db_path: SQLite database path.
        min_shared: Minimum number of papers that must share a reference for it to be included.
        paper_ids: Paper UUID whitelist (filters only in-library results).

    Returns:
        List of shared references, each with ``target_doi``, ``shared_count``,
        and ``target_id``; in-library papers also include ``title`` and ``dir_name``.
    """
    if not db_path.exists() or not paper_id_list:
        return []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in paper_id_list)
        rows = conn.execute(
            f"""SELECT c.target_doi,
                       COUNT(DISTINCT c.source_id) AS shared_count,
                       c.target_id,
                       pr.title, pr.dir_name, pr.year
                FROM citations c
                LEFT JOIN papers_registry pr ON c.target_id = pr.id
                WHERE c.source_id IN ({placeholders})
                GROUP BY LOWER(c.target_doi)
                HAVING shared_count >= ?
                ORDER BY shared_count DESC, c.target_doi""",
            [*paper_id_list, min_shared],
        ).fetchall()
    finally:
        conn.close()
    results = [dict(r) for r in rows]
    if paper_ids is not None:
        results = [r for r in results if r.get("target_id") is None or r["target_id"] in paper_ids]
    return results
