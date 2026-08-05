"""
explore.py — 学术探索
======================

从 OpenAlex 批量拉取论文（支持 ISSN / concept / author / institution /
keyword 等多维度 filter），本地 FTS5 关键词检索。拉取结果的主题分组由
agent（subagent）在 harness 侧完成，框架不做嵌入与聚类。数据存储在
``data/explore/<name>/``，与主库完全隔离。

用法::

    from scrinium.explore import explore_search, fetch_explore
    fetch_explore("jfm", issn="0022-1120")
    fetch_explore("turbulence", concept="C62520636", year_range="2020-2025")
    explore_search("jfm", "turbulent boundary layer")
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from scrinium.log import ui
from scrinium.search_common import fts_create_sql, sanitize_fts_query

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scrinium.config import Config

# ============================================================================
#  Config / paths
# ============================================================================

_DEFAULT_EXPLORE_DIR = Path("data/explore")


def _explore_dir(name: str, cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "explore" / name
    return _DEFAULT_EXPLORE_DIR / name


def _papers_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "papers.jsonl"


def _db_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "explore.db"


def explore_db_path(name: str, cfg: Config | None = None) -> Path:
    """Return the SQLite DB path for an explore library.

    Args:
        name: Explore library name.
        cfg: Optional Config instance; resolved from environment if omitted.

    Returns:
        Path to ``explore.db`` inside the library directory.
    """
    return _db_path(name, cfg)


def validate_explore_name(name: str) -> bool:
    """Return True if *name* is a safe, non-traversing library identifier.

    Rejects empty strings, absolute paths, and names that contain path
    separators or ``..`` components so that callers cannot escape the
    ``data/explore/`` directory.

    Args:
        name: Candidate explore library name supplied by the user.

    Returns:
        ``True`` when the name is safe to use in path construction.
    """
    if not name:
        return False
    import os

    # Reject absolute paths and names that contain any path separator.
    if os.path.isabs(name):
        return False
    if "/" in name or "\\" in name:
        return False
    # Reject any name containing "..".
    return ".." not in name


def _meta_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "meta.json"


# ============================================================================
#  Fetch from OpenAlex
# ============================================================================


_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _build_filter(
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
) -> tuple[str, dict]:
    """Build an OpenAlex filter string and extra query params.

    Returns:
        (filter_string, extra_params) — extra_params may contain ``search``.
    """
    parts: list[str] = []
    extra: dict[str, str] = {}

    if issn:
        parts.append(f"primary_location.source.issn:{issn}")
    if concept:
        parts.append(f"concepts.id:{concept}")
    if topic:
        parts.append(f"topics.id:{topic}")
    if author:
        parts.append(f"authorships.author.id:{author}")
    if institution:
        parts.append(f"authorships.institutions.id:{institution}")
    if source_type:
        parts.append(f"primary_location.source.type:{source_type}")
    if year_range:
        parts.append(f"publication_year:{year_range}")
    # OpenAlex cited_by_count filter expects a meaningful lower bound.
    # Non-positive values are treated as "no filter" to avoid invalid/odd expressions.
    if min_citations is not None and min_citations > 0:
        parts.append(f"cited_by_count:>{min_citations - 1}")
    if oa_type:
        parts.append(f"type:{oa_type}")

    return ",".join(parts), extra


# CLI --sort option name -> OpenAlex sort expression
_SORT_MAP = {
    "year_asc": "publication_year:asc",
    "year_desc": "publication_year:desc",
    "relevance": "relevance_score:desc",
    "citations": "cited_by_count:desc",
}


def _resolve_sort(sort: str | None, keyword: str | None) -> str:
    """Pick the OpenAlex sort expression for a fetch.

    Explicit ``sort`` (CLI option name or raw OpenAlex expression) wins.
    Otherwise: keyword searches default to relevance ranking — sorting a
    free-text search by year surfaces irrelevant old records; filter-only
    fetches (journal/author surveys) keep chronological ascending order.
    """
    if sort:
        return _SORT_MAP.get(sort, sort)
    if keyword:
        return "relevance_score:desc"
    return "publication_year:asc"


def _fetch_page(
    filt: str,
    extra_params: dict | None = None,
    *,
    cursor: str = "*",
    keyword: str | None = None,
    sort: str = "publication_year:asc",
    mailto: str = "",
) -> tuple[list[dict], str | None]:
    """Fetch one page of results from OpenAlex.

    Args:
        filt: Pre-built OpenAlex filter string.
        extra_params: Additional query params (e.g. search).
        cursor: Cursor for pagination.
        keyword: Free-text search keyword (OpenAlex ``search`` param).
        sort: OpenAlex sort expression (see ``_resolve_sort``).
        mailto: Contact email for the OpenAlex polite pool (better rate limits).
    """
    params: dict[str, str | int] = {
        "per_page": _PER_PAGE,
        "cursor": cursor,
        "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,"
        "primary_location,cited_by_count,type",
        "sort": sort,
    }
    if mailto:
        params["mailto"] = mailto
    if filt:
        params["filter"] = filt
    if keyword:
        params["search"] = keyword
    if extra_params:
        params.update(extra_params)
    # Retry with exponential backoff for transient errors. 429s from OpenAlex
    # can persist well beyond a few seconds under shared-IP load, so use longer
    # waits and more attempts than a typical transient-failure retry.
    last_exc: Exception | None = None
    for attempt in range(5):
        wait = min(60, 2 ** (attempt + 2))
        try:
            resp = requests.get(_OA_WORKS, params=params, timeout=30, proxies={"http": None, "https": None})
            if resp.status_code == 429:
                _log.warning("OpenAlex 429 rate limit, retrying in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            _log.warning("OpenAlex request failed (attempt %d/5): %s, retrying in %ds", attempt + 1, e, wait)
            time.sleep(wait)
    else:
        if last_exc:
            raise last_exc
        raise requests.HTTPError("OpenAlex API returned 429 after 5 retries")

    papers = []
    for item in data.get("results", []):
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        authors = []
        for a in item.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        # Strip HTML tags from title (OpenAlex includes <b>, <scp>, <i>, etc.)
        raw_title = item.get("title") or ""
        clean_title = re.sub(r"<[^>]+>", "", raw_title)

        papers.append(
            {
                "openalex_id": item.get("id", ""),
                "doi": doi,
                "title": clean_title,
                "abstract": abstract,
                "authors": authors,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "type": item.get("type", ""),
            }
        )

    next_cursor = data.get("meta", {}).get("next_cursor")
    return papers, next_cursor


def fetch_explore(
    name: str,
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    keyword: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
    sort: str | None = None,
    incremental: bool = False,
    limit: int | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 批量拉取论文（支持多维度 filter）。

    使用 cursor-based 分页遍历符合条件的所有论文，
    提取 title、abstract、authors 等字段，写入 JSONL 文件。

    Args:
        name: 探索库名称（如 ``"jfm"``），用作目录名。
        issn: 期刊 ISSN 过滤（如 ``"0022-1120"``）。
        concept: OpenAlex concept ID（如 ``"C62520636"`` = Turbulence）。
        topic: OpenAlex topic ID。
        author: OpenAlex author ID。
        institution: OpenAlex institution ID。
        keyword: 标题/摘要关键词搜索。
        source_type: 来源类型过滤（journal / conference / repository）。
        year_range: 年份过滤（如 ``"2020-2025"``）。
        min_citations: 最小引用量过滤。
        oa_type: OpenAlex work type 过滤（article / review 等）。
        sort: 排序方式（``year_asc`` / ``year_desc`` / ``relevance`` /
            ``citations`` 或原始 OpenAlex 表达式）。``None`` 时自动选择：
            关键词检索按相关度，纯 filter 拉取按年份升序。
        incremental: 为 ``True`` 时追加到现有 JSONL，基于 DOI 去重。
        limit: 最多拉取的论文数量上限（``None`` 表示无限制）。
        cfg: 可选的全局配置。

    Returns:
        本次新拉取的论文数量。
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit 必须为正整数，当前为: {limit}")

    resolved_sort = _resolve_sort(sort, keyword)
    mailto = (cfg.ingest.contact_email if cfg else "") or os.environ.get("OPENALEX_MAILTO", "")

    out_dir = _explore_dir(name, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    papers_file = _papers_path(name, cfg)
    meta_file = _meta_path(name, cfg)

    filt, extra_params = _build_filter(
        issn=issn,
        concept=concept,
        topic=topic,
        author=author,
        institution=institution,
        source_type=source_type,
        year_range=year_range,
        min_citations=min_citations,
        oa_type=oa_type,
    )
    if not filt and not keyword:
        raise ValueError("至少需要一个过滤条件（issn / concept / author / keyword 等）")

    # Incremental mode: load existing IDs (DOI or openalex_id) to skip duplicates
    existing_pids: set[str] = set()
    if incremental and papers_file.exists():
        for p in iter_papers(name, cfg):
            pid = p.get("doi", "").lower() or p.get("openalex_id", "")
            if pid:
                existing_pids.add(pid)
        _log.info("incremental mode: %d existing papers loaded", len(existing_pids))

    from scrinium.metrics import timer

    total = 0
    cursor: str | None = "*"

    with timer("explore.fetch", "api") as t:
        if incremental and papers_file.exists():
            f_handle = open(papers_file, "a", encoding="utf-8")
        else:
            tmp_file = papers_file.with_suffix(".jsonl.tmp")
            f_handle = open(tmp_file, "w", encoding="utf-8")

        try:
            page = 0
            while cursor:
                if limit is not None and total >= limit:
                    break
                page += 1
                papers, cursor = _fetch_page(
                    filt,
                    extra_params,
                    cursor=cursor,
                    keyword=keyword,
                    sort=resolved_sort,
                    mailto=mailto,
                )
                if not papers:
                    break
                written = 0
                for p in papers:
                    if limit is not None and total >= limit:
                        break
                    # Skip duplicates in incremental mode (by DOI or openalex_id)
                    if incremental:
                        pid = p.get("doi", "").lower() or p.get("openalex_id", "")
                        if pid and pid in existing_pids:
                            continue
                    f_handle.write(json.dumps(p, ensure_ascii=False) + "\n")
                    total += 1
                    written += 1
                    if incremental:
                        pid = p.get("doi", "").lower() or p.get("openalex_id", "")
                        if pid:
                            existing_pids.add(pid)
                _log.info(
                    "page %d: fetched=%d, written=%d (total %d, %.0fs)",
                    page,
                    len(papers),
                    written,
                    total,
                    t.elapsed,
                )
        finally:
            f_handle.close()

        if not incremental or not papers_file.exists():
            tmp_file.replace(papers_file)  # type: ignore[possibly-undefined]

    # Build query record for meta.json
    query_params: dict[str, str | int | None] = {}
    for key, val in [
        ("issn", issn),
        ("concept", concept),
        ("topic", topic),
        ("author", author),
        ("institution", institution),
        ("keyword", keyword),
        ("source_type", source_type),
        ("year_range", year_range),
        ("min_citations", min_citations),
        ("oa_type", oa_type),
        ("sort", resolved_sort),
    ]:
        if val is not None:
            query_params[key] = val

    # Update count: for incremental mode, add to existing count
    total_count = total
    if incremental and meta_file.exists():
        old_meta = json.loads(meta_file.read_text("utf-8"))
        total_count = old_meta.get("count", 0) + total

    meta = {
        "name": name,
        "source": "openalex",
        "query": query_params,
        # Keep "issn" at top level for backward compatibility
        "issn": issn or "",
        "year_range": year_range,
        "count": total_count,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(t.elapsed, 1),
    }
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ui(f"Done: {total} {'new ' if incremental else ''}papers, {t.elapsed:.0f}s -> {papers_file}")
    return total


def fetch_journal(
    name: str,
    issn: str,
    *,
    year_range: str | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 拉取期刊全量论文（向后兼容别名）。

    等价于 ``fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)``。
    """
    return fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)


# ============================================================================
#  Load papers from JSONL
# ============================================================================


def iter_papers(name: str, cfg: Config | None = None) -> Iterator[dict]:
    """逐行读取 JSONL，yield 论文字典。"""
    path = _papers_path(name, cfg)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def count_papers(name: str, cfg: Config | None = None) -> int:
    """返回探索库中的论文数量。"""
    meta_file = _meta_path(name, cfg)
    if meta_file.exists():
        return json.loads(meta_file.read_text("utf-8")).get("count", 0)
    return sum(1 for _ in iter_papers(name, cfg))


def build_papers_map(name: str, cfg: Config | None = None) -> dict[str, dict]:
    """从 JSONL 构建 paper_id → metadata 映射。

    Args:
        name: 探索库名称。
        cfg: 可选的全局配置。

    Returns:
        ``{paper_id: paper_dict}`` 映射，paper_id 为 DOI 或 openalex_id。
    """
    pm: dict[str, dict] = {}
    for p in iter_papers(name, cfg):
        pid = p.get("doi") or p.get("openalex_id", "")
        if pid:
            pm[pid] = p
    return pm


# ============================================================================
#  FTS5 keyword search for explore silos
# ============================================================================

_FTS_SCHEMA = fts_create_sql(
    "papers_fts",
    [
        ("paper_id", False),
        ("title", True),
        ("authors", True),
        ("abstract", True),
        ("year", False),
    ],
)

#: Per-column BM25 weights for the ``papers_fts`` table, in ``_FTS_SCHEMA``
#: column order. Proportional to the main library's ``_BM25_WEIGHTS``:
#: title is the dominant signal, authors carry provenance weight, abstract
#: is long body text where incidental mentions are common. UNINDEXED
#: columns never match, so their weight is pinned to 0.0.
_FTS_BM25_WEIGHTS = (
    0.0,  # paper_id (UNINDEXED)
    10.0,  # title
    5.0,  # authors
    2.0,  # abstract
    0.0,  # year (UNINDEXED)
)

#: Pre-rendered ``bm25(papers_fts, ...)`` rank expression for ORDER BY.
_FTS_BM25_EXPR = f"bm25(papers_fts, {', '.join(str(w) for w in _FTS_BM25_WEIGHTS)})"


def _ensure_fts(db_path: Path) -> None:
    """Create FTS5 table in explore.db if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_FTS_SCHEMA)
    conn.close()


def build_explore_fts(name: str, *, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为探索库构建 FTS5 全文索引。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置。

    Returns:
        索引的论文数量。
    """
    db = _db_path(name, cfg)
    _ensure_fts(db)
    conn = sqlite3.connect(db)
    try:
        if rebuild:
            conn.execute("DELETE FROM papers_fts")
            conn.commit()

        existing = {row[0] for row in conn.execute("SELECT paper_id FROM papers_fts").fetchall()}

        count = 0
        for p in iter_papers(name, cfg):
            pid = p.get("doi") or p.get("openalex_id", "")
            if not pid or pid in existing:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title:
                continue
            authors = ", ".join(p.get("authors") or [])
            year = str(p.get("year") or "")
            conn.execute(
                "INSERT INTO papers_fts (paper_id, title, authors, abstract, year) VALUES (?, ?, ?, ?, ?)",
                (pid, title, authors, abstract, year),
            )
            count += 1

        conn.commit()
    finally:
        conn.close()

    _log.info("FTS5 index: %d papers indexed for %s", count, name)
    return count


def explore_search(name: str, query: str, *, top_k: int = 20, cfg: Config | None = None) -> list[dict]:
    """在探索库中进行 FTS5 关键词搜索。

    Args:
        name: 探索库名称。
        query: 查询文本（先经 ``sanitize_fts_query`` 净化，与主库策略一致）。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 BM25 排名（标题列权重最高，见 ``_FTS_BM25_WEIGHTS``）。
    """
    db = _db_path(name, cfg)
    if not db.exists():
        return []

    _ensure_fts(db)

    # Auto-build if FTS table is empty
    conn = sqlite3.connect(db)
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    finally:
        conn.close()

    if fts_count == 0:
        build_explore_fts(name, cfg=cfg)

    conn = sqlite3.connect(db)
    try:
        # Sanitize with the same strategy as the main library; an empty
        # sanitized query has no usable terms and must skip MATCH.
        safe_query = sanitize_fts_query(query)
        if not safe_query:
            return []
        try:
            # bm25() returns negative scores (ascending = best first); the
            # explicit per-column weights replace the default equal-weight
            # ``rank`` ordering.
            rows = conn.execute(
                f"""
                SELECT paper_id, {_FTS_BM25_EXPR} AS bm25_score
                FROM papers_fts
                WHERE papers_fts MATCH ?
                ORDER BY bm25_score
                LIMIT ?
                """,
                (safe_query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Best-effort API: degrade to "no hits" instead of raising.
            rows = []
    finally:
        conn.close()

    if not rows:
        return []

    paper_map = build_papers_map(name, cfg)
    results = []
    for pid, bm25_score in rows:
        p = paper_map.get(pid, {})
        results.append({**p, "score": -bm25_score})
    return results


def list_explore_libs(cfg: Config | None = None) -> list[str]:
    """列出所有探索库名称。"""
    if cfg is not None:
        root = cfg._root / "data" / "explore"
    else:
        root = _DEFAULT_EXPLORE_DIR
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / "papers.jsonl").exists())
