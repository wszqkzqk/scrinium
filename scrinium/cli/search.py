"""cli/search.py — index/search/show commands and federated search."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scrinium.log import ui

from .common import (
    _add_filter_args,
    _add_tag_arg,
    _emit_json,
    _record_search_metrics,
    _resolve_paper,
    _resolve_tag_filters,
    _resolve_top,
    _search_result_json,
)

_log = logging.getLogger(__package__)


def cmd_index(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import build_index

    papers_dir = cfg.papers_dir
    db_path = cfg.index_db

    if not papers_dir.exists():
        _log.error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Rebuilding index" if args.rebuild else "Building index"
    ui(f"{action}: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=args.rebuild)
    ui(f"Done: indexed {count} papers.")
    ui("Next step: run `scrinium search <keywords>` to start searching.")


def cmd_search_author(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import search_author

    query = " ".join(args.query)
    try:
        results = search_author(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui(f'No papers found for author "{query}".')
        return

    ui(f'Found {len(results)} papers by author ("{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def cmd_search(args: argparse.Namespace, cfg) -> None:
    # --scope delegates to federated search; keyword is the only retrieval mode.
    if getattr(args, "scope", None):
        cmd_fsearch(args, cfg)
        return

    import time

    from scrinium.index import search
    from scrinium.metrics import get_store

    query = " ".join(args.query)
    tags = _resolve_tag_filters(args, cfg)
    t0 = time.monotonic()
    try:
        results = search(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
            tags=tags,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "search", query, results, elapsed, args)

    if getattr(args, "json", False):
        _emit_json({"query": query, "count": len(results), "results": [_search_result_json(r) for r in results]})
        return

    if not results:
        ui(f'No results found for "{query}".')
        return

    ui(f'Keyword search found {len(results)} papers ("{query}"):\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def _show_json(args: argparse.Namespace, l1: dict, notes: str | None, json_path: Path, md_path: Path) -> None:
    """Emit ``show --json`` output: L1 metadata plus the fields of the requested layer."""
    from scrinium.loader import load_l2, load_l3, load_l4

    payload: dict = {
        "id": l1["paper_id"],
        "dir_name": l1.get("dir_name", ""),
        "title": l1.get("title") or "",
        "authors": l1.get("authors") or [],
        "year": l1.get("year"),
        "journal": l1.get("journal") or "",
        "doi": l1.get("doi") or "",
        "paper_type": l1.get("paper_type") or "",
        "citation_count": l1.get("citation_count") or {},
        "layer": args.layer,
    }
    if notes:
        payload["notes"] = notes

    if args.layer == 2:
        payload["abstract"] = load_l2(json_path)
    elif args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            from scrinium.ingest.pipeline import HINT_L3_MISSING

            _log.error("This paper has no conclusion yet")
            ui(f"hint: {HINT_L3_MISSING}")
            sys.exit(1)
        payload["conclusion"] = conclusion
    elif args.layer == 4:
        if not md_path.exists():
            _log.error("paper.md not found: %s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scrinium.loader import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                _log.error("Invalid language code '%s'", lang)
                sys.exit(1)
            payload["lang"] = lang
        payload["content"] = load_l4(md_path, lang=lang)

    _emit_json(payload)


def cmd_show(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.pipeline import HINT_L3_MISSING
    from scrinium.loader import append_notes, load_l1, load_l2, load_l3, load_l4, load_notes, load_si
    from scrinium.metrics import get_store

    paper_d = _resolve_paper(args.paper_id, cfg)
    json_path = paper_d / "meta.json"
    md_path = paper_d / "paper.md"

    # Handle --append-notes (append, then continue to show content)
    if getattr(args, "append_notes", None):
        notes_text = str(args.append_notes).strip()
        if not notes_text:
            ui("Warning: --append-notes is empty; ignored.")
        else:
            try:
                append_notes(paper_d, notes_text)
            except (UnicodeDecodeError, OSError) as e:
                _log.error("Failed to append notes: %s", e)
                ui(f"Failed to append notes to {paper_d.name}/notes.md: {e}")
            else:
                ui(f"Appended notes to {paper_d.name}/notes.md")

    l1 = load_l1(json_path)
    l1["dir_name"] = paper_d.name

    # Curated tags are shown in the L1 header when present
    from scrinium.tags import paper_tags

    l1["tags"] = paper_tags(paper_d)

    # Load existing agent notes (T2 layer) if available
    try:
        notes = load_notes(paper_d)
    except (UnicodeDecodeError, OSError) as e:
        _log.warning("Failed to read notes.md: %s", e)
        notes = None

    store = get_store()

    def _record_read() -> None:
        if store:
            try:
                store.record(
                    category="read",
                    name=paper_d.name,  # use dir_name so insights can find the paper
                    detail={
                        "layer": args.layer,
                        "title": l1.get("title", ""),
                        "doi": l1.get("doi", ""),
                    },
                )
            except Exception as _e:
                _log.debug("metrics record failed: %s", _e)

    if getattr(args, "json", False):
        _show_json(args, l1, notes, json_path, md_path)
        _record_read()
        return

    _print_header(l1)

    if notes:
        ui("\n--- Agent Notes (notes.md) ---\n")
        ui(notes)
        ui("\n--- End of Notes ---\n")

    if getattr(args, "si", False):
        si_docs = load_si(paper_d)
        if not si_docs:
            ui("\nThis paper has no SI yet (si/ is empty).")
            ui(
                "hint: run `scrinium si fetch <paper-id>` to fetch automatically, "
                "or download manually and attach with `scrinium attach-si <paper-id> <file>`"
            )
        else:
            for name, text in si_docs:
                ui(f"\n--- SI: {name} ---\n")
                ui(text)
        _record_read()
        return

    if args.layer == 1:
        _record_read()
        return

    if args.layer == 2:
        abstract = load_l2(json_path)
        ui("\n--- Abstract ---\n")
        ui(abstract)
        _record_read()
        return

    if args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log.error("This paper has no conclusion yet")
            ui(f"hint: {HINT_L3_MISSING}")
            sys.exit(1)
        ui("\n--- Conclusion ---\n")
        ui(conclusion)
        _record_read()
        return

    if args.layer == 4:
        if not md_path.exists():
            _log.error("paper.md not found: %s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scrinium.loader import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                ui(f"Error: invalid language code '{lang}'")
                sys.exit(1)
            translated_path = md_path.parent / f"paper_{lang}.md"
            if translated_path.exists():
                ui(f"\n--- Full Text ({lang}) ---\n")
            else:
                ui(f"\n--- Full Text (original; paper_{lang}.md not found) ---\n")
        else:
            ui("\n--- Full Text ---\n")
        ui(load_l4(md_path, lang=lang))
        _record_read()
        return


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import top_cited

    try:
        results = top_cited(
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if getattr(args, "json", False):
        _emit_json({"count": len(results), "results": [_search_result_json(r) for r in results]})
        return

    if not results:
        ui("No citation data in the index. Run scrinium refetch --all first.")
        return

    ui(f"Top {len(results)} papers by citation count:\n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def _search_arxiv(query: str, top_k: int) -> list[dict]:
    """Call arXiv Atom API, return simplified paper dicts."""
    from scrinium.sources.arxiv import search_arxiv

    return search_arxiv(query, top_k)


def _query_dois_for_set(cfg, doi_set: list[str]) -> set[str]:
    """Return the subset of doi_set that exists in the main library (case-insensitive).

    Only queries the specific DOIs requested, so this is O(len(doi_set)) regardless
    of library size. Returns an empty set if the index DB is missing or on any error.
    """
    import sqlite3

    if not doi_set or not Path(cfg.index_db).exists():
        return set()
    try:
        normalized = [d.lower() for d in doi_set]
        placeholders = ",".join("?" * len(normalized))
        with sqlite3.connect(str(cfg.index_db)) as conn:
            rows = conn.execute(
                f"SELECT doi FROM papers_registry WHERE LOWER(doi) IN ({placeholders})",
                normalized,
            ).fetchall()
        return {r[0].lower() for r in rows}
    except Exception:
        return set()


def _query_arxiv_ids_for_set(cfg, arxiv_id_set: list[str]) -> set[str]:
    """Return the subset of normalized arXiv IDs that exists in the main library."""
    from scrinium.papers import iter_paper_dirs, read_meta
    from scrinium.sources.arxiv import normalize_arxiv_ref

    if not arxiv_id_set or not Path(cfg.papers_dir).exists():
        return set()

    wanted: set[str] = set()
    for arxiv_id in arxiv_id_set:
        normalized = normalize_arxiv_ref(arxiv_id)
        if normalized:
            wanted.add(normalized)
    if not wanted:
        return set()

    found: set[str] = set()
    try:
        for paper_dir in iter_paper_dirs(Path(cfg.papers_dir)):
            try:
                meta = read_meta(paper_dir)
            except Exception:
                continue
            arxiv_id = meta.get("arxiv_id") or (meta.get("ids") or {}).get("arxiv", "")
            normalized = normalize_arxiv_ref(arxiv_id)
            if normalized and normalized in wanted:
                found.add(normalized)
    except Exception:
        return set()
    return found


def cmd_fsearch(args: argparse.Namespace, cfg) -> None:
    query = " ".join(args.query)
    top_k = _resolve_top(args, 10)
    scope_str = args.scope or "main"
    scopes = [s.strip() for s in scope_str.split(",") if s.strip()] or ["main"]

    ui(f'Federated search: "{query}"  scope={scope_str}\n')

    for scope in scopes:
        if scope == "main":
            ui("── [Main Library] ──")
            if not cfg.index_db.exists():
                ui("  Main library index does not exist; run scrinium index first")
                results = []
            else:
                from scrinium.index import search

                try:
                    results = search(query, cfg.index_db, top_k=top_k, cfg=cfg)
                except Exception as e:
                    ui(f"  Main library search failed: {e}")
                    results = []
            if not results:
                ui("  No results")
            else:
                for i, r in enumerate(results, 1):
                    _print_search_result(i, r)
            ui()

        elif scope.startswith("explore:"):
            explore_name = scope[len("explore:") :]
            from scrinium.explore import validate_explore_name

            if explore_name != "*" and not validate_explore_name(explore_name):
                ui(
                    f"  Invalid explore library name '{explore_name}': "
                    "must be non-empty and contain no path separators or '..'"
                )
                ui()
                continue
            if explore_name == "*":
                from scrinium.explore import list_explore_libs

                names = list_explore_libs(cfg)
                if not names:
                    ui("── [explore: *] ──")
                    ui("  No explore libraries yet; run scrinium explore fetch --name <NAME> first")
                    ui()
            else:
                names = [explore_name]

            for name in names:
                ui(f"── [explore: {name}] ──")
                from scrinium.explore import explore_db_path, explore_search

                db = explore_db_path(name, cfg)
                if not db.exists():
                    ui(f"  Explore library {name} does not exist or is not indexed (explore.db missing)")
                    ui()
                    continue
                try:
                    results = explore_search(name, query, top_k=top_k, cfg=cfg)
                except Exception as e:
                    ui(f"  Search failed: {e}")
                    ui()
                    continue
                if not results:
                    ui("  No results")
                else:
                    for i, r in enumerate(results, 1):
                        authors = r.get("authors", [])
                        first = authors[0] if authors else "?"
                        score = r.get("score", 0.0)
                        ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
                        ui(f"       {first} | Score: {score:.3f}")
                        ui()

        elif scope == "arxiv":
            ui("── [arXiv] ──")
            arxiv_results = _search_arxiv(query, top_k)
            if not arxiv_results:
                ui("  arXiv unavailable or no results")
            else:
                # Only query the library for DOIs that actually appear in results
                arxiv_dois = [r["doi"].lower() for r in arxiv_results if r.get("doi")]
                arxiv_ids = [r.get("arxiv_id", "") for r in arxiv_results if r.get("arxiv_id")]
                in_lib_dois = _query_dois_for_set(cfg, arxiv_dois)
                in_lib_arxiv_ids = _query_arxiv_ids_for_set(cfg, arxiv_ids)
                for i, r in enumerate(arxiv_results, 1):
                    from scrinium.sources.arxiv import normalize_arxiv_ref

                    authors = r.get("authors", [])
                    first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
                    doi = r.get("doi", "")
                    arxiv_id = r.get("arxiv_id", "")
                    normalized_arxiv_id = normalize_arxiv_ref(arxiv_id)
                    in_lib = bool(
                        (doi and doi.lower() in in_lib_dois)
                        or (normalized_arxiv_id and normalized_arxiv_id in in_lib_arxiv_ids)
                    )
                    status = "  [In Library]" if in_lib else ""
                    ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}{status}")
                    ui(f"       {first} | arxiv:{arxiv_id}" + (f" | doi:{doi}" if doi else ""))
                    ui()

        elif scope == "proceedings":
            ui("── [Proceedings] ──")
            from scrinium.index import search_proceedings
            from scrinium.proceedings import proceedings_db_path

            db = proceedings_db_path(cfg._root)
            if not db.exists():
                ui("  Proceedings index does not exist; import proceedings first")
                results = []
            else:
                try:
                    results = search_proceedings(query, db, top_k=top_k)
                except Exception as e:
                    ui(f"  Proceedings search failed: {e}")
                    results = []
            if not results:
                ui("  No results")
            else:
                for i, r in enumerate(results, 1):
                    extra = f"proceedings:{r.get('proceeding_title', r.get('proceeding_dir', '?'))}"
                    _print_search_result(i, r, extra=extra)
            ui()

        else:
            ui(f"  Unknown scope: {scope}; supported: main / proceedings / explore:NAME / explore:* / arxiv")


def _print_search_result(idx: int, r: dict, extra: str = "") -> None:
    authors = r.get("authors") or ""
    author_display = authors.split(",")[0].strip() + (" et al." if "," in authors else "")
    cite = r.get("citation_count") or ""
    cite_suffix = f"  [Citations: {cite}]" if cite else ""
    extra_suffix = f"  ({extra})" if extra else ""
    # Prefer dir_name for display, fall back to paper_id (UUID)
    display_id = r.get("dir_name") or r["paper_id"]
    ui(f"[{idx}] {display_id}{extra_suffix}")
    ui(f"     {author_display} | {r.get('year', '?')} | {r.get('journal', '?')}{cite_suffix}")
    ui(f"     {r['title']}")
    ui()


def _print_search_next_steps(include_ws_add: bool = True) -> None:
    ui("Next steps: run `scrinium show <paper-id> --layer 2/3/4` to view the abstract, conclusion, or full text.")
    if include_ws_add:
        ui("Or run `scrinium workspace add <workspace-name> <paper-id>` to add papers of interest to a workspace.")


def _format_citations(cc: dict) -> str:
    if not cc:
        return ""
    parts = []
    for src in ("semantic_scholar", "openalex", "crossref"):
        if src in cc:
            label = {"semantic_scholar": "S2", "openalex": "OA", "crossref": "CR"}[src]
            parts.append(f"{label}:{cc[src]}")
    return " | ".join(parts)


def _print_header(l1: dict) -> None:
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"
    ui(f"Paper ID  : {l1['paper_id']}")
    if l1.get("dir_name"):
        ui(f"Dir Name  : {l1['dir_name']}")
    ui(f"Title     : {l1['title']}")
    ui(f"Authors   : {author_str}")
    ui(f"Year      : {l1.get('year') or '?'}  |  Journal: {l1.get('journal') or '?'}")
    if l1.get("doi"):
        ui(f"DOI       : {l1['doi']}")
    ids = l1.get("ids") or {}
    if ids.get("patent_publication_number"):
        ui(f"Pub No.   : {ids['patent_publication_number']}")
    if l1.get("paper_type"):
        ui(f"Type      : {l1['paper_type']}")
    tags = l1.get("tags") or []
    if tags:
        ui(f"Tags      : {', '.join(tags)}")
    si_files = [f for f in ((l1.get("si") or {}).get("files") or []) if isinstance(f, dict)]
    if si_files:
        names = ", ".join(f.get("name", "?") for f in si_files[:3])
        ui(f"SI        : {len(si_files)} files ({names}{'...' if len(si_files) > 3 else ''})")
    cite_str = _format_citations(l1.get("citation_count") or {})
    if cite_str:
        ui(f"Citations : {cite_str}")
    if ids.get("semantic_scholar_url"):
        ui(f"S2        : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        ui(f"OpenAlex  : {ids['openalex_url']}")


def register(sub) -> None:
    """Register search-domain subcommands."""
    # --- index ---
    p_index = sub.add_parser("index", help="Build the FTS5 search index")
    p_index.set_defaults(func=cmd_index)
    p_index.add_argument("--rebuild", action="store_true", help="Clear and rebuild from scratch")

    # --- search ---
    p_search = sub.add_parser(
        "search",
        help="Keyword search papers (--scope for cross-library federated search)",
    )
    p_search.set_defaults(func=cmd_search)
    p_search.add_argument("query", nargs="+", help="Search keywords")
    p_search.add_argument(
        "--scope",
        type=str,
        default=None,
        help="Run federated search (comma-separated): main / proceedings / explore:NAME / explore:* / arxiv",
    )
    p_search.add_argument(
        "--top", type=int, default=None, help="Return at most N results (defaults to config search.top_k)"
    )
    p_search.add_argument("--json", action="store_true", help="Output results in JSON format (pipe-friendly)")
    _add_filter_args(p_search)
    _add_tag_arg(p_search)

    # --- search-author ---
    p_sa = sub.add_parser("search-author", help="Search by author name")
    p_sa.set_defaults(func=cmd_search_author)
    p_sa.add_argument("query", nargs="+", help="Author name (fuzzy match)")
    p_sa.add_argument(
        "--top", type=int, default=None, help="Return at most N results (defaults to config search.top_k)"
    )
    _add_filter_args(p_sa)

    # --- show ---
    p_show = sub.add_parser("show", help="View paper content")
    p_show.set_defaults(func=cmd_show)
    p_show.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_show.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="Detail layer: 1=metadata, 2=abstract, 3=conclusion, 4=full text (default: 2)",
    )
    p_show.add_argument("--lang", type=str, default=None, help="Load a translated version (e.g. zh); L4 only")
    p_show.add_argument("--si", action="store_true", help="View converted SI (Supporting Information) text")
    p_show.add_argument("--json", action="store_true", help="Output in JSON format (pipe-friendly)")
    p_show.add_argument(
        "--append-notes",
        type=str,
        default=None,
        metavar="TEXT",
        help="Append text to the paper's notes.md (T2 layer, reused across sessions)",
    )

    # --- top-cited ---
    p_tc = sub.add_parser("top-cited", help="List papers sorted by citation count")
    p_tc.set_defaults(func=cmd_top_cited)
    p_tc.add_argument(
        "--top", type=int, default=None, help="Return at most N results (defaults to config search.top_k)"
    )
    p_tc.add_argument("--json", action="store_true", help="Output results in JSON format (pipe-friendly)")
    _add_filter_args(p_tc)

    # --- fsearch (legacy alias of `search --scope`; no help => hidden) ---
    p_fsearch = sub.add_parser("fsearch")
    p_fsearch.set_defaults(func=cmd_fsearch)
    p_fsearch.add_argument("query", nargs="+", help="Search keywords")
    p_fsearch.add_argument(
        "--scope",
        type=str,
        default="main",
        help="Search scope (comma-separated): main / proceedings / explore:NAME / explore:* / arxiv (default: main)",
    )
    p_fsearch.add_argument("--top", type=int, default=None, help="Max results per source (default: 10)")
