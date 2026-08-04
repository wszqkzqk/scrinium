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
        ui("该论文没有参考文献数据。请先运行 refetch 拉取 references。")
        return

    in_lib = [r for r in refs if r.get("target_id")]
    out_lib = [r for r in refs if not r.get("target_id")]

    scope = f"工作区 {args.ws}" if getattr(args, "ws", None) else "库内"
    ui(f"参考文献共 {len(refs)} 篇（{scope} {len(in_lib)} 篇，库外 {len(out_lib)} 篇）\n")

    if in_lib:
        ui("── 库内 ──")
        for i, r in enumerate(in_lib, 1):
            display = r.get("dir_name") or r["target_id"]
            year = r.get("year") or "?"
            author = r.get("first_author") or "?"
            ui(f"[{i}] {display}")
            ui(f"     {author} | {year} | {r.get('title', '?')}")
            ui(f"     DOI: {r['target_doi']}")
            ui()

    if out_lib:
        ui("── 库外 ──")
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
        scope = f"工作区 {args.ws} 中" if getattr(args, "ws", None) else "本地"
        ui(f"没有找到引用该论文的{scope}论文。")
        return

    scope = f"工作区 {args.ws}" if getattr(args, "ws", None) else "本地"
    ui(f"共 {len(results)} 篇{scope}论文引用了此论文：\n")
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
        ui(f"没有找到被 ≥{min_shared} 篇论文共同引用的参考文献。")
        return

    ui(f"共同参考文献（被 ≥{min_shared} 篇共引）：共 {len(results)} 篇\n")
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
        raise ValueError(f"snowball 当前仅支持 --depth 1（收到 {depth}）")

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
        raise ValueError(f"无法解析种子论文: {', '.join(unresolved)}")

    ws_ids = _resolve_ws_paper_ids(args, cfg)
    ranked = snowball_candidates(seed_uuids, cfg.index_db, ws_ids=ws_ids)
    if not ranked:
        ui("没有发现任何候选论文：引用图数据不足。")
        ui("可对种子运行 scrinium refetch <paper-id> 拉取 references，然后 scrinium index 重建索引。")
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

    scope = f"工作区 {args.ws} 内" if getattr(args, "ws", None) else "库内"
    ui(f"种子论文：{', '.join(seed_labels)}")
    ui(f"{scope}滚雪球候选共 {len(ranked)} 篇（score = 2×共享引用 + 1×引用种子 + 1×被种子引用）\n")
    for i, c in enumerate(show, 1):
        rel = "+".join(c["relations"])
        ui(f"[{i}] [score {c['score']}] {c['dir_name'] or c['id']}")
        ui(f"     {c.get('title') or '?'} | {c.get('year') or '?'} | 被引 {c['citation_count']}")
        ui(f"     关系 {rel} | 共享引用 {c['shared']} | 引用种子 {c['cites_seeds']} | 被种子引用 {c['cited_by_seeds']}")
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
                ui("未索引任何页面。请检查版本号或文档源。")

        elif action == "show":
            results = toolref_show(args.tool, *args.path, cfg=cfg)
            if not results:
                ui(f"未找到匹配：{args.tool} {' '.join(args.path)}")
                ui(f"尝试搜索：scrinium toolref search {args.tool} {' '.join(args.path)}")
                return
            for r in results:
                ui(f"\n{'=' * 60}")
                ui(r["page_name"])
                if r.get("section"):
                    ui(f"   段落：{r['section']}  |  程序：{r.get('program', '')}")
                if r.get("synopsis"):
                    ui(f"   {r['synopsis']}")
                ui(f"{'─' * 60}")
                ui(r.get("content", "(无内容)"))

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
                ui(f"无结果：{query}")
                return
            ui(f"找到 {len(results)} 条结果：\n")
            for i, r in enumerate(results, 1):
                synopsis = r.get("synopsis", "")[:80]
                ui(f"  {i:2d}. [{r['page_name']}] {synopsis}")

        elif action == "list":
            entries = toolref_list(args.tool, cfg=cfg)
            if not entries:
                tools = ", ".join(TOOL_REGISTRY.keys())
                ui(f"无已拉取文档。支持的工具：{tools}")
                ui("使用 `scrinium toolref fetch <tool> --version <ver>` 拉取")
                return
            current_tool = ""
            for e in entries:
                if e["tool"] != current_tool:
                    current_tool = e["tool"]
                    ui(f"\n{e['display_name']}:")
                marker = " (current)" if e["is_current"] else ""
                completeness = ""
                unit = "页" if e.get("source_type") == "manifest" else "条"
                if e.get("source_type") == "manifest" and e.get("expected_pages"):
                    completeness = f" [{e['page_count']}/{e['expected_pages']} 已索引"
                    failed_pages = e.get("failed_pages")
                    if failed_pages:
                        completeness += f", {failed_pages} 失败"
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
    else:
        _log.error("请指定 document 子命令: inspect")
        sys.exit(1)


def _cmd_document_inspect(args: argparse.Namespace, cfg) -> None:
    from scrinium.document import inspect

    file_path = Path(args.file)
    if not file_path.exists():
        _log.error("文件不存在: %s", file_path)
        sys.exit(1)
    fmt = getattr(args, "format", None)
    try:
        result = inspect(file_path, fmt=fmt)
    except (ValueError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)
    print(result)


def cmd_style(args: argparse.Namespace, cfg) -> None:
    """Dispatcher for `scrinium style` subcommands."""
    sub = getattr(args, "style_sub", None)
    if sub == "list":
        _cmd_style_list(args, cfg)
    elif sub == "show":
        _cmd_style_show(args, cfg)
    else:
        _log.error("请指定 style 子命令: list / show")
        sys.exit(1)


def _cmd_style_list(args: argparse.Namespace, cfg) -> None:
    from scrinium.citation_styles import list_styles

    styles = list_styles(cfg)
    ui(f"可用引用格式（共 {len(styles)} 种）：")
    for s in styles:
        tag = f"[{s['source']}]"
        desc = f" — {s['description']}" if s.get("description") else ""
        print(f"  {s['name']:<28} {tag:<10}{desc}")
    print()
    ui("用法：scrinium export markdown --all --style <name>")


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
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return

        candidates_path = build_proceedings_clean_candidates(proceeding_dir)
        ui(f"已生成 proceedings clean candidates: {candidates_path}")
        ui("等待 agent 审阅 clean_candidates.json 并生成 clean_plan.json，然后再执行后续清洗。")
        return

    if args.proceedings_action == "apply-split":
        from scrinium.ingest.proceedings import apply_proceedings_split_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        split_plan = Path(args.split_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return
        if not split_plan.exists():
            ui(f"split plan 不存在: {split_plan}")
            return

        apply_proceedings_split_plan(proceeding_dir, split_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"已应用 proceedings split plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} 篇)")
        return

    if args.proceedings_action == "apply-clean":
        from scrinium.ingest.proceedings import apply_proceedings_clean_plan

        proceeding_dir = Path(args.proceeding_dir).expanduser()
        clean_plan = Path(args.clean_plan).expanduser()

        if not proceeding_dir.exists():
            ui(f"proceedings 目录不存在: {proceeding_dir}")
            return
        if not clean_plan.exists():
            ui(f"clean plan 不存在: {clean_plan}")
            return

        apply_proceedings_clean_plan(proceeding_dir, clean_plan)
        meta = json.loads((proceeding_dir / "meta.json").read_text(encoding="utf-8"))
        ui(f"已应用 proceedings clean plan: {proceeding_dir.name} ({meta.get('child_paper_count', 0)} 篇)")
        return

    ui(f"未知 proceedings 子命令: {args.proceedings_action}")


def cmd_insights(args: argparse.Namespace, cfg) -> None:
    from datetime import datetime, timedelta, timezone

    from scrinium import insights
    from scrinium.metrics import get_store

    store = get_store()
    if not store:
        ui("暂无足够数据（metrics 未初始化）")
        return

    days = args.days
    if days <= 0:
        ui("--days 必须为正整数")
        return
    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since_dt.isoformat()

    # Fetch search events
    search_events = store.query(category="search", since=since_iso, limit=10000)
    # Fetch read events
    read_events = store.query(category="read", since=since_iso, limit=10000)

    if not search_events and not read_events:
        ui(f"暂无足够数据（过去 {days} 天内无搜索或阅读记录）")
        return

    ui(f"=== 科研行为分析（过去 {days} 天）===\n")

    ui("【搜索热词前 10】")
    hot_keywords = insights.extract_hot_keywords(search_events, top_k=10)
    if hot_keywords:
        for word, cnt in hot_keywords:
            bar = "█" * min(cnt, 20)
            ui(f"  {word:<20s} {bar} ({cnt})")
    else:
        ui("  暂无搜索记录")
    ui()

    ui("【最常阅读论文前 10】")
    most_read = insights.aggregate_most_read_titles(read_events, cfg.papers_dir, top_k=10)
    if most_read:
        for rank, (title_key, cnt) in enumerate(most_read, 1):
            label = title_key[:60]
            ui(f"  {rank:2d}. [{cnt}次] {label}")
    else:
        ui("  暂无阅读记录")
    ui()

    # 3. Weekly read-count trend (ASCII bar chart)
    ui("【阅读量趋势（按周）】")
    if read_events:
        week_counts = insights.build_weekly_read_trend(read_events)
        if week_counts:
            max_count = max(cnt for _, cnt in week_counts) or 1
            for week, cnt in week_counts:
                bar_len = round(cnt / max_count * 20)
                bar = "█" * bar_len
                ui(f"  {week}  {bar} {cnt}")
        else:
            ui("  暂无足够数据")
    else:
        ui("  暂无阅读记录")
    ui()

    # 4. Active workspaces — list workspaces with paper counts
    ui("【活跃工作区】")
    try:
        ws_root = cfg._root / "workspace"
        workspaces = insights.list_workspace_counts(ws_root)
        if workspaces:
            for ws_name, count in workspaces:
                ui(f"  {ws_name:<30s} {count} 篇论文")
        else:
            ui("  暂无工作区")
    except Exception:
        ui("  工作区信息不可用")
    ui()


def cmd_metrics(args: argparse.Namespace, cfg) -> None:
    from scrinium.metrics import get_store

    store = get_store()
    if not store:
        _log.error("Metrics 数据库尚未初始化。")
        return

    rows = store.query(
        category=args.category,
        since=args.since,
        limit=args.last,
    )
    if not rows:
        ui("没有记录。")
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
        lang = getattr(args, "lang", "zh")
        results = run_check(cfg, lang)
        ui(format_check_results(results))
    else:
        run_wizard(cfg)


def cmd_citation_check(args: argparse.Namespace, cfg) -> None:
    from scrinium.citation_check import check_citations, extract_citations

    # Read input text
    if args.file:
        p = Path(args.file)
        if not p.exists():
            _log.error("文件不存在：%s", p)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    if not text.strip():
        ui("输入文本为空。")
        return

    citations = extract_citations(text)
    if not citations:
        ui("未在文本中发现引用。")
        return

    ui(f"提取到 {len(citations)} 条引用，正在验证…\n")

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
        "VERIFIED": "已验证",
        "NOT_IN_LIBRARY": "库中未找到",
        "AMBIGUOUS": "候选不唯一",
    }

    for r in results:
        status_icon = {"VERIFIED": "✓", "NOT_IN_LIBRARY": "✗", "AMBIGUOUS": "?"}.get(r["status"], " ")
        status_text = status_labels.get(r["status"], r["status"])
        ui(f"  [{status_icon}] {status_text:8s}  {r['raw']}  ({r['author']}, {r['year']})")
        if r["matches"]:
            for m in r["matches"][:3]:
                display_id = m.get("dir_name") or m.get("paper_id", "?")
                ui(f"       → {display_id}")
                ui(f"         {m.get('title', '?')}")

    ui()
    ui(
        f"验证结果：已验证 {counts['VERIFIED']} / "
        f"候选不唯一 {counts['AMBIGUOUS']} / "
        f"库中未找到 {counts['NOT_IN_LIBRARY']}"
    )


def _add_parser_with_optional_help(sub, name: str, help_text: str | None):
    """add_parser where ``help_text=None`` hides the entry from ``--help``."""
    return sub.add_parser(name, **({"help": help_text} if help_text else {}))


def _add_refs_parser(sub, name: str, help_text: str | None = None) -> None:
    p_refs = _add_parser_with_optional_help(sub, name, help_text)
    p_refs.set_defaults(func=cmd_refs)
    p_refs.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_refs.add_argument("--ws", type=str, default=None, help="限定工作区范围")


def _add_citing_parser(sub, name: str, help_text: str | None = None) -> None:
    p_citing = _add_parser_with_optional_help(sub, name, help_text)
    p_citing.set_defaults(func=cmd_citing)
    p_citing.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_citing.add_argument("--ws", type=str, default=None, help="限定工作区范围")


def _add_shared_refs_parser(sub, name: str, help_text: str | None = None) -> None:
    p_sr = _add_parser_with_optional_help(sub, name, help_text)
    p_sr.set_defaults(func=cmd_shared_refs)
    p_sr.add_argument("paper_ids", nargs="+", help="论文 ID（至少 2 个）")
    p_sr.add_argument("--min", type=int, default=None, help="最少共引次数（默认 2）")
    p_sr.add_argument("--ws", type=str, default=None, help="限定工作区范围")


def _add_style_parser(sub, name: str, help_text: str | None = None) -> None:
    """Register the citation-styles parser tree under *name* (used for the `style` alias)."""
    p_style = _add_parser_with_optional_help(sub, name, help_text)
    p_style.set_defaults(func=cmd_style)
    p_style_sub = p_style.add_subparsers(dest="style_sub", required=True)

    p_style_list = p_style_sub.add_parser("list", help="列出所有可用引用格式")
    del p_style_list  # no extra args needed

    p_style_show = p_style_sub.add_parser("show", help="查看引用格式的格式化函数代码")
    p_style_show.add_argument("name", help="格式名称，如 jcp / apa / vancouver")


def register(sub) -> None:
    """Register misc-domain subcommands."""
    # --- references / cited-by / shared-references (legacy aliases hidden) ---
    _add_refs_parser(sub, "references", "查看论文的参考文献列表")
    _add_refs_parser(sub, "refs", None)
    _add_citing_parser(sub, "cited-by", "查看哪些本地论文引用了此论文")
    _add_citing_parser(sub, "citing", None)
    _add_shared_refs_parser(sub, "shared-references", "共同参考文献分析")
    _add_shared_refs_parser(sub, "shared-refs", None)

    # --- snowball ---
    p_sb = sub.add_parser("snowball", help="引用滚雪球：从种子论文沿引用扩张并排序")
    p_sb.set_defaults(func=cmd_snowball)
    p_sb.add_argument("paper_ids", nargs="+", help="种子论文 ID（目录名 / UUID / DOI，可多篇）")
    p_sb.add_argument("--depth", type=int, default=1, help="扩张深度（当前仅支持 1）")
    p_sb.add_argument("--top", type=int, default=None, help="返回条数（默认 20）")
    p_sb.add_argument("--ws", type=str, default=None, help="限定工作区范围")
    p_sb.add_argument("--json", action="store_true", help="以 JSON 输出")

    # --- citation-check ---
    p_cc = sub.add_parser("citation-check", help="验证文本中的引用是否在本地知识库中")
    p_cc.set_defaults(func=cmd_citation_check)
    p_cc.add_argument("file", nargs="?", default=None, help="待检查的文件路径（省略则从 stdin 读取）")
    p_cc.add_argument("--ws", type=str, default=None, help="在指定工作区范围内验证")

    # --- setup ---
    p_setup = sub.add_parser(
        "setup",
        help="环境检测与安装向导",
        description="默认进入交互式安装向导；使用 `check` 子命令仅做环境诊断。",
    )
    p_setup.set_defaults(func=cmd_setup)
    p_setup_sub = p_setup.add_subparsers(dest="setup_action")
    p_setup_check = p_setup_sub.add_parser("check", help="检查环境状态")
    p_setup_check.add_argument("--lang", choices=["en", "zh"], default="zh", help="输出语言（zh 或 en，默认 zh）")

    # --- proceedings ---
    p_proc = sub.add_parser("proceedings", help="论文集辅助命令（apply-split 等）")
    p_proc.set_defaults(func=cmd_proceedings)
    p_proc_sub = p_proc.add_subparsers(dest="proceedings_action", required=True)

    p_proc_apply = p_proc_sub.add_parser("apply-split", help="对已准备好的 proceedings 应用 split_plan.json")
    p_proc_apply.add_argument("proceeding_dir", help="proceedings 目录路径")
    p_proc_apply.add_argument("split_plan", help="split_plan.json 路径")

    p_proc_clean_candidates = p_proc_sub.add_parser(
        "build-clean-candidates", help="为已拆分的 proceedings 生成 clean_candidates.json"
    )
    p_proc_clean_candidates.add_argument("proceeding_dir", help="proceedings 目录路径")

    p_proc_apply_clean = p_proc_sub.add_parser("apply-clean", help="对已拆分的 proceedings 应用 clean_plan.json")
    p_proc_apply_clean.add_argument("proceeding_dir", help="proceedings 目录路径")
    p_proc_apply_clean.add_argument("clean_plan", help="clean_plan.json 路径")

    # --- insights ---
    p_insights = sub.add_parser("insights", help="研究行为分析：搜索热词、最常阅读论文等")
    p_insights.set_defaults(func=cmd_insights)
    p_insights.add_argument("--days", type=int, default=30, help="分析最近 N 天的数据（默认 30）")

    # --- metrics ---
    p_metrics = sub.add_parser("metrics", help="查看运行指标（步骤/API 调用计时）")
    p_metrics.set_defaults(func=cmd_metrics)
    p_metrics.add_argument("--last", type=int, default=20, help="最近 N 条记录")
    p_metrics.add_argument("--category", default="step", help="事件类别（step/api/search/read，默认 step）")
    p_metrics.add_argument("--since", default=None, help="起始时间（ISO 格式，如 2026-03-01）")

    # --- citation-styles (primary name; `style` kept as a hidden legacy alias) ---
    _add_style_parser(sub, "citation-styles", "引用格式管理（列出 / 查看自定义格式）")
    _add_style_parser(sub, "style", None)

    # --- document ---
    p_doc = sub.add_parser("document", help="Office 文档工具（inspect 等）")
    p_doc.set_defaults(func=cmd_document)
    p_doc_sub = p_doc.add_subparsers(dest="doc_action", required=True)

    p_doc_inspect = p_doc_sub.add_parser("inspect", help="检查 Office 文档结构（DOCX / PPTX / XLSX）")
    p_doc_inspect.add_argument("file", help="文件路径")
    p_doc_inspect.add_argument(
        "--format",
        choices=["docx", "pptx", "xlsx"],
        default=None,
        help="文件格式（默认从扩展名推断）",
    )

    # --- toolref ---
    p_tr = sub.add_parser("toolref", help="科学计算工具文档查阅（fetch/show/search/list/use）")
    p_tr.set_defaults(func=cmd_toolref)
    p_tr_sub = p_tr.add_subparsers(dest="toolref_action", required=True)

    p_trf = p_tr_sub.add_parser("fetch", help="拉取工具文档（git clone → 提取 → 索引）")
    p_trf.add_argument("tool", help="工具名（qe/lammps/gromacs/openfoam/bioinformatics）")
    p_trf.add_argument("--version", default=None, help="版本号（如 7.5, 22Jul2025_update3）")
    p_trf.add_argument("--force", action="store_true", help="强制重新拉取并覆盖本地缓存")

    p_trs = p_tr_sub.add_parser("show", help="查看指定命令/参数的文档")
    p_trs.add_argument("tool", help="工具名")
    p_trs.add_argument("path", nargs="+", help="查找路径（如 pw ecutwfc）")

    p_trq = p_tr_sub.add_parser("search", help="全文搜索工具文档")
    p_trq.add_argument("tool", help="工具名")
    p_trq.add_argument("query", nargs="+", help="搜索关键词")
    p_trq.add_argument("--top", type=int, default=20, help="返回条数（默认 20）")
    p_trq.add_argument("--program", default=None, help="按程序过滤（如 pw.x）")
    p_trq.add_argument("--section", default=None, help="按 namelist/section 过滤（如 SYSTEM）")

    p_trl = p_tr_sub.add_parser("list", help="列出已有工具文档及版本")
    p_trl.add_argument("tool", nargs="?", default=None, help="工具名（省略列出全部）")

    p_tru = p_tr_sub.add_parser("use", help="切换工具文档的当前活跃版本")
    p_tru.add_argument("tool", help="工具名")
    p_tru.add_argument("version", help="目标版本号")
