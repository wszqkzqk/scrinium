"""Developer-only parser benchmark harness (not wired into the CLI).

Unix only: the subprocess reader uses selectors on pipes, which Windows does
not support. On Windows, run it under WSL.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

from scrinium.config import load_config
from scrinium.ingest.mineru import ConvertOptions, convert_pdf, convert_pdf_cloud
from scrinium.ingest.pdf_fallback import copy_parser_assets, pick_and_write_md, run_pymupdf


@dataclass
class RunConfig:
    """Single parser/configuration benchmark entry."""

    parser: str
    name: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


def slugify_value(value: Any) -> str:
    """Render a value into a stable directory-safe slug fragment."""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "empty"


def slugify_key(value: Any) -> str:
    """Render an option key into a stable slug while preserving underscores."""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "-", text)
    return text.strip("-") or "empty"


def make_run_slug(cfg: RunConfig) -> str:
    """Build a deterministic slug from parser + sorted options."""
    if cfg.name:
        return slugify_value(cfg.name)
    parts = [slugify_value(cfg.parser)]
    for key in sorted(cfg.options):
        parts.append(f"{slugify_key(key)}-{slugify_value(cfg.options[key])}")
    return "__".join(parts)


def make_output_dir(root: Path, index: int, cfg: RunConfig) -> Path:
    """Compute the output directory for one run."""
    return root / f"{index:02d}__{make_run_slug(cfg)}"


def normalize_parser_name(parser: str) -> str:
    """Normalize parser names so hyphenated and underscored spellings both work."""
    return str(parser).strip().lower().replace("-", "_")


def expand_run_configs(spec: dict[str, Any]) -> list[RunConfig]:
    """Expand one parser spec into one or more concrete run configs."""
    parser = str(spec["parser"])
    name = spec.get("name")
    base_options = dict(spec.get("options") or {})
    base_env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    matrix = dict(spec.get("matrix") or {})
    if not matrix:
        return [RunConfig(parser=parser, name=name, options=base_options, env=base_env)]

    keys = list(matrix.keys())
    runs: list[RunConfig] = []
    for values in product(*(matrix[key] for key in keys)):
        opts = dict(base_options)
        opts.update(dict(zip(keys, values, strict=False)))
        runs.append(RunConfig(parser=parser, name=name, options=opts, env=dict(base_env)))
    return runs


def score_text(text: str) -> dict[str, Any]:
    """Compute simple content metrics from output markdown."""
    lines = text.splitlines()
    nonempty = [ln for ln in lines if ln.strip()]
    words = re.findall(r"\b\w+\b", text)
    headings = sum(1 for ln in lines if ln.lstrip().startswith("#"))
    image_refs = text.count("![") + len(re.findall(r"\]\((?:images|fig|figure|data:image)", text, flags=re.I))
    formula_blocks = text.count("$$")
    formula_placeholders = text.count("<!-- formula-not-decoded -->")
    replacement_chars = text.count("\ufffd")
    return {
        "chars": len(text),
        "words": len(words),
        "lines": len(lines),
        "nonempty_lines": len(nonempty),
        "headings": headings,
        "image_refs": image_refs,
        "formula_blocks": formula_blocks,
        "formula_placeholders": formula_placeholders,
        "replacement_chars": replacement_chars,
        "preview": text[:500],
    }


def run_benchmark(
    pdf_path: Path,
    run_specs: list[dict[str, Any]],
    output_root: Path,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Run all configs sequentially against one PDF."""
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise ValueError("output_root must be empty or not exist")
    else:
        output_root.mkdir(parents=True, exist_ok=True)

    runs: list[RunConfig] = []
    for spec in run_specs:
        runs.extend(expand_run_configs(spec))

    results: list[dict[str, Any]] = []
    for idx, cfg in enumerate(runs, start=1):
        out_dir = make_output_dir(output_root, idx, cfg)
        out_dir.mkdir(parents=True, exist_ok=True)
        if progress_callback:
            progress_callback("start", idx, len(runs), cfg, out_dir, None)
        result = run_one(pdf_path, cfg, out_dir)
        results.append(result)
        if progress_callback:
            progress_callback("end", idx, len(runs), cfg, out_dir, result)

    summary = summarize_results(results)
    (output_root / "results.json").write_text(
        json.dumps({"pdf": str(pdf_path), "summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_root / "summary.md").write_text(render_summary(pdf_path, results, summary), encoding="utf-8")
    return {"summary": summary, "results": results}


def run_one(pdf_path: Path, cfg: RunConfig, out_dir: Path) -> dict[str, Any]:
    """Run a single parser/configuration."""
    t0 = time.perf_counter()
    logs_dir = out_dir / "logs"
    raw_dir = out_dir / "raw"
    result_dir = out_dir / "result"
    logs_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    md_path = result_dir / "paper.md"

    entry: dict[str, Any] = {
        "parser": cfg.parser,
        "name": cfg.name,
        "slug": make_run_slug(cfg),
        "options": dict(cfg.options),
        "env": dict(cfg.env),
        "pdf": str(pdf_path),
        "ok": False,
        "elapsed_sec": None,
        "command": None,
        "error": None,
    }

    try:
        parser_name = normalize_parser_name(cfg.parser)
        if parser_name == "pymupdf":
            ok, err = run_pymupdf(pdf_path, md_path)
            entry["ok"] = ok
            entry["error"] = err
        elif parser_name == "mineru_cloud":
            res = _run_mineru_cloud(pdf_path, md_path, raw_dir, cfg)
            entry.update(res)
        elif parser_name == "mineru_local":
            res = _run_mineru_local(pdf_path, md_path, raw_dir, cfg)
            entry.update(res)
        elif parser_name == "docling":
            res = _run_cli_parser(pdf_path, md_path, raw_dir, logs_dir, cfg)
            entry.update(res)
        else:
            entry["error"] = f"unsupported parser: {cfg.parser}"
    except Exception as exc:  # pragma: no cover - defensive
        entry["error"] = f"{type(exc).__name__}: {exc}"

    entry["elapsed_sec"] = round(time.perf_counter() - t0, 3)
    entry["artifact_files"] = sorted(str(p.relative_to(out_dir)) for p in out_dir.rglob("*") if p.is_file())
    entry["output_exists"] = md_path.exists()
    if md_path.exists():
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        entry["md_size_bytes"] = md_path.stat().st_size
        entry.update(score_text(text))

    (out_dir / "run.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


def _run_cli_parser(
    pdf_path: Path,
    md_path: Path,
    raw_dir: Path,
    logs_dir: Path,
    cfg: RunConfig,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(cfg.env)
    parser_name = normalize_parser_name(cfg.parser)

    if parser_name == "docling":
        cmd = _build_docling_command(pdf_path, raw_dir, cfg.options)
    else:  # pragma: no cover - guarded by caller
        raise ValueError(cfg.parser)

    artifacts_path = (
        cfg.options.get("artifacts_path") or cfg.options.get("artifacts-path") or env.get("DOCLING_ARTIFACTS_PATH")
    )
    if parser_name == "docling" and artifacts_path:
        artifacts_dir = Path(str(artifacts_path))
        if not artifacts_dir.exists():
            return {
                "command": " ".join(shlex.quote(part) for part in cmd),
                "returncode": 2,
                "ok": False,
                "error": f"docling artifacts_path 不存在: {artifacts_dir}",
            }

    timeout_sec = int(cfg.options.get("timeout_sec", 3600))
    stdout_path = logs_dir / "stdout.txt"
    stderr_path = logs_dir / "stderr.txt"
    command_path = logs_dir / "command.txt"
    command_path.write_text(" ".join(shlex.quote(part) for part in cmd) + "\n", encoding="utf-8")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        bufsize=0,
        env=env,
    )
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    deadline = time.monotonic() + timeout_sec
    last_heartbeat = time.monotonic()

    with stdout_path.open("w", encoding="utf-8") as stdout_fh, stderr_path.open("w", encoding="utf-8") as stderr_fh:
        sel = selectors.DefaultSelector()
        timeout_error: subprocess.TimeoutExpired | None = None
        assert proc.stdout is not None
        assert proc.stderr is not None
        sel.register(proc.stdout, selectors.EVENT_READ, ("stdout", stdout_fh, out_chunks, sys.stdout))
        sel.register(proc.stderr, selectors.EVENT_READ, ("stderr", stderr_fh, err_chunks, sys.stderr))
        try:
            while sel.get_map():
                now = time.monotonic()
                if now > deadline:
                    proc.kill()
                    timeout_error = subprocess.TimeoutExpired(cmd, timeout_sec)
                    break

                events = sel.select(timeout=1.0)
                if not events and now - last_heartbeat >= 15:
                    print(f"[child] still running: {cfg.parser} ({make_run_slug(cfg)})", flush=True)
                    last_heartbeat = now

                for key, _ in events:
                    stream_name, sink_fh, chunks, mirror = key.data
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if chunk == b"":
                        sel.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    text = chunk.decode("utf-8", errors="replace")
                    sink_fh.write(text)
                    sink_fh.flush()
                    chunks.append(chunk)
                    print(text, end="", file=mirror, flush=True)

            if timeout_error is None:
                returncode = proc.wait()
        finally:
            for stream in (proc.stdout, proc.stderr):
                if stream is None:
                    continue
                try:
                    sel.unregister(stream)
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            sel.close()
            if timeout_error is not None:
                try:
                    proc.wait()
                except Exception:
                    pass
                raise timeout_error

    result = {
        "command": " ".join(shlex.quote(part) for part in cmd),
        "returncode": returncode,
    }
    stdout_text = b"".join(out_chunks).decode("utf-8", errors="replace")
    stderr_text = b"".join(err_chunks).decode("utf-8", errors="replace")
    if returncode != 0:
        result["error"] = (stderr_text.strip() or stdout_text.strip() or "command failed")[:2000]
        result["ok"] = False
        return result

    ok, err = pick_and_write_md(raw_dir, md_path, cfg.parser)
    result["ok"] = ok
    result["error"] = err
    return result


def _build_docling_command(pdf_path: Path, raw_dir: Path, options: dict[str, Any]) -> list[str]:
    cmd = [
        shutil.which("docling") or "docling",
        str(pdf_path),
        "--output",
        str(raw_dir),
        "--to",
        str(options.get("to", "md")),
    ]
    artifacts_path = options.get("artifacts_path") or options.get("artifacts-path")
    if artifacts_path:
        cmd.extend(["--artifacts-path", str(artifacts_path)])
    for key, value in sorted(options.items()):
        if key in {"to", "timeout_sec", "artifacts_path", "artifacts-path"}:
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        flag = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            cmd.append(flag if value else f"--no-{key.replace('_', '-')}")
        else:
            cmd.extend([flag, str(value)])
    return cmd


def _normalized_option_text(options: dict[str, Any], key: str, default: str) -> str:
    """Normalize benchmark option values like runtime config choices."""
    text = str(options.get(key, default) or "").strip().lower()
    return text or default


def _run_mineru_cloud(pdf_path: Path, md_path: Path, raw_dir: Path, cfg: RunConfig) -> dict[str, Any]:
    loaded = load_config()
    api_key = str(cfg.options.get("api_key") or loaded.resolved_mineru_api_key())
    cloud_url = str(cfg.options.get("cloud_url") or loaded.ingest.mineru_cloud_url)
    opts = ConvertOptions(
        output_dir=raw_dir,
        backend=_normalized_option_text(cfg.options, "backend", "pipeline"),
        cloud_model_version=_normalized_option_text(cfg.options, "cloud_model_version", ""),
        lang=_normalized_option_text(cfg.options, "lang", "ch"),
        parse_method=_normalized_option_text(cfg.options, "parse_method", "auto"),
        formula_enable=bool(cfg.options.get("formula_enable", True)),
        table_enable=bool(cfg.options.get("table_enable", True)),
        force=True,
    )
    res = convert_pdf_cloud(pdf_path, opts, api_key=api_key, cloud_url=cloud_url)
    result = {
        "command": "internal:convert_pdf_cloud",
        "returncode": 0 if res.success else 1,
        "ok": res.success,
        "error": res.error,
    }
    if res.success and res.md_path and res.md_path.exists():
        selected = res.md_path
        content = selected.read_text(encoding="utf-8", errors="ignore")
        copy_parser_assets(selected, md_path)
        md_path.write_text(content, encoding="utf-8")
    return result


def _run_mineru_local(pdf_path: Path, md_path: Path, raw_dir: Path, cfg: RunConfig) -> dict[str, Any]:
    loaded = load_config()
    opts = ConvertOptions(
        api_url=str(cfg.options.get("api_url", loaded.ingest.mineru_endpoint)).strip(),
        output_dir=raw_dir,
        backend=_normalized_option_text(cfg.options, "backend", "pipeline"),
        lang=_normalized_option_text(cfg.options, "lang", "ch"),
        parse_method=_normalized_option_text(cfg.options, "parse_method", "auto"),
        formula_enable=bool(cfg.options.get("formula_enable", True)),
        table_enable=bool(cfg.options.get("table_enable", True)),
        force=True,
    )
    res = convert_pdf(pdf_path, opts)
    result = {
        "command": "internal:convert_pdf",
        "returncode": 0 if res.success else 1,
        "ok": res.success,
        "error": res.error,
    }
    if res.success and res.md_path and res.md_path.exists():
        selected = res.md_path
        content = selected.read_text(encoding="utf-8", errors="ignore")
        copy_parser_assets(selected, md_path)
        md_path.write_text(content, encoding="utf-8")
    return result


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build compact summary from individual run results."""
    success_count = sum(1 for row in results if row.get("ok"))
    return {
        "total_runs": len(results),
        "successes": success_count,
        "failures": len(results) - success_count,
    }


def render_summary(pdf_path: Path, results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Render a compact markdown summary."""
    lines = [
        "# Single PDF Parser Matrix Benchmark",
        "",
        f"- PDF: `{pdf_path}`",
        f"- Total runs: {summary['total_runs']}",
        f"- Successes: {summary['successes']}",
        f"- Failures: {summary['failures']}",
        "",
        "## Runs",
        "",
        "| # | Parser | Slug | OK | Time (s) | Formula Blocks | Formula Placeholders | Image Refs | Output |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for idx, row in enumerate(results, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    str(row["parser"]),
                    str(row["slug"]),
                    "yes" if row.get("ok") else "no",
                    str(row.get("elapsed_sec")),
                    str(row.get("formula_blocks", "")),
                    str(row.get("formula_placeholders", "")),
                    str(row.get("image_refs", "")),
                    "`result/paper.md`" if row.get("output_exists") else "",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"
