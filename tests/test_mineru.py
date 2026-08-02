from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from scrinium.ingest.mineru import (
    ConvertOptions,
    ConvertResult,
    _convert_chunk_cloud,
    _convert_long_pdf_cloud,
    _locate_cloud_markdown_output,
    _plan_cloud_chunking,
    _resolve_cloud_model_version,
    convert_pdf_cloud,
    convert_pdfs_cloud_batch,
)


def test_convert_long_pdf_cloud_preserves_cloud_model_version(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    chunk_pdf = tmp_path / "chunk-1.pdf"
    chunk_pdf.write_bytes(b"%PDF-1.4")

    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "scrinium.ingest.mineru._split_pdf",
        lambda _pdf_path, chunk_size, output_dir: [chunk_pdf],
    )

    def fake_convert_pdfs_cloud_batch(
        pdf_paths: list[Path],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
        batch_size: int = 20,
    ) -> list[ConvertResult]:
        captured["cloud_model_version"] = opts.cloud_model_version
        return [ConvertResult(pdf_path=pdf_paths[0], md_path=output_dir / "chunk-1.md", success=True)]

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    def fake_merge_chunk_results(chunk_results, original_pdf_path, out_dir):
        assert chunk_results[0].success is True
        assert original_pdf_path == pdf_path
        return ConvertResult(pdf_path=original_pdf_path, md_path=out_dir / "paper.md", success=True)

    monkeypatch.setattr("scrinium.ingest.mineru.convert_pdfs_cloud_batch", fake_convert_pdfs_cloud_batch)
    monkeypatch.setattr("scrinium.ingest.mineru._merge_chunk_results", fake_merge_chunk_results)

    opts = ConvertOptions(
        output_dir=output_dir,
        backend="pipeline",
        cloud_model_version="MinerU-HTML",
        lang="en",
    )

    result = _convert_long_pdf_cloud(
        pdf_path,
        opts,
        api_key="test-key",
        cloud_url="https://mineru.example/api",
    )

    assert result.success is True
    assert captured["cloud_model_version"] == "MinerU-HTML"


def test_resolve_cloud_model_version_falls_back_to_backend_when_unset():
    opts = ConvertOptions(backend="vlm-auto-engine", cloud_model_version="")
    assert _resolve_cloud_model_version(opts) == "vlm"


def test_resolve_cloud_model_version_uses_backend_mapping_by_default():
    opts = ConvertOptions(backend="vlm-auto-engine")
    assert _resolve_cloud_model_version(opts) == "vlm"


def test_convert_pdf_cloud_invokes_mineru_open_api_extract_with_token_and_flags(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    captured: dict[str, object] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env_token"] = env.get("MINERU_TOKEN")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# ok\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="saved")

    monkeypatch.setattr(subprocess, "run", fake_run)

    opts = ConvertOptions(
        output_dir=output_dir,
        cloud_model_version="vlm",
        lang="en",
        parse_method="ocr",
        formula_enable=False,
        table_enable=True,
        poll_timeout=321,
    )

    result = convert_pdf_cloud(
        pdf_path,
        opts,
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is True
    assert result.md_path == output_dir / "paper.md"
    assert result.md_path.read_text(encoding="utf-8") == "# ok\n"
    assert captured["env_token"] == "test-key"
    assert captured["cwd"] == str(tmp_path)
    assert captured["cmd"] == [
        "/usr/bin/mineru-open-api",
        "extract",
        str(pdf_path),
        "-o",
        str(output_dir),
        "--language",
        "en",
        "--model",
        "vlm",
        "--ocr",
        "--formula=false",
        "--table=true",
        "--timeout",
        "321",
    ]


def test_convert_pdf_cloud_omits_pdf_only_flags_for_html_model_and_passes_custom_base_url(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    captured: dict[str, object] = {}

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        captured["cmd"] = cmd
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# html\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(
            output_dir=output_dir,
            cloud_model_version="MinerU-HTML",
            lang="en",
            parse_method="ocr",
            formula_enable=False,
            table_enable=False,
        ),
        api_key="test-key",
        cloud_url="https://private-mineru.example/api",
    )

    assert result.success is True
    assert captured["cmd"] == [
        "/usr/bin/mineru-open-api",
        "extract",
        str(pdf_path),
        "-o",
        str(output_dir),
        "--language",
        "en",
        "--model",
        "html",
        "--timeout",
        "900",
        "--base-url",
        "https://private-mineru.example/api",
    ]


def test_convert_pdf_cloud_returns_actionable_error_when_cli_missing(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is False
    assert "mineru-open-api" in (result.error or "")
    assert "pip install" in (result.error or "")


def test_convert_pdf_cloud_surfaces_cli_failure_details(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        return subprocess.CompletedProcess(cmd, 6, stdout="", stderr="timed out")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is False
    assert "exit code 6" in (result.error or "")
    assert "timed out" in (result.error or "")


def test_convert_pdf_cloud_retries_timeout_with_exponential_backoff(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    output_dir = tmp_path / "out"

    attempts = {"count": 0}
    sleeps: list[float] = []

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/mineru-open-api" if name == "mineru-open-api" else None)

    def fake_run(cmd, *, capture_output, text, cwd, env, timeout, check):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "paper.md").write_text("# ok after retry\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("scrinium.ingest.mineru.time.sleep", lambda seconds: sleeps.append(seconds))

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=output_dir, upload_retries=3),
        api_key="test-key",
        cloud_url="https://mineru.net/api/v4",
    )

    assert result.success is True
    assert attempts["count"] == 3
    assert sleeps == [1.0, 2.0]
    assert result.md_path == output_dir / "paper.md"


def test_convert_pdfs_cloud_batch_splits_into_chunks(tmp_path, monkeypatch):
    pdf_paths: list[Path] = []
    for idx in range(3):
        pdf_path = tmp_path / f"paper-{idx}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pdf_paths.append(pdf_path)

    calls: list[list[str]] = []

    def fake_convert_chunk_cloud(
        chunk: list[tuple[int, Path]],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
    ) -> list[ConvertResult]:
        calls.append([f"{idx}:{path.name}" for idx, path in chunk])
        return [ConvertResult(pdf_path=path, md_path=tmp_path / f"{path.stem}.md", success=True) for idx, path in chunk]

    monkeypatch.setattr("scrinium.ingest.mineru._convert_chunk_cloud", fake_convert_chunk_cloud)

    results = convert_pdfs_cloud_batch(
        pdf_paths,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.example/api",
        batch_size=2,
    )

    assert calls == [["0:paper-0.pdf", "1:paper-1.pdf"], ["2:paper-2.pdf"]]
    assert len(results) == 3
    assert all(result.success for result in results)


def test_convert_pdfs_cloud_batch_preserves_global_unique_indexes_across_chunks(tmp_path, monkeypatch):
    pdf_paths: list[Path] = []
    for subdir in ("a", "b", "c", "d"):
        pdf_path = tmp_path / subdir / "paper.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4")
        pdf_paths.append(pdf_path)

    seen_dirs: list[Path] = []

    def fake_convert_chunk_cloud(
        chunk: list[tuple[int, Path]],
        opts: ConvertOptions,
        *,
        api_key: str,
        cloud_url: str,
    ) -> list[ConvertResult]:
        results: list[ConvertResult] = []
        for global_idx, path in chunk:
            out_dir = opts.output_dir / f"{global_idx:04d}_{path.stem}"
            seen_dirs.append(out_dir)
            results.append(ConvertResult(pdf_path=path, md_path=out_dir / "index.md", success=True))
        return results

    monkeypatch.setattr("scrinium.ingest.mineru._convert_chunk_cloud", fake_convert_chunk_cloud)

    convert_pdfs_cloud_batch(
        pdf_paths,
        ConvertOptions(output_dir=tmp_path / "out"),
        api_key="test-key",
        cloud_url="https://mineru.example/api",
        batch_size=2,
    )

    assert [path.name for path in seen_dirs] == [
        "0000_paper",
        "0001_paper",
        "0002_paper",
        "0003_paper",
    ]
    assert len(set(seen_dirs)) == 4


def test_convert_chunk_cloud_uses_bounded_parallel_workers(tmp_path, monkeypatch):
    import scrinium.ingest.mineru as mineru

    pdf_paths = []
    for idx in range(3):
        path = tmp_path / f"paper-{idx}.pdf"
        path.write_bytes(b"%PDF-1.4\n")
        pdf_paths.append(path)

    submitted: list[Path] = []
    max_workers_seen: list[int] = []

    class FakeExecutor:
        def __init__(self, max_workers):
            max_workers_seen.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def map(self, fn, items):
            result = []
            for item in items:
                submitted.append(item)
                result.append(fn(item))
            return result

    monkeypatch.setattr(mineru.concurrent.futures, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(
        "scrinium.ingest.mineru.convert_pdf_cloud",
        lambda pdf_path, *_args, **_kwargs: ConvertResult(
            pdf_path=pdf_path,
            md_path=pdf_path.with_suffix(".md"),
            success=True,
        ),
    )

    results = _convert_chunk_cloud(
        list(enumerate(pdf_paths)),
        ConvertOptions(output_dir=tmp_path / "out", upload_workers=2),
        api_key="token",
        cloud_url="https://mineru.example/api",
    )

    assert max_workers_seen == [2]
    assert submitted == list(enumerate(pdf_paths))
    assert [res.pdf_path for res in results] == pdf_paths


def test_convert_chunk_cloud_isolates_duplicate_stems_into_unique_output_dirs(tmp_path, monkeypatch):
    pdf_a = tmp_path / "a" / "source.pdf"
    pdf_b = tmp_path / "b" / "source.pdf"
    pdf_a.parent.mkdir()
    pdf_b.parent.mkdir()
    pdf_a.write_bytes(b"%PDF-1.4\n")
    pdf_b.write_bytes(b"%PDF-1.4\n")

    seen_output_dirs: list[Path] = []

    monkeypatch.setattr(
        "scrinium.ingest.mineru.convert_pdf_cloud",
        lambda pdf_path, opts, **_kwargs: (
            seen_output_dirs.append(opts.output_dir),
            ConvertResult(pdf_path=pdf_path, md_path=(opts.output_dir / "index.md"), success=True),
        )[1],
    )

    results = _convert_chunk_cloud(
        list(enumerate([pdf_a, pdf_b])),
        ConvertOptions(output_dir=tmp_path / "out", upload_workers=2),
        api_key="token",
        cloud_url="https://mineru.example/api",
    )

    assert len(results) == 2
    assert seen_output_dirs[0] != seen_output_dirs[1]


def test_plan_cloud_chunking_uses_600_page_limit_when_only_page_count_exceeds(tmp_path, monkeypatch):
    pdf_path = tmp_path / "long.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_page_count", lambda _path: 601)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 600
    assert "601 pages" in reason


def test_plan_cloud_chunking_uses_size_limit_when_file_is_too_large(tmp_path, monkeypatch):
    pdf_path = tmp_path / "big.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_page_count", lambda _path: 400)
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 320
    assert "250.0 MB" in reason


def test_plan_cloud_chunking_uses_safe_fallback_chunk_size_when_page_count_unknown(tmp_path, monkeypatch):
    pdf_path = tmp_path / "unknown.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_page_count", lambda _path: -1)
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, reason = _plan_cloud_chunking(pdf_path)

    assert should_chunk is True
    assert chunk_size == 100
    assert "250.0 MB" in reason


def test_plan_cloud_chunking_clamps_unknown_page_fallback_to_cloud_max(tmp_path, monkeypatch):
    pdf_path = tmp_path / "unknown.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_page_count", lambda _path: -1)
    monkeypatch.setattr("scrinium.ingest.mineru._get_pdf_size_bytes", lambda _path: 250 * 1024 * 1024)

    should_chunk, chunk_size, _reason = _plan_cloud_chunking(pdf_path, default_chunk_size=800)

    assert should_chunk is True
    assert chunk_size == 600


def test_convert_pdf_cloud_skips_when_markdown_exists_in_nested_layout(tmp_path, monkeypatch):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"
    nested_md = out_dir / pdf_path.stem / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("existing\n", encoding="utf-8")

    monkeypatch.setattr("scrinium.ingest.mineru.shutil.which", lambda _name: "/usr/bin/mineru-open-api")
    monkeypatch.setattr(
        "scrinium.ingest.mineru._locate_cloud_markdown_output",
        lambda _out_dir, _stem: nested_md,
    )
    monkeypatch.setattr(
        "scrinium.ingest.mineru.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should skip existing output")),
    )

    result = convert_pdf_cloud(
        pdf_path,
        ConvertOptions(output_dir=out_dir),
        api_key="token",
    )

    assert result.success is True
    assert result.md_path == nested_md


def test_locate_cloud_markdown_output_does_not_reuse_unrelated_single_markdown(tmp_path):
    out_dir = tmp_path / "out"
    unrelated_md = out_dir / "other" / "index.md"
    unrelated_md.parent.mkdir(parents=True)
    unrelated_md.write_text("other\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") is None


def test_locate_cloud_markdown_output_matches_nested_index_for_requested_stem(tmp_path):
    out_dir = tmp_path / "out"
    nested_md = out_dir / "paper" / "index.md"
    nested_md.parent.mkdir(parents=True)
    nested_md.write_text("paper\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") == nested_md


def test_locate_cloud_markdown_output_ignores_generic_root_markdown_in_shared_output_dir(tmp_path):
    out_dir = tmp_path / "out"
    generic_md = out_dir / "full.md"
    generic_md.parent.mkdir(parents=True)
    generic_md.write_text("generic\n", encoding="utf-8")

    assert _locate_cloud_markdown_output(out_dir, "paper") is None
