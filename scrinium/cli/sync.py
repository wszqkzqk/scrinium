"""sync — cross-device sync of data/, workspace/, and personal preferences/.

Subcommands:
    scrinium sync push <target>          push data/ + workspace/ + preferences/ to a target (SSH or local path)
    scrinium sync pull <target>          pull data/ + workspace/ + preferences/ from a target
    scrinium sync status <target>        show files that would change (dry-run)
    scrinium sync export <file.tar.gz>   pack data/ + workspace/ + preferences/ into an archive (offline transfer)
    scrinium sync import <file.tar.gz>   import from an archive
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from scrinium.log import ui

# Items excluded from sync (transient staging, runtime logs, caches, trash).
_EXCLUDES = (
    "inbox",
    "inbox-doc",
    "inbox-patent",
    "inbox-proceedings",
    "inbox-thesis",
    "*.log",
    "scholaraio.log*",
    "metrics.db*",
    ".coverage",
    "__pycache__",
    ".DS_Store",
    "trash",
    "topic_model",
)


def register(sub) -> None:
    """Register sync-domain subcommands."""
    p_sync = sub.add_parser(
        "sync",
        help="Sync knowledge base, workspaces, and personal preferences across devices (data/, workspace/, preferences/)",
    )
    p_sync.set_defaults(func=cmd_sync)
    p_sync_sub = p_sync.add_subparsers(dest="sync_action", required=True)

    for name, help_text in (
        ("push", "Push data/ + workspace/ + preferences/ to a target (user@host:path or local path)"),
        ("pull", "Pull data/ + workspace/ + preferences/ from a target to local"),
        ("status", "Show files that would change (dry-run; no actual changes)"),
    ):
        p = p_sync_sub.add_parser(name, help=help_text)
        p.add_argument("target", help="Target: user@host:remote/path (SSH) or /local/path (local path)")
        p.add_argument(
            "--mirror",
            action="store_true",
            help="Mirror mode: delete files on target that do not exist on source (requires --yes)",
        )
        p.add_argument("--yes", action="store_true", help="Confirm deletions when using --mirror")
        p.set_defaults(sync_action=name)

    p_exp = p_sync_sub.add_parser(
        "export", help="Pack data/ + workspace/ + preferences/ into an archive (offline transfer)"
    )
    p_exp.add_argument("file", help="Output archive path (e.g. sync_backup.tar.gz)")
    p_exp.set_defaults(sync_action="export")

    p_imp = p_sync_sub.add_parser("import", help="Import data/ + workspace/ + preferences/ from an archive")
    p_imp.add_argument("file", help="Archive path (e.g. sync_backup.tar.gz)")
    p_imp.set_defaults(sync_action="import")


def cmd_sync(args: argparse.Namespace, cfg) -> None:
    action = args.sync_action
    if action in {"push", "pull", "status"}:
        _sync_dirs(args, cfg, action)
    elif action == "export":
        _export(args, cfg)
    elif action == "import":
        _import(args, cfg)


def _sources(cfg) -> list[Path]:
    return [cfg.papers_dir.parent, cfg.workspace_dir, cfg._root / "preferences"]


def _sync_dirs(args: argparse.Namespace, cfg, action: str) -> None:
    rsync = shutil.which("rsync")
    if rsync is None:
        ui(
            "Error: rsync not found. Install rsync, or use `scrinium sync export` / `scrinium sync import` for offline transfer"
        )
        sys.exit(1)

    mirror = getattr(args, "mirror", False)
    yes = getattr(args, "yes", False)
    target = args.target.rstrip("/")

    if mirror and not yes:
        ui(
            "Mirror mode (--mirror) will delete files on the target that do not exist on the source. "
            "Running a dry-run preview first:"
        )
        for src in _sources(cfg):
            if src.exists():
                _run_rsync(
                    rsync,
                    *(_pull_paths(src, target, cfg) if action == "pull" else _push_paths(src, target)),
                    dry_run=True,
                    mirror=True,
                )
        ui("If the deletions above look correct, re-run with --yes to perform the actual mirror sync")
        return

    for src in _sources(cfg):
        if not src.exists():
            continue
        if action == "pull":
            src_str, dst_str = _pull_paths(src, target, cfg)
        else:
            src_str, dst_str = _push_paths(src, target)
        ret = _run_rsync(rsync, src_str, dst_str, dry_run=(action == "status"), mirror=mirror)
        if ret != 0:
            ui(f"Error: rsync failed ({src_str} -> {dst_str}), exit code {ret}")
            sys.exit(ret)
    if action == "status":
        ui("Dry-run complete (no changes made)")


def _push_paths(src: Path, target: str) -> tuple[str, str]:
    # rsync -az src dst/  ->  dst/src.name/ with contents of src/
    return str(src), f"{target}/"


def _pull_paths(src: Path, target: str, cfg) -> tuple[str, str]:
    # rsync -az target/src.name dst/  ->  dst/src.name/ with contents of target/src.name/
    return f"{target}/{src.name}", f"{cfg._root}/"


def _run_rsync(rsync: str, src_str: str, dst_str: str, *, dry_run: bool, mirror: bool) -> int:
    cmd = [rsync, "-avz", "--update"]
    for pat in _EXCLUDES:
        cmd += ["--exclude", pat]
    if mirror:
        cmd.append("--delete")
    if dry_run:
        cmd.append("-n")
    cmd += [src_str, dst_str]
    return subprocess.call(cmd)


def _export(args: argparse.Namespace, cfg) -> None:
    out = args.file
    count = 0
    with tarfile.open(out, "w:gz") as tar:
        for src in _sources(cfg):
            if not src.exists():
                continue
            for path in sorted(src.rglob("*")):
                if _excluded(path):
                    continue
                tar.add(path, arcname=path.relative_to(cfg._root))
                count += 1
    ui(f"Exported {count} files to {out}")


def _import(args: argparse.Namespace, cfg) -> None:
    with tarfile.open(args.file, "r:gz") as tar:
        tar.extractall(cfg._root)
    ui(f"Imported from {args.file} into {cfg._root}")


def _excluded(path: Path) -> bool:
    for pat in _EXCLUDES:
        if "*" in pat:
            if path.match(pat):
                return True
        elif pat in path.parts:
            return True
    return False
