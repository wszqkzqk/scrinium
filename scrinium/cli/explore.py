"""cli/explore.py — OpenAlex exploration library commands."""

from __future__ import annotations

import argparse
import logging
import sys

from scrinium.log import ui

from .common import _resolve_top

_log = logging.getLogger(__package__)


def cmd_explore(args: argparse.Namespace, cfg) -> None:
    action = args.explore_action

    if action == "fetch":
        if args.limit is not None and args.limit <= 0:
            ui(f"--limit must be a positive integer, got: {args.limit}")
            return
        # Determine name: explicit --name, or derive from filters
        name = args.name
        if not name:
            if args.issn:
                name = args.issn.replace("-", "")
            elif args.concept:
                name = f"concept-{args.concept}"
            elif args.author:
                name = f"author-{args.author}"
            elif args.keyword:
                name = args.keyword.replace(" ", "-")[:30]
            else:
                ui("Provide --name or at least one filter")
                return
        from scrinium.explore import fetch_explore

        total = fetch_explore(
            name,
            issn=getattr(args, "issn", None),
            concept=getattr(args, "concept", None),
            topic=getattr(args, "topic_id", None),
            author=getattr(args, "author", None),
            institution=getattr(args, "institution", None),
            keyword=getattr(args, "keyword", None),
            source_type=getattr(args, "source_type", None),
            year_range=getattr(args, "year_range", None),
            min_citations=getattr(args, "min_citations", None),
            oa_type=getattr(args, "oa_type", None),
            sort=getattr(args, "sort", None),
            incremental=getattr(args, "incremental", False),
            limit=getattr(args, "limit", None),
            cfg=cfg,
        )
        ui(f"\nFetched {total} papers")

    elif action == "search":
        query = " ".join(args.query)
        top_k = _resolve_top(args, 10)
        from scrinium.explore import explore_search

        results = explore_search(args.name, query, top_k=top_k, cfg=cfg)
        if not results:
            ui("No results found.")
            return
        for i, r in enumerate(results, 1):
            authors = r.get("authors", [])
            first = authors[0] if authors else ""
            cited = r.get("cited_by_count", 0)
            cite_str = f"  [Citations: {cited}]" if cited else ""
            ui(f"[{i}] [{r.get('year', '?')}] {r.get('title', '')}")
            ui(f"     {first} | {r.get('doi', '')}  (Score: {r['score']:.3f}){cite_str}")
            ui()

    elif action == "list":
        import json as _json

        explore_root = cfg._root / "data" / "explore"
        if not explore_root.exists():
            ui("No explore libraries yet. Run scrinium explore fetch --issn <ISSN> to create one.")
            return
        for d in sorted(explore_root.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = _json.loads(meta_file.read_text("utf-8"))
                except (OSError, _json.JSONDecodeError) as e:
                    ui(f"  {d.name}: failed to read meta.json, skipped ({e})")
                    continue
                query = meta.get("query", {})
                if query:
                    qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                elif meta.get("issn"):
                    qinfo = f"ISSN {meta['issn']}"
                else:
                    qinfo = "?"
                ui(f"  {d.name}: {meta.get('count', '?')} papers ({qinfo}, fetched at {meta.get('fetched_at', '?')})")
        return

    elif action == "info":
        import json as _json

        if not args.name:
            # List all explore libraries
            explore_root = cfg._root / "data" / "explore"
            if not explore_root.exists():
                ui("No explore libraries yet. Run scrinium explore fetch --issn <ISSN> to create one.")
                return
            for d in sorted(explore_root.iterdir()):
                if not d.is_dir():
                    continue
                meta_file = d / "meta.json"
                if meta_file.exists():
                    try:
                        meta = _json.loads(meta_file.read_text("utf-8"))
                    except (OSError, _json.JSONDecodeError) as e:
                        ui(f"  {d.name}: failed to read meta.json, skipped ({e})")
                        continue
                    # Show query info (backward compatible with old ISSN-only format)
                    query = meta.get("query", {})
                    if query:
                        qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                    elif meta.get("issn"):
                        qinfo = f"ISSN {meta['issn']}"
                    else:
                        qinfo = "?"
                    ui(
                        f"  {d.name}: {meta.get('count', '?')} papers ({qinfo}, fetched at {meta.get('fetched_at', '?')})"
                    )
            return
        from scrinium.explore import count_papers

        meta_file = cfg._root / "data" / "explore" / args.name / "meta.json"
        if meta_file.exists():
            try:
                meta = _json.loads(meta_file.read_text("utf-8"))
            except (OSError, _json.JSONDecodeError) as e:
                ui(f"Failed to read {meta_file}: {e}")
                return
            ui(f"Explore library: {args.name}")
            for k, v in meta.items():
                ui(f"  {k}: {v}")
        else:
            n = count_papers(args.name, cfg=cfg)
            ui(f"Explore library {args.name}: {n} papers")

    else:
        _log.error("Unknown action: %s", action)
        sys.exit(1)


def register(sub) -> None:
    """Register explore-domain subcommands."""
    # --- explore ---
    p_explore = sub.add_parser(
        "explore", help="Multi-dimensional literature exploration (OpenAlex fetch + keyword search)"
    )
    p_explore.set_defaults(func=cmd_explore)
    p_explore_sub = p_explore.add_subparsers(dest="explore_action", required=True)

    p_ef = p_explore_sub.add_parser("fetch", help="Fetch papers from OpenAlex (multi-dimensional filters)")
    p_ef.add_argument("--issn", default=None, help="Journal ISSN (e.g. 0022-1120)")
    p_ef.add_argument("--concept", default=None, help="OpenAlex concept ID (e.g. C62520636)")
    p_ef.add_argument("--topic-id", default=None, help="OpenAlex topic ID")
    p_ef.add_argument("--author", default=None, help="OpenAlex author ID")
    p_ef.add_argument("--institution", default=None, help="OpenAlex institution ID")
    p_ef.add_argument("--keyword", default=None, help="Title/abstract keyword search")
    p_ef.add_argument("--source-type", default=None, help="Source type (journal/conference/repository)")
    p_ef.add_argument("--oa-type", default=None, help="Work type (article/review, etc.)")
    p_ef.add_argument("--min-citations", type=int, default=None, help="Minimum citation count")
    p_ef.add_argument(
        "--sort",
        default=None,
        choices=["year_asc", "year_desc", "relevance", "citations"],
        help="Sort order (default: relevance for keyword search, year_asc for filter-only fetch)",
    )
    p_ef.add_argument("--name", help="Explore library name (derived from filters by default)")
    p_ef.add_argument("--year-range", help="Year range filter (e.g. 2020-2025)")
    p_ef.add_argument("--incremental", action="store_true", help="Incremental update (append new papers)")
    p_ef.add_argument(
        "--limit", type=int, default=None, help="Maximum number of papers to fetch (unlimited if omitted)"
    )

    p_es = p_explore_sub.add_parser("search", help="Keyword search in an explore library")
    p_es.add_argument("--name", required=True, help="Explore library name")
    p_es.add_argument("query", nargs="+", help="Search query")
    p_es.add_argument("--top", type=int, default=None, help="Number of results to return")

    p_el = p_explore_sub.add_parser("list", help="List all explore libraries")

    p_ei = p_explore_sub.add_parser("info", help="Show explore library info")
    p_ei.add_argument("--name", default=None, help="Explore library name (list all if omitted)")
