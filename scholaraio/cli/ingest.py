"""cli/ingest.py — ingest pipeline, enrichment, pending/audit/repair, attach-pdf."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from pathlib import Path

from scholaraio.log import ui

from .common import _emit_json, _resolve_paper

_log = logging.getLogger(__package__)


def cmd_audit(args: argparse.Namespace, cfg) -> None:
    from scholaraio.audit import audit_papers, format_report

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    ui(f"正在审计论文库: {papers_dir}\n")
    issues = audit_papers(papers_dir)

    if args.severity:
        issues = [i for i in issues if i.severity == args.severity]

    ui(format_report(issues))


def cmd_tag(args: argparse.Namespace, cfg) -> None:
    from scholaraio.tags import normalize_tag, paper_tags, register_tag, resolve_tag, set_paper_tags

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
            ui(f"{paper_d.name} 的标签: {', '.join(current)}")
        else:
            ui(f"{paper_d.name} 暂无标签（可用 scholaraio tag {paper_d.name} <标签...> 添加）")
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
        ui(f"已移除标签: {', '.join(removed) if removed else '（无变化）'}")
    else:
        if added:
            ui(f"已添加标签: {', '.join(added)}")
        elif not new_tags:
            ui("标签无变化")
        for tag in new_tags:
            ui(f"新标签已加入词表: {tag}（可用 scholaraio tags 查看）")
    ui(f"{paper_d.name} 当前标签: {', '.join(final) if final else '（无）'}")
    if added or removed:
        ui("提示: 运行 scholaraio index 后标签才会进入检索索引")


def cmd_tags(args: argparse.Namespace, cfg) -> None:
    from scholaraio.tags import all_tags_with_counts, load_taxonomy

    tax = load_taxonomy(cfg).get("tags") or {}
    counts = all_tags_with_counts(cfg)
    names = sorted(set(tax) | set(counts))

    if not names:
        if getattr(args, "json", False):
            _emit_json({"count": 0, "tags": []})
            return
        ui("标签词表为空（可用 scholaraio tag <论文> <标签...> 创建）")
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

    ui(f"标签词表（共 {len(entries)} 个标签）\n")
    for e in entries:
        alias_str = f"（别名: {', '.join(e['aliases'])}）" if e["aliases"] else ""
        desc_str = f"  {e['description']}" if e["description"] else ""
        ui(f"  {e['name']}{alias_str}: {e['count']} 篇{desc_str}")
    ui(f"\n总计: {len(entries)} 个标签，{sum(counts.values())} 次标注")


# Suggested remediation per pending.json issue type.


_PENDING_SUGGESTIONS = {
    "no_doi": "补全 DOI 后将文件放回 data/inbox/ 重新 ingest",
    "no_pub_num": "确认公开号后将文件放回 data/inbox-patent/ 重新 ingest",
    "duplicate": "确认重复后可删除该目录；若需覆盖请先移除原论文",
}


def _collect_pending_items(cfg) -> list[dict]:
    """Collect entries from data/pending/ and data/duplicates/ for `scholaraio pending`."""
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
            items.append(
                {
                    "path": d,
                    "issue": data.get("issue", "unknown"),
                    "title": meta.get("title", ""),
                    "duplicate_of": data.get("duplicate_of", ""),
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
            items.append({"path": d, "issue": "duplicate", "title": title, "duplicate_of": ""})
    return items


def cmd_pending(args: argparse.Namespace, cfg) -> None:
    items = _collect_pending_items(cfg)
    if not items:
        ui("无待确认项")
        return

    ui(f"待确认项（共 {len(items)} 项）\n")
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["issue"], []).append(item)
    for issue in sorted(groups):
        group = groups[issue]
        suggestion = _PENDING_SUGGESTIONS.get(issue, "人工确认后处理")
        ui(f"[{issue}] {len(group)} 项")
        for item in group:
            ui(f"  {item['path']}")
            if item["title"]:
                ui(f"    标题: {item['title']}")
            if item["duplicate_of"]:
                ui(f"    重复于: {item['duplicate_of']}")
            ui(f"    建议: {suggestion}")
        ui("")
    summary = " | ".join(f"{issue} {len(groups[issue])}" for issue in sorted(groups))
    ui(f"汇总: {summary}（共 {len(items)} 项）")


def cmd_repair(args: argparse.Namespace, cfg) -> None:
    import json

    from scholaraio.ingest.metadata import (
        PaperMetadata,
        _extract_lastname,
        enrich_metadata,
        generate_new_stem,
        rename_files,
        write_metadata_json,
    )

    papers_dir = cfg.papers_dir
    paper_id = args.paper_id

    paper_d = papers_dir / paper_id
    md_path = paper_d / "paper.md"
    json_path = paper_d / "meta.json"

    if not md_path.exists():
        _log.error("文件不存在: %s", md_path)
        sys.exit(1)

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

    ui(f"修复论文: {paper_id}")
    ui(f"  标题: {meta.title}")
    ui(f"  作者: {meta.first_author or '?'} | 年份: {meta.year or '?'} | DOI: {meta.doi or '无'}")

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

    ui(f"  结果: {meta.first_author_lastname} ({meta.year}) {meta.title[:60]}")
    if meta.doi:
        ui(f"  DOI: {meta.doi}")
    ui(f"  方法: {meta.extraction_method}")

    if args.dry_run:
        ui("  [dry-run] 未写入任何文件")
        return

    # Write new JSON
    write_metadata_json(meta, json_path)
    ui(f"  已写入: {json_path.name}")

    new_stem = generate_new_stem(meta)
    rename_files(md_path, json_path, new_stem, dry_run=False)

    _log.debug("done. consider running pipeline reindex")


def cmd_enrich_toc(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import enrich_toc
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            ),
            success_message=_toc_success_message,
            failure_message="  TOC 提取失败",
            max_retries=2,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
                skip += 1
                continue

            ui(f"\n{json_path.parent.name}")
            ui("  开始提取 TOC...")
            success = enrich_toc(
                json_path,
                md_path,
                cfg,
                force=args.force,
                inspect=args.inspect,
            )
            if success:
                ok += 1
                ui(_toc_success_message(json_path))
            else:
                fail += 1
                ui("  TOC 提取失败")

    if args.all or len(targets) > 1:
        ui(f"\n完成: {ok} 成功 | {fail} 失败 | {skip} 跳过")


def cmd_pipeline(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.pipeline import PRESETS, STEPS, PipelineOptions, run_pipeline

    if args.list_steps:
        ui("可用步骤：")
        for name, sdef in STEPS.items():
            ui(f"  {name:<10} [{sdef.scope:<7}]  {sdef.desc}")
        ui("\n可用预设：")
        for name, steps in PRESETS.items():
            ui(f"  {name:<10} = {', '.join(steps)}")
        return

    # Resolve step list
    if args.preset:
        if args.preset not in PRESETS:
            _log.error("未知预设 '%s'。可用预设: %s", args.preset, ", ".join(PRESETS))
            sys.exit(1)
        step_names = PRESETS[args.preset]
    elif args.steps:
        step_names = [s.strip() for s in args.steps.split(",") if s.strip()]
    else:
        _log.error("请指定一个预设名称或使用 --steps")
        sys.exit(1)

    opts = PipelineOptions(
        dry_run=args.dry_run,
        no_api=args.no_api,
        force=args.force,
        inspect=args.inspect,
        max_retries=args.max_retries,
        rebuild=args.rebuild,
        inbox_dir=Path(args.inbox).resolve() if args.inbox else None,
        papers_dir=Path(args.papers).resolve() if args.papers else None,
    )

    run_pipeline(step_names, cfg, opts)


def cmd_enrich_l3(args: argparse.Namespace, cfg) -> None:
    from scholaraio.loader import enrich_l3
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    if args.all:
        ok, fail, skip = _run_batch_enrich(
            targets,
            cfg,
            worker_fn=lambda json_path, md_path: enrich_l3(
                json_path,
                md_path,
                cfg,
                force=args.force,
                max_retries=args.max_retries,
                inspect=args.inspect,
            ),
            success_message="  结论提取完成",
            failure_message="  结论提取失败",
            max_retries=args.max_retries,
        )
    else:
        ok = fail = skip = 0
        for json_path in targets:
            md_path = json_path.parent / "paper.md"
            if not md_path.exists():
                _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
                skip += 1
                continue

            ui(f"\n{json_path.parent.name}")
            success = enrich_l3(
                json_path,
                md_path,
                cfg,
                force=args.force,
                max_retries=args.max_retries,
                inspect=args.inspect,
            )
            if success:
                ok += 1
                ui("  结论提取完成")
            else:
                fail += 1
                ui("  结论提取失败")

    if args.all or len(targets) > 1:
        ui(f"\n完成: {ok} 成功 | {fail} 失败 | {skip} 跳过")


def _toc_success_message(json_path: Path) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return f"  TOC 提取完成: {len(data.get('toc', []))} 节"
    except (OSError, json.JSONDecodeError):
        return "  TOC 提取完成"


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
            _log.error("已跳过（缺少 paper.md）: %s", json_path.parent.name)
            skip += 1
            continue
        queued.append((json_path, md_path))

    if not queued:
        return 0, 0, skip

    workers = min(max(1, int(getattr(cfg.llm, "concurrency", 1))), len(queued))
    ui(f"并发处理（{workers} workers，共 {len(queued)} 篇）...")

    def _retry_one(json_path: Path, md_path: Path) -> tuple[Path, bool, int]:
        for attempt in range(1, max_retries + 2):
            try:
                success = worker_fn(json_path, md_path)
                if success:
                    return json_path, True, attempt
            except Exception as e:
                _log.warning("批量富化失败（%s，第 %d 次）: %s", json_path.parent.name, attempt, e)
            if attempt <= max_retries:
                time.sleep(float(2 ** (attempt - 1)))
        return json_path, False, max_retries + 1

    ok = fail = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for json_path, md_path in queued:
            ui(f"\n{_batch_message(json_path, '开始处理...')}")
            futures.append(pool.submit(_retry_one, json_path, md_path))
        for future in concurrent.futures.as_completed(futures):
            json_path, success, attempts = future.result()
            if success:
                ok += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"重试后成功（共 {attempts} 次）"))
                ui(
                    _batch_message(
                        json_path,
                        success_message(json_path) if callable(success_message) else success_message,
                    )
                )
            else:
                fail += 1
                if attempts > 1:
                    ui(_batch_message(json_path, f"已重试 {attempts - 1}/{max_retries} 次"))
                ui(_batch_message(json_path, failure_message))

    return ok, fail, skip


def cmd_refetch(args: argparse.Namespace, cfg) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scholaraio.ingest.metadata import refetch_metadata
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [_resolve_paper(args.paper_id, cfg) / "meta.json"]
    else:
        _log.error("请指定 <paper-id> 或 --all")
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
        ui(f"共 {len(targets)} 篇，{len(filtered)} 篇需要补全")
        targets = filtered

    if not targets:
        ui("无需更新")
        return

    # Filter out non-existent paths
    valid = []
    fail = 0
    for jp in targets:
        if jp.exists():
            valid.append(jp)
        else:
            _log.error("未找到论文: %s", jp.parent.name)
            fail += 1
    targets = valid
    if not targets:
        if args.all:
            ui("无需更新")
            return
        sys.exit(1)

    ok = skip = 0
    total = len(targets)
    workers = min(getattr(args, "jobs", 5) or 5, total)
    ui(f"并发 refetch（{workers} workers，共 {total} 篇）...")

    def _do_refetch(jp: Path) -> tuple[Path, bool | None]:
        try:
            return jp, refetch_metadata(jp)
        except Exception as e:
            _log.error("refetch 失败 %s: %s", jp.parent.name, e)
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

    ui(f"\n完成: {ok} 更新 | {skip} 无变化 | {fail} 失败")


def cmd_backfill_abstract(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.metadata import backfill_abstracts

    papers_dir = cfg.papers_dir
    if not papers_dir.exists():
        _log.error("论文目录不存在: %s", papers_dir)
        sys.exit(1)

    action = "预览补全" if args.dry_run else "补全摘要"
    doi_fetch = getattr(args, "doi_fetch", False)
    source = "DOI 官方来源" if doi_fetch else "本地 .md + LLM 回退"
    ui(f"{action}摘要（{source}）...\n")
    stats = backfill_abstracts(papers_dir, dry_run=args.dry_run, doi_fetch=doi_fetch, cfg=cfg)
    parts = [f"{stats['filled']} 已补全", f"{stats['skipped']} 跳过", f"{stats['failed']} 失败"]
    if stats.get("updated"):
        parts.insert(1, f"{stats['updated']} 已更新为官方摘要")
    ui(f"\n完成: {' | '.join(parts)}")
    if stats["filled"] and not args.dry_run:
        _log.debug("consider rebuilding vector index: scholaraio embed --rebuild")


def cmd_rename(args: argparse.Namespace, cfg) -> None:
    from scholaraio.ingest.metadata import rename_paper
    from scholaraio.papers import iter_paper_dirs

    papers_dir = cfg.papers_dir

    if args.all:
        targets = sorted(d / "meta.json" for d in iter_paper_dirs(papers_dir))
    elif args.paper_id:
        targets = [papers_dir / args.paper_id / "meta.json"]
    else:
        _log.error("请指定 <paper-id> 或 --all")
        sys.exit(1)

    renamed = skip = fail = 0
    for json_path in targets:
        if not json_path.exists():
            _log.error("未找到论文: %s", json_path.parent.name)
            fail += 1
            continue

        new_path = rename_paper(json_path, dry_run=args.dry_run)
        if new_path:
            action = "预览" if args.dry_run else "重命名"
            ui(f"{action}: {json_path.parent.name} -> {new_path.parent.name}")
            renamed += 1
        else:
            skip += 1

    ui(f"\n完成: {renamed} 已重命名 | {skip} 未变化 | {fail} 失败")
    if renamed and not args.dry_run:
        _log.debug("consider rebuilding index: scholaraio index --rebuild")


def cmd_attach_pdf(args: argparse.Namespace, cfg) -> None:
    import shutil

    paper_d = _resolve_paper(args.paper_id, cfg)
    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        ui(f"错误：PDF 文件不存在: {pdf_path}")
        sys.exit(1)

    existing_md = paper_d / "paper.md"
    dry_run = getattr(args, "dry_run", False)

    if dry_run:
        ui(f"[dry-run] 论文目录: {paper_d}")
        ui(f"[dry-run] PDF 来源: {pdf_path}")
        ui(f"[dry-run] 目标 paper.md: {paper_d / 'paper.md'}")
        if existing_md.exists():
            ui("[dry-run] 警告：已有 paper.md，实际运行时将被覆盖")
        ui("[dry-run] 将执行: MinerU 转换 → 摘要补全 → 重新嵌入 → 重建索引")
        ui("[dry-run] 如确认无误，去掉 --dry-run 参数再运行")
        return

    if existing_md.exists():
        ui(f"警告：{paper_d.name} 已有 paper.md，将被覆盖")

    # Copy PDF to paper directory
    dest_pdf = paper_d / pdf_path.name
    shutil.copy2(str(pdf_path), str(dest_pdf))
    ui(f"已复制 PDF: {dest_pdf.name}")

    # Convert PDF → markdown via MinerU
    from scholaraio.ingest.mineru import (
        ConvertOptions,
        _convert_long_pdf,
        _convert_long_pdf_cloud,
        _get_pdf_page_count,
        _plan_cloud_chunking,
        check_server,
        convert_pdf,
    )
    from scholaraio.ingest.pdf_fallback import (
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
            ui(f"首选解析器失败: {fallback_err}")
            sys.exit(1)
        ui(f"已按配置优先使用 {parser_name} 生成 paper.md")
        preferred_done = True
    elif check_server(cfg.ingest.mineru_endpoint):
        page_count = _get_pdf_page_count(dest_pdf)
        if page_count > local_chunk_limit:
            ui(f"检测到长 PDF（{page_count} 页，超过 {local_chunk_limit} 页限制），正在分片处理...")
            result = _convert_long_pdf(dest_pdf, mineru_opts, chunk_size=local_chunk_limit)
        else:
            result = convert_pdf(dest_pdf, mineru_opts)
    else:
        api_key = cfg.resolved_mineru_api_key()
        if not api_key:
            ui("MinerU 不可达且无 MinerU token，改用 fallback 解析器")
        else:
            from scholaraio.ingest.mineru import convert_pdf_cloud

            should_chunk, chunk_size, reason = _plan_cloud_chunking(
                dest_pdf,
                default_chunk_size=local_chunk_limit,
            )
            if should_chunk:
                ui(f"检测到云端需分片 PDF（{reason}），正在分片处理...")
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
                    ui(f"云端分片依赖缺失，尝试 fallback：{exc}。可安装 scholaraio[pdf]")
                except Exception as exc:
                    result = None
                    ui(f"云端分片失败，尝试 fallback：{exc}")
            else:
                result = convert_pdf_cloud(
                    dest_pdf,
                    mineru_opts,
                    api_key=api_key,
                    cloud_url=cfg.ingest.mineru_cloud_url,
                )

    if not preferred_done and (result is None or not result.success):
        err = result.error if result is not None else "MinerU unavailable"
        ui(f"MinerU 转换失败，尝试 fallback: {err}")
        ok, parser_name, fallback_err = convert_pdf_with_fallback(
            dest_pdf,
            existing_md,
            parser_order=fallback_order,
            auto_detect=fallback_auto_detect,
        )
        if not ok:
            ui(f"fallback 解析失败: {fallback_err}")
            sys.exit(1)
        ui(f"已降级使用 {parser_name} 生成 paper.md")
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

    # Clean up the copied PDF (we only need the markdown)
    if dest_pdf.exists() and dest_pdf.name != "paper.pdf":
        dest_pdf.unlink()

    ui(f"paper.md 已生成: {paper_d.name}/")

    # Backfill abstract if missing
    from scholaraio.papers import read_meta, write_meta

    data = read_meta(paper_d)
    if not data.get("abstract"):
        from scholaraio.ingest.metadata import extract_abstract_from_md

        abstract = extract_abstract_from_md(existing_md, cfg)
        if abstract:
            data["abstract"] = abstract
            write_meta(paper_d, data)
            ui(f"abstract 已补全 ({len(abstract)} chars)")

    # Incremental re-embed + re-index
    from scholaraio.ingest.pipeline import PipelineOptions, step_embed, step_index

    step_embed(cfg.papers_dir, cfg, PipelineOptions())
    step_index(cfg.papers_dir, cfg, PipelineOptions())


def register(sub) -> None:
    """Register ingest-domain subcommands."""
    # --- enrich-toc ---
    p_toc = sub.add_parser("enrich-toc", help="LLM 过滤标题噪声，提取论文 TOC 写入 JSON")
    p_toc.set_defaults(func=cmd_enrich_toc)
    p_toc.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_toc.add_argument("--all", action="store_true", help="处理 papers_dir 中所有论文")
    p_toc.add_argument("--force", action="store_true", help="强制重新提取")
    p_toc.add_argument("--inspect", action="store_true", help="展示过滤过程")

    # --- pipeline ---
    p_pipe = sub.add_parser("pipeline", help="组合步骤流水线（可任意组装）")
    p_pipe.set_defaults(func=cmd_pipeline)
    p_pipe.add_argument(
        "preset",
        nargs="?",
        help="预设名称：full | ingest | enrich | reindex",
    )
    p_pipe.add_argument("--steps", help="自定义步骤序列（逗号分隔），如 toc,l3,index")
    p_pipe.add_argument("--list", dest="list_steps", action="store_true", help="列出所有步骤和预设")
    p_pipe.add_argument("--dry-run", action="store_true", help="预览，不写文件")
    p_pipe.add_argument("--no-api", action="store_true", help="离线模式，跳过外部 API")
    p_pipe.add_argument("--force", action="store_true", help="强制重新处理（toc/l3）")
    p_pipe.add_argument("--inspect", action="store_true", help="展示处理详情")
    p_pipe.add_argument("--max-retries", type=int, default=2, help="l3 最大重试次数（默认 2）")
    p_pipe.add_argument("--rebuild", action="store_true", help="重建索引（index 步骤）")
    p_pipe.add_argument("--inbox", help="inbox 目录（默认 data/inbox）")
    p_pipe.add_argument("--papers", help="papers 目录（默认配置值）")

    # --- refetch ---
    p_refetch = sub.add_parser("refetch", help="重新查询 API 补全引用量等字段")
    p_refetch.set_defaults(func=cmd_refetch)
    p_refetch.add_argument("paper_id", nargs="?", help="论文 ID（目录名 / UUID / DOI；省略则需 --all）")
    p_refetch.add_argument("--all", action="store_true", help="补查所有缺失引用量的论文")
    p_refetch.add_argument("--force", action="store_true", help="强制重新查询（包括已有引用量的论文）")
    p_refetch.add_argument("--jobs", "-j", type=int, default=5, help="并发数（默认 5）")

    # --- backfill-abstract ---
    p_bf = sub.add_parser("backfill-abstract", help="补全缺失的 abstract（支持 DOI 官方抓取）")
    p_bf.set_defaults(func=cmd_backfill_abstract)
    p_bf.add_argument("--dry-run", action="store_true", help="预览，不写文件")
    p_bf.add_argument("--doi-fetch", action="store_true", help="从出版商网页抓取官方 abstract（覆盖现有）")

    # --- rename ---
    p_rename = sub.add_parser("rename", help="根据 JSON 元数据重命名论文文件")
    p_rename.set_defaults(func=cmd_rename)
    p_rename.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_rename.add_argument("--all", action="store_true", help="重命名所有文件名不正确的论文")
    p_rename.add_argument("--dry-run", action="store_true", help="预览，不实际重命名")

    # --- audit ---
    p_audit = sub.add_parser("audit", help="审计已入库论文的数据质量")
    p_audit.set_defaults(func=cmd_audit)
    p_audit.add_argument("--severity", choices=["error", "warning", "info"], help="只显示指定严重级别的问题")

    # --- tag ---
    p_tag = sub.add_parser("tag", help="为论文添加/移除/查看策展标签")
    p_tag.set_defaults(func=cmd_tag)
    p_tag.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_tag.add_argument("tags", nargs="*", help="要添加的标签（别名自动归一；未注册的自动加入词表）")
    p_tag.add_argument("--remove", action="store_true", help="移除而非添加标签")
    p_tag.add_argument("--json", action="store_true", help="以 JSON 格式输出（便于管道解析）")

    # --- tags ---
    p_tags = sub.add_parser("tags", help="浏览标签词表与各标签论文数")
    p_tags.set_defaults(func=cmd_tags)
    p_tags.add_argument("--json", action="store_true", help="以 JSON 格式输出（便于管道解析）")

    # --- pending ---
    p_pending = sub.add_parser("pending", help="列出待确认项（data/pending 与 data/duplicates）")
    p_pending.set_defaults(func=cmd_pending)

    # --- repair ---
    p_repair = sub.add_parser("repair", help="修复论文元数据（手动指定 title/DOI，跳过 MD 解析）")
    p_repair.set_defaults(func=cmd_repair)
    p_repair.add_argument("paper_id", help="论文 ID（文件名 stem）")
    p_repair.add_argument("--title", required=True, help="正确的论文标题")
    p_repair.add_argument("--doi", default="", help="已知 DOI（加速 API 查询）")
    p_repair.add_argument("--author", default="", help="一作全名")
    p_repair.add_argument("--year", type=int, default=None, help="发表年份")
    p_repair.add_argument("--no-api", action="store_true", help="跳过 API 查询，仅用提供的信息")
    p_repair.add_argument("--dry-run", action="store_true", help="预览，不实际修改")

    # --- attach-pdf ---
    p_ap = sub.add_parser("attach-pdf", help="为已入库论文补充 PDF 并生成 paper.md")
    p_ap.set_defaults(func=cmd_attach_pdf)
    p_ap.add_argument("paper_id", help="论文 ID（目录名 / UUID / DOI）")
    p_ap.add_argument("pdf_path", help="PDF 文件路径")
    p_ap.add_argument("--dry-run", action="store_true", help="预览将要执行的操作，不实际运行")

    # --- enrich-l3 ---
    p_l3 = sub.add_parser("enrich-l3", help="LLM 提取结论段写入 JSON")
    p_l3.set_defaults(func=cmd_enrich_l3)
    p_l3.add_argument("paper_id", nargs="?", help="论文 ID（省略则需 --all）")
    p_l3.add_argument("--all", action="store_true", help="处理 papers_dir 中所有论文")
    p_l3.add_argument("--force", action="store_true", help="强制重新提取（覆盖已有结果）")
    p_l3.add_argument("--inspect", action="store_true", help="展示提取过程详情")
    p_l3.add_argument("--max-retries", type=int, default=2, help="最大重试次数（默认 2）")
