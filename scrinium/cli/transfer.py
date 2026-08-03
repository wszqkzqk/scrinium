"""cli/transfer.py — export / import / arxiv / translate commands."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from scrinium.log import ui

from .common import _check_import_error, _resolve_export_paper_ids, _resolve_paper, _resolve_top

_log = logging.getLogger(__package__)


def cmd_translate(args: argparse.Namespace, cfg) -> None:
    from scrinium.translate import batch_translate, translate_paper

    papers_dir = cfg.papers_dir

    # Determine target language: CLI flag > config default; normalize input
    target_lang = (args.lang or cfg.translate.target_lang).lower().strip()

    try:
        from scrinium.translate import validate_lang

        validate_lang(target_lang)
    except ValueError:
        ui(f"错误: 无效的语言代码 '{target_lang}'（应为 2-5 个小写字母，如 zh、en、ja）")
        sys.exit(1)

    if args.paper_id:
        paper_d = _resolve_paper(args.paper_id, cfg)
        tr = translate_paper(
            paper_d,
            cfg,
            target_lang=target_lang,
            force=args.force,
            portable=args.portable,
            progress_callback=ui,
        )
        if tr.ok:
            ui(f"翻译完成: {tr.path}")
            if tr.portable_path:
                ui(f"可移植导出: {tr.portable_path}")
        else:
            from scrinium.translate import (
                SKIP_ALL_CHUNKS_FAILED,
                SKIP_ALREADY_EXISTS,
                SKIP_EMPTY,
                SKIP_NO_MD,
                SKIP_SAME_LANG,
            )

            _skip_messages = {
                SKIP_NO_MD: "跳过: 该论文目录下无 paper.md 文件",
                SKIP_EMPTY: "跳过: paper.md 内容为空",
                SKIP_SAME_LANG: f"跳过: 论文已是目标语言 ({target_lang})",
                SKIP_ALREADY_EXISTS: "跳过: 翻译已存在（使用 --force 强制重新翻译）",
            }
            if tr.partial and tr.path:
                ui(
                    f"翻译中断：已完成 {tr.completed_chunks}/{tr.total_chunks} 块，"
                    f"当前结果已写入 {tr.path}，可稍后继续续翻"
                )
                sys.exit(1)
            if tr.skip_reason == SKIP_ALL_CHUNKS_FAILED:
                ui("翻译失败: 所有分块都翻译失败，未写出目标文件")
                sys.exit(1)
            ui(_skip_messages.get(tr.skip_reason, "跳过"))
    elif args.all:
        ui(f"批量翻译 → {target_lang}")
        stats = batch_translate(papers_dir, cfg, target_lang=target_lang, force=args.force, portable=args.portable)
        ui(f"完成: {stats['translated']} 已翻译 | {stats['skipped']} 跳过 | {stats['failed']} 失败")
    else:
        ui("请指定 <paper-id> 或 --all")
        sys.exit(1)


def cmd_export(args: argparse.Namespace, cfg) -> None:
    action = args.export_action
    if action == "bibtex":
        _cmd_export_bibtex(args, cfg)
    elif action == "ris":
        _cmd_export_ris(args, cfg)
    elif action == "markdown":
        _cmd_export_markdown(args, cfg)
    elif action == "docx":
        _cmd_export_docx(args, cfg)
    else:
        _log.error("未知导出操作: %s", action)
        sys.exit(1)


def _cmd_export_ris(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_ris

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)
    paper_ids = _resolve_export_paper_ids(paper_ids, cfg)

    ris = export_ris(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not ris:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(ris, encoding="utf-8")
        count = ris.count("TY  -")
        ui(f"已导出到 {out}（{count} 篇）")
    else:
        print(ris)


def _cmd_export_markdown(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_markdown_refs

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)
    paper_ids = _resolve_export_paper_ids(paper_ids, cfg)

    style = getattr(args, "style", "apa") or "apa"

    try:
        md = export_markdown_refs(
            cfg.papers_dir,
            cfg=cfg,
            paper_ids=paper_ids,
            year=args.year,
            journal=args.journal,
            numbered=not args.bullet,
            style=style,
        )
    except (FileNotFoundError, ValueError, AttributeError, ImportError) as e:
        _log.error("%s", e)
        sys.exit(1)

    if not md:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(md, encoding="utf-8")
        count = md.count("\n")
        ui(f"已导出到 {out}（{count} 条引用，{style} 格式）")
    else:
        print(md)


def _cmd_export_docx(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_docx

    # Determine input content
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            _log.error("输入文件不存在: %s", args.input)
            sys.exit(1)
        content = input_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        _log.error("请通过 --input 指定 Markdown 文件，或通过 stdin 传入内容")
        sys.exit(1)

    output = Path(args.output) if args.output else cfg._root / "workspace" / "output.docx"

    try:
        export_docx(content, output, title=args.title or None)
        ui(f"已导出到 {output}")
    except ImportError as e:
        _log.error("%s", e)
        sys.exit(1)


def _cmd_export_bibtex(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_bibtex

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("请指定论文 ID 或 --all")
        sys.exit(1)
    paper_ids = _resolve_export_paper_ids(paper_ids, cfg)

    bib = export_bibtex(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not bib:
        ui("未找到匹配的论文")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(bib, encoding="utf-8")
        ui(f"已导出到 {out}（{bib.count('@')} 篇）")
    else:
        print(bib)


def cmd_arxiv_search(args: argparse.Namespace, cfg) -> None:
    from scrinium.sources.arxiv import search_arxiv

    query = " ".join(args.query).strip()
    top_k = _resolve_top(args, 10)
    category = (args.category or "").strip()
    sort = args.sort or "relevance"

    if not query and not category:
        ui("请至少提供检索词，或使用 --category 指定 arXiv 分类。")
        return

    ui(f'arXiv 搜索: query="{query or "*"}" category={category or "-"} sort={sort}\n')

    try:
        results = search_arxiv(query, top_k=top_k, category=category, sort=sort)
    except Exception as e:
        ui(f"arXiv 搜索失败: {e}")
        return
    if not results:
        ui("arXiv 不可用或无结果")
        return

    for i, r in enumerate(results, 1):
        authors = r.get("authors", [])
        first = (authors[0] if authors else "?") + (" et al." if len(authors) > 1 else "")
        ui(f"  [{i}] [{r.get('year', '?')}] {r.get('title', '')}")
        ui(f"       {first} | arxiv:{r.get('arxiv_id', '')}")
        if r.get("doi"):
            ui(f"       doi:{r['doi']}")
        if r.get("abstract"):
            ui(f"       {r['abstract'][:220]}{'...' if len(r['abstract']) > 220 else ''}")
        ui()


def cmd_arxiv_fetch(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.pipeline import PRESETS, PipelineOptions, run_pipeline
    from scrinium.sources.arxiv import download_arxiv_pdf, normalize_arxiv_ref

    canonical_id = normalize_arxiv_ref(args.arxiv_ref)
    if not canonical_id:
        ui(f"无效的 arXiv 标识或 URL: {args.arxiv_ref}")
        return

    if args.dry_run:
        if args.ingest:
            ui(f"[dry-run] 将下载 arXiv PDF 并直接入库: {canonical_id}")
        else:
            ui(f"[dry-run] 将下载 arXiv PDF 到 inbox: {canonical_id}")
        return

    if args.ingest:
        ui(f"开始直接入库 arXiv 预印本: {canonical_id}")
        try:
            with tempfile.TemporaryDirectory(prefix="scrinium_arxiv_") as tmpdir:
                tmp_inbox = Path(tmpdir)
                pdf_path = download_arxiv_pdf(canonical_id, tmp_inbox, overwrite=args.force)
                ui(f"已下载 PDF: {pdf_path.name}")
                run_pipeline(
                    PRESETS["ingest"],
                    cfg,
                    PipelineOptions(inbox_dir=tmp_inbox, force=args.force, include_aux_inboxes=False),
                )
        except Exception as e:
            ui(f"arXiv 下载或入库失败: {e}")
        return

    inbox_dir = cfg._root / "data" / "inbox"
    try:
        pdf_path = download_arxiv_pdf(canonical_id, inbox_dir, overwrite=args.force)
    except Exception as e:
        ui(f"arXiv 下载失败: {e}")
        return
    ui(f"已下载到 inbox: {pdf_path}")


def cmd_import_endnote(args: argparse.Namespace, cfg) -> None:
    try:
        from scrinium.sources.endnote import parse_endnote_full
    except ImportError as e:
        _check_import_error(e)

    from scrinium.ingest.pipeline import import_external

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            ui(f"错误：文件不存在: {p}")
            sys.exit(1)

    try:
        records, pdf_paths = parse_endnote_full(paths)
    except ImportError as e:
        _check_import_error(e)

    if not records:
        ui("未解析到任何记录")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"解析到 {len(records)} 条记录，{n_pdfs} 个可匹配 PDF")
    else:
        ui(f"解析到 {len(records)} 条记录")

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + enrich (toc/l3/abstract)
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)


def _batch_convert_pdfs(cfg, *, enrich: bool = False) -> None:
    """Convert all unprocessed PDFs in papers_dir to paper.md via MinerU."""
    from scrinium.ingest.pipeline import batch_convert_pdfs

    batch_convert_pdfs(cfg, enrich=enrich)


def cmd_import_zotero(args: argparse.Namespace, cfg) -> None:
    import tempfile

    # Resolve credentials
    api_key = args.api_key or cfg.resolved_zotero_api_key()
    library_id = args.library_id or cfg.resolved_zotero_library_id()
    library_type = args.library_type or cfg.zotero.library_type

    # Local SQLite mode
    if args.local:
        db_path = Path(args.local)
        if not db_path.exists():
            ui(f"错误：Zotero 数据库不存在: {db_path}")
            sys.exit(1)

        from scrinium.sources.zotero import list_collections_local, parse_zotero_local

        if args.list_collections:
            collections = list_collections_local(db_path)
            if not collections:
                ui("没有找到 collections")
                return
            ui(f"{'Key':<12} {'Items':>5}  Name")
            ui("-" * 50)
            for c in collections:
                ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
            return

        records, pdf_paths = parse_zotero_local(
            db_path,
            collection_key=args.collection,
            item_types=args.item_type,
        )
    else:
        # Web API mode
        if not api_key:
            ui("错误：需要 Zotero API key（--api-key 或 config.local.yaml zotero.api_key 或 ZOTERO_API_KEY 环境变量）")
            sys.exit(1)
        if not library_id:
            ui(
                "错误：需要 Zotero library ID（--library-id 或 config.local.yaml zotero.library_id 或 ZOTERO_LIBRARY_ID 环境变量）"
            )
            sys.exit(1)

        try:
            from scrinium.sources.zotero import fetch_zotero_api, list_collections_api
        except ImportError as e:
            _check_import_error(e)

        if args.list_collections:
            collections = list_collections_api(library_id, api_key, library_type=library_type)
            if not collections:
                ui("没有找到 collections")
                return
            ui(f"{'Key':<12} {'Items':>5}  Name")
            ui("-" * 50)
            for c in collections:
                ui(f"{c['key']:<12} {c['numItems']:>5}  {c['name']}")
            return

        download_pdfs = not args.no_pdf
        pdf_dir = Path(tempfile.mkdtemp(prefix="scrinium_zotero_")) if download_pdfs else None

        records, pdf_paths = fetch_zotero_api(
            library_id,
            api_key,
            library_type=library_type,
            collection_key=args.collection,
            item_types=args.item_type,
            download_pdfs=download_pdfs,
            pdf_dir=pdf_dir,
        )

    if not records:
        ui("未获取到任何记录")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"获取到 {len(records)} 条记录，{n_pdfs} 个 PDF")
    else:
        ui(f"获取到 {len(records)} 条记录")

    from scrinium.ingest.pipeline import import_external

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + enrich (toc/l3/abstract)
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg, enrich=True)

    # Import collections as workspaces
    if args.import_collections and not args.dry_run:
        _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type)


def _import_zotero_collections_as_workspaces(args, cfg, api_key, library_id, library_type):
    """Create workspaces from Zotero collections after import."""

    from scrinium import workspace
    from scrinium.papers import iter_paper_dirs

    if args.local:
        from scrinium.sources.zotero import list_collections_local, parse_zotero_local

        collections = list_collections_local(Path(args.local))
    else:
        from scrinium.sources.zotero import list_collections_api

        collections = list_collections_api(library_id, api_key, library_type=library_type)

    # Build DOI → UUID map from existing papers
    from scrinium.papers import read_meta

    doi_to_uuid: dict[str, str] = {}
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            meta = read_meta(pdir)
        except (ValueError, FileNotFoundError):
            continue
        if meta.get("doi") and meta.get("id"):
            doi_to_uuid[meta["doi"].lower()] = meta["id"]

    ws_root = cfg._root / "workspace"
    for coll in collections:
        name = coll["name"].replace("/", "-").replace(" ", "_")
        ws_dir = ws_root / name

        # Get papers in this collection
        if args.local:
            coll_records, _ = parse_zotero_local(
                Path(args.local),
                collection_key=coll["key"],
            )
        else:
            from scrinium.sources.zotero import fetch_zotero_api

            coll_records, _ = fetch_zotero_api(
                library_id,
                api_key,
                library_type=library_type,
                collection_key=coll["key"],
                download_pdfs=False,
            )

        # Match to ingested papers by DOI
        uuids = []
        for r in coll_records:
            if r.doi and r.doi.lower() in doi_to_uuid:
                uuids.append(doi_to_uuid[r.doi.lower()])

        if not uuids:
            continue

        workspace.create(ws_dir)
        workspace.add(ws_dir, uuids, cfg.index_db)
        ui(f"工作区 {name}: {len(uuids)} 篇论文")


def _add_import_endnote_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``import endnote`` and its legacy alias ``import-endnote``."""
    p.set_defaults(func=cmd_import_endnote)
    p.add_argument("files", nargs="+", help="Endnote 导出文件（.xml 或 .ris）")
    p.add_argument("--no-api", action="store_true", help="跳过 API 查询，仅用文件中的元数据")
    p.add_argument("--dry-run", action="store_true", help="预览，不实际导入")
    p.add_argument("--no-convert", action="store_true", help="跳过 PDF → paper.md 转换（默认自动转换）")


def _add_import_zotero_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``import zotero`` and its legacy alias ``import-zotero``."""
    p.set_defaults(func=cmd_import_zotero)
    p.add_argument("--local", metavar="SQLITE_PATH", help="使用本地 zotero.sqlite")
    p.add_argument("--api-key", help="Zotero API key")
    p.add_argument("--library-id", help="Zotero library ID")
    p.add_argument("--library-type", choices=["user", "group"], help="Library 类型（默认 user）")
    p.add_argument("--collection", metavar="KEY", help="仅导入指定 collection")
    p.add_argument("--item-type", nargs="+", help="限定 item 类型（如 journalArticle conferencePaper）")
    p.add_argument("--list-collections", action="store_true", help="列出所有 collections 后退出")
    p.add_argument("--no-pdf", action="store_true", help="跳过 PDF 下载/复制")
    p.add_argument("--no-api", action="store_true", help="跳过学术 API 查询")
    p.add_argument("--dry-run", action="store_true", help="预览，不实际导入")
    p.add_argument("--no-convert", action="store_true", help="跳过 PDF → paper.md 转换")
    p.add_argument("--import-collections", action="store_true", help="将 Zotero collections 创建为工作区")


def register(sub) -> None:
    """Register transfer-domain subcommands."""
    # --- export ---
    p_export = sub.add_parser("export", help="导出论文或文档（BibTeX / RIS / Markdown / DOCX）")
    p_export.set_defaults(func=cmd_export)
    p_export_sub = p_export.add_subparsers(dest="export_action", required=True)

    p_eb = p_export_sub.add_parser("bibtex", help="导出 BibTeX 格式（LaTeX 引用）")
    p_eb.add_argument("paper_ids", nargs="*", help="论文 ID（目录名 / UUID / DOI，可多个）")
    p_eb.add_argument("--all", action="store_true", help="导出全部论文")
    p_eb.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_eb.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_eb.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_er = p_export_sub.add_parser("ris", help="导出 RIS 格式（Zotero / Endnote / Mendeley 导入）")
    p_er.add_argument("paper_ids", nargs="*", help="论文 ID（目录名 / UUID / DOI，可多个）")
    p_er.add_argument("--all", action="store_true", help="导出全部论文")
    p_er.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_er.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_er.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_em = p_export_sub.add_parser("markdown", help="导出 Markdown 文献列表（可直接粘贴到文档）")
    p_em.add_argument("paper_ids", nargs="*", help="论文 ID（目录名 / UUID / DOI，可多个）")
    p_em.add_argument("--all", action="store_true", help="导出全部论文")
    p_em.add_argument("--year", type=str, default=None, help="年份过滤：2023 / 2020-2024")
    p_em.add_argument("--journal", type=str, default=None, help="期刊名过滤（模糊匹配）")
    p_em.add_argument("--bullet", action="store_true", help="使用无序列表（默认有序）")
    p_em.add_argument(
        "--style",
        type=str,
        default="apa",
        help="引用格式：apa（默认）/ vancouver / chicago-author-date / mla / <自定义>",
    )
    p_em.add_argument("-o", "--output", type=str, default=None, help="输出文件路径（省略则输出到屏幕）")

    p_ed = p_export_sub.add_parser("docx", help="将 Markdown 文本导出为 Word DOCX 文件")
    p_ed.add_argument("--input", "-i", type=str, default=None, help="输入 Markdown 文件路径（省略则从 stdin 读取）")
    p_ed.add_argument(
        "--output", "-o", type=str, default=None, help="输出 .docx 文件路径（默认 workspace/output.docx）"
    )
    p_ed.add_argument("--title", type=str, default=None, help="文档标题（可选，插入为一级标题）")

    # --- import (grouped entry point; legacy aliases hidden) ---
    p_import = sub.add_parser("import", help="从外部文献管理器导入论文（Endnote / Zotero）")
    p_import_sub = p_import.add_subparsers(dest="import_action", required=True)
    _add_import_endnote_args(p_import_sub.add_parser("endnote", help="从 Endnote XML/RIS 导入论文元数据"))
    _add_import_zotero_args(p_import_sub.add_parser("zotero", help="从 Zotero 导入论文元数据和 PDF"))

    # --- import-endnote (legacy alias of `import endnote`; no help => hidden) ---
    _add_import_endnote_args(sub.add_parser("import-endnote"))

    # --- import-zotero (legacy alias of `import zotero`; no help => hidden) ---
    _add_import_zotero_args(sub.add_parser("import-zotero"))

    # --- arxiv ---
    p_arxiv = sub.add_parser("arxiv", help="arXiv 检索与拉取工具")
    p_arxiv_sub = p_arxiv.add_subparsers(dest="arxiv_action", required=True)

    p_arxiv_search = p_arxiv_sub.add_parser("search", help="搜索 arXiv 预印本")
    p_arxiv_search.set_defaults(func=cmd_arxiv_search)
    p_arxiv_search.add_argument("query", nargs="*", help="检索词（可省略，配合 --category 使用）")
    p_arxiv_search.add_argument("--top", type=int, default=None, help="最多返回 N 条（默认 10）")
    p_arxiv_search.add_argument("--category", type=str, default="", help="arXiv 分类，如 physics.flu-dyn")
    p_arxiv_search.add_argument(
        "--sort", choices=["relevance", "recent"], default="relevance", help="排序方式（默认 relevance）"
    )

    p_arxiv_fetch = p_arxiv_sub.add_parser("fetch", help="下载 arXiv PDF，可选直接入库")
    p_arxiv_fetch.set_defaults(func=cmd_arxiv_fetch)
    p_arxiv_fetch.add_argument("arxiv_ref", help="arXiv ID、arXiv:ID、abs URL 或 pdf URL")
    p_arxiv_fetch.add_argument("--ingest", action="store_true", help="下载后直接走 ingest pipeline 入库")
    p_arxiv_fetch.add_argument("--force", action="store_true", help="覆盖已有同名 PDF 或强制 pipeline 处理")
    p_arxiv_fetch.add_argument("--dry-run", action="store_true", help="预览将要执行的操作")

    # --- translate ---
    p_trans = sub.add_parser("translate", help="翻译论文 Markdown 到目标语言")
    p_trans.set_defaults(func=cmd_translate)
    p_trans.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_trans.add_argument("--all", action="store_true", help="批量翻译所有论文")
    p_trans.add_argument("--lang", type=str, default=None, help="目标语言（默认读 config translate.target_lang）")
    p_trans.add_argument("--force", action="store_true", help="强制重新翻译（覆盖已有翻译）")
    p_trans.add_argument(
        "--portable",
        action="store_true",
        help="额外导出到 workspace/translation-ws/ 的可移植翻译包（复制 images/）",
    )
