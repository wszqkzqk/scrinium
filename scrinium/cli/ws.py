"""cli/ws.py — workspace paper-subset management commands."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scrinium.log import ui

from .common import _add_filter_args, _add_tag_arg, _emit_json, _format_match_tag, _resolve_tag_filters, _resolve_top
from .search import _print_search_next_steps, _print_search_result

_log = logging.getLogger(__package__)


def _raise_ws_not_found(ws_root: Path, name: str) -> None:
    """Raise ValueError listing existing workspaces when *name* is unknown."""
    from scrinium import workspace

    msg = f"工作区不存在: {name}，请先运行 `scrinium ws init {name}` 创建"
    names = workspace.list_workspaces(ws_root)
    if names:
        msg += f"；现有工作区: {', '.join(names)}"
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
            ui(f"非法工作区名称: {name}")
            return

    if action == "init":
        ws_dir = ws_root / args.name
        workspace.create(ws_dir)
        ui(f"工作区已创建: {ws_dir}")

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
                ui("索引数据库不存在，可能尚未初始化。")
                ui("请先运行: scrinium index")
                return

            try:
                with sqlite3.connect(cfg.index_db) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT id, dir_name FROM papers_registry").fetchall()
            except sqlite3.OperationalError as e:
                _log.debug("索引数据库查询失败: %s", e)
                ui("索引数据库结构不完整或尚未初始化。")
                ui("请先运行: scrinium index")
                return

            resolved = [{"id": r["id"], "dir_name": r["dir_name"]} for r in rows]
            if not resolved:
                ui("主库中没有论文")
                return
            added = workspace.add(ws_dir, [], cfg.index_db, resolved=resolved)
            ui(f"已添加 {len(added)} 篇论文到 {args.name}")
            for e in added:
                ui(f"  + {e['dir_name']}")
            return
        elif args.add_topic is not None:
            from scrinium.topics import get_topic_papers, load_model

            try:
                model = load_model(cfg.topics_model_dir)
            except (FileNotFoundError, ImportError) as e:
                ui(f"无法加载主题模型: {e}")
                ui("请先运行: scrinium topics --build")
                return
            papers = get_topic_papers(model, args.add_topic)
            if not papers:
                ui(f"主题 {args.add_topic} 中没有论文")
                return
            paper_refs = [p["paper_id"] for p in papers]
            ui(f"主题 {args.add_topic}: 找到 {len(paper_refs)} 篇论文")
        elif args.add_search is not None:
            from scrinium.index import unified_search

            results = unified_search(
                args.add_search,
                cfg.index_db,
                top_k=_resolve_top(args, cfg.search.top_k),
                cfg=cfg,
                year=getattr(args, "year", None),
                journal=getattr(args, "journal", None),
                paper_type=getattr(args, "paper_type", None),
            )
            if not results:
                ui(f'未找到 "{args.add_search}" 的结果')
                return
            paper_refs = [r["paper_id"] for r in results]
            ui(f'搜索 "{args.add_search}": 找到 {len(paper_refs)} 篇论文')

        if not paper_refs:
            ui("未指定论文引用")
            return

        unresolved: list[str] = []
        added = workspace.add(ws_dir, paper_refs, cfg.index_db, unresolved=unresolved)
        ui(f"已添加 {len(added)} 篇论文到 {args.name}")
        for e in added:
            ui(f"  + {e['dir_name']}")
        for ref in unresolved:
            ui(f"无法解析: {ref}")
        if unresolved and not added:
            raise ValueError(f"所有论文引用均无法解析: {', '.join(unresolved)}")

    elif action == "remove":
        ws_dir = ws_root / args.name
        removed = workspace.remove(ws_dir, args.paper_refs, cfg.index_db)
        ui(f"已移除 {len(removed)} 篇论文")
        for e in removed:
            ui(f"  - {e['dir_name']}")

    elif action == "list":
        names = workspace.list_workspaces(ws_root)
        if not names:
            ui("没有工作区")
            return
        for name in names:
            ws_dir = ws_root / name
            ids = workspace.read_paper_ids(ws_dir)
            ui(f"  {name}（{len(ids)} 篇论文）")

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
        ui(f"工作区 {args.name}: {len(papers)} 篇论文")
        for i, p in enumerate(papers, 1):
            ui(f"  {i:3d}. {p['dir_name']}")

    elif action == "search":
        ws_dir = ws_root / args.name
        pids = workspace.read_paper_ids(ws_dir)
        if not pids:
            ui("工作区为空")
            return
        query = " ".join(args.query)
        mode = getattr(args, "mode", "unified")
        top_k = _resolve_top(args, cfg.search.top_k)
        tags = _resolve_tag_filters(args, cfg)

        if mode == "keyword":
            from scrinium.index import search as kw_search

            results = kw_search(
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
        elif mode == "semantic":
            from scrinium.vectors import vsearch

            if tags:
                from scrinium.index import paper_ids_for_tags

                # vsearch has no native tag filter; intersect the workspace
                # whitelist with the tag-matching id set instead
                pids = pids & paper_ids_for_tags(cfg.index_db, tags)

            results = vsearch(
                query,
                cfg.index_db,
                top_k=top_k,
                cfg=cfg,
                year=args.year,
                journal=args.journal,
                paper_type=args.paper_type,
                paper_ids=pids,
            )
        else:
            from scrinium.index import unified_search

            results = unified_search(
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
            ui(f'工作区 {args.name} 中未找到 "{query}" 的结果')
            return
        ui(f"工作区 {args.name} 中找到 {len(results)} 篇:\n")
        for i, r in enumerate(results, 1):
            match = r.get("match")
            extra = _format_match_tag(match) if match else ""
            _print_search_result(i, r, extra=extra)
        _print_search_next_steps(include_ws_add=False)

    elif action == "export":
        ws_dir = ws_root / args.name
        dir_names = workspace.read_dir_names(ws_dir, cfg.index_db)
        if not dir_names:
            ui("工作区为空")
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
            ui("未找到匹配的论文")
            return
        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(bib, encoding="utf-8")
            ui(f"已导出到 {out}（{bib.count('@')} 篇）")
        else:
            print(bib)

    elif action == "rename":
        try:
            workspace.rename(ws_root, args.old_name, args.new_name)
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            ui(str(e))
            return
        ui(f"工作区已重命名: {args.old_name} → {args.new_name}")


def register(sub) -> None:
    """Register workspace subcommands."""
    # --- ws (workspace) ---
    p_ws = sub.add_parser("ws", help="工作区论文子集管理")
    p_ws.set_defaults(func=cmd_ws)
    p_ws_sub = p_ws.add_subparsers(dest="ws_action", required=True)

    p_ws_init = p_ws_sub.add_parser("init", help="初始化工作区")
    p_ws_init.add_argument("name", help="工作区名称（workspace/ 下的子目录名）")

    p_ws_add = p_ws_sub.add_parser("add", help="添加论文到工作区")
    p_ws_add.add_argument("name", help="工作区名称")
    p_ws_add.add_argument("paper_refs", nargs="*", help="论文引用（UUID / 目录名 / DOI）")
    p_ws_add_batch = p_ws_add.add_mutually_exclusive_group()
    p_ws_add_batch.add_argument("--search", dest="add_search", type=str, default=None, help="按搜索结果批量添加")
    p_ws_add_batch.add_argument("--topic", dest="add_topic", type=int, default=None, help="按主题 ID 批量添加")
    p_ws_add_batch.add_argument("--all", dest="add_all", action="store_true", default=False, help="添加全库论文")
    p_ws_add.add_argument("--top", type=int, default=None, help="限制 --search 返回条数")
    _add_filter_args(p_ws_add)

    p_ws_rm = p_ws_sub.add_parser("remove", help="从工作区移除论文")
    p_ws_rm.add_argument("name", help="工作区名称")
    p_ws_rm.add_argument("paper_refs", nargs="+", help="论文引用（UUID / 目录名 / DOI）")

    p_ws_list = p_ws_sub.add_parser("list", help="列出所有工作区")

    p_ws_show = p_ws_sub.add_parser("show", help="查看工作区中的论文")
    p_ws_show.add_argument("name", help="工作区名称")
    p_ws_show.add_argument("--json", action="store_true", help="以 JSON 格式输出（便于管道解析）")

    p_ws_search = p_ws_sub.add_parser("search", help="在工作区内搜索")
    p_ws_search.add_argument("name", help="工作区名称")
    p_ws_search.add_argument("query", nargs="+", help="查询文本")
    p_ws_search.add_argument("--top", type=int, default=None, help="返回条数")
    p_ws_search.add_argument(
        "--mode", choices=["unified", "keyword", "semantic"], default="unified", help="搜索模式（默认 unified）"
    )
    _add_filter_args(p_ws_search)
    _add_tag_arg(p_ws_search)

    p_ws_rename = p_ws_sub.add_parser("rename", help="重命名工作区")
    p_ws_rename.add_argument("old_name", help="当前工作区名称")
    p_ws_rename.add_argument("new_name", help="新工作区名称")

    p_ws_export = p_ws_sub.add_parser("export", help="导出工作区论文 BibTeX")
    p_ws_export.add_argument("name", help="工作区名称")
    p_ws_export.add_argument("-o", "--output", type=str, default=None, help="输出文件路径")
    _add_filter_args(p_ws_export)
