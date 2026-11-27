"""cli/si.py — SI (Supporting Information) scan, auto-fetch, status, and attach."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from scrinium.log import ui

from .common import _emit_json, _resolve_paper

_log = logging.getLogger(__package__)

#: Rate-limit delay (seconds) between papers during batch fetch, matching pipeline api_delay
_FETCH_DELAY = 2.0

#: Handoff hints to the agent per fetch_status
_STATUS_HINTS = {
    "not_found": "No SI URL found by rule chain; try a manual web search",
    "blocked": "Blocked by publisher (403/429); try alternative channels (PMC / author homepage / preprint mirror)",
    "mismatch": "Downloaded file failed verification; manually inspect the downloaded file",
    "paywalled": "SI appears paywalled; check whether an OA mirror exists",
    "error": "Network/conversion error; safe to retry",
}


def _iter_states(cfg) -> list[dict]:
    from scrinium.papers import iter_paper_dirs
    from scrinium.si import paper_si_state

    return [paper_si_state(pdir) for pdir in iter_paper_dirs(cfg.papers_dir)]


def _reindex(cfg) -> None:
    from scrinium.index import build_index

    build_index(cfg.papers_dir, cfg.index_db)


# ============================================================================
#  Commands
# ============================================================================


def cmd_si_scan(args: argparse.Namespace, cfg) -> None:
    """Scan the library and mark papers whose full text mentions SI (writes meta.json si.mentioned)."""
    from scrinium.papers import iter_paper_dirs, read_meta, write_meta
    from scrinium.si import paper_si_state, si_mentioned_in_text

    states = []
    n_mentioned = n_present = 0
    for pdir in iter_paper_dirs(cfg.papers_dir):
        state = paper_si_state(pdir)
        states.append(state)
        if state.get("error"):
            continue
        # refresh the cached flag when it was never computed
        try:
            meta = read_meta(pdir)
        except (ValueError, FileNotFoundError):
            continue
        si = meta.get("si") or {}
        if si.get("mentioned") is None:
            md = pdir / "paper.md"
            mentioned = si_mentioned_in_text(md.read_text(encoding="utf-8", errors="replace")) if md.exists() else False
            si["mentioned"] = mentioned
            meta["si"] = si
            write_meta(pdir, meta)
            state["mentioned"] = mentioned
        n_mentioned += bool(state["mentioned"])
        n_present += bool(state["present"])

    if getattr(args, "json", False):
        _emit_json({"total": len(states), "mentioned": n_mentioned, "present": n_present, "papers": states})
        return

    ui(f"Scan complete: {len(states)} papers | SI mentioned in text: {n_mentioned} | SI attached: {n_present}")
    missing = [s for s in states if s.get("mentioned") and not s.get("present")]
    if missing:
        ui(f"\nMentions SI but not attached: {len(missing)} papers")
        for s in missing[:20]:
            status = f" [{s['fetch_status']}]" if s.get("fetch_status") else ""
            ui(f"  {s['paper_id']}{status}")
        if len(missing) > 20:
            ui(f"  ... and {len(missing) - 20} more")
        ui(
            "\nhint: run `scrinium si fetch --missing` to fetch automatically; "
            "dispatch a subagent following the si skill workflow for failures"
        )


def cmd_si_fetch(args: argparse.Namespace, cfg) -> None:
    """Auto-fetch SI: resolve candidates via rule chain -> download -> verify -> attach."""
    from scrinium.papers import iter_paper_dirs
    from scrinium.si import TERMINAL_STATUSES, fetch_si_for_paper, paper_si_state

    convert = not getattr(args, "no_convert", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)

    if args.paper_id:
        targets = [_resolve_paper(args.paper_id, cfg)]
    else:
        targets = []
        for pdir in iter_paper_dirs(cfg.papers_dir):
            state = paper_si_state(pdir)
            if state.get("error") or not state["mentioned"] or state["present"]:
                continue
            if not force and state["fetch_status"] in TERMINAL_STATUSES:
                continue
            targets.append(pdir)
        if not targets:
            ui("No papers need SI fetch (marked as mentioned by scan and not yet attached).")
            ui(
                "hint: run `scrinium si scan` first to refresh flags, or specify a paper with `scrinium si fetch <paper-id>`"
            )
            return

    ui(f"To fetch: {len(targets)} papers")
    stats: dict[str, int] = {}
    failed: list[tuple[str, str]] = []
    for idx, pdir in enumerate(targets):
        try:
            status = fetch_si_for_paper(pdir, cfg, convert=convert, dry_run=dry_run, force=force)
        except Exception:
            _log.exception("si fetch failed for %s", pdir.name)
            status = "error"
        stats[status] = stats.get(status, 0) + 1
        ui(f"  [{idx + 1}/{len(targets)}] {pdir.name} -> {status}")
        if status not in ("ok", "skip", "dry_run"):
            failed.append((pdir.name, status))
        if not dry_run and idx < len(targets) - 1:
            time.sleep(_FETCH_DELAY)

    ui("\nFetch complete: " + " | ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
    if stats.get("ok") and not dry_run:
        _reindex(cfg)
        ui("Index updated (SI content is now searchable)")
    if failed:
        ui("\nFailed items (consider dispatching a subagent following the si skill workflow):")
        for name, status in failed:
            hint = _STATUS_HINTS.get(status, "")
            ui(f"  [{status}] {name}" + (f" — {hint}" if hint else ""))
        ui(
            "hint: after locating the SI file manually, attach it with `scrinium attach-si <paper-id> <file>`; "
            "if confirmed unavailable, set si.fetch_status to exhausted in meta.json"
        )


def cmd_si_status(args: argparse.Namespace, cfg) -> None:
    """SI queue overview: counts by status + list awaiting agent takeover."""
    states = _iter_states(cfg)
    total = len(states)
    mentioned = sum(1 for s in states if s.get("mentioned"))
    present = sum(1 for s in states if s.get("present"))
    n_files = sum(s.get("n_files", 0) for s in states)
    by_status: dict[str, list[str]] = {}
    for s in states:
        if s.get("mentioned") and not s.get("present"):
            by_status.setdefault(s.get("fetch_status") or "pending", []).append(s["paper_id"])

    if getattr(args, "json", False):
        _emit_json(
            {
                "total": total,
                "mentioned": mentioned,
                "present": present,
                "si_files": n_files,
                "missing_by_status": {k: len(v) for k, v in by_status.items()},
                "missing": by_status,
            }
        )
        return

    ui(f"Total papers: {total} | SI mentioned: {mentioned} | Attached: {present} ({n_files} files)")
    if not by_status:
        ui("Queue empty: all papers mentioning SI are attached or marked with a terminal status.")
        return
    ui("\nUnattached queue:")
    for status, ids in sorted(by_status.items()):
        ui(f"  [{status}] {len(ids)} papers")
        for pid in ids[:10]:
            ui(f"    {pid}")
        if len(ids) > 10:
            ui(f"    ... and {len(ids) - 10} more")
    pending = [s for s in ("pending", "not_found", "blocked", "mismatch") if s in by_status]
    if pending:
        ui(
            "\nhint: `scrinium si fetch --missing` retries pending/error items; "
            "consider dispatching a subagent for not_found/blocked/mismatch items"
        )


def cmd_attach_si(args: argparse.Namespace, cfg) -> None:
    """Attach a local file as SI to a paper (unified entry point for agent takeover)."""
    from scrinium.si import attach_si

    paper_d = _resolve_paper(args.paper_id, cfg)
    src = Path(args.file)
    if not src.exists():
        ui(f"Error: file not found: {src}")
        sys.exit(1)

    res = attach_si(
        paper_d,
        src,
        cfg,
        source_url=getattr(args, "source_url", "") or "",
        attached_by="agent",
        convert=not getattr(args, "no_convert", False),
        verify=not getattr(args, "no_verify", False),
        dry_run=getattr(args, "dry_run", False),
    )
    ui(res["message"])
    if not res["ok"]:
        sys.exit(1)
    if res["status"] != "dry_run":
        _reindex(cfg)
        ui("Index updated")


# ============================================================================
#  Parser registration
# ============================================================================


def register(sub) -> None:
    """Register SI subcommands."""
    p_si = sub.add_parser("si", help="Scan, fetch, and attach Supporting Information")
    p_si.set_defaults(func=cmd_si_status)
    si_sub = p_si.add_subparsers(dest="si_action")

    p_scan = si_sub.add_parser("scan", help="Scan the library and mark papers whose text mentions SI")
    p_scan.set_defaults(func=cmd_si_scan)
    p_scan.add_argument("--json", action="store_true", help="Output in JSON format")

    p_fetch = si_sub.add_parser("fetch", help="Auto-fetch SI (rule chain -> download -> verify -> attach)")
    p_fetch.set_defaults(func=cmd_si_fetch)
    p_fetch.add_argument("paper_id", nargs="?", default=None, help="Paper ID (omit with --missing for batch mode)")
    p_fetch.add_argument(
        "--missing", action="store_true", help="Batch process papers that mention SI but have none attached"
    )
    p_fetch.add_argument(
        "--force", action="store_true", help="Ignore existing files and terminal statuses; force retry"
    )
    p_fetch.add_argument(
        "--no-convert", action="store_true", help="Keep original files only; do not convert to Markdown"
    )
    p_fetch.add_argument("--dry-run", action="store_true", help="Preview mode")

    p_status = si_sub.add_parser("status", help="SI queue overview and items awaiting takeover")
    p_status.set_defaults(func=cmd_si_status)
    p_status.add_argument("--json", action="store_true", help="Output in JSON format")

    p_attach = sub.add_parser("attach-si", help="Attach a local file as SI to a paper (verify -> convert -> ingest)")
    p_attach.set_defaults(func=cmd_attach_si)
    p_attach.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_attach.add_argument("file", help="Path to the SI file (PDF/Office/data file)")
    p_attach.add_argument("--source-url", dest="source_url", default="", help="Source URL of the SI (for audit trail)")
    p_attach.add_argument(
        "--no-convert", action="store_true", help="Keep original files only; do not convert to Markdown"
    )
    p_attach.add_argument(
        "--no-verify", action="store_true", help="Skip verification against the main text (use with caution)"
    )
    p_attach.add_argument("--dry-run", action="store_true", help="Preview mode")
