"""cli/transfer.py — export / import / arxiv commands."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from scrinium.log import ui

from .common import _check_import_error, _resolve_export_paper_ids, _resolve_top

_log = logging.getLogger(__package__)


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
        _log.error("Unknown export action: %s", action)
        sys.exit(1)


def _cmd_export_ris(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_ris

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("Specify paper IDs or --all")
        sys.exit(1)
    paper_ids = _resolve_export_paper_ids(paper_ids, cfg)

    ris = export_ris(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not ris:
        ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(ris, encoding="utf-8")
        count = ris.count("TY  -")
        ui(f"Exported to {out} ({count} entries)")
    else:
        print(ris)


def _cmd_export_markdown(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_markdown_refs

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("Specify paper IDs or --all")
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
        ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(md, encoding="utf-8")
        count = md.count("\n")
        ui(f"Exported to {out} ({count} references, {style} style)")
    else:
        print(md)


def _cmd_export_docx(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_docx

    # Determine input content
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            _log.error("Input file does not exist: %s", args.input)
            sys.exit(1)
        content = input_path.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        _log.error("Specify a Markdown file via --input, or pipe content via stdin")
        sys.exit(1)

    output = Path(args.output) if args.output else cfg._root / "workspace" / "output.docx"

    try:
        export_docx(content, output, title=args.title or None)
        ui(f"Exported to {output}")
    except ImportError as e:
        _log.error("%s", e)
        sys.exit(1)


def _cmd_export_bibtex(args: argparse.Namespace, cfg) -> None:
    from scrinium.export import export_bibtex

    paper_ids = args.paper_ids if args.paper_ids else None
    if not paper_ids and not args.all:
        _log.error("Specify paper IDs or --all")
        sys.exit(1)
    paper_ids = _resolve_export_paper_ids(paper_ids, cfg)

    bib = export_bibtex(
        cfg.papers_dir,
        paper_ids=paper_ids,
        year=args.year,
        journal=args.journal,
    )

    if not bib:
        ui("No matching papers found")
        return

    if args.output:
        out = Path(args.output)
        out.write_text(bib, encoding="utf-8")
        ui(f"Exported to {out} ({bib.count('@')} entries)")
    else:
        print(bib)


def cmd_arxiv_search(args: argparse.Namespace, cfg) -> None:
    from scrinium.sources.arxiv import search_arxiv

    query = " ".join(args.query).strip()
    top_k = _resolve_top(args, 10)
    category = (args.category or "").strip()
    sort = args.sort or "relevance"

    if not query and not category:
        ui("Provide at least one search term, or specify an arXiv category with --category.")
        return

    ui(f'arXiv search: query="{query or "*"}" category={category or "-"} sort={sort}\n')

    try:
        results = search_arxiv(query, top_k=top_k, category=category, sort=sort)
    except Exception as e:
        ui(f"arXiv search failed: {e}")
        return
    if not results:
        ui("arXiv unavailable or no results")
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
        ui(f"Invalid arXiv identifier or URL: {args.arxiv_ref}")
        return

    if args.dry_run:
        if args.ingest:
            ui(f"[dry-run] Would download arXiv PDF and ingest directly: {canonical_id}")
        else:
            ui(f"[dry-run] Would download arXiv PDF to inbox: {canonical_id}")
        return

    if args.ingest:
        ui(f"Starting direct ingest of arXiv preprint: {canonical_id}")
        try:
            with tempfile.TemporaryDirectory(prefix="scrinium_arxiv_") as tmpdir:
                tmp_inbox = Path(tmpdir)
                pdf_path = download_arxiv_pdf(canonical_id, tmp_inbox, overwrite=args.force)
                ui(f"Downloaded PDF: {pdf_path.name}")
                run_pipeline(
                    PRESETS["ingest"],
                    cfg,
                    PipelineOptions(inbox_dir=tmp_inbox, force=args.force, include_aux_inboxes=False),
                )
        except Exception as e:
            ui(f"arXiv download or ingest failed: {e}")
        return

    inbox_dir = cfg._root / "data" / "inbox"
    try:
        pdf_path = download_arxiv_pdf(canonical_id, inbox_dir, overwrite=args.force)
    except Exception as e:
        ui(f"arXiv download failed: {e}")
        return
    ui(f"Downloaded to inbox: {pdf_path}")


def cmd_import_endnote(args: argparse.Namespace, cfg) -> None:
    try:
        from scrinium.sources.endnote import parse_endnote_full
    except ImportError as e:
        _check_import_error(e)

    from scrinium.ingest.pipeline import import_external

    paths = [Path(f) for f in args.files]
    for p in paths:
        if not p.exists():
            ui(f"Error: file not found: {p}")
            sys.exit(1)

    try:
        records, pdf_paths = parse_endnote_full(paths)
    except ImportError as e:
        _check_import_error(e)

    if not records:
        ui("No records parsed")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"Parsed {len(records)} records, {n_pdfs} matchable PDFs")
    else:
        ui(f"Parsed {len(records)} records")

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + abstract backfill
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg)


def _batch_convert_pdfs(cfg) -> None:
    """Convert all unprocessed PDFs in papers_dir to paper.md via MinerU."""
    from scrinium.ingest.pipeline import batch_convert_pdfs

    batch_convert_pdfs(cfg)


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
            ui(f"Error: Zotero database not found: {db_path}")
            sys.exit(1)

        from scrinium.sources.zotero import list_collections_local, parse_zotero_local

        if args.list_collections:
            collections = list_collections_local(db_path)
            if not collections:
                ui("No collections found")
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
            ui(
                "Error: Zotero API key required (--api-key, config.local.yaml zotero.api_key, or ZOTERO_API_KEY env var)"
            )
            sys.exit(1)
        if not library_id:
            ui(
                "Error: Zotero library ID required "
                "(--library-id, config.local.yaml zotero.library_id, or ZOTERO_LIBRARY_ID env var)"
            )
            sys.exit(1)

        try:
            from scrinium.sources.zotero import fetch_zotero_api, list_collections_api
        except ImportError as e:
            _check_import_error(e)

        if args.list_collections:
            collections = list_collections_api(library_id, api_key, library_type=library_type)
            if not collections:
                ui("No collections found")
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
        ui("No records fetched")
        return

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    if n_pdfs:
        ui(f"Fetched {len(records)} records, {n_pdfs} PDFs")
    else:
        ui(f"Fetched {len(records)} records")

    from scrinium.ingest.pipeline import import_external

    stats = import_external(
        records,
        cfg,
        pdf_paths=pdf_paths,
        no_api=args.no_api,
        dry_run=args.dry_run,
    )

    # Batch convert PDFs → paper.md via MinerU + abstract backfill
    if not args.dry_run and not args.no_convert and stats["ingested"] > 0:
        _batch_convert_pdfs(cfg)

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
        ui(f"Workspace {name}: {len(uuids)} papers")


def _add_import_endnote_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``import endnote`` and its legacy alias ``import-endnote``."""
    p.set_defaults(func=cmd_import_endnote)
    p.add_argument("files", nargs="+", help="Endnote export files (.xml or .ris)")
    p.add_argument("--no-api", action="store_true", help="Skip API queries; use only metadata in the file")
    p.add_argument("--dry-run", action="store_true", help="Preview without importing")
    p.add_argument(
        "--no-convert", action="store_true", help="Skip PDF -> paper.md conversion (converts automatically by default)"
    )


def _add_import_zotero_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``import zotero`` and its legacy alias ``import-zotero``."""
    p.set_defaults(func=cmd_import_zotero)
    p.add_argument("--local", metavar="SQLITE_PATH", help="Use a local zotero.sqlite")
    p.add_argument("--api-key", help="Zotero API key")
    p.add_argument("--library-id", help="Zotero library ID")
    p.add_argument("--library-type", choices=["user", "group"], help="Library type (default: user)")
    p.add_argument("--collection", metavar="KEY", help="Import only the specified collection")
    p.add_argument("--item-type", nargs="+", help="Restrict item types (e.g. journalArticle conferencePaper)")
    p.add_argument("--list-collections", action="store_true", help="List all collections and exit")
    p.add_argument("--no-pdf", action="store_true", help="Skip PDF download/copy")
    p.add_argument("--no-api", action="store_true", help="Skip scholarly API queries")
    p.add_argument("--dry-run", action="store_true", help="Preview without importing")
    p.add_argument("--no-convert", action="store_true", help="Skip PDF -> paper.md conversion")
    p.add_argument("--import-collections", action="store_true", help="Create workspaces from Zotero collections")


def register(sub) -> None:
    """Register transfer-domain subcommands."""
    # --- export ---
    p_export = sub.add_parser("export", help="Export papers or documents (BibTeX / RIS / Markdown / DOCX)")
    p_export.set_defaults(func=cmd_export)
    p_export_sub = p_export.add_subparsers(dest="export_action", required=True)

    p_eb = p_export_sub.add_parser("bibtex", help="Export in BibTeX format (for LaTeX citations)")
    p_eb.add_argument("paper_ids", nargs="*", help="Paper IDs (dir_name / UUID / DOI; multiple allowed)")
    p_eb.add_argument("--all", action="store_true", help="Export all papers")
    p_eb.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_eb.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_eb.add_argument("-o", "--output", type=str, default=None, help="Output file path (prints to stdout if omitted)")

    p_er = p_export_sub.add_parser("ris", help="Export in RIS format (for Zotero / Endnote / Mendeley import)")
    p_er.add_argument("paper_ids", nargs="*", help="Paper IDs (dir_name / UUID / DOI; multiple allowed)")
    p_er.add_argument("--all", action="store_true", help="Export all papers")
    p_er.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_er.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_er.add_argument("-o", "--output", type=str, default=None, help="Output file path (prints to stdout if omitted)")

    p_em = p_export_sub.add_parser("markdown", help="Export a Markdown reference list (ready to paste into documents)")
    p_em.add_argument("paper_ids", nargs="*", help="Paper IDs (dir_name / UUID / DOI; multiple allowed)")
    p_em.add_argument("--all", action="store_true", help="Export all papers")
    p_em.add_argument("--year", type=str, default=None, help="Year filter: 2023 / 2020-2024")
    p_em.add_argument("--journal", type=str, default=None, help="Journal name filter (fuzzy match)")
    p_em.add_argument("--bullet", action="store_true", help="Use bullet list (numbered by default)")
    p_em.add_argument(
        "--style",
        type=str,
        default="apa",
        help="Citation style: apa (default) / vancouver / chicago-author-date / mla / <custom>",
    )
    p_em.add_argument("-o", "--output", type=str, default=None, help="Output file path (prints to stdout if omitted)")

    p_ed = p_export_sub.add_parser("docx", help="Export Markdown text as a Word DOCX file")
    p_ed.add_argument(
        "--input", "-i", type=str, default=None, help="Input Markdown file path (reads from stdin if omitted)"
    )
    p_ed.add_argument(
        "--output", "-o", type=str, default=None, help="Output .docx file path (default: workspace/output.docx)"
    )
    p_ed.add_argument("--title", type=str, default=None, help="Document title (optional; inserted as an H1 heading)")

    # --- import (grouped entry point; legacy aliases hidden) ---
    p_import = sub.add_parser("import", help="Import papers from external reference managers (Endnote / Zotero)")
    p_import_sub = p_import.add_subparsers(dest="import_action", required=True)
    _add_import_endnote_args(p_import_sub.add_parser("endnote", help="Import paper metadata from Endnote XML/RIS"))
    _add_import_zotero_args(p_import_sub.add_parser("zotero", help="Import paper metadata and PDFs from Zotero"))

    # --- import-endnote (legacy alias of `import endnote`; no help => hidden) ---
    _add_import_endnote_args(sub.add_parser("import-endnote"))

    # --- import-zotero (legacy alias of `import zotero`; no help => hidden) ---
    _add_import_zotero_args(sub.add_parser("import-zotero"))

    # --- arxiv ---
    p_arxiv = sub.add_parser("arxiv", help="arXiv search and fetch tools")
    p_arxiv_sub = p_arxiv.add_subparsers(dest="arxiv_action", required=True)

    p_arxiv_search = p_arxiv_sub.add_parser("search", help="Search arXiv preprints")
    p_arxiv_search.set_defaults(func=cmd_arxiv_search)
    p_arxiv_search.add_argument("query", nargs="*", help="Search keywords (optional when --category is used)")
    p_arxiv_search.add_argument("--top", type=int, default=None, help="Return at most N results (default: 10)")
    p_arxiv_search.add_argument("--category", type=str, default="", help="arXiv category, e.g. physics.flu-dyn")
    p_arxiv_search.add_argument(
        "--sort", choices=["relevance", "recent"], default="relevance", help="Sort order (default: relevance)"
    )

    p_arxiv_fetch = p_arxiv_sub.add_parser("fetch", help="Download an arXiv PDF, optionally ingesting it directly")
    p_arxiv_fetch.set_defaults(func=cmd_arxiv_fetch)
    p_arxiv_fetch.add_argument("arxiv_ref", help="arXiv ID, arXiv:ID, abs URL, or pdf URL")
    p_arxiv_fetch.add_argument(
        "--ingest", action="store_true", help="Run the ingest pipeline immediately after download"
    )
    p_arxiv_fetch.add_argument(
        "--force", action="store_true", help="Overwrite an existing PDF with the same name or force pipeline processing"
    )
    p_arxiv_fetch.add_argument("--dry-run", action="store_true", help="Preview the actions that would be taken")
