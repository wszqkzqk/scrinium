"""cli/explore.py — OpenAlex exploration library commands."""

from __future__ import annotations

import argparse
import logging
import sys

from scrinium.log import ui

from .common import _resolve_top

_log = logging.getLogger(__package__)


def cmd_explore(args: argparse.Namespace, cfg) -> None:
    action = args.explore_action

    if action == "fetch":
        if args.limit is not None and args.limit <= 0:
            ui(f"--limit 必须为正整数，当前为: {args.limit}")
            return
        # Determine name: explicit --name, or derive from filters
        name = args.name
        if not name:
            if args.issn:
                name = args.issn.replace("-", "")
            elif args.concept:
                name = f"concept-{args.concept}"
            elif args.author:
                name = f"author-{args.author}"
            elif args.keyword:
                name = args.keyword.replace(" ", "-")[:30]
            else:
                ui("请提供 --name 或至少一个过滤条件")
                return
        from scrinium.explore import fetch_explore

        total = fetch_explore(
            name,
            issn=getattr(args, "issn", None),
            concept=getattr(args, "concept", None),
            topic=getattr(args, "topic_id", None),
            author=getattr(args, "author", None),
            institution=getattr(args, "institution", None),
            keyword=getattr(args, "keyword", None),
            source_type=getattr(args, "source_type", None),
            year_range=getattr(args, "year_range", None),
            min_citations=getattr(args, "min_citations", None),
            oa_type=getattr(args, "oa_type", None),
            incremental=getattr(args, "incremental", False),
            limit=getattr(args, "limit", None),
            cfg=cfg,
        )
        ui(f"\n已抓取 {total} 篇论文")

    elif action == "search":
        query = " ".join(args.query)
        top_k = _resolve_top(args, 10)
        from scrinium.explore import explore_search

        results = explore_search(args.name, query, top_k=top_k, cfg=cfg)
        if not results:
            ui("未找到结果。")
            return
        for i, r in enumerate(results, 1):
            authors = r.get("authors", [])
            first = authors[0] if authors else ""
            cited = r.get("cited_by_count", 0)
            cite_str = f"  [被引: {cited}]" if cited else ""
            ui(f"[{i}] [{r.get('year', '?')}] {r.get('title', '')}")
            ui(f"     {first} | {r.get('doi', '')}  (分数: {r['score']:.3f}){cite_str}")
            ui()

    elif action == "list":
        import json as _json

        explore_root = cfg._root / "data" / "explore"
        if not explore_root.exists():
            ui("暂无 explore 库，请先运行 scrinium explore fetch --issn <ISSN> 创建。")
            return
        for d in sorted(explore_root.iterdir()):
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = _json.loads(meta_file.read_text("utf-8"))
                except (OSError, _json.JSONDecodeError) as e:
                    ui(f"  {d.name}: meta.json 读取失败，已跳过（{e}）")
                    continue
                query = meta.get("query", {})
                if query:
                    qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                elif meta.get("issn"):
                    qinfo = f"ISSN {meta['issn']}"
                else:
                    qinfo = "?"
                ui(f"  {d.name}: {meta.get('count', '?')} 篇 ({qinfo}，抓取时间 {meta.get('fetched_at', '?')})")
        return

    elif action == "info":
        import json as _json

        if not args.name:
            # List all explore libraries
            explore_root = cfg._root / "data" / "explore"
            if not explore_root.exists():
                ui("暂无 explore 库，请先运行 scrinium explore fetch --issn <ISSN> 创建。")
                return
            for d in sorted(explore_root.iterdir()):
                if not d.is_dir():
                    continue
                meta_file = d / "meta.json"
                if meta_file.exists():
                    try:
                        meta = _json.loads(meta_file.read_text("utf-8"))
                    except (OSError, _json.JSONDecodeError) as e:
                        ui(f"  {d.name}: meta.json 读取失败，已跳过（{e}）")
                        continue
                    # Show query info (backward compatible with old ISSN-only format)
                    query = meta.get("query", {})
                    if query:
                        qinfo = ", ".join(f"{k}={v}" for k, v in query.items())
                    elif meta.get("issn"):
                        qinfo = f"ISSN {meta['issn']}"
                    else:
                        qinfo = "?"
                    ui(f"  {d.name}: {meta.get('count', '?')} 篇 ({qinfo}，抓取时间 {meta.get('fetched_at', '?')})")
            return
        from scrinium.explore import count_papers

        meta_file = cfg._root / "data" / "explore" / args.name / "meta.json"
        if meta_file.exists():
            try:
                meta = _json.loads(meta_file.read_text("utf-8"))
            except (OSError, _json.JSONDecodeError) as e:
                ui(f"读取 {meta_file} 失败：{e}")
                return
            ui(f"Explore 库: {args.name}")
            for k, v in meta.items():
                ui(f"  {k}: {v}")
        else:
            n = count_papers(args.name, cfg=cfg)
            ui(f"Explore 库 {args.name}: {n} 篇论文")

    else:
        _log.error("未知操作: %s", action)
        sys.exit(1)


def register(sub) -> None:
    """Register explore-domain subcommands."""
    # --- explore ---
    p_explore = sub.add_parser("explore", help="多维文献探索（OpenAlex 拉取 + 关键词检索）")
    p_explore.set_defaults(func=cmd_explore)
    p_explore_sub = p_explore.add_subparsers(dest="explore_action", required=True)

    p_ef = p_explore_sub.add_parser("fetch", help="从 OpenAlex 拉取论文（多维度 filter）")
    p_ef.add_argument("--issn", default=None, help="期刊 ISSN（如 0022-1120）")
    p_ef.add_argument("--concept", default=None, help="OpenAlex concept ID（如 C62520636）")
    p_ef.add_argument("--topic-id", default=None, help="OpenAlex topic ID")
    p_ef.add_argument("--author", default=None, help="OpenAlex author ID")
    p_ef.add_argument("--institution", default=None, help="OpenAlex institution ID")
    p_ef.add_argument("--keyword", default=None, help="标题/摘要关键词搜索")
    p_ef.add_argument("--source-type", default=None, help="来源类型（journal/conference/repository）")
    p_ef.add_argument("--oa-type", default=None, help="论文类型（article/review 等）")
    p_ef.add_argument("--min-citations", type=int, default=None, help="最小引用量")
    p_ef.add_argument("--name", help="探索库名称（默认从 filter 推导）")
    p_ef.add_argument("--year-range", help="年份过滤（如 2020-2025）")
    p_ef.add_argument("--incremental", action="store_true", help="增量更新（追加新论文）")
    p_ef.add_argument("--limit", type=int, default=None, help="最多拉取的论文数量上限（不设则无限）")

    p_es = p_explore_sub.add_parser("search", help="探索库关键词搜索")
    p_es.add_argument("--name", required=True, help="探索库名称")
    p_es.add_argument("query", nargs="+", help="查询文本")
    p_es.add_argument("--top", type=int, default=None, help="返回条数")

    p_el = p_explore_sub.add_parser("list", help="列出所有探索库")

    p_ei = p_explore_sub.add_parser("info", help="查看探索库信息")
    p_ei.add_argument("--name", default=None, help="探索库名称（省略列出全部）")
