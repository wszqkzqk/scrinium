"""cli/search.py — index/search/show commands and federated search."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scrinium.log import ui

from .common import (
    _add_filter_args,
    _add_tag_arg,
    _emit_json,
    _record_search_metrics,
    _resolve_paper,
    _resolve_tag_filters,
    _resolve_top,
    _search_result_json,
)

_log = logging.getLogger(__package__)

# Handoff hint shown when a paper has no L3 conclusion yet (agent writes it).
_L3_MISSING_HINT = (
    "该论文尚无结论。hint: 建议 agent（或派 subagent）阅读全文（--layer 4）后写入 "
    "meta.json 的 l3_conclusion 字段，并运行 scrinium index 使其可检索"
)


def cmd_index(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import build_index

    papers_dir = cfg.papers_dir
    db_path = cfg.index_db

    if not papers_dir.exists():
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    action = "重建索引" if args.rebuild else "构建索引"
    ui(f"{action}: {papers_dir} -> {db_path}")
    count = build_index(papers_dir, db_path, rebuild=args.rebuild)
    ui(f"完成：已索引 {count} 篇论文。")
    ui("下一步：运行 `scrinium search <关键词>` 开始检索。")


def cmd_search_author(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import search_author

    query = " ".join(args.query)
    try:
        results = search_author(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if not results:
        ui(f'未找到作者 "{query}" 的相关论文。')
        return

    ui(f'按作者检索到 {len(results)} 篇论文（"{query}"）:\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def cmd_search(args: argparse.Namespace, cfg) -> None:
    # --scope delegates to federated search; keyword is the only retrieval mode.
    if getattr(args, "scope", None):
        cmd_fsearch(args, cfg)
        return

    import time

    from scrinium.index import search
    from scrinium.metrics import get_store

    query = " ".join(args.query)
    tags = _resolve_tag_filters(args, cfg)
    t0 = time.monotonic()
    try:
        results = search(
            query,
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
            tags=tags,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    elapsed = time.monotonic() - t0
    store = get_store()
    _record_search_metrics(store, "search", query, results, elapsed, args)

    if getattr(args, "json", False):
        _emit_json({"query": query, "count": len(results), "results": [_search_result_json(r) for r in results]})
        return

    if not results:
        ui(f'未找到与 "{query}" 相关的结果。')
        return

    ui(f'关键词检索到 {len(results)} 篇论文（"{query}"）:\n')
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def _show_json(args: argparse.Namespace, l1: dict, notes: str | None, json_path: Path, md_path: Path) -> None:
    """Emit ``show --json`` output: L1 metadata plus the fields of the requested layer."""
    from scrinium.loader import load_l2, load_l3, load_l4

    payload: dict = {
        "id": l1["paper_id"],
        "dir_name": l1.get("dir_name", ""),
        "title": l1.get("title") or "",
        "authors": l1.get("authors") or [],
        "year": l1.get("year"),
        "journal": l1.get("journal") or "",
        "doi": l1.get("doi") or "",
        "paper_type": l1.get("paper_type") or "",
        "citation_count": l1.get("citation_count") or {},
        "layer": args.layer,
    }
    if notes:
        payload["notes"] = notes

    if args.layer == 2:
        payload["abstract"] = load_l2(json_path)
    elif args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log.error(_L3_MISSING_HINT)
            sys.exit(1)
        payload["conclusion"] = conclusion
    elif args.layer == 4:
        if not md_path.exists():
            _log.error("未找到 paper.md：%s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scrinium.loader import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                _log.error("无效的语言代码 '%s'", lang)
                sys.exit(1)
            payload["lang"] = lang
        payload["content"] = load_l4(md_path, lang=lang)

    _emit_json(payload)


def cmd_show(args: argparse.Namespace, cfg) -> None:
    from scrinium.loader import append_notes, load_l1, load_l2, load_l3, load_l4, load_notes
    from scrinium.metrics import get_store

    paper_d = _resolve_paper(args.paper_id, cfg)
    json_path = paper_d / "meta.json"
    md_path = paper_d / "paper.md"

    # Handle --append-notes (append, then continue to show content)
    if getattr(args, "append_notes", None):
        notes_text = str(args.append_notes).strip()
        if not notes_text:
            ui("警告：--append-notes 内容为空，已忽略。")
        else:
            try:
                append_notes(paper_d, notes_text)
            except (UnicodeDecodeError, OSError) as e:
                _log.error("追加笔记失败：%s", e)
                ui(f"追加笔记到 {paper_d.name}/notes.md 失败：{e}")
            else:
                ui(f"已追加笔记到 {paper_d.name}/notes.md")

    l1 = load_l1(json_path)
    l1["dir_name"] = paper_d.name

    # Curated tags are shown in the L1 header when present
    from scrinium.tags import paper_tags

    l1["tags"] = paper_tags(paper_d)

    # Load existing agent notes (T2 layer) if available
    try:
        notes = load_notes(paper_d)
    except (UnicodeDecodeError, OSError) as e:
        _log.warning("读取 notes.md 失败：%s", e)
        notes = None

    store = get_store()

    def _record_read() -> None:
        if store:
            try:
                store.record(
                    category="read",
                    name=paper_d.name,  # use dir_name so insights can find the paper
                    detail={
                        "layer": args.layer,
                        "title": l1.get("title", ""),
                        "doi": l1.get("doi", ""),
                    },
                )
            except Exception as _e:
                _log.debug("metrics record failed: %s", _e)

    if getattr(args, "json", False):
        _show_json(args, l1, notes, json_path, md_path)
        _record_read()
        return

    _print_header(l1)

    if notes:
        ui("\n--- Agent 笔记 (notes.md) ---\n")
        ui(notes)
        ui("\n--- 笔记结束 ---\n")

    if args.layer == 1:
        _record_read()
        return

    if args.layer == 2:
        abstract = load_l2(json_path)
        ui("\n--- 摘要 ---\n")
        ui(abstract)
        _record_read()
        return

    if args.layer == 3:
        conclusion = load_l3(json_path)
        if conclusion is None:
            _log.error(_L3_MISSING_HINT)
            sys.exit(1)
        ui("\n--- 结论 ---\n")
        ui(conclusion)
        _record_read()
        return

    if args.layer == 4:
        if not md_path.exists():
            _log.error("未找到 paper.md：%s", md_path)
            sys.exit(1)
        lang = getattr(args, "lang", None)
        if lang:
            from scrinium.loader import validate_lang

            try:
                lang = validate_lang(lang)
            except ValueError:
                ui(f"错误: 无效的语言代码 '{lang}'")
                sys.exit(1)
            translated_path = md_path.parent / f"paper_{lang}.md"
            if translated_path.exists():
                ui(f"\n--- 全文（{lang}） ---\n")
            else:
                ui(f"\n--- 全文（原文，paper_{lang}.md 不存在） ---\n")
        else:
            ui("\n--- 全文 ---\n")
        ui(load_l4(md_path, lang=lang))
        _record_read()
        return


def cmd_top_cited(args: argparse.Namespace, cfg) -> None:
    from scrinium.index import top_cited

    try:
        results = top_cited(
            cfg.index_db,
            top_k=_resolve_top(args, cfg.search.top_k),
            year=args.year,
            journal=args.journal,
            paper_type=args.paper_type,
        )
    except FileNotFoundError as e:
        _log.error("%s", e)
        sys.exit(1)

    if getattr(args, "json", False):
        _emit_json({"count": len(results), "results": [_search_result_json(r) for r in results]})
        return

    if not results:
        ui("索引中没有引用数据。请先运行 scrinium refetch --all。")
        return

    ui(f"按引用量排序的前 {len(results)} 篇论文：\n")
    for i, r in enumerate(results, start=1):
        _print_search_result(i, r)
    _print_search_next_steps()


def _search_arxiv(query: str, top_k: int) -> list[dict]:
    """Call arXiv Atom API, return simplified paper dicts."""
    from scrinium.sources.arxiv import search_arxiv

    return search_arxiv(query, top_k)


def _query_dois_for_set(cfg, doi_set: list[str]) -> set[str]:
    """Return the subset of doi_set that exists in the main library (case-insensitive).

    Only queries the specific DOIs requested, so this is O(len(doi_set)) regardless
    of library size. Returns an empty set if the index DB is missing or on any error.
    """
    import sqlite3

    if not doi_set or not Path(cfg.index_db).exists():
        return set()
    try:
        normalized = [d.lower() for d in doi_set]
        placeholders = ",".join("?" * len(normalized))
        with sqlite3.connect(str(cfg.index_db)) as conn:
            rows = conn.execute(
                f"SELECT doi FROM papers_registry WHERE LOWER(doi) IN ({placeholders})",
                normalized,
            ).fetchall()
        return {r[0].lower() for r in rows}
    except Exception:
        return set()


def _query_arxiv_ids_for_set(cfg, arxiv_id_set: list[str]) -> set[str]:
    """Return the subset of normalized arXiv IDs that exists in the main library."""
    from scrinium.papers import iter_paper_dirs, read_meta
    from scrinium.sources.arxiv import normalize_arxiv_ref

    if not arxiv_id_set or not Path(cfg.papers_dir).exists():
        return set()

    wanted: set[str] = set()
    for arxiv_id in arxiv_id_set:
        normalized = normalize_arxiv_ref(arxiv_id)
        if normalized:
            wanted.add(normalized)
    if not wanted:
        return set()

    found: set[str] = set()
    try:
        for paper_dir in iter_paper_dirs(Path(cfg.papers_dir)):
            try:
                meta = read_meta(paper_dir)
            except Exception:
                continue
            arxiv_id = meta.get("arxiv_id") or (meta.get("ids") or {}).get("arxiv", "")
            normalized = normalize_arxiv_ref(arxiv_id)
            if normalized and normalized in wanted:
                found.add(normalized)
    except Exception:
        return set()
    return found


def cmd_fsearch(args: argparse.Namespace, cfg) -> None:
    query = " ".join(args.query)
    top_k = _resolve_top(args, 10)
    scope_str = args.scope or "main"
    scopes = [s.strip() for s in scope_str.split(",") if s.strip()] or ["main"]

    ui(f'联邦搜索: "{query}"  scope={scope_str}\n')

    for scope in scopes:
        if scope == "main":
            ui("── [主库] ──")
            if not cfg.index_db.exists():
                ui("  主库索引不存在，请先运行 scrinium index")
                results = []
            else:
                from scrinium.index import search

                try:
                    results = search(query, cfg.index_db, top_k=top_k, cfg=cfg)
                except Exception as e:
                    ui(f"  主库搜索失败：{e}")
                    results = []
            if not results:
                ui("  无结果")
            else:
                for i, r in enumerate(results, 1):
                    _print_search_result(i, r)
            ui()

        elif scope.startswith("explore:"):
            explore_name = scope[len("explore:") :]
            from scrinium.explore import validate_explore_name

            if explore_name != "*" and not validate_explore_name(explore_name):
                ui(f"  无效的 explore 库名 '{explore_name}'：不能为空，且不能包含路径分隔符或 '..'")
                ui()
                continue
            if explore_name == "*":
                from scrinium.explore import list_explore_libs

                names = list_explore_libs(cfg)
                if not names:
                    ui("── [explore: *] ──")
                    ui("  暂无 explore 库，请先运行 scrinium explore fetch --name <名称>")
                    ui()
            else:
                names = [explore_name]

            for name in names:
                ui(f"── [explore: {name}] ──")
                from scrinium.explore import explore_db_path, explore_search

                db = explore_db_path(name, cfg)
                if not db.exists():
                    ui(f"  explore 库 {name} 不存在或未建索引（explore.db 缺失）")
                    ui()
                    continue
                try:
                    results = explore_search(name, query, top_k=top_k, cfg=cfg)
                except Exception as e:
                    ui(f"  搜索失败: {e}")
                    ui()
                    continue
                if not results:
                    ui("  无结果")
                else:
                    for i, r in enumerate(results, 1):
                        authors = r.get("authors", [])
                        first = authors[0] if authors else "?"
                        score = r.get("score", 0.0)
                        ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
                        ui(f"       {first} | 分数: {score:.3f}")
                        ui()

        elif scope == "arxiv":
            ui("── [arXiv] ──")
            arxiv_results = _search_arxiv(query, top_k)
            if not arxiv_results:
                ui("  arXiv 不可用或无结果")
            else:
                # Only query the library for DOIs that actually appear in results
                arxiv_dois = [r["doi"].lower() for r in arxiv_results if r.get("doi")]
                arxiv_ids = [r.get("arxiv_id", "") for r in arxiv_results if r.get("arxiv_id")]
                in_lib_dois = _query_dois_for_set(cfg, arxiv_dois)
                in_lib_arxiv_ids = _query_arxiv_ids_for_set(cfg, arxiv_ids)
                for i, r in enumerate(arxiv_results, 1):
                    from scrinium.sources.arxiv import normalize_arxiv_ref

                    authors = r.get("authors", [])
                    first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
                    doi = r.get("doi", "")
                    arxiv_id = r.get("arxiv_id", "")
                    normalized_arxiv_id = normalize_arxiv_ref(arxiv_id)
                    in_lib = bool(
                        (doi and doi.lower() in in_lib_dois)
                        or (normalized_arxiv_id and normalized_arxiv_id in in_lib_arxiv_ids)
                    )
                    status = "  [已入库]" if in_lib else ""
                    ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}{status}")
                    ui(f"       {first} | arxiv:{arxiv_id}" + (f" | doi:{doi}" if doi else ""))
                    ui()

        elif scope == "proceedings":
            ui("── [论文集] ──")
            from scrinium.index import search_proceedings
            from scrinium.proceedings import proceedings_db_path

            db = proceedings_db_path(cfg._root)
            if not db.exists():
                ui("  proceedings 索引不存在，请先导入论文集")
                results = []
            else:
                try:
                    results = search_proceedings(query, db, top_k=top_k)
                except Exception as e:
                    ui(f"  proceedings 搜索失败：{e}")
                    results = []
            if not results:
                ui("  无结果")
            else:
                for i, r in enumerate(results, 1):
                    extra = f"proceedings:{r.get('proceeding_title', r.get('proceeding_dir', '?'))}"
                    _print_search_result(i, r, extra=extra)
            ui()

        else:
            ui(f"  未知 scope: {scope}，支持: main / proceedings / explore:NAME / explore:* / arxiv")


def _print_search_result(idx: int, r: dict, extra: str = "") -> None:
    authors = r.get("authors") or ""
    author_display = authors.split(",")[0].strip() + (" et al." if "," in authors else "")
    cite = r.get("citation_count") or ""
    cite_suffix = f"  [被引: {cite}]" if cite else ""
    extra_suffix = f"  ({extra})" if extra else ""
    # Prefer dir_name for display, fall back to paper_id (UUID)
    display_id = r.get("dir_name") or r["paper_id"]
    ui(f"[{idx}] {display_id}{extra_suffix}")
    ui(f"     {author_display} | {r.get('year', '?')} | {r.get('journal', '?')}{cite_suffix}")
    ui(f"     {r['title']}")
    ui()


def _print_search_next_steps(include_ws_add: bool = True) -> None:
    ui("下一步：可以运行 `scrinium show <paper-id> --layer 2/3/4` 查看摘要、结论或全文。")
    if include_ws_add:
        ui("也可以运行 `scrinium workspace add <工作区名> <paper-id>` 把感兴趣的论文加入工作区。")


def _format_citations(cc: dict) -> str:
    if not cc:
        return ""
    parts = []
    for src in ("semantic_scholar", "openalex", "crossref"):
        if src in cc:
            label = {"semantic_scholar": "S2", "openalex": "OA", "crossref": "CR"}[src]
            parts.append(f"{label}:{cc[src]}")
    return " | ".join(parts)


def _print_header(l1: dict) -> None:
    authors = l1.get("authors") or []
    author_str = ", ".join(authors[:3])
    if len(authors) > 3:
        author_str += f" et al. ({len(authors)} total)"
    ui(f"论文ID   : {l1['paper_id']}")
    if l1.get("dir_name"):
        ui(f"目录名   : {l1['dir_name']}")
    ui(f"标题     : {l1['title']}")
    ui(f"作者     : {author_str}")
    ui(f"年份     : {l1.get('year') or '?'}  |  期刊: {l1.get('journal') or '?'}")
    if l1.get("doi"):
        ui(f"DOI      : {l1['doi']}")
    ids = l1.get("ids") or {}
    if ids.get("patent_publication_number"):
        ui(f"公开号   : {ids['patent_publication_number']}")
    if l1.get("paper_type"):
        ui(f"类型     : {l1['paper_type']}")
    tags = l1.get("tags") or []
    if tags:
        ui(f"标签     : {', '.join(tags)}")
    cite_str = _format_citations(l1.get("citation_count") or {})
    if cite_str:
        ui(f"引用     : {cite_str}")
    if ids.get("semantic_scholar_url"):
        ui(f"S2       : {ids['semantic_scholar_url']}")
    if ids.get("openalex_url"):
        ui(f"OpenAlex : {ids['openalex_url']}")


def register(sub) -> None:
    """Register search-domain subcommands."""
    # --- index ---
    p_index = sub.add_parser("index", help="构建 FTS5 检索索引")
    p_index.set_defaults(func=cmd_index)
    p_index.add_argument("--rebuild", action="store_true", help="清空后重建")

    # --- search ---
    p_search = sub.add_parser(
        "search",
        help="关键词检索论文（--scope 跨库联邦搜索）",
    )
    p_search.set_defaults(func=cmd_search)
    p_search.add_argument("query", nargs="+", help="检索词")
    p_search.add_argument(
        "--scope",
        type=str,
        default=None,
        help="提供时执行联邦搜索（逗号分隔）：main / proceedings / explore:NAME / explore:* / arxiv",
    )
    p_search.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    p_search.add_argument("--json", action="store_true", help="以 JSON 格式输出结果（便于管道解析）")
    _add_filter_args(p_search)
    _add_tag_arg(p_search)

    # --- search-author ---
    p_sa = sub.add_parser("search-author", help="按作者名搜索")
    p_sa.set_defaults(func=cmd_search_author)
    p_sa.add_argument("query", nargs="+", help="作者名（模糊匹配）")
    p_sa.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    _add_filter_args(p_sa)

    # --- show ---
    p_show = sub.add_parser("show", help="查看论文内容")
    p_show.set_defaults(func=cmd_show)
    p_show.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_show.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2, 3, 4],
        help="加载层级：1=元数据, 2=摘要, 3=结论, 4=全文（默认 2）",
    )
    p_show.add_argument("--lang", type=str, default=None, help="加载翻译版本（如 zh），仅 L4 生效")
    p_show.add_argument("--json", action="store_true", help="以 JSON 格式输出（便于管道解析）")
    p_show.add_argument(
        "--append-notes",
        type=str,
        default=None,
        metavar="TEXT",
        help="向论文笔记 notes.md 追加内容（T2 层，跨会话复用）",
    )

    # --- top-cited ---
    p_tc = sub.add_parser("top-cited", help="按引用量排序查看论文")
    p_tc.set_defaults(func=cmd_top_cited)
    p_tc.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认读 config search.top_k）")
    p_tc.add_argument("--json", action="store_true", help="以 JSON 格式输出结果（便于管道解析）")
    _add_filter_args(p_tc)

    # --- fsearch (legacy alias of `search --scope`; no help => hidden) ---
    p_fsearch = sub.add_parser("fsearch")
    p_fsearch.set_defaults(func=cmd_fsearch)
    p_fsearch.add_argument("query", nargs="+", help="检索词")
    p_fsearch.add_argument(
        "--scope",
        type=str,
        default="main",
        help="搜索范围（逗号分隔）：main / proceedings / explore:NAME / explore:* / arxiv（默认 main）",
    )
    p_fsearch.add_argument("--top", type=int, default=None, help="每个来源最多返回 N 条（默认 10）")
