"""sync — cross-device sync of the knowledge base (data/) and workspaces (workspace/).

Subcommands:
    scrinium sync push <target>          push data/ + workspace/ to a target (SSH or local path)
    scrinium sync pull <target>          pull data/ + workspace/ from a target
    scrinium sync status <target>        show files that would change (dry-run)
    scrinium sync export <file.tar.gz>   pack data/ + workspace/ into an archive (offline transfer)
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
    p_sync = sub.add_parser("sync", help="跨设备同步知识库（data/）与工作区（workspace/）")
    p_sync.set_defaults(func=cmd_sync)
    p_sync_sub = p_sync.add_subparsers(dest="sync_action", required=True)

    for name, help_text in (
        ("push", "推送 data/ + workspace/ 到目标（user@host:path 或本地路径）"),
        ("pull", "从目标拉取 data/ + workspace/ 到本地"),
        ("status", "显示将要变更的文件（dry-run，不实际变更）"),
    ):
        p = p_sync_sub.add_parser(name, help=help_text)
        p.add_argument("target", help="目标：user@host:remote/path（SSH）或 /local/path（本地路径）")
        p.add_argument("--mirror", action="store_true", help="镜像模式：删除目标端在源端不存在的文件（需配合 --yes 确认）")
        p.add_argument("--yes", action="store_true", help="配合 --mirror 确认删除操作")
        p.set_defaults(sync_action=name)

    p_exp = p_sync_sub.add_parser("export", help="打包 data/ + workspace/ 为归档文件（离线传输）")
    p_exp.add_argument("file", help="输出归档文件路径（如 sync_backup.tar.gz）")
    p_exp.set_defaults(sync_action="export")

    p_imp = p_sync_sub.add_parser("import", help="从归档文件导入 data/ + workspace/")
    p_imp.add_argument("file", help="归档文件路径（如 sync_backup.tar.gz）")
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
    return [cfg.papers_dir.parent, cfg.workspace_dir]


def _sync_dirs(args: argparse.Namespace, cfg, action: str) -> None:
    rsync = shutil.which("rsync")
    if rsync is None:
        ui("错误：未找到 rsync。请安装 rsync，或改用 `scrinium sync export` / `scrinium sync import` 离线传输")
        sys.exit(1)

    mirror = getattr(args, "mirror", False)
    yes = getattr(args, "yes", False)
    target = args.target.rstrip("/")

    if mirror and not yes:
        ui("镜像模式（--mirror）将删除目标端在源端不存在的文件。先做一次 dry-run 预览：")
        for src in _sources(cfg):
            if src.exists():
                _run_rsync(rsync, *(_pull_paths(src, target, cfg) if action == "pull" else _push_paths(src, target)), dry_run=True, mirror=True)
        ui("如确认上述删除无误，请重新运行并加 --yes 执行实际镜像同步")
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
            ui(f"错误：rsync 失败（{src_str} -> {dst_str}），退出码 {ret}")
            sys.exit(ret)
    if action == "status":
        ui("以上为 dry-run（未实际变更）")


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
    ui(f"已导出 {count} 个文件到 {out}")


def _import(args: argparse.Namespace, cfg) -> None:
    with tarfile.open(args.file, "r:gz") as tar:
        tar.extractall(cfg._root)
    ui(f"已从 {args.file} 导入到 {cfg._root}")


def _excluded(path: Path) -> bool:
    for pat in _EXCLUDES:
        if "*" in pat:
            if path.match(pat):
                return True
        elif pat in path.parts:
            return True
    return False
