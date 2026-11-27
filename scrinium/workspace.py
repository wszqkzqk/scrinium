"""
workspace.py — Workspace paper subset management
================================================

Each workspace is a ``workspace/<name>/`` directory containing a ``papers.json``
index pointing to papers in ``data/papers/``. Notes, code, drafts, and other
files can be stored freely inside a workspace.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


# ============================================================================
#  Internal helpers
# ============================================================================


def _papers_json(ws_dir: Path) -> Path:
    return ws_dir / "papers.json"


def _read(ws_dir: Path) -> list[dict]:
    pj = _papers_json(ws_dir)
    if not pj.exists():
        return []
    try:
        raw = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupted papers.json, aborting operation: {pj}") from e
    if not isinstance(raw, list):
        raise RuntimeError(f"Invalid papers.json format (expected list, got {type(raw).__name__}): {pj}")
    # Filter out malformed entries missing required "id" field
    valid = [e for e in raw if isinstance(e, dict) and "id" in e]
    if len(valid) < len(raw):
        _log.warning("Skipped %d entries missing 'id' in papers.json (%s)", len(raw) - len(valid), pj)
    return valid


def _write(ws_dir: Path, entries: list[dict]) -> None:
    pj = _papers_json(ws_dir)
    tmp = pj.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(pj)


# ============================================================================
#  Public API
# ============================================================================


def create(ws_dir: Path) -> Path:
    """Create the workspace directory and initialize an empty papers.json.

    Args:
        ws_dir: Workspace directory path.

    Returns:
        Path to papers.json.
    """
    ws_dir.mkdir(parents=True, exist_ok=True)
    pj = _papers_json(ws_dir)
    if not pj.exists():
        _write(ws_dir, [])
    return pj


def add(
    ws_dir: Path,
    paper_refs: list[str],
    db_path: Path,
    *,
    resolved: list[dict] | None = None,
    unresolved: list[str] | None = None,
) -> list[dict]:
    """Add papers to a workspace.

    Resolves papers by UUID, directory name, or DOI, deduplicates them, and
    appends them to papers.json.

    Callers that already hold resolved paper records can pass them via
    *resolved* to skip per-paper ``lookup_paper()`` queries (avoiding O(N)
    database connection overhead).

    Args:
        ws_dir: Workspace directory path.
        paper_refs: Paper references (UUID / directory name / DOI).
            Ignored when *resolved* is not ``None``.
        db_path: Path to index.db, used by lookup_paper.
        resolved: Pre-resolved paper records, each containing ``"id"`` and
            ``"dir_name"``. When provided, lookup_paper queries are skipped.
        unresolved: Optional output list; unresolvable references are appended
            here so the caller can report them individually.

    Returns:
        List of newly added entries.
    """
    entries = _read(ws_dir)
    existing_ids = {e["id"] for e in entries}
    added: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    if resolved is not None:
        required_keys = {"id", "dir_name"}
        for idx, rec in enumerate(resolved):
            if not isinstance(rec, dict):
                raise ValueError(
                    f"resolved[{idx}] must be a dict with keys {sorted(required_keys)}, got {type(rec).__name__!s}"
                )
            missing = required_keys.difference(rec.keys())
            if missing:
                raise ValueError(f"resolved[{idx}] is missing required keys {sorted(missing)}: {rec!r}")
            uid = rec["id"]
            if uid in existing_ids:
                continue
            entry = {"id": uid, "dir_name": rec["dir_name"], "added_at": now}
            entries.append(entry)
            existing_ids.add(uid)
            added.append(entry)
    else:
        from scrinium.index import lookup_paper

        for ref in paper_refs:
            record = lookup_paper(db_path, ref)
            if record is None:
                _log.warning("Unable to resolve paper reference: %s", ref)
                if unresolved is not None:
                    unresolved.append(ref)
                continue
            uid = record["id"]
            if uid in existing_ids:
                _log.debug("Already in workspace, skipping: %s", ref)
                continue
            entry = {"id": uid, "dir_name": record["dir_name"], "added_at": now}
            entries.append(entry)
            existing_ids.add(uid)
            added.append(entry)

    if added:
        _write(ws_dir, entries)
    return added


def remove(ws_dir: Path, paper_refs: list[str], db_path: Path) -> list[dict]:
    """Remove papers from a workspace.

    Args:
        ws_dir: Workspace directory path.
        paper_refs: Paper references (UUID / directory name / DOI).
        db_path: Path to index.db.

    Returns:
        List of removed entries.
    """
    from scrinium.index import lookup_paper

    entries = _read(ws_dir)
    remove_ids: set[str] = set()
    remove_dir_names: set[str] = set()
    entry_ids = {e["id"] for e in entries}
    entry_dir_names = {e.get("dir_name") for e in entries}
    for ref in paper_refs:
        try:
            record = lookup_paper(db_path, ref)
        except sqlite3.Error as exc:
            _log.warning("lookup_paper failed, falling back to workspace-visible identifiers: %s", exc)
            record = None
        if record:
            remove_ids.add(record["id"])
        else:
            # Fall back to exact workspace-visible identifiers when the index is stale
            # or unavailable, so users can still remove items they see in `ws show`.
            if ref in entry_ids:
                remove_ids.add(ref)
            elif ref in entry_dir_names:
                remove_dir_names.add(ref)

    removed = [e for e in entries if e["id"] in remove_ids or e.get("dir_name") in remove_dir_names]
    if removed:
        entries = [e for e in entries if e["id"] not in remove_ids and e.get("dir_name") not in remove_dir_names]
        _write(ws_dir, entries)
    return removed


def list_workspaces(ws_root: Path) -> list[str]:
    """List all workspaces containing a papers.json file.

    Args:
        ws_root: Root workspace/ directory.

    Returns:
        Sorted list of workspace names.
    """
    if not ws_root.is_dir():
        return []
    return sorted(d.name for d in ws_root.iterdir() if d.is_dir() and _papers_json(d).exists())


def validate_workspace_name(name: str) -> bool:
    """Return True if *name* is a safe workspace identifier.

    Rejects empty names, ``.``/``..`` names, leading/trailing whitespace,
    absolute paths, path separators, Windows drive-like names (``:``),
    and any name containing ``..`` to prevent path traversal outside
    ``workspace/``.

    Args:
        name: Candidate workspace name from user input.

    Returns:
        ``True`` when the name is safe for path construction.
    """
    if not name:
        return False
    normalized = name.strip()
    if not normalized:
        return False
    # Reject names with leading/trailing whitespace to avoid ambiguity.
    if normalized != name:
        return False
    if normalized in {".", ".."}:
        return False
    import os

    if os.path.isabs(normalized):
        return False
    # Reject Windows drive-like paths (e.g., C:foo).
    if ":" in normalized:
        return False
    if "/" in normalized or "\\" in normalized:
        return False
    return ".." not in normalized


def show(ws_dir: Path, db_path: Path) -> list[dict]:
    """Return the workspace paper list, refreshing stale dir_name values.

    Args:
        ws_dir: Workspace directory path.
        db_path: Path to index.db.

    Returns:
        Paper entries with up-to-date dir_name values.
    """
    from scrinium.index import lookup_paper

    entries = _read(ws_dir)
    changed = False
    for e in entries:
        record = lookup_paper(db_path, e["id"])
        if record and record["dir_name"] != e.get("dir_name"):
            e["dir_name"] = record["dir_name"]
            changed = True
    if changed:
        _write(ws_dir, entries)
    return entries


def read_paper_ids(ws_dir: Path) -> set[str]:
    """Return the set of UUIDs for all papers in a workspace.

    Args:
        ws_dir: Workspace directory path.

    Returns:
        Set of UUID strings, used for search filtering.
    """
    return {e["id"] for e in _read(ws_dir)}


def rename(ws_root: Path, old_name: str, new_name: str) -> Path:
    """Rename a workspace.

    Args:
        ws_root: Root workspace/ directory.
        old_name: Current workspace name.
        new_name: New workspace name.

    Returns:
        Path to the renamed workspace directory.

    Raises:
        ValueError: Workspace name is invalid (path traversal, absolute path, etc.).
        FileNotFoundError: Source workspace does not exist.
        FileExistsError: Target workspace already exists.
    """
    if not validate_workspace_name(old_name):
        raise ValueError(f"Invalid workspace name: {old_name}")
    if not validate_workspace_name(new_name):
        raise ValueError(f"Invalid workspace name: {new_name}")
    old_dir = ws_root / old_name
    new_dir = ws_root / new_name
    if not old_dir.exists():
        raise FileNotFoundError(f"Workspace not found: {old_name}")
    if not old_dir.is_dir():
        raise ValueError(f"Not a valid workspace directory: {old_name}")
    if not _papers_json(old_dir).exists():
        raise ValueError(f"Missing papers.json; cannot rename workspace: {old_name}")
    if new_dir.exists():
        raise FileExistsError(f"Target workspace already exists: {new_name}")
    old_dir.rename(new_dir)
    return new_dir


def read_dir_names(ws_dir: Path, db_path: Path) -> set[str]:
    """Return the current directory names of all papers in a workspace.

    Looks up the latest dir_name in papers_registry (handles renamed papers).

    Args:
        ws_dir: Workspace directory path.
        db_path: Path to index.db.

    Returns:
        Set of directory name strings, used for export filtering.
    """
    from scrinium.index import lookup_paper

    names: set[str] = set()
    for e in _read(ws_dir):
        record = lookup_paper(db_path, e["id"])
        if record:
            names.add(record["dir_name"])
        elif e.get("dir_name"):
            names.add(e["dir_name"])
    return names
