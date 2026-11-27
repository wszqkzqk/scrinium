"""cli/ingest.py — ingest pipeline, enrichment, pending/audit/repair, attach-pdf."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from pathlib import Path

from scrinium.log import ui

from .common import _emit_json, _resolve_paper

_log = logging.getLogger(__package__)


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    from scrinium.audit import audit_papers, format_report

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    ui(f"Auditing paper library: {papers_dir}\n")
    issues = audit_papers(papers_dir)

    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]

    ui(format_report(issues))


def cmd_tag(args: argparse.Namespace, cfg) -> None:
    from scrinium.tags import normalize_tag, paper_tags, register_tag, resolve_tag, set_paper_tags

    paper_d = _resolve_paper(args.paper_id, cfg)
    current = paper_tags(paper_d)
    raw_names = args.tags or []
    remove = getattr(args, "remove", False)
    json_mode = getattr(args, "json", False)

    # No tag arguments: display current tags
    if not raw_names:
        if json_mode:
            _emit_json({"paper": paper_d.name, "tags": current})
            return
        if current:
            ui(f"Tags for {paper_d.name}: {', '.join(current)}")
        else:
            ui(f"{paper_d.name}: No tags yet (add with scrinium tag {paper_d.name} <tag...>)")
        return

    added: list[str] = []
    removed: list[str] = []
    new_tags: list[str] = []
    final = list(current)
    for name in raw_names:
        canonical = resolve_tag(cfg, name)
        if canonical is None:
            if remove:
                # Allow removing stray tags missing from the taxonomy
                canonical = normalize_tag(name)
            else:
                register_tag(cfg, name)
                canonical = normalize_tag(name)
                new_tags.append(canonical)
        if remove:
            if canonical in final:
                final.remove(canonical)
                removed.append(canonical)
        elif canonical not in final:
            final.append(canonical)
            added.append(canonical)

    set_paper_tags(paper_d, final)

    if json_mode:
        _emit_json(
            {
                "paper": paper_d.name,
                "tags": final,
                "added": added,
                "removed": removed,
                "new_tags": new_tags,
            }
        )
        return

    if remove:
        ui(f"Removed tags: {', '.join(removed) if removed else '(no change)'}")
    else:
        if added:
            ui(f"Added tags: {', '.join(added)}")
        elif not new_tags:
            ui("Tags unchanged")
        for tag in new_tags:
            ui(f"Registered new tag: {tag} (view with scrinium tags)")
    ui(f"Current tags for {paper_d.name}: {', '.join(final) if final else '(none)'}")
    if added or removed:
        ui("Note: run scrinium index for tags to enter the search index")


def cmd_tags(args: argparse.Namespace, cfg) -> None:
    from scrinium.tags import all_tags_with_counts, load_taxonomy

    tax = load_taxonomy(cfg).get("tags") or {}
    counts = all_tags_with_counts(cfg)
    names = sorted(set(tax) | set(counts))

    if not names:
        if getattr(args, "json", False):
            _emit_json({"count": 0, "tags": []})
            return
        ui("Tag vocabulary is empty (create with scrinium tag <paper-id> <tag...>)")
        return

    entries = []
    for name in names:
        entry = tax.get(name) or {}
        entries.append(
            {
                "name": name,
                "aliases": entry.get("aliases") or [],
                "description": entry.get("description") or "",
                "count": counts.get(name, 0),
            }
        )

    if getattr(args, "json", False):
        _emit_json({"count": len(entries), "tags": entries})
        return

    ui(f"Tag vocabulary ({len(entries)} tags)\n")
    for e in entries:
        alias_str = f" (aliases: {', '.join(e['aliases'])})" if e["aliases"] else ""
        desc_str = f"  {e['description']}" if e["description"] else ""
        paper_word = "paper" if e["count"] == 1 else "papers"
        ui(f"  {e['name']}{alias_str}: {e['count']} {paper_word}{desc_str}")
    ui(f"\nTotal: {len(entries)} tags, {sum(counts.values())} taggings")


def cmd_topics(args: argparse.Namespace, cfg) -> None:
    from scrinium.tags import normalize_tag, papers_with_tag, resolve_tag, topic_overview, unknown_tag_message

    json_mode = getattr(args, "json", False)
    tag = getattr(args, "tag", None)

    if tag is None:
        overview = topic_overview(cfg)
        if json_mode:
            _emit_json(overview)
            return
        topics = overview["topics"]
        if not topics:
            ui("Topic vocabulary is empty (create with scrinium tag <paper-id> <tag...>)")
            return
        ui(f"Topic overview: {overview['total_papers']} papers, {len(topics)} topics\n")
        for t in topics:
            desc_str = f"  {t['description']}" if t["description"] else ""
            ui(f"  {t['tag']} ({t['count']} papers, {t['share']:.1%}){desc_str}")
        if overview["untagged_papers"]:
            untagged = overview["untagged_papers"]
            paper_word = "paper" if untagged == 1 else "papers"
            ui(f"\nUntagged: {untagged} {paper_word} (tag with scrinium tag or the curate workflow)")
        return

    canonical = resolve_tag(cfg, tag)
    tagged = papers_with_tag(cfg, tag)
    if not tagged:
        if canonical is None:
            raise ValueError(unknown_tag_message(cfg, tag))
        ui(f"No papers under topic {canonical}")
        return
    papers = [
        {"dir_name": pdir.name, "title": meta.get("title") or "", "year": meta.get("year")} for pdir, meta in tagged
    ]
    # Newest first; stable sort keeps dir-name order within the same year
    papers.sort(key=lambda p: str(p["year"] or ""), reverse=True)
    name = canonical or normalize_tag(tag)
    if json_mode:
        _emit_json({"topic": name, "count": len(papers), "papers": papers})
        return
    paper_word = "paper" if len(papers) == 1 else "papers"
    ui(f"Topic {name}: {len(papers)} {paper_word}\n")
    for i, p in enumerate(papers, 1):
        title = p["title"]
        if len(title) > 70:
            title = title[:67] + "..."
        ui(f"  {i:3d}. [{p['year'] or '?'}] {title}")
        ui(f"       {p['dir_name']}")


def _collect_pending_items(cfg) -> list[dict]:
    """Collect entries from data/pending/ and data/duplicates/ for `scrinium pending`."""
    from scrinium.ingest.pipeline import HINT_PENDING_FALLBACK, PENDING_HINTS

    items: list[dict] = []
    pending_root = cfg._root / "data" / "pending"
    if pending_root.is_dir():
        for d in sorted(pending_root.iterdir()):
            marker = d / "pending.json"
            if not d.is_dir() or not marker.exists():
                continue
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            meta = data.get("extracted_metadata") or {}
            issue = data.get("issue", "unknown")
            items.append(
                {
                    "path": d,
                    "issue": issue,
                    "title": meta.get("title", ""),
                    "duplicate_of": data.get("duplicate_of", ""),
                    "hint": data.get("hint") or PENDING_HINTS.get(issue, HINT_PENDING_FALLBACK),
                }
            )
    dup_root = cfg._root / "data" / "duplicates"
    if dup_root.is_dir():
        for d in sorted(dup_root.iterdir()):
            if not d.is_dir():
                continue
            title = ""
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    title = json.loads(meta_path.read_text(encoding="utf-8")).get("title", "")
                except json.JSONDecodeError:
                    pass
            items.append(
                {
                    "path": d,
                    "issue": "duplicate",
                    "title": title,
                    "duplicate_of": "",
                    "hint": PENDING_HINTS["duplicate"],
                }
            )
    return items


def cmd_pending(args: argparse.Namespace, cfg) -> None:
    items = _collect_pending_items(cfg)
    if not items:
        ui("No pending items")
        return

    ui(f"Pending items ({len(items)} total)\n")
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["issue"], []).append(item)
    for issue in sorted(groups):
        group = groups[issue]
        ui(f"[{issue}] {len(group)} items")
        for item in group:
            ui(f"  {item['path']}")
            if item["title"]:
                ui(f"    Title: {item['title']}")
            if item["duplicate_of"]:
                ui(f"    Duplicate of: {item['duplicate_of']}")
            ui(f"    hint: {item['hint']}")
        ui("")
    summary = " | ".join(f"{issue} {len(groups[issue])}" for issue in sorted(groups))
    ui(f"Summary: {summary} ({len(items)} total)")
    ui(
        "hint: consider dispatching subagents to handle these items using the matching skill workflows "
        "(ingest pending review / audit repair)"
    )


def cmd_repair(args: argparse.Namespace, cfg) -> None:
    import json

    from scrinium.ingest.metadata import (
        PaperMetadata,
        _extract_lastname,
        enrich_metadata,
        generate_new_stem,
        rename_files,
        write_metadata_json,
    )

    papers_dir = cfg.papers_dir
    paper_id = args.paper_id

    # Resolution order: library paper dir first, then the pending queue
    paper_d = papers_dir / paper_id
    md_path = paper_d / "paper.md"
    pending_d: Path | None = None
    if not md_path.exists():
        candidate = cfg._root / "data" / "pending" / paper_id
        if (candidate / "paper.md").exists():
            pending_d = candidate
            paper_d = candidate
            md_path = paper_d / "paper.md"
        else:
            _log.error("File does not exist: %s", md_path)
            sys.exit(1)
    json_path = paper_d / "meta.json"

    # Preserve existing UUID
    existing_uuid = ""
    if json_path.exists():
        try:
            existing_data = json.loads(json_path.read_text(encoding="utf-8"))
            existing_uuid = existing_data.get("id", "")
        except (json.JSONDecodeError, OSError) as e:
            _log.debug("failed to read existing meta.json: %s", e)

    # Build PaperMetadata from CLI args (skip md parsing)
    meta = PaperMetadata()
    meta.id = existing_uuid
    meta.title = args.title
    meta.doi = args.doi or ""
    meta.year = args.year
    meta.source_file = md_path.name
    if args.author:
        meta.authors = [args.author]
        meta.first_author = args.author
        meta.first_author_lastname = _extract_lastname(args.author)

    ui(f"Repairing paper: {paper_id}")
    ui(f"  Title: {meta.title}")
    ui(f"  Author: {meta.first_author or '?'} | Year: {meta.year or '?'} | DOI: {meta.doi or 'none'}")

    # API enrichment
    if not args.no_api:
        _log.debug("querying APIs")
        cli_author = meta.first_author
        cli_lastname = meta.first_author_lastname
        cli_year = meta.year

        meta = enrich_metadata(meta)

        if cli_author and not meta.authors:
            meta.authors = [cli_author]
            meta.first_author = cli_author
            meta.first_author_lastname = cli_lastname
        if cli_year and not meta.year:
            meta.year = cli_year
    else:
        meta.extraction_method = "manual_fix"
        _log.debug("skipping API query (--no-api)")

    ui(f"  Result: {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}")
    if meta.doi:
        ui(f"  DOI: {meta.doi}")
    ui(f"  Method: {meta.extraction_method}")

    # Dedup guard for pending targets: refuse to ingest what the library already has
    if pending_d is not None:
        from scrinium.ingest.pipeline import _collect_existing_ids, _normalize_arxiv_id

        index = _collect_existing_ids(papers_dir)
        dup_of = ""
        doi_key = (meta.doi or "").lower().strip()
        if doi_key and doi_key in index.dois:
            dup_of = index.dois[doi_key].parent.name
        else:
            arxiv_key = _normalize_arxiv_id(meta.arxiv_id)
            if arxiv_key and arxiv_key in index.arxiv_ids:
                dup_of = index.arxiv_ids[arxiv_key].parent.name
        if dup_of:
            ui(
                f"  Refusing to ingest: already in library: {dup_of}; "
                f"once confirmed as a duplicate, this pending item can be deleted: {pending_d}"
            )
            sys.exit(1)
        ui("  Dedup check: no duplicate found in library")

    if args.dry_run:
        ui("  [dry-run] No files written")
        return

    if pending_d is not None:
        _ingest_pending_repair(pending_d, meta, papers_dir)
        return

    # Write new JSON
    write_metadata_json(meta, json_path)
    ui(f"  Written: {json_path.name}")

    new_stem = generate_new_stem(meta)
    rename_files(md_path, json_path, new_stem, dry_run=False)

    _log.debug("done. consider running pipeline reindex")


def _ingest_pending_repair(pending_d: Path, meta, papers_dir: Path) -> None:
    """Finalize repair of a pending item: move it into the library as a new paper.

    Mirrors ``step_ingest`` semantics: standard ``{LastName}-{year}-{Title}``
    directory (``-2`` suffix on collision), meta.json + paper.md + images/,
    then the pending directory is removed (original PDF included).
    """
    import shutil

    from scrinium.ingest.metadata import generate_new_stem, write_metadata_json
    from scrinium.papers import generate_uuid

    papers_dir.mkdir(parents=True, exist_ok=True)
    if not meta.id:
        meta.id = generate_uuid()
    new_stem = generate_new_stem(meta)

    paper_d = papers_dir / new_stem
    suffix = 2
    while paper_d.exists():
        paper_d = papers_dir / f"{new_stem}-{suffix}"
        suffix += 1
    paper_d.mkdir(parents=True)

    write_metadata_json(meta, paper_d / "meta.json")
    shutil.move(str(pending_d / "paper.md"), str(paper_d / "paper.md"))
    images = pending_d / "images"
    if images.is_dir():
        shutil.move(str(images), str(paper_d / "images"))

    # Pending resolved: drop the whole pending dir (original PDF, pending.json, ...)
    shutil.rmtree(pending_d)

    ui(f"  Ingested: {paper_d.name}/")
    ui(f"  Pending item resolved and removed: {pending_d}")
    ui("hint: next step: run `scrinium index` to update the index")


def cmd_enrich_toc(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.pipeline import HINT_TOC_MISS
    from scrinium.loader import enrich_toc
    from scrinium.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Specify <paper-id> or --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_toc(
                json_path,
                md_path,
                force=args.force,
            ),
            success_message=_toc_success_message,
            failure_message="  TOC extraction failed",
            max_retries=2,
        )
        if fail:
            ui(f"hint: TOC extraction failed for {fail} papers; {HINT_TOC_MISS}")
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log.error("Skipped (missing paper.md): %s", json_path.parent.name)
                skip += 1
                continue

            ui(f"\n{json_path.parent.name}")
            ui("  Extracting TOC...")
            success = enrich_toc(
                json_path,
                md_path,
                force=args.force,
            )
            if success:
                ok += 1
                ui(_toc_success_message(json_path))
            else:
                fail += 1
                ui("  TOC extraction failed")
                ui(f"hint: {HINT_TOC_MISS}")

    if args.all or len(targets) > 1:
        ui(f"\nDone: {ok} succeeded | {fail} failed | {skip} skipped")


def cmd_pipeline(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.pipeline import PRESETS, STEPS, PipelineOptions, run_pipeline

    if args.list_steps:
        ui("Available steps:")
        for name, sdef in STEPS.items():
            ui(f"  {name:<10} [{sdef.scope:<7}]  {sdef.desc}")
        ui("\nAvailable presets:")
        for name, steps in PRESETS.items():
            ui(f"  {name:<10} = {', '.join(steps)}")
        return

    # Resolve step list
    if args.preset:
        if args.preset not in PRESETS:
            _log.error("Unknown preset '%s'. Available presets: %s", args.preset, ", ".join(PRESETS))
            sys.exit(1)
        step_names = PRESETS[args.preset]
    elif args.steps:
        step_names = [s.strip() for s in args.steps.split(",") if s.strip()]
    else:
        _log.error("Specify a preset name or use --steps")
        sys.exit(1)

    opts = PipelineOptions(
        dry_run=args.dry_run,
        no_api=args.no_api,
        force=args.force,
        rebuild=args.rebuild,
        inbox_dir=Path(args.inbox).resolve() if args.inbox else None,
        papers_dir=Path(args.papers).resolve() if args.papers else None,
    )

    run_pipeline(step_names, cfg, opts)


def _toc_success_message(json_path: Path) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return f"  TOC extracted: {len(data.get('toc', []))} sections"
    except (OSError, json.JSONDecodeError):
        return "  TOC extracted"


def _run_batch_enrich(
    targets: list[Path],
    cfg,
    *,
    worker_fn,
    success_message: str | callable,
    failure_message: str,
    max_retries: int,
) -> tuple[int, int, int]:
    def _batch_message(json_path: Path, message: str) -> str:
        return f"{json_path.parent.name} | {message.strip()}"

    queued: list[tuple[Path, Path]] = []
    skip = 0
    for json_path in targets:
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            _log.error("Skipped (missing paper.md): %s", json_path.parent.name)
            skip += 1
            continue
        queued.append((json_path, md_path))

    if not queued:
        return 0, 0, skip

    # Rule-based enrich is CPU-bound; a small fixed worker budget is enough.
    workers = min(min(8, os.cpu_count() or 1), len(queued))
    ui(f"Processing concurrently ({workers} workers, {len(queued)} papers)...")

    def _retry_one(json_path: Path, md_path: Path) -> tuple[Path, bool, int]:
        for attempt in range(1, max_retries + 2):
            try:
                success = worker_fn(json_path, md_path)
                if success:
                    return json_path, True, attempt
            except Exception as e:
                _log.warning("Batch enrichment failed (%s, attempt %d): %s", json_path.parent.name, attempt, e)
            if attempt <= max_retries:
                time.sleep(float(2 ** (attempt - 1)))
        return json_path, False, max_retries + 1

    ok = fail = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for json_path, md_path in queued:
            ui(f"\n{_batch_message(json_path, 'Processing...')}")
            futures.append(pool.submit(_retry_one, json_path, md_path))
        for future in concurrent.futures.as_completed(futures):
            json_path, success, attempts = future.result()
            if success:
                ok += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"Succeeded on retry ({attempts} attempts)"))
                ui(
                    _batch_message(
                        json_path,
                        success_message(json_path) if callable(success_message) else success_message,
                    )
                )
            else:
                fail += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"Retried {attempts - 1}/{max_retries} times"))
                ui(_batch_message(json_path, failure_message))

    return ok, fail, skip


def cmd_refetch(args: argparse.Namespace, cfg) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scrinium.ingest.metadata import refetch_metadata
    from scrinium.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [_resolve_paper(args.paper_id, cfg) / "meta.json"]
    else:
        _log.error("Specify <paper-id> or --all")
        sys.exit(1)

    # Filter: only papers missing citations or bibliographic details (unless --force)
    if args.all and not args.force:
        filtered = []
        for jp in targets:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if not data.get("doi"):
                continue
            missing_cite = not data.get("citation_count")
            missing_bib = not all(data.get(k) for k in ("volume", "publisher"))
            if missing_cite or missing_bib:
                filtered.append(jp)
        ui(f"{len(targets)} total, {len(filtered)} need enrichment")
        targets = filtered

    if not targets:
        ui("Nothing to update")
        return

    # Filter out non-existent paths
    valid = []
    fail = 0
    for jp in targets:
        if jp.exists():
            valid.append(jp)
        else:
            _log.error("Paper not found: %s", jp.parent.name)
            fail += 1
    targets = valid
    if not targets:
        if args.all:
            ui("Nothing to update")
            return
        sys.exit(1)

    ok = skip = 0
    total = len(targets)
    workers = min(getattr(args, "jobs", 5) or 5, total)
    ui(f"Concurrent refetch ({workers} workers, {total} papers)...")

    def _do_refetch(jp: Path) -> tuple[Path, bool | None]:
        try:
            return jp, refetch_metadata(jp)
        except Exception as e:
            _log.error("refetch failed for %s: %s", jp.parent.name, e)
            return jp, None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_do_refetch, jp): jp for jp in targets}
        for fut in as_completed(futures):
            jp, changed = fut.result()
            done += 1
            name = jp.parent.name
            if changed is None:
                fail += 1
                ui(f"[{done}/{total}] ✗ {name}")
            elif changed:
                ok += 1
                ui(f"[{done}/{total}] ✓ {name}")
            else:
                skip += 1
                ui(f"[{done}/{total}] - {name}")

    ui(f"\nDone: {ok} updated | {skip} unchanged | {fail} failed")


def cmd_backfill_abstract(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.metadata import backfill_abstracts
    from scrinium.ingest.pipeline import HINT_ABSTRACT_MISS

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("Papers directory does not exist: %s", papers_dir)
        sys.exit(1)

    action = "Previewing abstract backfill" if args.dry_run else "Backfilling abstracts"
    doi_fetch = getattr(args, "doi_fetch", False)
    source = "official DOI sources" if doi_fetch else "local .md regex only"
    ui(f"{action} ({source})...\n")
    stats = backfill_abstracts(papers_dir, dry_run=args.dry_run, doi_fetch=doi_fetch)
    parts = [f"{stats['filled']} filled", f"{stats['skipped']} skipped", f"{stats['failed']} failed"]
    if stats.get("updated"):
        parts.insert(1, f"{stats['updated']} updated to official abstracts")
    ui(f"\nDone: {' | '.join(parts)}")
    failed_dirs = stats.get("failed_dirs") or []
    if failed_dirs:
        ui(
            f"hint: regex found no abstract in {len(failed_dirs)} papers ({', '.join(failed_dirs[:5])}); {HINT_ABSTRACT_MISS}"
        )
    if stats["filled"] and not args.dry_run:
        _log.debug("consider rebuilding index: scrinium index --rebuild")


def cmd_rename(args: argparse.Namespace, cfg) -> None:
    from scrinium.ingest.metadata import rename_paper
    from scrinium.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("Specify <paper-id> or --all")
        sys.exit(1)

    renamed = skip = fail = 0
    for json_path in targets:
        if not json_path.exists():
            _log.error("Paper not found: %s", json_path.parent.name)
            fail += 1
            continue

        new_path = rename_paper(json_path, dry_run=args.dry_run)
        if new_path:
            action = "Preview" if args.dry_run else "Renamed"
            ui(f"{action}: {json_path.parent.name} -> {new_path.parent.name}")
            renamed += 1
        else:
            skip += 1

    ui(f"\nDone: {renamed} renamed | {skip} unchanged | {fail} failed")
    if renamed and not args.dry_run:
        _log.debug("consider rebuilding index: scrinium index --rebuild")


def cmd_attach_pdf(args: argparse.Namespace, cfg) -> None:
    import shutil

    paper_d = _resolve_paper(args.paper_id, cfg)
    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        ui(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)

    existing_md = paper_d / "paper.md"
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        ui(f"[dry-run] Paper directory: {paper_d}")
        ui(f"[dry-run] PDF source: {pdf_path}")
        ui(f"[dry-run] Target paper.md: {paper_d / 'paper.md'}")
        if existing_md.exists():
            ui("[dry-run] Warning: paper.md already exists and will be overwritten when run for real")
        ui("[dry-run] Will run: MinerU conversion -> abstract backfill -> reindex")
        ui("[dry-run] Remove --dry-run to execute")
        return

    if existing_md.exists():
        ui(f"Warning: {paper_d.name} already has paper.md; it will be overwritten")

    # Copy PDF to paper directory
    dest_pdf = paper_d / pdf_path.name
    shutil.copy2(str(pdf_path), str(dest_pdf))
    ui(f"Copied PDF: {dest_pdf.name}")

    # Convert PDF → markdown via MinerU
    from scrinium.ingest.mineru import (
        ConvertOptions,
        _convert_long_pdf,
        _convert_long_pdf_cloud,
        _get_pdf_page_count,
        _plan_cloud_chunking,
        check_server,
        convert_pdf,
    )
    from scrinium.ingest.pdf_fallback import (
        convert_pdf_with_fallback,
        preferred_parser_order,
        prefers_fallback_parser,
    )

    mineru_opts = ConvertOptions(
        api_url=cfg.ingest.mineru_endpoint,
        output_dir=paper_d,
        backend=cfg.ingest.mineru_backend_local,
        cloud_model_version=cfg.ingest.mineru_model_version_cloud,
        lang=cfg.ingest.mineru_lang,
        parse_method=cfg.ingest.mineru_parse_method,
        formula_enable=cfg.ingest.mineru_enable_formula,
        table_enable=cfg.ingest.mineru_enable_table,
        poll_timeout=cfg.ingest.mineru_poll_timeout,
    )

    result = None
    preferred_done = False
    fallback_auto_detect = getattr(cfg.ingest, "pdf_fallback_auto_detect", True)
    fallback_order = preferred_parser_order(
        getattr(cfg.ingest, "pdf_preferred_parser", "mineru"),
        getattr(cfg.ingest, "pdf_fallback_order", None),
        auto_detect=fallback_auto_detect,
    )
    local_chunk_limit = getattr(cfg.ingest, "chunk_page_limit", 100)
    if prefers_fallback_parser(getattr(cfg.ingest, "pdf_preferred_parser", "mineru")):
        ok, parser_name, fallback_err = convert_pdf_with_fallback(
            dest_pdf,
            existing_md,
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            ui(f"Preferred parser failed: {fallback_err}")
            sys.exit(1)
        ui(f"Generated paper.md with configured preferred parser {parser_name}")
        preferred_done = True
    elif check_server(cfg.ingest.mineru_endpoint):
        page_count = _get_pdf_page_count(dest_pdf)
        if page_count > local_chunk_limit:
            ui(f"Long PDF detected ({page_count} pages, over the {local_chunk_limit}-page limit); chunking...")
            result = _convert_long_pdf(dest_pdf, mineru_opts, chunk_size=local_chunk_limit)
        else:
            result = convert_pdf(dest_pdf, mineru_opts)
    else:
        api_key = cfg.resolved_mineru_api_key()
        if not api_key:
            ui("MinerU unreachable and no MinerU token configured; switching to fallback parser")
        else:
            from scrinium.ingest.mineru import convert_pdf_cloud

            should_chunk, chunk_size, reason = _plan_cloud_chunking(
                dest_pdf,
                default_chunk_size=local_chunk_limit,
            )
            if should_chunk:
                ui(f"Cloud chunking required ({reason}); chunking...")
                try:
                    result = _convert_long_pdf_cloud(
                        dest_pdf,
                        mineru_opts,
                        api_key=api_key,
                        cloud_url=cfg.ingest.mineru_cloud_url,
                        chunk_size=chunk_size,
                    )
                except ImportError as exc:
                    result = None
                    ui(f"Missing dependency for cloud chunking, trying fallback: {exc}. Install scrinium[pdf]")
                except Exception as exc:
                    result = None
                    ui(f"Cloud chunking failed, trying fallback: {exc}")
            else:
                result = convert_pdf_cloud(
                    dest_pdf,
                    mineru_opts,
                    api_key=api_key,
                    cloud_url=cfg.ingest.mineru_cloud_url,
                )

    if not preferred_done and (result is None or not result.success):
        err = result.error if result is not None else "MinerU unavailable"
        ui(f"MinerU conversion failed, trying fallback: {err}")
        ok, parser_name, fallback_err = convert_pdf_with_fallback(
            dest_pdf,
            existing_md,
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            ui(f"Fallback parsing failed: {fallback_err}")
            sys.exit(1)
        ui(f"Generated paper.md via fallback parser {parser_name}")
    elif result is not None:
        # Move/rename output to paper.md
        if result.md_path and result.md_path != existing_md:
            md_src = result.md_path
            md_src_parent = md_src.parent
            if existing_md.exists():
                existing_md.unlink()
            shutil.move(str(md_src), str(existing_md))
            for images_src in [md_src.parent / "images", md_src.parent / f"{md_src.stem}_images"]:
                if images_src.is_dir():
                    target = paper_d / "images"
                    if images_src == target:
                        break
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.move(str(images_src), str(target))
                    break
            if md_src_parent != paper_d and md_src_parent.is_dir() and not any(md_src_parent.iterdir()):
                md_src_parent.rmdir()

    # Clean up MinerU artifacts (keep images/)
    for pattern in ["*_layout.json", "*_content_list.json", "*_origin.pdf"]:
        for f in paper_d.glob(pattern):
            f.unlink(missing_ok=True)
    # Rename MinerU images dir if needed
    for img_dir in paper_d.glob("*_images"):
        if img_dir.name != "images" and img_dir.is_dir():
            target = paper_d / "images"
            if target.exists():
                shutil.rmtree(target)
            img_dir.rename(target)

    # Preserve the copied PDF as paper.pdf
    if dest_pdf.exists() and dest_pdf.name != "paper.pdf":
        dest_pdf.replace(dest_pdf.parent / "paper.pdf")

    ui(f"paper.md generated: {paper_d.name}/")

    # Backfill abstract if missing
    from scrinium.ingest.pipeline import HINT_ABSTRACT_MISS
    from scrinium.papers import read_meta, write_meta

    data = read_meta(paper_d)
    if not data.get("abstract"):
        from scrinium.ingest.metadata import extract_abstract_from_md

        abstract = extract_abstract_from_md(existing_md)
        if abstract:
            data["abstract"] = abstract
            write_meta(paper_d, data)
            ui(f"Abstract backfilled ({len(abstract)} chars)")
        else:
            ui(f"hint: regex found no abstract; {HINT_ABSTRACT_MISS}")

    # Incremental re-index
    from scrinium.ingest.pipeline import PipelineOptions, step_index

    step_index(cfg.papers_dir, cfg, PipelineOptions())


def _add_enrich_toc_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``enrich toc`` and its legacy alias ``enrich-toc``."""
    p.set_defaults(func=cmd_enrich_toc)
    p.add_argument("paper_id", nargs="?", help="Paper ID (required unless --all is given)")
    p.add_argument("--all", action="store_true", help="Process all papers in papers_dir")
    p.add_argument("--force", action="store_true", help="Force re-extraction")


def _add_backfill_abstract_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``enrich abstract`` and its legacy alias ``backfill-abstract``."""
    p.set_defaults(func=cmd_backfill_abstract)
    p.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    p.add_argument(
        "--doi-fetch", action="store_true", help="Fetch official abstracts from publisher pages (overwrites existing)"
    )


def _add_pipeline_args(p: argparse.ArgumentParser, *, preset_default: str | None = None) -> None:
    """Arguments shared by ``pipeline`` and its ``ingest`` preset alias."""
    p.set_defaults(func=cmd_pipeline)
    p.add_argument(
        "preset",
        nargs="?",
        default=preset_default,
        help="Preset name: full | ingest | enrich | reindex"
        + (f" (default: {preset_default})" if preset_default else ""),
    )
    p.add_argument("--steps", help="Custom comma-separated step sequence, e.g. abstract,toc,index")
    p.add_argument("--list", dest="list_steps", action="store_true", help="List all steps and presets")
    p.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    p.add_argument("--no-api", action="store_true", help="Offline mode; skip external APIs")
    p.add_argument("--force", action="store_true", help="Force reprocessing (abstract/toc)")
    p.add_argument("--rebuild", action="store_true", help="Rebuild the index (index step)")
    p.add_argument("--inbox", help="Inbox directory (default: data/inbox)")
    p.add_argument("--papers", help="Papers directory (default: configured value)")


def _add_refetch_args(p: argparse.ArgumentParser) -> None:
    """Arguments shared by ``refresh`` and its legacy alias ``refetch``."""
    p.set_defaults(func=cmd_refetch)
    p.add_argument("paper_id", nargs="?", help="Paper ID (dir_name / UUID / DOI; required unless --all is given)")
    p.add_argument("--all", action="store_true", help="Refresh all papers missing citation counts")
    p.add_argument(
        "--force", action="store_true", help="Force re-query (including papers that already have citation counts)"
    )
    p.add_argument("--jobs", "-j", type=int, default=5, help="Concurrency level (default: 5)")


def register(sub) -> None:
    """Register ingest-domain subcommands."""
    # --- enrich (grouped entry point) ---
    p_enrich = sub.add_parser("enrich", help="Content enrichment: extract TOC / backfill abstracts")
    p_enrich_sub = p_enrich.add_subparsers(dest="enrich_action", required=True)
    _add_enrich_toc_args(p_enrich_sub.add_parser("toc", help="Rule-based TOC extraction written to JSON"))
    _add_backfill_abstract_args(
        p_enrich_sub.add_parser(
            "abstract", help="Backfill missing abstracts (regex-only, with official DOI fetch support)"
        )
    )

    # --- enrich-toc (legacy alias of `enrich toc`; no help => hidden) ---
    _add_enrich_toc_args(sub.add_parser("enrich-toc"))

    # --- pipeline ---
    _add_pipeline_args(sub.add_parser("pipeline", help="Composable step pipeline"))

    # --- ingest (alias for the `pipeline ingest` preset) ---
    _add_pipeline_args(
        sub.add_parser(
            "ingest", help="Ingest pipeline (equivalent to `pipeline ingest`; supports all pipeline options)"
        ),
        preset_default="ingest",
    )

    # --- refresh (primary name; `refetch` kept as a hidden legacy alias) ---
    _add_refetch_args(
        sub.add_parser("refresh", help="Refresh paper metadata, citation counts, and references from APIs")
    )

    # --- refetch (legacy alias of `refresh`; no help => hidden) ---
    _add_refetch_args(sub.add_parser("refetch"))

    # --- backfill-abstract (legacy alias of `enrich abstract`; no help => hidden) ---
    _add_backfill_abstract_args(sub.add_parser("backfill-abstract"))

    # --- rename ---
    p_rename = sub.add_parser("rename", help="Rename paper files based on JSON metadata")
    p_rename.set_defaults(func=cmd_rename)
    p_rename.add_argument("paper_id", nargs="?", help="Paper ID (required unless --all is given)")
    p_rename.add_argument("--all", action="store_true", help="Rename all papers with non-standard filenames")
    p_rename.add_argument("--dry-run", action="store_true", help="Preview without renaming")

    # --- audit ---
    p_audit = sub.add_parser("audit", help="Audit data quality of ingested papers")
    p_audit.set_defaults(func=cmd_audit)
    p_audit.add_argument(
        "--severity", choices=["error", "warning", "info"], help="Show only issues at the given severity level"
    )

    # --- tag ---
    p_tag = sub.add_parser("tag", help="Add, remove, or view curated tags on a paper")
    p_tag.set_defaults(func=cmd_tag)
    p_tag.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_tag.add_argument(
        "tags", nargs="*", help="Tags to add (aliases normalized; unregistered tags added to vocabulary)"
    )
    p_tag.add_argument("--remove", action="store_true", help="Remove tags instead of adding")
    p_tag.add_argument("--json", action="store_true", help="Output in JSON format (pipe-friendly)")

    # --- tags ---
    p_tags = sub.add_parser("tags", help="Browse the tag vocabulary and per-tag paper counts")
    p_tags.set_defaults(func=cmd_tags)
    p_tags.add_argument("--json", action="store_true", help="Output in JSON format (pipe-friendly)")

    # --- topics ---
    p_topics = sub.add_parser("topics", help="Browse topics: tag-topic overview and drill-down (tags are topics)")
    p_topics.set_defaults(func=cmd_topics)
    p_topics.add_argument(
        "tag", nargs="?", default=None, help="Topic (tag) name; supports aliases. Omit to show the overview"
    )
    p_topics.add_argument("--json", action="store_true", help="Output in JSON format (pipe-friendly)")

    # --- pending ---
    p_pending = sub.add_parser("pending", help="List pending review items (data/pending and data/duplicates)")
    p_pending.set_defaults(func=cmd_pending)

    # --- repair ---
    p_repair = sub.add_parser(
        "repair",
        help="Repair paper metadata (rename library papers in place; dedup-check and ingest data/pending items)",
    )
    p_repair.set_defaults(func=cmd_repair)
    p_repair.add_argument("paper_id", help="Paper ID (library directory name or item name under data/pending)")
    p_repair.add_argument("--title", required=True, help="Correct paper title")
    p_repair.add_argument("--doi", default="", help="Known DOI (speeds up API lookup)")
    p_repair.add_argument("--author", default="", help="First author's full name")
    p_repair.add_argument("--year", type=int, default=None, help="Publication year")
    p_repair.add_argument("--no-api", action="store_true", help="Skip API queries; use only the provided information")
    p_repair.add_argument("--dry-run", action="store_true", help="Preview without modifying anything")

    # --- attach-pdf ---
    p_ap = sub.add_parser("attach-pdf", help="Attach a PDF to an ingested paper and generate paper.md")
    p_ap.set_defaults(func=cmd_attach_pdf)
    p_ap.add_argument("paper_id", help="Paper ID (dir_name / UUID / DOI)")
    p_ap.add_argument("pdf_path", help="Path to the PDF file")
    p_ap.add_argument(
        "--dry-run", action="store_true", help="Preview the actions that would be taken without running them"
    )
