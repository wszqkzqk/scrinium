"""cli/misc.py — graph/metrics/style/document/toolref/setup/proceedings/citation-check."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from scrinium.log import ui

from .common import (
    _emit_json,
    _resolve_paper,
    _resolve_ws_paper_ids,
    _try_resolve_paper,
)

_log = logging.getLogger(__package__)


def cmd_refs(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import get_references
    from scrinium.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    refs = get_references(paper_uuid, cfg.index_db, paper_ids=pids)
    if not refs:
        ui("This paper has no reference data. Run refetch first to pull references.")
        return

    in_lib = [r for r in refs if r.get("target_id")]
    out_lib = [r for r in refs if not r.get("target_id")]

    scope = f"workspace {args.ws}" if getattr(args, "ws", None) else "library"
    ui(f"References: {len(refs)} total ({len(in_lib)} in {scope}, {len(out_lib)} outside library)\n")

    if in_lib:
        ui("── In Library ──")
        for i, r in enumerate(in_lib, 1):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            author = r.get("first_author") or "?"
            ui(f"[{i}] {display}")
            ui(f"     {author} | {year} | {r.get('title', '?')}")
            ui(f"     DOI: {r['target_doi']}")
            ui()

    if out_lib:
        ui("── Outside Library ──")
        for i, r in enumerate(out_lib, 1):
            ui(f"[{i}] DOI: {r['target_doi']}")
        ui()


def cmd_citing(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import get_citing_papers
    from scrinium.papers import read_meta

    paper_d = _resolve_paper(args.paper_id, cfg)
    meta = read_meta(paper_d)
    paper_uuid = meta.get("id", "")

    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_citing_papers(paper_uuid, cfg.index_db, paper_ids=pids)
    if not results:
        scope = f"in workspace {args.ws}" if getattr(args, "ws", None) else "local"
        ui(f"No {scope} papers found citing this paper.")
        return

    scope = f"workspace {args.ws}" if getattr(args, "ws", None) else "local"
    ui(f"{len(results)} {scope} papers cite this paper:\n")
    for i, r in enumerate(results, 1):
        display = r.get("dir_name") or r["source_id"]
        year = r.get("year") or "?"
        author = r.get("first_author") or "?"
        ui(f"[{i}] {display}")
        ui(f"     {author} | {year} | {r.get('title', '?')}")
        ui()


def cmd_shared_refs(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import get_shared_references
    from scrinium.papers import read_meta

    paper_uuids = []
    for pid in args.paper_ids:
        paper_d = _resolve_paper(pid, cfg)
        meta = read_meta(paper_d)
        paper_uuids.append(meta.get("id", ""))

    min_shared = args.min if args.min is not None else 2
    pids = _resolve_ws_paper_ids(args, cfg)
    results = get_shared_references(paper_uuids, cfg.index_db, min_shared=min_shared, paper_ids=pids)
    if not results:
        ui(f"No references shared by >={min_shared} papers found.")
        return

    ui(f"Shared references (co-cited by >={min_shared} papers): {len(results)} total\n")
    for i, r in enumerate(results, 1):
        count = r["shared_count"]
        if r.get("target_id"):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            ui(f"[{i}] [{count}x] {display}")
            ui(f"     {r.get('title', '?')} | {year}")
            ui(f"     DOI: {r['target_doi']}")
        else:
            ui(f"[{i}] [{count}x] DOI: {r['target_doi']}")
        ui()


def cmd_snowball(args: argparse.Namespace, cfg) -> None:
    from scrinium.papers import read_meta
    from scrinium.snowball import snowball_candidates

    depth = getattr(args, "depth", 1) or 1
    if depth != 1:
        raise ValueError(f"snowball currently only supports --depth 1 (got {depth})")

    # Resolve seeds (dir_name / UUID / DOI). Any unresolvable ref is fatal:
    # seeds are the basis of the whole expansion.
    seed_uuids: list[str] = []
    seed_labels: list[str] = []
    unresolved: list[str] = []
    for ref in args.paper_ids:
        paper_d = _try_resolve_paper(ref, cfg)
        if paper_d is None:
            unresolved.append(ref)
            continue
        meta = read_meta(paper_d)
        uuid = meta.get("id", "")
        if uuid and uuid not in seed_uuids:
            seed_uuids.append(uuid)
            seed_labels.append(paper_d.name)
    if unresolved:
        raise ValueError(f"Unable to resolve seed papers: {', '.join(unresolved)}")

    ws_ids = _resolve_ws_paper_ids(args, cfg)
    ranked = snowball_candidates(seed_uuids, cfg.index_db, ws_ids=ws_ids)
    if not ranked:
        ui("No candidate papers found: insufficient citation graph data.")
        ui("Run scrinium refetch <paper-id> on the seeds to pull references, then scrinium index to rebuild the index.")
        return

    top = args.top if args.top is not None else 20
    show = ranked[:top]

    # Attach citation counts from meta.json (papers_registry has no such column).
    for cand in show:
        cc: dict = {}
        try:
            cc = read_meta(cfg.papers_dir / cand["dir_name"]).get("citation_count") or {}
        except (ValueError, FileNotFoundError):
            pass
        cand["citation_count"] = max((v for v in cc.values() if isinstance(v, int | float)), default=0)

    if getattr(args, "json", False):
        _emit_json(
            {
                "seeds": [{"id": u, "dir_name": n} for u, n in zip(seed_uuids, seed_labels)],
                "depth": depth,
                "total": len(ranked),
                "count": len(show),
                "results": show,
            }
        )
        return

    scope = f"in workspace {args.ws}" if getattr(args, "ws", None) else "in library"
    ui(f"Seed papers: {', '.join(seed_labels)}")
    ui(f"Found {len(ranked)} snowball candidates {scope} (score = 2*shared refs + 1*cites seeds + 1*cited by seeds)\n")
    for i, c in enumerate(show, 1):
        rel = "+".join(c["relations"])
        ui(f"[{i}] [score {c['score']}] {c['dir_name'] or c['id']}")
        ui(f"     {c.get('title') or '?'} | {c.get('year') or '?'} | Citations {c['citation_count']}")
        ui(
            f"     relations {rel} | shared refs {c['shared']} | "
            f"cites seeds {c['cites_seeds']} | cited by seeds {c['cited_by_seeds']}"
        )
        ui()


def cmd_toolref(args: argparse.Namespace, cfg) -> None:
    from scrinium.toolref import (
        TOOL_REGISTRY,
        toolref_fetch,
        toolref_list,
        toolref_search,
        toolref_show,
        toolref_use,
    )

    try:
        action = args.toolref_action

        if action == "fetch":
            count = toolref_fetch(args.tool, version=args.version, force=args.force, cfg=cfg)
            if count == 0:
                ui("No pages indexed. Check the version number or documentation source.")

        elif action == "show":
            results = toolref_show(args.tool, *args.path, cfg=cfg)
            if not results:
                ui(f"No match found: {args.tool} {' '.join(args.path)}")
                ui(f"Try searching: scrinium toolref search {args.tool} {' '.join(args.path)}")
                return
            for r in results:
                ui(f"\n{'=' * 60}")
                ui(r["page_name"])
                if r.get("section"):
                    ui(f"   Section: {r['section']}  |  Program: {r.get('program', '')}")
                if r.get("synopsis"):
                    ui(f"   {r['synopsis']}")
                ui(f"{'─' * 60}")
                ui(r.get("content", "(no content)"))

        elif action == "search":
            query = " ".join(args.query)
            results = toolref_search(
                args.tool,
                query,
                top_k=args.top,
                program=args.program,
                section=args.section,
                cfg=cfg,
            )
            if not results:
                ui(f"No results: {query}")
                return
            ui(f"Found {len(results)} results:\n")
            for i, r in enumerate(results, 1):
                synopsis = r.get("synopsis", "")[:80]
                ui(f"  {i:2d}. [{r['page_name']}] {synopsis}")

        elif action == "list":
            entries = toolref_list(args.tool, cfg=cfg)
            if not entries:
                tools = ", ".join(TOOL_REGISTRY.keys())
                ui(f"No documentation fetched yet. Supported tools: {tools}")
                ui("Fetch with `scrinium toolref fetch <tool> --version <ver>`")
                return
            current_tool = ""
            for e in entries:
                if e["tool"] != current_tool:
                    current_tool = e["tool"]
                    ui(f"\n{e['display_name']}:")
                marker = " (current)" if e["is_current"] else ""
                completeness = ""
                unit = "pages" if e.get("source_type") == "manifest" else "entries"
                if e.get("source_type") == "manifest" and e.get("expected_pages"):
                    completeness = f" [{e['page_count']}/{e['expected_pages']} indexed"
                    failed_pages = e.get("failed_pages")
                    if failed_pages:
                        completeness += f", {failed_pages} failed"
                    completeness += "]"
                ui(f"  {e['version']}{marker} — {e['page_count']} {unit}{completeness}")

        elif action == "use":
            toolref_use(args.tool, args.version, cfg=cfg)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _log.error("%s", e)
        sys.exit(1)


def cmd_document(args: argparse.Namespace, cfg) -> None:
    action = getattr(args, "doc_action", None)
    if action == "inspect":
        _cmd_document_inspect(args, cfg)
    elif action == "editable":
        _cmd_document_editable(args, cfg)
    elif action == "diff":
        _cmd_document_diff(args, cfg)
    else:
        _log.error("Specify a document subcommand: inspect / editable / diff")
        sys.exit(1)


def _cmd_document_inspect(args: argparse.Namespace, cfg) -> None:
    from scrinium.document import inspect

    file_path = Path(args.file)
    if not file_path.exists():
        _log.error("File does not exist: %s", file_path)
        sys.exit(1)
    fmt = getattr(args, "format", None)
    try:
        result = inspect(file_path, fmt=fmt)
    except (ValueError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)
    print(result)


def _load_editable_module():
    from scrinium.presentation import editable

    return editable


def _cmd_document_editable(args: argparse.Namespace, cfg) -> None:
    source = Path(args.source)
    target = Path(args.output) if args.output else source.with_name(f"{source.stem}_editable.pptx")
    try:
        editable = _load_editable_module()
        result = editable.prepare_editable(source, target, force=args.force)
    except (OSError, ValueError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)
    ui(f"Created editable copy: {result}")


def _text_preview(value, limit=70):
    if value is None:
        return "(none)"
    preview = str(value).replace("\n", "\\n")
    return preview if len(preview) <= limit else f"{preview[:limit]}…"


def _geometry_preview(geometry):
    left = geometry["left"] / 914400
    top = geometry["top"] / 914400
    width = geometry["width"] / 914400
    height = geometry["height"] / 914400
    return f'({left:.2f}", {top:.2f}") {width:.2f}" × {height:.2f}"'


def _print_part_changes(label, changes, limit=12):
    added = len(changes["added"])
    removed = len(changes["removed"])
    modified = len(changes["modified"])
    total = added + removed + modified
    if not total:
        return
    ui(f"{label}: added {added} | removed {removed} | modified {modified}")
    shown = 0
    for action, caption in (("added", "+"), ("removed", "-"), ("modified", "~")):
        for change in changes[action]:
            if shown == limit:
                ui(f"  ... and {total - shown} more parts (use --json to see all)")
                return
            ui(f"  {caption} {change['part']} [{change['kind']}]")
            shown += 1


def _print_pptx_diff(result) -> None:
    ui(f"=== PPTX diff: {Path(result['baseline']).name} -> {Path(result['edited']).name} ===")
    if not result["has_changes"]:
        ui("No content differences found.")
        _print_part_changes("Metadata (not counted as content diff)", result["metadata_changes"])
        return

    for slide in result["slides_added"]:
        ui(f"Slide {slide['index']}: added slide (slide_id={slide['slide_id']})")
    for slide in result["slides_removed"]:
        ui(f"Original slide {slide['index']}: removed slide (slide_id={slide['slide_id']})")
    if result["slide_order_change"] is not None:
        count = len(result["slide_order_change"]["before"])
        ui(f"Relative order of {count} shared slides changed; use --json to see full before/after order")

    aspect_names = {
        "font": "font",
        "paragraph": "paragraph",
        "crop": "image crop",
        "rotation": "rotation",
        "shape": "shape properties",
        "other": "other properties",
    }
    for slide in result["slides_modified"]:
        ui(f"Slide {slide['edited_slide']} (was slide {slide['baseline_slide']}):")
        for shape in slide["shapes_added"]:
            ui(f"  + Shape [{shape['name']}] (shape_id={shape['shape_id']})")
        for shape in slide["shapes_removed"]:
            ui(f"  - Shape [{shape['name']}] (shape_id={shape['shape_id']})")
        for change in slide["text_changes"]:
            ui(f"  Text [{change['name']}]: '{_text_preview(change['before'])}' -> '{_text_preview(change['after'])}'")
        for change in slide["geometry_changes"]:
            ui(
                f"  Position/Size [{change['name']}]: "
                f"{_geometry_preview(change['before'])} -> {_geometry_preview(change['after'])}"
            )
        for change in slide["image_changes"]:
            before = (change["before"] or {}).get("sha256", "(none)")[:12]
            after = (change["after"] or {}).get("sha256", "(none)")[:12]
            ui(f"  Image [{change['name']}]: {before} -> {after}")
        for change in slide["property_changes"]:
            aspects = ", ".join(aspect_names.get(aspect, aspect) for aspect in change["aspects"])
            ui(f"  Properties [{change['name']}]: {aspects}")
        if slide["notes_change"] is not None:
            change = slide["notes_change"]
            ui(f"  Notes: '{_text_preview(change['before'])}' -> '{_text_preview(change['after'])}'")

    summary = result["summary"]
    ui(
        "Summary: "
        f"slides added/removed/modified {summary['slides_added']}/{summary['slides_removed']}/{summary['slides_modified']} | "
        f"slide order {summary['slide_order_changes']} | "
        f"shapes added/removed {summary['shapes_added']}/{summary['shapes_removed']} | "
        f"text {summary['text_changes']} | position/size {summary['geometry_changes']} | "
        f"images {summary['image_changes']} | properties {summary['property_changes']} | notes {summary['notes_changes']}"
    )
    _print_part_changes("PPTX package integrity check", result["package_changes"])
    _print_part_changes("Metadata (not counted as content diff)", result["metadata_changes"])

    if result["slides_added"] or result["slides_removed"] or result["slide_order_change"] is not None:
        ui("Tip: when slide structure changes, also check slide order and Notes mapping in the generation script.")
    package_changes = result["package_changes"]
    if any(
        change["part"].startswith("ppt/media/")
        for action in ("added", "removed", "modified")
        for change in package_changes[action]
    ):
        ui(
            "Tip: when media content changes, verify original images, audio/video, "
            "or embedded assets referenced by the generation script."
        )
    ui(
        "Tip: semantic diffs locate edits; package-level diffs (theme, master, relationships, unparsed XML) "
        "need manual review. No automatic merge is performed."
    )


def _cmd_document_diff(args: argparse.Namespace, cfg) -> None:
    try:
        editable = _load_editable_module()
        result = editable.compare_pptx(Path(args.baseline), Path(args.edited))
    except (OSError, ValueError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)
    if args.json:
        _emit_json(result)
        return
    _print_pptx_diff(result)


def cmd_style(args: argparse.Namespace, cfg) -> None:
    """Dispatcher for `scrinium style` subcommands."""
    sub = getattr(args, "style_sub", None)
    if sub == "list":
        _cmd_style_list(args, cfg)
    elif sub == "show":
        _cmd_style_show(args, cfg)
    else:
        _log.error("Specify a style subcommand: list / show")
        sys.exit(1)


def _cmd_style_list(args: argparse.Namespace, cfg) -> None:
    from scrinium.citation_styles import list_styles

    styles = list_styles(cfg)
    ui(f"Available citation styles ({len(styles)} total):")
    for s in styles:
        tag = f"[{s['source']}]"
        desc = f" — {s['description']}" if s.get("description") else ""
        print(f"  {s['name']:<28} {tag:<10}{desc}")
    print()
    ui("Usage: scrinium export markdown --all --style <name>")


def _cmd_style_show(args: argparse.Namespace, cfg) -> None:
    from scrinium.citation_styles import show_style

    try:
        code = show_style(args.name, cfg)
        print(code)
    except (FileNotFoundError, ValueError) as e:
        _log.error("%s", e)
        sys.exit(1)


def cmd_proceedings(args: argparse.Namespace, cfg) -> None:
    if args.proceedings_action == "build-clean-candidates":
        from scrinium.ingest.proceedings import build_proceedings_clean_candidates

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        if not proceeding_dir.exists():
            ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return

        candidates_path = build_proceedings_clean_candidates(proceeding_dir)
        ui(f"Generated proceedings clean candidates: {candidates_path}")
        ui(
            "Waiting for an agent to review clean_candidates.json and produce clean_plan.json "
            "before running the cleanup."
        )
        return

    if args.proceedings_action == "apply-split":
        from scrinium.ingest.proceedings import apply_proceedings_split_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        split_plan = Path(args.split_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return
        if not split_plan.exists():
            ui(f"Split plan does not exist: {split_plan}")
            return

        apply_proceedings_split_plan(proceeding_dir, split_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"Applied proceedings split plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} papers)")
        return

    if args.proceedings_action == "apply-clean":
        from scrinium.ingest.proceedings import apply_proceedings_clean_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        clean_plan = Path(args.clean_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"Proceedings directory does not exist: {proceeding_dir}")
            return
        if not clean_plan.exists():
            ui(f"Clean plan does not exist: {clean_plan}")
            return

        apply_proceedings_clean_plan(proceeding_dir, clean_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"Applied proceedings clean plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} papers)")
        return

    ui(f"Unknown proceedings subcommand: {args.proceedings_action}")


def cmd_insights(args: argparse.Namespace, cfg) -> None:
    from datetime import datetime, timedelta, timezone

    from scrinium import insights
    from scrinium.metrics import get_store

    store = get_store()
    if not store:
        ui("Not enough data (metrics not initialized)")
        return

    days = args.days
    if days <= 0:
        ui("--days must be a positive integer")
        return
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    # Fetch search events
    search_events = store.query(category="search", since=since_iso, limit=10000)
    # Fetch read events
    read_events = store.query(category="read", since=since_iso, limit=10000)

    if not search_events and not read_events:
        ui(f"Not enough data (no search or read events in the past {days} days)")
        return

    ui(f"=== Research Activity Insights (past {days} days) ===\n")

    ui("[Top 10 Hot Search Keywords]")
    hot_keywords = insights.extract_hot_keywords(search_events, top_k=10)
    if hot_keywords:
        for word, cnt in hot_keywords:
            bar = "█" * min(cnt, 20)
            ui(f"  {word:<20s} {bar} ({cnt})")
    else:
        ui("  No search events")
    ui()

    ui("[Top 10 Most-Read Papers]")
    most_read = insights.aggregate_most_read_titles(read_events, cfg.papers_dir, top_k=10)
    if most_read:
        for rank, (title_key, cnt) in enumerate(most_read, 1):
            label = title_key[:60]
            ui(f"  {rank:2d}. [{cnt}x] {label}")
    else:
        ui("  No read events")
    ui()

    # 3. Weekly read-count trend (ASCII bar chart)
    ui("[Weekly Read Trend]")
    if read_events:
        week_counts = insights.build_weekly_read_trend(read_events)
        if week_counts:
            max_count = max(cnt for _, cnt in week_counts) or 1
            for week, cnt in week_counts:
                bar_len = round(cnt / max_count * 20)
                bar = "█" * bar_len
                ui(f"  {week}  {bar} {cnt}")
        else:
            ui("  Not enough data")
    else:
        ui("  No read events")
    ui()

    # 4. Active workspaces — list workspaces with paper counts
    ui("[Active Workspaces]")
    try:
        ws_root = cfg._root / "workspace"
        workspaces = insights.list_workspace_counts(ws_root)
        if workspaces:
            for ws_name, count in workspaces:
                ui(f"  {ws_name:<30s} {count} papers")
        else:
            ui("  No workspaces")
    except Exception:
        ui("  Workspace info unavailable")
    ui()


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    from scrinium.metrics import get_store

    store = get_store()
    if not store:
        _log.error("Metrics database is not initialized yet.")
        return

    rows = store.query(
        category=args.category,
        since=args.since,
        limit=args.last,
    )
    if not rows:
        ui("No records.")
        return

    # Header
    if args.category == "llm":
        # Historical llm events (pre-removal) still render with token columns.
        ui(f"{'time':<20s} {'purpose':<24s} {'prompt':>8s} {'compl':>8s} {'total':>8s} {'time':>7s} {'status':<5s}")
        ui("-" * 82)
        total_in = total_out = 0
        for r in reversed(rows):
            ts = r["timestamp"][:19].replace("T", " ")
            name = r["name"][:24]
            t_in = r["tokens_in"] or 0
            t_out = r["tokens_out"] or 0
            dur = r["duration_s"] or 0
            total_in += t_in
            total_out += t_out
            ui(f"{ts:<20s} {name:<24s} {t_in:>8,d} {t_out:>8,d} {t_in + t_out:>8,d} {dur:>6.1f}s {r['status']:<5s}")
        ui("-" * 82)
        ui(f"{'total':<20s} {'':<24s} {total_in:>8,d} {total_out:>8,d} {total_in + total_out:>8,d}")
    else:
        ui(f"{'time':<20s} {'name':<32s} {'time':>7s} {'status':<5s}")
        ui("-" * 66)
        for r in reversed(rows):
            ts = r["timestamp"][:19].replace("T", " ")
            name = r["name"][:32]
            dur = r["duration_s"] or 0
            ui(f"{ts:<20s} {name:<32s} {dur:>6.1f}s {r['status']:<5s}")


def cmd_setup(args: argparse.Namespace, cfg) -> None:
    from scrinium.setup import format_check_results, run_check, run_wizard

    action = getattr(args, "setup_action", None)
    if action == "check":
        results = run_check(cfg)
        ui(format_check_results(results))
    else:
        run_wizard(cfg)


def cmd_citation_check(args: argparse.Namespace, cfg) -> None:
    from scrinium.citation_check import check_citations, extract_citations

    # Read input text
    if args.file:
        p = Path(args.file)
        if not p.exists():
            _log.error("File does not exist: %s", p)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        ui("Input text is empty.")
        return

    citations = extract_citations(text)
    if not citations:
        ui("No citations found in the text.")
        return

    ui(f"Extracted {len(citations)} citations; verifying...\n")

    try:
        paper_ids = _resolve_ws_paper_ids(args, cfg)
    except ValueError as e:
        ui(str(e))
        return

    results = check_citations(
        citations,
        cfg.index_db,
        paper_ids=paper_ids,
    )

    # Count by status (internal codes)
    counts = {"VERIFIED": 0, "NOT_IN_LIBRARY": 0, "AMBIGUOUS": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    status_labels = {
        "VERIFIED": "Verified",
        "NOT_IN_LIBRARY": "Not in library",
        "AMBIGUOUS": "Ambiguous",
    }

    for r in results:
        status_icon = {"VERIFIED": "✓", "NOT_IN_LIBRARY": "✗", "AMBIGUOUS": "?"}.get(r["status"], " ")
        status_text = status_labels.get(r["status"], r["status"])
        ui(f"  [{status_icon}] {status_text:<14s}  {r['raw']}  ({r['author']}, {r['year']})")
        if r["matches"]:
            for m in r["matches"][:3]:
                display_id = m.get("dir_name") or m.get("paper_id", "?")
                ui(f"       -> {display_id}")
                ui(f"         {m.get('title', '?')}")

    ui()
    ui(
        f"Verification summary: verified {counts['VERIFIED']} / "
        f"ambiguous {counts['AMBIGUOUS']} / "
        f"not in library {counts['NOT_IN_LIBRARY']}"
    )


def _add_parser_with_optional_help(sub, name: str, help_text: str | None):
    """add_parser where ``help_text=None`` hides the entry from ``--help``."""
    return sub.add_parser(name, **({"help": help_text} if help_text else {}))


def _add_refs_parser(sub, name: str, help_text: str | None = None) -> None:
    p_refs = _add_parser_with_optional_help(sub, name, help_text)
    p_refs.set_defaults(func=cmd_refs)
    p_refs.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_refs.add_argument("--ws", type=str, default=None, help="Restrict to a workspace")


def _add_citing_parser(sub, name: str, help_text: str | None = None) -> None:
    p_citing = _add_parser_with_optional_help(sub, name, help_text)
    p_citing.set_defaults(func=cmd_citing)
    p_citing.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_citing.add_argument("--ws", type=str, default=None, help="Restrict to a workspace")


def _add_shared_refs_parser(sub, name: str, help_text: str | None = None) -> None:
    p_sr = _add_parser_with_optional_help(sub, name, help_text)
    p_sr.set_defaults(func=cmd_shared_refs)
    p_sr.add_argument("paper_ids", nargs="+", help="Paper IDs (at least 2)")
    p_sr.add_argument("--min", type=int, default=None, help="Minimum co-citation count (default: 2)")
    p_sr.add_argument("--ws", type=str, default=None, help="Restrict to a workspace")


def _add_style_parser(sub, name: str, help_text: str | None = None) -> None:
    """Register the citation-styles parser tree under *name* (used for the `style` alias)."""
    p_style = _add_parser_with_optional_help(sub, name, help_text)
    p_style.set_defaults(func=cmd_style)
    p_style_sub = p_style.add_subparsers(dest="style_sub", required=True)

    p_style_list = p_style_sub.add_parser("list", help="List all available citation styles")
    del p_style_list  # no extra args needed

    p_style_show = p_style_sub.add_parser("show", help="Show the formatting function code of a citation style")
    p_style_show.add_argument("name", help="Style name, e.g. jcp / apa / vancouver")


def register(sub) -> None:
    """Register misc-domain subcommands."""
    # --- references / cited-by / shared-references (legacy aliases hidden) ---
    _add_refs_parser(sub, "references", "Show a paper's reference list")
    _add_refs_parser(sub, "refs", None)
    _add_citing_parser(sub, "cited-by", "Show which local papers cite this paper")
    _add_citing_parser(sub, "citing", None)
    _add_shared_refs_parser(sub, "shared-references", "Shared-reference (co-citation) analysis")
    _add_shared_refs_parser(sub, "shared-refs", None)

    # --- snowball ---
    p_sb = sub.add_parser(
        "snowball", help="Citation snowballing: expand from seed papers along the citation graph and rank"
    )
    p_sb.set_defaults(func=cmd_snowball)
    p_sb.add_argument("paper_ids", nargs="+", help="Seed paper IDs (dir_name / UUID / DOI; multiple allowed)")
    p_sb.add_argument("--depth", type=int, default=1, help="Expansion depth (currently only 1 is supported)")
    p_sb.add_argument("--top", type=int, default=None, help="Number of results to return (default: 20)")
    p_sb.add_argument("--ws", type=str, default=None, help="Restrict to a workspace")
    p_sb.add_argument("--json", action="store_true", help="Output in JSON format")

    # --- citation-check ---
    p_cc = sub.add_parser("citation-check", help="Verify whether citations in text exist in the local knowledge base")
    p_cc.set_defaults(func=cmd_citation_check)
    p_cc.add_argument("file", nargs="?", default=None, help="File path to check (reads from stdin if omitted)")
    p_cc.add_argument("--ws", type=str, default=None, help="Verify within the specified workspace")

    # --- setup ---
    p_setup = sub.add_parser(
        "setup",
        help="Environment check and setup wizard",
        description="Start the interactive setup wizard by default; use the `check` subcommand to run environment diagnostics only.",
    )
    p_setup.set_defaults(func=cmd_setup)
    p_setup_sub = p_setup.add_subparsers(dest="setup_action")
    p_setup_sub.add_parser("check", help="Check environment status")

    # --- proceedings ---
    p_proc = sub.add_parser("proceedings", help="Proceedings helper commands (apply-split, etc.)")
    p_proc.set_defaults(func=cmd_proceedings)
    p_proc_sub = p_proc.add_subparsers(dest="proceedings_action", required=True)

    p_proc_apply = p_proc_sub.add_parser("apply-split", help="Apply split_plan.json to prepared proceedings")
    p_proc_apply.add_argument("proceeding_dir", help="Path to the proceedings directory")
    p_proc_apply.add_argument("split_plan", help="Path to split_plan.json")

    p_proc_clean_candidates = p_proc_sub.add_parser(
        "build-clean-candidates", help="Generate clean_candidates.json for split proceedings"
    )
    p_proc_clean_candidates.add_argument("proceeding_dir", help="Path to the proceedings directory")

    p_proc_apply_clean = p_proc_sub.add_parser("apply-clean", help="Apply clean_plan.json to split proceedings")
    p_proc_apply_clean.add_argument("proceeding_dir", help="Path to the proceedings directory")
    p_proc_apply_clean.add_argument("clean_plan", help="Path to clean_plan.json")

    # --- insights ---
    p_insights = sub.add_parser(
        "insights", help="Research activity insights: hot search keywords, most-read papers, etc."
    )
    p_insights.set_defaults(func=cmd_insights)
    p_insights.add_argument("--days", type=int, default=30, help="Analyze data from the past N days (default: 30)")

    # --- metrics ---
    p_metrics = sub.add_parser("metrics", help="View runtime metrics (step/API call timings)")
    p_metrics.set_defaults(func=cmd_metrics)
    p_metrics.add_argument("--last", type=int, default=20, help="Show the last N records")
    p_metrics.add_argument(
        "--category",
        default="step",
        help="Event category (step/api/search/read/llm, default: step; llm is only for viewing historical events)",
    )
    p_metrics.add_argument("--since", default=None, help="Start time (ISO format, e.g. 2026-03-01)")

    # --- citation-styles (primary name; `style` kept as a hidden legacy alias) ---
    _add_style_parser(sub, "citation-styles", "Manage citation styles (list / view custom styles)")
    _add_style_parser(sub, "style", None)

    # --- document ---
    p_doc = sub.add_parser("document", help="Office document tools (inspect / editable / diff)")
    p_doc.set_defaults(func=cmd_document)
    p_doc_sub = p_doc.add_subparsers(dest="doc_action", required=True)

    p_doc_inspect = p_doc_sub.add_parser("inspect", help="Inspect Office document structure (DOCX / PPTX / XLSX)")
    p_doc_inspect.add_argument("file", help="File path")
    p_doc_inspect.add_argument(
        "--format",
        choices=["docx", "pptx", "xlsx"],
        default=None,
        help="File format (inferred from extension by default)",
    )

    p_doc_editable = p_doc_sub.add_parser("editable", help="Create an editable PPTX copy for the user")
    p_doc_editable.add_argument("source", help="Source PPTX file path")
    p_doc_editable.add_argument("--output", default=None, help="Output path (default: <source_stem>_editable.pptx)")
    p_doc_editable.add_argument("--force", action="store_true", help="Overwrite an existing editable copy")

    p_doc_diff = p_doc_sub.add_parser("diff", help="Compare a baseline PPTX with an edited copy")
    p_doc_diff.add_argument("baseline", help="Baseline PPTX file path")
    p_doc_diff.add_argument("edited", help="Edited PPTX file path")
    p_doc_diff.add_argument("--json", action="store_true", help="Output in JSON format")

    # --- toolref ---
    p_tr = sub.add_parser("toolref", help="Scientific computing tool documentation lookup (fetch/show/search/list/use)")
    p_tr.set_defaults(func=cmd_toolref)
    p_tr_sub = p_tr.add_subparsers(dest="toolref_action", required=True)

    p_trf = p_tr_sub.add_parser("fetch", help="Fetch tool documentation (git clone -> extract -> index)")
    p_trf.add_argument("tool", help="Tool name (qe/lammps/gromacs/openfoam/bioinformatics)")
    p_trf.add_argument("--version", default=None, help="Version number (e.g. 7.5, 22Jul2025_update3)")
    p_trf.add_argument("--force", action="store_true", help="Force re-fetch and overwrite local cache")

    p_trs = p_tr_sub.add_parser("show", help="Show documentation for a specific command/parameter")
    p_trs.add_argument("tool", help="Tool name")
    p_trs.add_argument("path", nargs="+", help="Lookup path (e.g. pw ecutwfc)")

    p_trq = p_tr_sub.add_parser("search", help="Full-text search in tool documentation")
    p_trq.add_argument("tool", help="Tool name")
    p_trq.add_argument("query", nargs="+", help="Search keywords")
    p_trq.add_argument("--top", type=int, default=20, help="Number of results to return (default: 20)")
    p_trq.add_argument("--program", default=None, help="Filter by program (e.g. pw.x)")
    p_trq.add_argument("--section", default=None, help="Filter by namelist/section (e.g. SYSTEM)")

    p_trl = p_tr_sub.add_parser("list", help="List available tool documentation and versions")
    p_trl.add_argument("tool", nargs="?", default=None, help="Tool name (list all if omitted)")

    p_tru = p_tr_sub.add_parser("use", help="Switch the active version of tool documentation")
    p_tru.add_argument("tool", help="Tool name")
    p_tru.add_argument("version", help="Target version number")
