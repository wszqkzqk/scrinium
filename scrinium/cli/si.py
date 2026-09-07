"""cli/si.py — SI（Supporting Information）扫描、自动获取、状态与挂接。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from scrinium.log import ui

from .common import _emit_json, _resolve_paper

_log = logging.getLogger(__package__)

#: 批量 fetch 时论文之间的限速间隔（秒），与 pipeline 的 api_delay 一致
_FETCH_DELAY = 2.0

#: 各 fetch_status 给 agent 的接管提示
_STATUS_HINTS = {
    "not_found": "规则链未找到 SI 地址，值得 web search 人工寻找",
    "blocked": "出版社拦截（403/429），建议换渠道（PMC/作者主页/预印本镜像）",
    "mismatch": "下载件验证未过，需人工核对下载到的文件",
    "paywalled": "SI 疑似付费墙，可判断是否有 OA 镜像",
    "error": "网络/转换错误，可直接重试",
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
    """扫描全库：标记正文引用了 SI 的论文（写 meta.json 的 si.mentioned）。"""
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

    ui(f"扫描完成: 共 {len(states)} 篇 | 正文引用 SI: {n_mentioned} 篇 | 已挂接 SI: {n_present} 篇")
    missing = [s for s in states if s.get("mentioned") and not s.get("present")]
    if missing:
        ui(f"\n提到 SI 但未挂接: {len(missing)} 篇")
        for s in missing[:20]:
            status = f" [{s['fetch_status']}]" if s.get("fetch_status") else ""
            ui(f"  {s['paper_id']}{status}")
        if len(missing) > 20:
            ui(f"  ... 以及另外 {len(missing) - 20} 篇")
        ui("\nhint: 运行 `scrinium si fetch --missing` 自动获取；失败项派 subagent 按 si skill 工作流接管")


def cmd_si_fetch(args: argparse.Namespace, cfg) -> None:
    """自动获取 SI：规则链解析候选 → 下载 → 验证 → 挂接。"""
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
            ui("没有需要获取 SI 的论文（scan 标记 mentioned 且未挂接）。")
            ui("hint: 先运行 `scrinium si scan` 刷新标记；或用 `scrinium si fetch <paper-id>` 指定论文")
            return

    ui(f"待获取: {len(targets)} 篇")
    stats: dict[str, int] = {}
    failed: list[tuple[str, str]] = []
    for idx, pdir in enumerate(targets):
        try:
            status = fetch_si_for_paper(pdir, cfg, convert=convert, dry_run=dry_run, force=force)
        except Exception as exc:
            _log.exception("si fetch failed for %s", pdir.name)
            status = "error"
        stats[status] = stats.get(status, 0) + 1
        ui(f"  [{idx + 1}/{len(targets)}] {pdir.name} -> {status}")
        if status not in ("ok", "skip", "dry_run"):
            failed.append((pdir.name, status))
        if not dry_run and idx < len(targets) - 1:
            time.sleep(_FETCH_DELAY)

    ui("\n获取完成: " + " | ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
    if stats.get("ok") and not dry_run:
        _reindex(cfg)
        ui("索引已更新（SI 内容可检索）")
    if failed:
        ui("\n失败项（建议派 subagent 按 si skill 工作流接管）:")
        for name, status in failed:
            hint = _STATUS_HINTS.get(status, "")
            ui(f"  [{status}] {name}" + (f" — {hint}" if hint else ""))
        ui(
            "hint: 人工找到 SI 文件后用 `scrinium attach-si <paper-id> <file>` 挂接；"
            "确认不存在则将 meta.json 的 si.fetch_status 置为 exhausted"
        )


def cmd_si_status(args: argparse.Namespace, cfg) -> None:
    """SI 队列总览：各状态计数 + 待 agent 接管清单。"""
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

    ui(f"论文总数: {total} | 提到 SI: {mentioned} | 已挂接: {present}（{n_files} 个文件）")
    if not by_status:
        ui("队列清空：提到 SI 的论文均已挂接或标记终态。")
        return
    ui("\n未挂接队列:")
    for status, ids in sorted(by_status.items()):
        ui(f"  [{status}] {len(ids)} 篇")
        for pid in ids[:10]:
            ui(f"    {pid}")
        if len(ids) > 10:
            ui(f"    ... 以及另外 {len(ids) - 10} 篇")
    pending = [s for s in ("pending", "not_found", "blocked", "mismatch") if s in by_status]
    if pending:
        ui(
            "\nhint: `scrinium si fetch --missing` 可重试 pending/error 项；"
            "not_found/blocked/mismatch 建议派 subagent 接管"
        )


def cmd_attach_si(args: argparse.Namespace, cfg) -> None:
    """把本地文件作为 SI 挂接到论文（agent 接管的统一入口）。"""
    from scrinium.si import attach_si

    paper_d = _resolve_paper(args.paper_id, cfg)
    src = Path(args.file)
    if not src.exists():
        ui(f"错误：文件不存在: {src}")
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
        ui("索引已更新")


# ============================================================================
#  Parser registration
# ============================================================================


def register(sub) -> None:
    """Register SI subcommands."""
    p_si = sub.add_parser("si", help="Supporting Information 扫描、获取与挂接")
    p_si.set_defaults(func=cmd_si_status)
    si_sub = p_si.add_subparsers(dest="si_action")

    p_scan = si_sub.add_parser("scan", help="扫描全库，标记正文引用了 SI 的论文")
    p_scan.set_defaults(func=cmd_si_scan)
    p_scan.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    p_fetch = si_sub.add_parser("fetch", help="自动获取 SI（规则链 → 下载 → 验证 → 挂接）")
    p_fetch.set_defaults(func=cmd_si_fetch)
    p_fetch.add_argument("paper_id", nargs="?", default=None, help="论文 ID（缺省配合 --missing 批量）")
    p_fetch.add_argument("--missing", action="store_true", help="批量处理提到 SI 但未挂接的论文")
    p_fetch.add_argument("--force", action="store_true", help="忽略已有文件与终态，强制重试")
    p_fetch.add_argument("--no-convert", action="store_true", help="只存原始文件，不转 Markdown")
    p_fetch.add_argument("--dry-run", action="store_true", help="预览模式")

    p_status = si_sub.add_parser("status", help="SI 队列总览与待接管清单")
    p_status.set_defaults(func=cmd_si_status)
    p_status.add_argument("--json", action="store_true", help="以 JSON 格式输出")

    p_attach = sub.add_parser("attach-si", help="把本地文件作为 SI 挂接到论文（验证 → 转换 → 入库）")
    p_attach.set_defaults(func=cmd_attach_si)
    p_attach.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_attach.add_argument("file", help="SI 文件路径（PDF/Office/数据文件）")
    p_attach.add_argument("--source-url", dest="source_url", default="", help="SI 来源 URL（审计追溯）")
    p_attach.add_argument("--no-convert", action="store_true", help="只存原始文件，不转 Markdown")
    p_attach.add_argument("--no-verify", action="store_true", help="跳过与主文的匹配验证（慎用）")
    p_attach.add_argument("--dry-run", action="store_true", help="预览模式")
