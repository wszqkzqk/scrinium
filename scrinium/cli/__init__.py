"""
cli/ — scrinium 命令行入口（按域拆分的包）
=============================================

命令：
    scrinium index [--rebuild]
    scrinium search <query> [--top N] [--year Y] [--journal J] [--type T] [--tag T]
    scrinium search <query> --scope main,proceedings,explore:*,arxiv [--top N]
    scrinium search-author <query> [--top N] [--year Y] [--journal J] [--type T]
    scrinium show <paper-id> [--layer 1|2|3|4] [--lang LANG] [--json] [--append-notes TEXT]
    scrinium enrich toc [<paper-id> | --all] [--force]
    scrinium enrich abstract [--dry-run] [--doi-fetch]
    scrinium top-cited [--top N] [--year Y] [--journal J] [--type T]
    scrinium references <paper-id>
    scrinium cited-by <paper-id>
    scrinium shared-references <id1> <id2> ... [--min N]
    scrinium snowball <paper-id>... [--depth 1] [--top N] [--ws NAME] [--json]
    scrinium refresh [<paper-id> | --all] [--force]
    scrinium rename [<paper-id> | --all] [--dry-run]
    scrinium audit [--severity error|warning|info]
    scrinium tag <paper-id> [<标签> ...] [--remove] [--json]
    scrinium tags [--json]
    scrinium topics [<标签>] [--json]
    scrinium pending
    scrinium repair <paper-id> --title "..." [--doi DOI] [--author NAME] [--year Y] [--no-api] [--dry-run]   （库内论文原地改名；data/pending 待确认项查重后入库）
    scrinium ingest [--dry-run] [--no-api] [--force] ...   (= pipeline 的 ingest 预设)
    scrinium pipeline <preset> | --steps <s1,s2,...> [--list] [--dry-run] ...
    scrinium metrics [--last N] [--category CAT] [--since DATE]
    scrinium insights [--days N]
    scrinium setup [check] [--lang en|zh]
    scrinium explore fetch [--issn X] [--concept C] [--topic-id T] [--author A] [--institution I]
                              [--keyword K] [--source-type T] [--oa-type T] [--min-citations N]
                              [--name NAME] [--year-range Y] [--incremental] [--limit N]
    scrinium explore search --name <NAME> <query> [--top N]
    scrinium explore list
    scrinium explore info [--name NAME]
    scrinium export bibtex|ris|markdown [<paper-id> ...] [--all] [--year Y] [--journal J] [-o FILE]
    scrinium export docx [-i input.md] [-o output.docx] [--title T]
    scrinium import endnote <file.xml|file.ris> [--no-api] [--dry-run] [--no-convert]
    scrinium import zotero [--api-key KEY] [--library-id ID] [--local PATH] [--list-collections] ...
    scrinium arxiv search [<query> ...] [--category CAT] [--sort relevance|recent] [--top N]
    scrinium arxiv fetch <arxiv-id-or-url> [--ingest] [--force] [--dry-run]
    scrinium attach-pdf <paper-id> <path/to/paper.pdf>
    scrinium citation-check [<file>] [--ws <workspace-name>]
    scrinium citation-styles list
    scrinium citation-styles show <name>
    scrinium document inspect <file> [--format docx|pptx|xlsx]
    scrinium toolref fetch <tool> [--version V] [--force]
    scrinium toolref show <tool> <path...>
    scrinium toolref search <tool> <query> [--top N] [--program P] [--section S]
    scrinium toolref list [<tool>]
    scrinium toolref use <tool> <version>
    scrinium proceedings apply-split <proceeding_dir> <split_plan.json>
    scrinium proceedings build-clean-candidates <proceeding_dir>
    scrinium proceedings apply-clean <proceeding_dir> <clean_plan.json>
    scrinium workspace init <name>
    scrinium workspace add <name> <paper-refs...> [--search Q] [--tag T] [--all]
    scrinium workspace remove <name> <paper-refs...>
    scrinium workspace list
    scrinium workspace show <name>
    scrinium workspace search <name> <query> [--top N]
    scrinium workspace rename <old-name> <new-name>
    scrinium workspace export <name> [-o FILE]

Legacy aliases（仍然可用，但从 --help 顶层列表隐藏；新代码请用上方主名）：
    fsearch            -> search --scope ...
    enrich-toc         -> enrich toc
    backfill-abstract  -> enrich abstract
    import-endnote     -> import endnote
    import-zotero      -> import zotero
    refetch            -> refresh
    refs               -> references
    citing             -> cited-by
    shared-refs        -> shared-references
    ws                 -> workspace
    style              -> citation-styles
"""

from __future__ import annotations

import argparse
import errno
import logging
import os
import sys

from scrinium import __version__
from scrinium.config import load_config
from scrinium.log import ui

from . import explore, ingest, misc, search, sync, transfer, ws
from .common import (
    _INSTALL_HINTS,
    _add_filter_args,
    _check_import_error,
    _emit_json,
    _record_search_metrics,
    _resolve_export_paper_ids,
    _resolve_paper,
    _resolve_top,
    _resolve_ws_paper_ids,
    _search_result_json,
    _try_resolve_paper,
)
from .explore import cmd_explore
from .ingest import (
    _collect_pending_items,
    _run_batch_enrich,
    _toc_success_message,
    cmd_attach_pdf,
    cmd_audit,
    cmd_backfill_abstract,
    cmd_enrich_toc,
    cmd_pending,
    cmd_pipeline,
    cmd_refetch,
    cmd_rename,
    cmd_repair,
    cmd_tag,
    cmd_tags,
    cmd_topics,
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
    cmd_snowball,
    cmd_style,
    cmd_toolref,
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
    cmd_fsearch,
    cmd_index,
    cmd_search,
    cmd_search_author,
    cmd_show,
    cmd_top_cited,
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
)
from .ws import _raise_ws_not_found, cmd_ws

_log = logging.getLogger(__package__)

__all__ = [
    "_INSTALL_HINTS",
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
    "_emit_json",
    "_format_citations",
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
    "cmd_arxiv_fetch",
    "cmd_arxiv_search",
    "cmd_attach_pdf",
    "cmd_audit",
    "cmd_backfill_abstract",
    "cmd_citation_check",
    "cmd_citing",
    "cmd_document",
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
    "cmd_snowball",
    "cmd_style",
    "cmd_tag",
    "cmd_tags",
    "cmd_toolref",
    "cmd_top_cited",
    "cmd_topics",
    "cmd_ws",
    "load_config",
    "ui",
]


# ============================================================================
#  Entry point
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrinium",
        description="面向 AI coding agent 的研究终端",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    # Explicit metavar keeps hidden legacy aliases out of the usage line.
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    search.register(sub)
    ingest.register(sub)
    explore.register(sub)
    ws.register(sub)
    transfer.register(sub)
    misc.register(sub)
    sync.register(sub)

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

        from scrinium import log as _log
        from scrinium import metrics as _metrics
        from scrinium.ingest.metadata._models import configure_s2_session, configure_session
        from scrinium.ingest.pipeline import PipelineError

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
    except OSError as exc:
        # Windows reports a broken pipe as EINVAL instead of BrokenPipeError.
        if exc.errno not in (errno.EPIPE, errno.EINVAL):
            raise
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)


if __name__ == "__main__":
    main()
