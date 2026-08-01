"""cli/explore.py — OpenAlex exploration library commands."""

from __future__ import annotations

import argparse
import logging
import sys

from scholaraio.log import ui

from .common import _check_import_error, _resolve_top, _write_all_viz

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
        from scholaraio.explore import fetch_explore

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

    elif action == "embed":
        try:
            from scholaraio.explore import build_explore_vectors
        except ImportError as e:
            _check_import_error(e)
        n = build_explore_vectors(args.name, rebuild=args.rebuild, cfg=cfg)
        provider = (getattr(cfg.embed, "provider", "local") or "local").strip().lower()
        if provider == "none":
            ui("当前 embed.provider=none：探索库跳过向量生成，仅保留关键词检索。")
            return
        ui(f"完成: 新增 {n} 条向量嵌入")

    elif action == "topics":
        try:
            from scholaraio.explore import _explore_dir, build_explore_topics
        except ImportError as e:
            _check_import_error(e)
        try:
            from scholaraio.topics import get_topic_overview, get_topic_papers, load_model
        except ImportError as e:
            _check_import_error(e)

        model_dir = _explore_dir(args.name, cfg) / "topic_model"

        if args.build or args.rebuild:
            nr_topics = args.nr_topics
            info = build_explore_topics(
                args.name,
                rebuild=args.rebuild,
                min_topic_size=args.min_topic_size or 30,
                nr_topics=nr_topics,
                cfg=cfg,
            )
            ui(f"\n聚类完成: {info['n_topics']} 个主题，{info['n_outliers']} 篇离群论文，{info['n_papers']} 篇论文")

        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            ui("尚未构建主题模型。请先运行 scholaraio explore topics --name <name> --build。")
            return

        if args.topic is not None:
            papers = get_topic_papers(model, args.topic)
            top_n = _resolve_top(args, 20)
            papers = papers[:top_n]
            ui(f"主题 {args.topic}: {len(papers)} 篇论文\n")
            for i, p in enumerate(papers, 1):
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, int | float)), default=0)
                cite_str = f"  [被引: {best}]" if best else ""
                authors = p.get("authors", "")
                first_author = authors.split(",")[0].strip() if authors else ""
                title = p.get("title", "")
                if len(title) > 70:
                    title = title[:67] + "..."
                ui(f"  {i:3d}. [{p.get('year', '?')}] {title}")
                ui(f"       {first_author} | {p.get('paper_id', '')}{cite_str}")
            return

        overview = get_topic_overview(model)
        if not overview:
            ui("没有可用主题。请先运行 scholaraio explore topics --name <name> --build。")
            return
        from scholaraio.topics import get_outliers

        outliers = get_outliers(model)
        total = sum(t["count"] for t in overview) + len(outliers)
        ui(f"\n{len(overview)} 个主题，{total} 篇论文，{len(outliers)} 篇离群论文\n")
        for t in overview:
            kw = ", ".join(t["keywords"][:6])
            ui(f"主题 {t['topic_id']:2d}（{t['count']:3d} 篇）: {kw}")
            for p in t["representative_papers"][:3]:
                title = p.get("title", "")
                if len(title) > 65:
                    title = title[:62] + "..."
                cc = p.get("citation_count", {})
                best = max((v for v in (cc or {}).values() if isinstance(v, int | float)), default=0)
                cite_str = f"  [被引: {best}]" if best else ""
                ui(f"    [{p.get('year', '?')}] {title}{cite_str}")
            ui()

    elif action == "search":
        query = " ".join(args.query)
        mode = getattr(args, "mode", "semantic") or "semantic"
        top_k = _resolve_top(args, 10)
        if mode == "keyword":
            from scholaraio.explore import explore_search

            results = explore_search(args.name, query, top_k=top_k, cfg=cfg)
        elif mode == "unified":
            try:
                from scholaraio.explore import explore_unified_search
            except ImportError as e:
                _check_import_error(e)
            results = explore_unified_search(args.name, query, top_k=top_k, cfg=cfg)
        else:
            try:
                from scholaraio.explore import explore_vsearch
            except ImportError as e:
                _check_import_error(e)
            results = explore_vsearch(args.name, query, top_k=top_k, cfg=cfg)
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

    elif action == "viz":
        try:
            from scholaraio.explore import _explore_dir
            from scholaraio.topics import load_model
        except ImportError as e:
            _check_import_error(e)
        model_dir = _explore_dir(args.name, cfg) / "topic_model"
        try:
            model = load_model(model_dir)
        except FileNotFoundError:
            ui("尚未构建主题模型。请先运行 scholaraio explore topics --name <name> --build。")
            return
        _write_all_viz(model, model_dir / "viz")

    elif action == "list":
        import json as _json

        explore_root = cfg._root / "data" / "explore"
        if not explore_root.exists():
            ui("暂无 explore 库，请先运行 scholaraio explore fetch --issn <ISSN> 创建。")
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
                ui("暂无 explore 库，请先运行 scholaraio explore fetch --issn <ISSN> 创建。")
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
        from scholaraio.explore import count_papers

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
    p_explore = sub.add_parser("explore", help="多维文献探索（OpenAlex 拉取 + 嵌入 + 聚类）")
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

    p_ee = p_explore_sub.add_parser("embed", help="为探索库生成语义向量")
    p_ee.add_argument("--name", required=True, help="探索库名称")
    p_ee.add_argument("--rebuild", action="store_true", help="清空后重建")

    p_et = p_explore_sub.add_parser("topics", help="探索库主题建模")
    p_et.add_argument("--name", required=True, help="探索库名称")
    p_et.add_argument("--build", action="store_true", help="构建主题模型")
    p_et.add_argument("--rebuild", action="store_true", help="重建主题模型")
    p_et.add_argument("--topic", type=int, default=None, help="查看指定主题的论文")
    p_et.add_argument("--top", type=int, default=None, help="返回条数")
    p_et.add_argument("--min-topic-size", type=int, default=None, help="最小聚类大小（默认 30）")
    p_et.add_argument("--nr-topics", type=int, default=None, help="目标主题数（默认自然聚类）")

    p_es = p_explore_sub.add_parser("search", help="探索库搜索（语义/关键词/融合）")
    p_es.add_argument("--name", required=True, help="探索库名称")
    p_es.add_argument("query", nargs="+", help="查询文本")
    p_es.add_argument("--top", type=int, default=None, help="返回条数")
    p_es.add_argument(
        "--mode", choices=["semantic", "keyword", "unified"], default="semantic", help="搜索模式（默认 semantic）"
    )

    p_ev = p_explore_sub.add_parser("viz", help="生成全部可视化（HTML）")
    p_ev.add_argument("--name", required=True, help="探索库名称")

    p_el = p_explore_sub.add_parser("list", help="列出所有探索库")

    p_ei = p_explore_sub.add_parser("info", help="查看探索库信息")
    p_ei.add_argument("--name", default=None, help="探索库名称（省略列出全部）")
