"""Standalone CLI for metadata extraction (python -m scrinium.ingest.metadata)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_log = logging.getLogger(__name__)

from scrinium.log import ui

from ._api import enrich_metadata
from ._extract import _extract_lastname
from ._models import PaperMetadata
from ._writer import (
    generate_new_stem,
    metadata_to_dict,
    rename_files,
    write_metadata_json,
)


def cmd_show(args: argparse.Namespace) -> None:
    """Parse and display metadata without writing files."""
    from ._extract import extract_metadata_from_markdown

    filepath = Path(args.file).resolve()
    if not filepath.exists():
        _log.error("file not found: %s", filepath)
        sys.exit(1)

    meta = extract_metadata_from_markdown(filepath)
    ui(f"Title:    {meta.title}")
    ui(f"Authors:  {', '.join(meta.authors) if meta.authors else '(none)'}")
    ui(f"1st auth: {meta.first_author} -> lastname: {meta.first_author_lastname}")
    ui(f"Year:     {meta.year}")
    ui(f"DOI:      {meta.doi or '(none)'}")
    ui(f"Journal:  {meta.journal or '(none)'}")
    ui(f"Rename -> {generate_new_stem(meta)}")


def _process_one(
    filepath: Path,
    *,
    no_api: bool = False,
    no_rename: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
    extractor=None,
) -> tuple[bool, PaperMetadata]:
    """Process a single markdown file. Returns (success, metadata)."""
    from scrinium.ingest.extractor import RegexExtractor

    extractor = extractor or RegexExtractor()

    _log.info("processing: %s", filepath.name)

    # Step 1: Extract from markdown
    meta = extractor.extract(filepath)
    ui(f"Title:  {meta.title[:80]}{'...' if len(meta.title) > 80 else ''}")
    ui(f"Author: {meta.first_author_lastname or '?'} | Year: {meta.year or '?'} | DOI: {meta.doi or 'none'}")

    # Step 2: API enrichment
    if not no_api:
        _log.debug("querying APIs...")
        meta = enrich_metadata(meta)
        if meta.citation_count_crossref is not None:
            _log.debug("[CR] citations: %s", meta.citation_count_crossref)
        if meta.citation_count_s2 is not None:
            _log.debug("[S2] citations: %s", meta.citation_count_s2)
        if meta.citation_count_openalex is not None:
            _log.debug("[OA] citations: %s", meta.citation_count_openalex)
        if meta.paper_type:
            _log.debug("type: %s", meta.paper_type)
        if meta.extraction_method:
            _log.debug("method: %s", meta.extraction_method)
    else:
        meta.extraction_method = "local_only"

    # Step 3: Write JSON
    json_path = filepath.with_suffix(".json")
    if not dry_run:
        write_metadata_json(meta, json_path)
        _log.info("wrote: %s", json_path.name)
    else:
        _log.debug("would write: %s", json_path.name)
        if verbose:
            d = metadata_to_dict(meta)
            ui(json.dumps(d, indent=2, ensure_ascii=False))

    # Step 4: Rename
    if not no_rename:
        new_stem = generate_new_stem(meta)
        new_md, new_json = rename_files(filepath, json_path, new_stem, dry_run=dry_run)

    _log.info("done.")
    return True, meta


def cmd_extract(args: argparse.Namespace) -> None:
    """Full extraction pipeline (single file)."""
    filepath = Path(args.file).resolve()
    if not filepath.exists():
        _log.error("file not found: %s", filepath)
        sys.exit(1)
    _process_one(
        filepath,
        no_api=args.no_api,
        no_rename=args.no_rename,
        dry_run=args.dry_run,
    )


def cmd_batch(args: argparse.Namespace) -> None:
    """Batch-process all markdown files in a directory."""
    dirpath = Path(args.directory).resolve()
    if not dirpath.is_dir():
        _log.error("not a directory: %s", dirpath)
        sys.exit(1)

    # Collect .md files (recursive or flat)
    pattern = "**/*.md" if args.recursive else "*.md"
    all_md = sorted(dirpath.glob(pattern))

    # Skip files that already have a .json sibling (unless --force)
    if args.force:
        targets = all_md
    else:
        targets = [f for f in all_md if not f.with_suffix(".json").exists()]

    if not targets:
        _log.info("no unprocessed .md files in %s%s", dirpath, " (use --force to reprocess)" if all_md else "")
        return

    total = len(targets)
    skipped = len(all_md) - total
    _log.info("found %d file(s) to process%s", total, f" ({skipped} skipped, already have .json)" if skipped else "")

    succeeded = 0
    failed = 0
    # Polite delay: with S2 API key, requests are authenticated (1 req/s allowed);
    # without key, public rate limit is tight (100 req/5min), so wait longer.
    from ._models import SESSION

    _has_s2_key = bool(SESSION.headers.get("x-api-key"))
    api_delay = (1.0 if _has_s2_key else 3.0) if not args.no_api else 0  # polite delay to avoid S2 rate limit

    for i, filepath in enumerate(targets, 1):
        _log.info("[%d/%d] %s", i, total, filepath.name)
        try:
            ok, _ = _process_one(
                filepath,
                no_api=args.no_api,
                no_rename=args.no_rename,
                dry_run=args.dry_run,
                verbose=False,
            )
            if ok:
                succeeded += 1
        except Exception as e:
            _log.error("failed: %s", e)
            failed += 1

        # Polite delay between files to avoid API rate limiting
        if api_delay and i < total and not args.no_api:
            time.sleep(api_delay)

    # Summary
    ui(f"batch complete: {succeeded} succeeded, {failed} failed, {skipped} skipped")


def cmd_fix(args: argparse.Namespace) -> None:
    """Fix metadata for a file by manually providing correct title/DOI/author,
    then run API enrichment, write JSON, and rename."""
    filepath = Path(args.file).resolve()
    if not filepath.exists():
        _log.error("file not found: %s", filepath)
        sys.exit(1)

    # Build PaperMetadata from CLI args (skip md parsing entirely)
    meta = PaperMetadata()
    meta.title = args.title
    meta.doi = args.doi or ""
    meta.year = args.year
    meta.source_file = filepath.name
    if args.author:
        meta.authors = [args.author]
        meta.first_author = args.author
        meta.first_author_lastname = _extract_lastname(args.author)

    _log.info("fixing: %s", filepath.name)
    ui(f"Title:  {meta.title}")
    ui(f"Author: {meta.first_author or '?'} | Year: {meta.year or '?'} | DOI: {meta.doi or 'none'}")

    # API enrichment
    if not args.no_api:
        _log.debug("querying APIs...")
        # Save CLI-provided values to restore if API doesn't override
        cli_author = meta.first_author
        cli_lastname = meta.first_author_lastname
        cli_year = meta.year

        meta = enrich_metadata(meta)

        # If CLI provided author but API didn't find authors, restore CLI value
        if cli_author and not meta.authors:
            meta.authors = [cli_author]
            meta.first_author = cli_author
            meta.first_author_lastname = cli_lastname
        # If CLI provided year but API didn't find one, restore CLI value
        if cli_year and not meta.year:
            meta.year = cli_year

        if meta.citation_count_crossref is not None:
            _log.debug("[CR] citations: %s", meta.citation_count_crossref)
        if meta.citation_count_s2 is not None:
            _log.debug("[S2] citations: %s", meta.citation_count_s2)
        if meta.citation_count_openalex is not None:
            _log.debug("[OA] citations: %s", meta.citation_count_openalex)
        if meta.extraction_method:
            _log.debug("method: %s", meta.extraction_method)
    else:
        meta.extraction_method = "manual_fix"

    # Show final metadata
    ui(f"Final -> {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}...")

    # Write JSON
    json_path = filepath.with_suffix(".json")
    if not args.dry_run:
        write_metadata_json(meta, json_path)
        _log.info("wrote: %s", json_path.name)
    else:
        d = metadata_to_dict(meta)
        _log.debug("would write: %s", json_path.name)
        ui(json.dumps(d, indent=2, ensure_ascii=False))

    # Rename
    if not args.no_rename:
        new_stem = generate_new_stem(meta)
        rename_files(filepath, json_path, new_stem, dry_run=args.dry_run)

    _log.info("done.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scrinium ingest metadata",
        description="Extract metadata from MinerU paper markdown, query citation APIs, rename files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_show = sub.add_parser("show", help="Preview extracted metadata (no writes)")
    p_show.add_argument("file", type=str, help="Path to MinerU markdown file")

    p_extract = sub.add_parser("extract", help="Extract metadata, query APIs, write JSON, rename")
    p_extract.add_argument("file", type=str, help="Path to MinerU markdown file")
    p_extract.add_argument("--dry-run", action="store_true", help="Preview without writing/renaming")
    p_extract.add_argument("--no-rename", action="store_true", help="Write JSON but don't rename")
    p_extract.add_argument("--no-api", action="store_true", help="Skip API queries")

    p_batch = sub.add_parser("batch", help="Batch-process all .md files in a directory")
    p_batch.add_argument("directory", type=str, help="Directory containing .md files")
    p_batch.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    p_batch.add_argument("--force", action="store_true", help="Reprocess files that already have .json")
    p_batch.add_argument("--dry-run", action="store_true", help="Preview without writing/renaming")
    p_batch.add_argument("--no-rename", action="store_true", help="Write JSON but don't rename")
    p_batch.add_argument("--no-api", action="store_true", help="Skip API queries")

    p_fix = sub.add_parser("fix", help="Fix metadata with manual title/DOI/author, then enrich via API")
    p_fix.add_argument("file", type=str, help="Path to .md file to fix")
    p_fix.add_argument("--title", required=True, help="Correct paper title")
    p_fix.add_argument("--doi", default="", help="Known DOI (speeds up API lookup)")
    p_fix.add_argument("--author", default="", help="First author full name")
    p_fix.add_argument("--year", type=int, default=None, help="Publication year")
    p_fix.add_argument("--dry-run", action="store_true", help="Preview without writing/renaming")
    p_fix.add_argument("--no-rename", action="store_true", help="Write JSON but don't rename")
    p_fix.add_argument("--no-api", action="store_true", help="Skip API queries")

    args = parser.parse_args()

    # Ensure S2 API key is configured for standalone CLI usage
    # (the main scrinium CLI does this in cli/__init__.py:main(); this covers
    # `python -m scrinium.ingest.metadata` invocations.)
    from scrinium.config import load_config

    from ._models import configure_s2_session

    _cfg = load_config()
    configure_s2_session(_cfg.resolved_s2_api_key())

    if args.command == "show":
        cmd_show(args)
    elif args.command == "extract":
        cmd_extract(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "fix":
        cmd_fix(args)
