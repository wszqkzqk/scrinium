"""
cli/ — scholaraio 命令行入口（按域拆分的包）
=============================================

命令：
    scholaraio index [--rebuild]
    scholaraio embed [--rebuild]
    scholaraio search <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio search-author <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio vsearch <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio usearch <query> [--top N] [--year Y] [--journal J] [--type T]
    scholaraio show <paper-id> [--layer 1|2|3|4]
    scholaraio enrich-toc [<paper-id> | --all] [--force] [--inspect]
    scholaraio enrich-l3 [<paper-id> | --all] [--force] [--inspect] [--max-retries N]
    scholaraio top-cited [--top N] [--year Y] [--journal J] [--type T]
    scholaraio refs <paper-id>
    scholaraio citing <paper-id>
    scholaraio shared-refs <id1> <id2> ... [--min N]
    scholaraio refetch [<paper-id> | --all] [--force]
    scholaraio rename [<paper-id> | --all] [--dry-run]
    scholaraio audit [--severity error|warning|info]
    scholaraio pending
    scholaraio repair <paper-id> --title "..." [--doi DOI] [--author NAME] [--year Y] [--no-api] [--dry-run]
    scholaraio backfill-abstract [--dry-run]
    scholaraio topics [--build] [--rebuild] [--viz] [--topic ID]
    scholaraio pipeline <preset> | --steps <s1,s2,...> [--list] [--dry-run] ...
    scholaraio metrics [--summary] [--last N] [--category CAT] [--since DATE]
    scholaraio setup [check] [--lang en|zh]
    scholaraio explore fetch --issn <ISSN> [--name NAME] [--year-range Y]
    scholaraio explore embed --name <NAME> [--rebuild]
    scholaraio explore topics --name <NAME> [--build] [--rebuild] [--topic ID]
    scholaraio explore search --name <NAME> <query> [--top N]
    scholaraio explore viz --name <NAME>
    scholaraio explore list
    scholaraio explore info [--name NAME]
    scholaraio export bibtex [<paper-id> ...] [--all] [--year Y] [--journal J] [-o FILE]
    scholaraio translate [<paper-id> | --all] [--lang LANG] [--force]
    scholaraio import-endnote <file.xml|file.ris> [--no-api] [--dry-run] [--no-convert]
    scholaraio import-zotero [--api-key KEY] [--library-id ID] [--local PATH] [--list-collections] ...
    scholaraio attach-pdf <paper-id> <path/to/paper.pdf>
    scholaraio citation-check [<file>] [--ws <workspace-name>]
    scholaraio proceedings apply-split <proceeding_dir> <split_plan.json>
    scholaraio proceedings build-clean-candidates <proceeding_dir>
    scholaraio proceedings apply-clean <proceeding_dir> <clean_plan.json>
    scholaraio ws init <name>
    scholaraio ws add <name> <paper-refs...> [--search Q] [--topic ID] [--all]
    scholaraio ws remove <name> <paper-refs...>
    scholaraio ws list
    scholaraio ws show <name>
    scholaraio ws search <name> <query> [--top N] [--mode unified|keyword|semantic]
    scholaraio ws rename <old-name> <new-name>
    scholaraio ws export <name> [-o FILE]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from scholaraio import __version__
from scholaraio.config import load_config
from scholaraio.log import ui

from . import explore, ingest, misc, search, transfer, ws
from .common import (
    _INSTALL_HINTS,
    _add_filter_args,
    _check_import_error,
    _count_registry_papers,
    _emit_json,
    _format_match_tag,
    _record_search_metrics,
    _resolve_export_paper_ids,
    _resolve_paper,
    _resolve_top,
    _resolve_ws_paper_ids,
    _search_result_json,
    _try_resolve_paper,
    _write_all_viz,
)
from .explore import cmd_explore
from .ingest import (
    _PENDING_SUGGESTIONS,
    _collect_pending_items,
    _run_batch_enrich,
    _toc_success_message,
    cmd_attach_pdf,
    cmd_audit,
    cmd_backfill_abstract,
    cmd_enrich_l3,
    cmd_enrich_toc,
    cmd_pending,
    cmd_pipeline,
    cmd_refetch,
    cmd_rename,
    cmd_repair,
)
from .misc import (
    _cmd_document_inspect,
    _cmd_style_list,
    _cmd_style_show,
    cmd_citation_check,
    cmd_citing,
    cmd_document,
    cmd_insights,
    cmd_metrics,
    cmd_proceedings,
    cmd_refs,
    cmd_setup,
    cmd_shared_refs,
    cmd_style,
    cmd_toolref,
    cmd_topics,
)
from .search import (
    _format_citations,
    _print_header,
    _print_search_next_steps,
    _print_search_result,
    _query_arxiv_ids_for_set,
    _query_dois_for_set,
    _search_arxiv,
    _show_json,
    cmd_embed,
    cmd_fsearch,
    cmd_index,
    cmd_search,
    cmd_search_author,
    cmd_show,
    cmd_top_cited,
    cmd_usearch,
    cmd_vsearch,
)
from .transfer import (
    _batch_convert_pdfs,
    _cmd_export_bibtex,
    _cmd_export_docx,
    _cmd_export_markdown,
    _cmd_export_ris,
    _import_zotero_collections_as_workspaces,
    cmd_arxiv_fetch,
    cmd_arxiv_search,
    cmd_export,
    cmd_import_endnote,
    cmd_import_zotero,
    cmd_translate,
)
from .ws import _raise_ws_not_found, cmd_ws

_log = logging.getLogger(__package__)

__all__ = [
    "_INSTALL_HINTS",
    "_PENDING_SUGGESTIONS",
    "_add_filter_args",
    "_batch_convert_pdfs",
    "_check_import_error",
    "_cmd_document_inspect",
    "_cmd_export_bibtex",
    "_cmd_export_docx",
    "_cmd_export_markdown",
    "_cmd_export_ris",
    "_cmd_style_list",
    "_cmd_style_show",
    "_collect_pending_items",
    "_count_registry_papers",
    "_emit_json",
    "_format_citations",
    "_format_match_tag",
    "_import_zotero_collections_as_workspaces",
    "_print_header",
    "_print_search_next_steps",
    "_print_search_result",
    "_query_arxiv_ids_for_set",
    "_query_dois_for_set",
    "_raise_ws_not_found",
    "_record_search_metrics",
    "_resolve_export_paper_ids",
    "_resolve_paper",
    "_resolve_top",
    "_resolve_ws_paper_ids",
    "_run_batch_enrich",
    "_search_arxiv",
    "_search_result_json",
    "_show_json",
    "_toc_success_message",
    "_try_resolve_paper",
    "_write_all_viz",
    "cmd_arxiv_fetch",
    "cmd_arxiv_search",
    "cmd_attach_pdf",
    "cmd_audit",
    "cmd_backfill_abstract",
    "cmd_citation_check",
    "cmd_citing",
    "cmd_document",
    "cmd_embed",
    "cmd_enrich_l3",
    "cmd_enrich_toc",
    "cmd_explore",
    "cmd_export",
    "cmd_fsearch",
    "cmd_import_endnote",
    "cmd_import_zotero",
    "cmd_index",
    "cmd_insights",
    "cmd_metrics",
    "cmd_pending",
    "cmd_pipeline",
    "cmd_proceedings",
    "cmd_refetch",
    "cmd_refs",
    "cmd_rename",
    "cmd_repair",
    "cmd_search",
    "cmd_search_author",
    "cmd_setup",
    "cmd_shared_refs",
    "cmd_show",
    "cmd_style",
    "cmd_toolref",
    "cmd_top_cited",
    "cmd_topics",
    "cmd_translate",
    "cmd_usearch",
    "cmd_vsearch",
    "cmd_ws",
    "load_config",
    "ui",
]


# ============================================================================
#  Entry point
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholaraio",
        description="面向 AI coding agent 的研究终端",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    search.register(sub)
    ingest.register(sub)
    explore.register(sub)
    ws.register(sub)
    transfer.register(sub)
    misc.register(sub)

    return parser


def main() -> None:
    # A downstream pipe closing early (e.g. `| head`) makes every logging flush
    # fail with BrokenPipeError; don't dump "--- Logging error ---" tracebacks
    # for that. The pipe itself is handled below (exit 0).
    logging.raiseExceptions = False

    parser = _build_parser()

    try:
        args = parser.parse_args()
        cfg = load_config()
        cfg.ensure_dirs()

        from scholaraio import log as _log
        from scholaraio import metrics as _metrics
        from scholaraio.ingest.metadata._models import configure_s2_session, configure_session
        from scholaraio.ingest.pipeline import PipelineError

        session_id = _log.setup(cfg)
        if getattr(args, "json", False):
            # Keep stdout reserved for the JSON payload; logs go to stderr.
            _log.set_console_stream(sys.stderr)
        is_setup_cmd = args.command == "setup"
        try:
            _metrics.init(cfg.metrics_db_path, session_id)
        except Exception as exc:
            if not is_setup_cmd:
                raise
            ui(f"警告：metrics 初始化失败，已跳过，不影响 setup: {exc}")
        configure_session(cfg.ingest.contact_email)
        configure_s2_session(cfg.resolved_s2_api_key())

        try:
            args.func(args, cfg)
        except (ValueError, PipelineError) as exc:
            # CLI boundary: argument-level ValueError (e.g. bad --year) and fatal
            # pipeline errors (e.g. MinerU unreachable) get a one-line message
            # instead of a traceback; the message is still shown.
            ui(f"错误: {exc}")
            sys.exit(1)
        # Surface a buffered broken pipe here instead of at interpreter shutdown.
        sys.stdout.flush()
    except BrokenPipeError:
        # Downstream closed the pipe early (e.g. `| head`): not a failure.
        # Redirect stdout to devnull so the shutdown flush cannot raise again.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)


if __name__ == "__main__":
    main()
