"""cli/common.py — helpers and constants shared across CLI domain modules."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from scrinium.log import ui

_log = logging.getLogger(__package__)


def _resolve_top(args: argparse.Namespace, default: int) -> int:
    return args.top if args.top is not None else default


def _record_search_metrics(
    store,
    name: str,
    query: str,
    results: list[dict],
    elapsed: float,
    args: argparse.Namespace,
) -> None:
    """Record a search event to the metrics store, silently ignoring failures."""
    if not store:
        return
    try:
        store.record(
            category="search",
            name=name,
            duration_s=elapsed,
            detail={
                "query": query,
                "result_count": len(results),
                "top_dois": [r["doi"] for r in results[:5] if r.get("doi")],
                "filters": {
                    "year": getattr(args, "year", None),
                    "journal": getattr(args, "journal", None),
                    "paper_type": getattr(args, "paper_type", None),
                },
            },
        )
    except Exception as _e:
        _log.debug("metrics record failed: %s", _e)


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024 / 2020-")
    parser.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        dest="paper_type",
        help="论文类型过滤：review / journal-article 等（模糊匹配）",
    )


def _add_tag_arg(parser: argparse.ArgumentParser) -> None:
    """Add the repeatable ``--tag`` exact-filter argument to a search parser."""
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=None,
        metavar="TAG",
        help="按策展标签精确过滤（可重复，AND 语义，支持别名）",
    )


def _resolve_tag_filters(args: argparse.Namespace, cfg) -> list[str] | None:
    """Resolve ``--tag`` values to canonical tag names via the taxonomy.

    Raises:
        ValueError: any tag is unknown to the taxonomy (message lists the
            current vocabulary).
    """
    raw = getattr(args, "tags", None)
    if not raw:
        return None
    from scrinium.tags import load_taxonomy, resolve_tag

    resolved: list[str] = []
    unknown: list[str] = []
    for name in raw:
        canonical = resolve_tag(cfg, name)
        if canonical is None:
            unknown.append(name)
        elif canonical not in resolved:
            resolved.append(canonical)
    if unknown:
        known = sorted((load_taxonomy(cfg).get("tags") or {}).keys())
        hint = f"；当前词表: {', '.join(known)}" if known else "（词表为空，可先用 scrinium tag 打标）"
        raise ValueError(f"未知标签: {', '.join(unknown)}{hint}")
    return resolved or None


def _resolve_ws_paper_ids(args: argparse.Namespace, cfg) -> set[str] | None:
    ws_name = getattr(args, "ws", None)
    if not ws_name:
        return None
    from scrinium import workspace

    if not workspace.validate_workspace_name(ws_name):
        raise ValueError(f"非法工作区名称: {ws_name}")

    ws_dir = cfg._root / "workspace" / ws_name
    pids = workspace.read_paper_ids(ws_dir)
    if not pids:
        ui(f"工作区 {ws_name} 为空或不存在")
    return pids


# Suggested install commands per missing optional dependency.


_INSTALL_HINTS: dict[str, str] = {
    "sentence_transformers": "pip install scrinium[embed]",
    "faiss": "pip install scrinium[embed]",
    "numpy": "pip install scrinium[embed]",
    "bertopic": "pip install scrinium[topics]",
    "pandas": "pip install scrinium[topics]",
    "endnote_utils": "pip install scrinium[import]",
    "pyzotero": "pip install scrinium[import]",
    "docx": "pip install scrinium[office]",
    "pptx": "pip install scrinium[office]",
    "openpyxl": "pip install scrinium[office]",
    "markitdown": "pip install scrinium[office]",
    "fitz": "pip install scrinium[pdf]",
}


def _check_import_error(e: ImportError) -> None:
    """Log a user-friendly message for missing optional dependencies, then exit."""
    mod = getattr(e, "name", "") or ""
    # Match the top-level package name
    top = mod.split(".")[0] if mod else ""
    hint = _INSTALL_HINTS.get(top, "")
    if hint:
        _log.error("缺少依赖: %s\n  安装: %s", mod, hint)
    else:
        _log.error("缺少依赖: %s\n  请安装所需的 Python 包", e)
    sys.exit(1)


def _write_all_viz(model, viz_dir: Path) -> None:
    """Write 6 BERTopic HTML visualizations to *viz_dir*."""
    from scrinium.topics import (
        visualize_barchart,
        visualize_heatmap,
        visualize_term_rank,
        visualize_topic_hierarchy,
        visualize_topics_2d,
        visualize_topics_over_time,
    )

    viz_dir.mkdir(parents=True, exist_ok=True)
    _log.debug("generating visualizations")

    charts = [
        ("topics_2d", "2D scatter", visualize_topics_2d),
        ("barchart", "Keywords  ", visualize_barchart),
        ("hierarchy", "Hierarchy ", visualize_topic_hierarchy),
        ("heatmap", "Heatmap   ", visualize_heatmap),
        ("term_rank", "Term rank ", visualize_term_rank),
    ]
    for fname, label, func in charts:
        html = func(model)
        (viz_dir / f"{fname}.html").write_text(html, encoding="utf-8")
        ui(f"  {label} -> {viz_dir / f'{fname}.html'}")

    try:
        html = visualize_topics_over_time(model)
        (viz_dir / "topics_over_time.html").write_text(html, encoding="utf-8")
        ui(f"  Over time  -> {viz_dir / 'topics_over_time.html'}")
    except Exception as e:
        _log.error("Topics-over-time failed: %s", e)


def _emit_json(payload: object) -> None:
    """Print *payload* as JSON to stdout (``--json`` mode; pipe-safe)."""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _search_result_json(r: dict) -> dict:
    """Normalize a search result dict into the ``--json`` output shape."""
    return {
        "id": r.get("paper_id"),
        "dir_name": r.get("dir_name") or "",
        "title": r.get("title"),
        "authors": r.get("authors"),
        "year": r.get("year"),
        "journal": r.get("journal"),
        "doi": r.get("doi"),
        "paper_type": r.get("paper_type"),
        "citation_count": r.get("citation_count"),
        "tags": r.get("tags") or [],
        "score": r.get("score"),
        "match": r.get("match"),
    }


def _resolve_export_paper_ids(paper_ids: list[str] | None, cfg) -> list[str] | None:
    """Resolve export identifiers (dir_name / UUID / DOI) to dir names.

    Reports each unresolvable identifier; raises ValueError when all fail.
    """
    if not paper_ids:
        return paper_ids
    resolved: list[str] = []
    unresolved: list[str] = []
    for ref in paper_ids:
        paper_d = _try_resolve_paper(ref, cfg)
        if paper_d is None:
            unresolved.append(ref)
        else:
            resolved.append(paper_d.name)
    for ref in unresolved:
        ui(f"无法解析: {ref}")
    if unresolved and not resolved:
        raise ValueError(f"所有论文 ID 均无法解析: {', '.join(unresolved)}")
    return list(dict.fromkeys(resolved))


def _count_registry_papers(index_db) -> int | None:
    """Return the number of papers in papers_registry, or None if unavailable."""
    import sqlite3

    if not Path(index_db).exists():
        return None
    try:
        with sqlite3.connect(str(index_db)) as conn:
            row = conn.execute("SELECT COUNT(*) FROM papers_registry").fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _format_match_tag(match: str) -> str:
    mapping = {
        "both": "关键词+语义",
        "fts": "关键词",
        "vec": "语义",
    }
    return mapping.get(match, match)


def _resolve_paper(paper_id: str, cfg) -> Path:
    """Resolve a paper identifier (dir_name, UUID, or DOI) to its directory.

    Exits with error when the identifier cannot be resolved; see
    :func:`_try_resolve_paper` for a non-exiting variant.
    """
    paper_d = _try_resolve_paper(paper_id, cfg)
    if paper_d is None:
        _log.error("未找到论文: %s", paper_id)
        sys.exit(1)
    return paper_d


def _try_resolve_paper(paper_id: str, cfg) -> Path | None:
    """Resolve a paper identifier (dir_name, UUID, or DOI) to its directory.

    Resolution order:
    1. Direct dir_name match on filesystem
    2. Registry lookup (UUID / DOI) → dir_name
    3. Filesystem scan — read each meta.json["id"] to find UUID match

    Returns the paper directory Path, or None when unresolvable.
    """
    from scrinium.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir
    # 1. Direct dir_name
    paper_d = papers_dir / paper_id
    if (paper_d / "meta.json").exists():
        return paper_d
    # 2. Registry lookup (fast, but may be stale)
    from scrinium.index import lookup_paper

    reg = lookup_paper(cfg.index_db, paper_id)
    if reg:
        paper_d = papers_dir / reg["dir_name"]
        if (paper_d / "meta.json").exists():
            return paper_d
    # 3. Filesystem scan fallback (handles stale registry / pre-index state)
    from scrinium.papers import read_meta as _read_meta

    normalized_doi = paper_id.strip().lower()
    for pdir in iter_paper_dirs(papers_dir):
        try:
            data = _read_meta(pdir)
        except (ValueError, FileNotFoundError) as e:
            _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
            continue
        doi = str(data.get("doi") or "").strip().lower()
        if data.get("id") == paper_id or (doi and doi == normalized_doi):
            return pdir
    return None
