"""cli/ws.py — workspace paper-subset management commands."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scrinium.log import ui

from .common import _add_filter_args, _add_tag_arg, _emit_json, _resolve_tag_filters, _resolve_top
from .search import _print_search_next_steps, _print_search_result

_log = logging.getLogger(__package__)


def _raise_ws_not_found(ws_root: Path, name: str) -> None:
    """Raise ValueError listing existing workspaces when *name* is unknown."""
    from scrinium import workspace

    msg = f"Workspace not found: {name}; create it first with `scrinium ws init {name}`"
    names = workspace.list_workspaces(ws_root)
    if names:
        msg += f"; existing workspaces: {', '.join(names)}"
    raise ValueError(msg)


def cmd_ws(args: argparse.Namespace, cfg) -> None:
    from scrinium import workspace

    ws_root = cfg._root / "workspace"
    action = args.ws_action

    # Validate workspace-name style arguments in CLI layer to prevent path traversal.
    names_to_check: list[str] = []
    if action in {"init", "add", "remove", "show", "search", "export"}:
        names_to_check.append(args.name)
    elif action == "rename":
        names_to_check.extend([args.old_name, args.new_name])

    for name in names_to_check:
        if not workspace.validate_workspace_name(name):
            ui(f"Invalid workspace name: {name}")
            return

    if action == "init":
        ws_dir = ws_root / args.name
        workspace.create(ws_dir)
        ui(f"Workspace created: {ws_dir}")

    elif action == "add":
        ws_dir = ws_root / args.name
        if not (ws_dir / "papers.json").exists():
            _raise_ws_not_found(ws_root, args.name)

        # Resolve paper_refs from batch flags or positional args
        paper_refs = args.paper_refs or []
        if args.add_all:
            import sqlite3

            index_db_path = Path(cfg.index_db)
            if not index_db_path.exists():
                ui("Index database does not exist; it may not be initialized yet.")
                ui("Run this first: scrinium index")
                return

            try:
                with sqlite3.connect(cfg.index_db) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT id, dir_name FROM papers_registry").fetchall()
            except sqlite3.OperationalError as e:
                _log.debug("Index database query failed: %s", e)
                ui("Index database schema is incomplete or not initialized.")
                ui("Run this first: scrinium index")
                return

            resolved = [{"id": r["id"], "dir_name": r["dir_name"]} for r in rows]
            if not resolved:
                ui("No papers in the main library")
                return
            added = workspace.add(ws_dir, [], cfg.index_db, resolved=resolved)
            ui(f"Added {len(added)} papers to {args.name}")
            for e in added:
                ui(f"  + {e['dir_name']}")
            return
        elif args.add_tag is not None:
            from scrinium.tags import papers_with_tag, resolve_tag, unknown_tag_message

            canonical = resolve_tag(cfg, args.add_tag)
            tagged = papers_with_tag(cfg, args.add_tag)
            if not tagged:
                if canonical is None:
                    raise ValueError(unknown_tag_message(cfg, args.add_tag))
                ui(f"No papers under topic {canonical}")
                return
            paper_refs = [(meta.get("id") or pdir.name) for pdir, meta in tagged]
            ui(f"Topic {canonical or args.add_tag}: found {len(paper_refs)} papers")
        elif args.add_search is not None:
            from scrinium.index import search

            results = search(
                args.add_search,
                cfg.index_db,
                top_k=_resolve_top(args, cfg.search.top_k),
                cfg=cfg,
                year=getattr(args, "year", None),
                journal=getattr(args, "journal", None),
                paper_type=getattr(args, "paper_type", None),
            )
            if not results:
                ui(f'No results found for "{args.add_search}"')
                return
            paper_refs = [r["paper_id"] for r in results]
            ui(f'Search "{args.add_search}": found {len(paper_refs)} papers')

        if not paper_refs:
            ui("No paper references specified")
            return

        unresolved: list[str] = []
        added = workspace.add(ws_dir, paper_refs, cfg.index_db, unresolved=unresolved)
        ui(f"Added {len(added)} papers to {args.name}")
        for e in added:
            ui(f"  + {e['dir_name']}")
        for ref in unresolved:
            ui(f"Could not resolve: {ref}")
        if unresolved and not added:
            raise ValueError(f"Could not resolve any paper references: {', '.join(unresolved)}")

    elif action == "remove":
        ws_dir = ws_root / args.name
        removed = workspace.remove(ws_dir, args.paper_refs, cfg.index_db)
        ui(f"Removed {len(removed)} papers")
        for e in removed:
            ui(f"  - {e['dir_name']}")

    elif action == "list":
        names = workspace.list_workspaces(ws_root)
        if not names:
            ui("No workspaces")
            return
        for name in names:
            ws_dir = ws_root / name
            ids = workspace.read_paper_ids(ws_dir)
            ui(f"  {name} ({len(ids)} papers)")

    elif action == "show":
        ws_dir = ws_root / args.name
        if not (ws_dir / "papers.json").exists():
            _raise_ws_not_found(ws_root, args.name)
        papers = workspace.show(ws_dir, cfg.index_db)
        if getattr(args, "json", False):
            _emit_json(
                {
                    "workspace": args.name,
                    "count": len(papers),
                    "papers": [
                        {"id": p.get("id"), "dir_name": p.get("dir_name"), "added_at": p.get("added_at")}
                        for p in papers
                    ],
                }
            )
            return
        ui(f"Workspace {args.name}: {len(papers)} papers")
        for i, p in enumerate(papers, 1):
            ui(f"  {i:3d}. {p['dir_name']}")

    elif action == "search":
        ws_dir = ws_root / args.name
        pids = workspace.read_paper_ids(ws_dir)
        if not pids:
            ui("Workspace is empty")
            return
        query = " ".join(args.query)
        top_k = _resolve_top(args, cfg.search.top_k)
        tags = _resolve_tag_filters(args, cfg)

        from scrinium.index import search

        results = search(
            query,
            cfg.index_db,
            top_k=top_k,
            cfg=cfg,
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
            paper_ids=pids,
            tags=tags,
        )

        if not results:
            ui(f'No results found for "{query}" in workspace {args.name}')
            return
        ui(f"Found {len(results)} papers in workspace {args.name}:\n")
        for i, r in enumerate(results, 1):
            _print_search_result(i, r)
        _print_search_next_steps(include_ws_add=False)

    elif action == "export":
        ws_dir = ws_root / args.name
        dir_names = workspace.read_dir_names(ws_dir, cfg.index_db)
        if not dir_names:
            ui("Workspace is empty")
            return
        from scrinium.export import export_bibtex

        bib = export_bibtex(
            cfg.papers_dir,
            paper_ids=list(dir_names),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
        if not bib:
            ui("No matching papers found")
            return
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(bib, encoding="utf-8")
            ui(f"Exported to {out} ({bib.count('@')} entries)")
        else:
            print(bib)

    elif action == "rename":
        try:
            workspace.rename(ws_root, args.old_name, args.new_name)
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            ui(str(e))
            return
        ui(f"Workspace renamed: {args.old_name} -> {args.new_name}")


def _add_ws_parser(sub, name: str, help_text: str | None = None) -> None:
    """Register the workspace parser tree under *name* (used for the `ws` alias).

    A ``None`` help means the parser is registered without a help entry,
    which keeps it out of the top-level ``--help`` listing.
    """
    p_ws = sub.add_parser(name, **({"help": help_text} if help_text else {}))
    p_ws.set_defaults(func=cmd_ws)
    p_ws_sub = p_ws.add_subparsers(dest="ws_action", required=True)

    p_ws_init = p_ws_sub.add_parser("init", help="Initialize a workspace")
    p_ws_init.add_argument("name", help="Workspace name (subdirectory under workspace/)")

    p_ws_add = p_ws_sub.add_parser("add", help="Add papers to a workspace")
    p_ws_add.add_argument("name", help="Workspace name")
    p_ws_add.add_argument("paper_refs", nargs="*", help="Paper references (UUID / dir_name / DOI)")
    p_ws_add_batch = p_ws_add.add_mutually_exclusive_group()
    p_ws_add_batch.add_argument(
        "--search", dest="add_search", type=str, default=None, help="Batch add from search results"
    )
    p_ws_add_batch.add_argument(
        "--tag", dest="add_tag", type=str, default=None, help="Batch add by curated tag (topic); supports aliases"
    )
    p_ws_add_batch.add_argument(
        "--all", dest="add_all", action="store_true", default=False, help="Add all papers in the library"
    )
    p_ws_add.add_argument("--top", type=int, default=None, help="Limit the number of results returned by --search")
    _add_filter_args(p_ws_add)

    p_ws_rm = p_ws_sub.add_parser("remove", help="Remove papers from a workspace")
    p_ws_rm.add_argument("name", help="Workspace name")
    p_ws_rm.add_argument("paper_refs", nargs="+", help="Paper references (UUID / dir_name / DOI)")

    p_ws_list = p_ws_sub.add_parser("list", help="List all workspaces")

    p_ws_show = p_ws_sub.add_parser("show", help="Show papers in a workspace")
    p_ws_show.add_argument("name", help="Workspace name")
    p_ws_show.add_argument("--json", action="store_true", help="Output in JSON format (pipe-friendly)")

    p_ws_search = p_ws_sub.add_parser("search", help="Search within a workspace")
    p_ws_search.add_argument("name", help="Workspace name")
    p_ws_search.add_argument("query", nargs="+", help="Search query")
    p_ws_search.add_argument("--top", type=int, default=None, help="Number of results to return")
    _add_filter_args(p_ws_search)
    _add_tag_arg(p_ws_search)

    p_ws_rename = p_ws_sub.add_parser("rename", help="Rename a workspace")
    p_ws_rename.add_argument("old_name", help="Current workspace name")
    p_ws_rename.add_argument("new_name", help="New workspace name")

    p_ws_export = p_ws_sub.add_parser("export", help="Export workspace papers as BibTeX")
    p_ws_export.add_argument("name", help="Workspace name")
    p_ws_export.add_argument("-o", "--output", type=str, default=None, help="Output file path")
    _add_filter_args(p_ws_export)


def register(sub) -> None:
    """Register workspace subcommands (`ws` kept as a hidden legacy alias)."""
    _add_ws_parser(sub, "workspace", "Workspace paper-subset management")
    _add_ws_parser(sub, "ws", None)
