from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scrinium.config import Config
from scrinium.ingest import parser_matrix_benchmark as bench


def test_slugify_value_handles_common_types():
    assert bench.slugify_value(True) == "true"
    assert bench.slugify_value(False) == "false"
    assert bench.slugify_value(300) == "300"
    assert bench.slugify_value(" referenced ") == "referenced"
    assert bench.slugify_value("RapidOCR + CUDA") == "rapidocr-cuda"


def test_make_run_slug_includes_parser_and_sorted_options():
    cfg = bench.RunConfig(
        parser="docling",
        options={
            "ocr_engine": "rapidocr",
            "enrich_formula": True,
            "image_export_mode": "referenced",
        },
    )
    assert bench.make_run_slug(cfg) == "docling__enrich_formula-true__image_export_mode-referenced__ocr_engine-rapidocr"


def test_expand_run_configs_builds_cross_product():
    spec = {
        "parser": "docling",
        "matrix": {
            "ocr_engine": ["rapidocr", "tesseract"],
            "enrich_formula": [False, True],
        },
    }
    runs = bench.expand_run_configs(spec)
    assert [r.parser for r in runs] == ["docling", "docling", "docling", "docling"]
    assert [r.options for r in runs] == [
        {"ocr_engine": "rapidocr", "enrich_formula": False},
        {"ocr_engine": "rapidocr", "enrich_formula": True},
        {"ocr_engine": "tesseract", "enrich_formula": False},
        {"ocr_engine": "tesseract", "enrich_formula": True},
    ]


def test_expand_run_configs_uses_explicit_name_when_given():
    spec = {
        "parser": "marker",
        "name": "marker_best",
        "options": {
            "force_ocr": True,
        },
    }
    runs = bench.expand_run_configs(spec)
    assert len(runs) == 1
    assert runs[0].name == "marker_best"


def test_make_output_dir_uses_index_and_slug(tmp_path: Path):
    cfg = bench.RunConfig(parser="pymupdf", options={"mode": "text"})
    out_dir = bench.make_output_dir(tmp_path, 3, cfg)
    assert out_dir == tmp_path / "03__pymupdf__mode-text"


def test_run_one_rejects_marker_parser(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"
    cfg = bench.RunConfig(parser="marker")

    result = bench.run_one(pdf, cfg, out_dir)

    assert result["ok"] is False
    assert result["error"] == "unsupported parser: marker"


def test_build_docling_command_includes_artifacts_path(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    raw_dir = tmp_path / "raw"
    cmd = bench._build_docling_command(
        pdf,
        raw_dir,
        {
            "to": "md",
            "artifacts_path": "/home/lzmo/.cache/scrinium/docling",
            "image_export_mode": "referenced",
        },
    )

    assert "--artifacts-path" in cmd
    assert "/home/lzmo/.cache/scrinium/docling" in cmd
    assert "--image-export-mode" in cmd


def test_build_docling_command_skips_none_and_empty_values(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    raw_dir = tmp_path / "raw"
    cmd = bench._build_docling_command(
        pdf,
        raw_dir,
        {
            "to": "md",
            "ocr_engine": None,
            "image_export_mode": "",
            "force_ocr": True,
        },
    )

    assert "--ocr-engine" not in cmd
    assert "--image-export-mode" not in cmd
    assert "--force-ocr" in cmd


def test_run_mineru_cloud_threads_cloud_model_version(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md = tmp_path / "paper.md"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    captured = {}

    monkeypatch.setattr(bench, "load_config", lambda: Config())

    class DummyResult:
        def __init__(self, md_path: Path):
            self.success = True
            self.error = None
            self.md_path = md_path

    monkeypatch.setattr(
        bench,
        "convert_pdf_cloud",
        lambda pdf_path, opts, api_key, cloud_url: (
            captured.setdefault("cloud_model_version", opts.cloud_model_version),
            DummyResult(raw_dir / "result.md"),
        )[1],
    )
    (raw_dir / "result.md").write_text("ok\n", encoding="utf-8")

    result = bench._run_mineru_cloud(
        pdf,
        md,
        raw_dir,
        bench.RunConfig(parser="mineru-cloud", options={"cloud_model_version": "vlm"}),
    )

    assert result["ok"] is True
    assert captured["cloud_model_version"] == "vlm"


def test_run_mineru_cloud_normalizes_choice_like_options(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md = tmp_path / "paper.md"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    captured = {}

    monkeypatch.setattr(bench, "load_config", lambda: Config())

    class DummyResult:
        def __init__(self, md_path: Path):
            self.success = True
            self.error = None
            self.md_path = md_path

    monkeypatch.setattr(
        bench,
        "convert_pdf_cloud",
        lambda pdf_path, opts, api_key, cloud_url: (
            captured.setdefault("backend", opts.backend),
            captured.setdefault("cloud_model_version", opts.cloud_model_version),
            captured.setdefault("lang", opts.lang),
            captured.setdefault("parse_method", opts.parse_method),
            DummyResult(raw_dir / "result.md"),
        )[-1],
    )
    (raw_dir / "result.md").write_text("ok\n", encoding="utf-8")

    result = bench._run_mineru_cloud(
        pdf,
        md,
        raw_dir,
        bench.RunConfig(
            parser="mineru-cloud",
            options={
                "backend": "Pipeline",
                "cloud_model_version": "VLM",
                "lang": " EN ",
                "parse_method": "OCR",
            },
        ),
    )

    assert result["ok"] is True
    assert captured == {
        "backend": "pipeline",
        "cloud_model_version": "vlm",
        "lang": "en",
        "parse_method": "ocr",
    }


def test_run_one_accepts_hyphenated_mineru_cloud_name(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(
        bench,
        "_run_mineru_cloud",
        lambda pdf_path, md_path, raw_dir, cfg: {"ok": True, "error": None, "command": "cloud"},
    )

    result = bench.run_one(pdf, bench.RunConfig(parser="mineru-cloud"), out_dir)

    assert result["ok"] is True
    assert result["error"] is None


def test_run_one_accepts_mixed_case_docling_name(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    out_dir = tmp_path / "out"

    monkeypatch.setattr(bench, "_build_docling_command", lambda *_args, **_kwargs: ["docling", "--version"])
    monkeypatch.setattr(
        bench.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("popen called")),
    )

    result = bench.run_one(pdf, bench.RunConfig(parser="Docling"), out_dir)

    assert result["ok"] is False
    assert result["error"] == "RuntimeError: popen called"


def test_run_benchmark_refuses_non_empty_output_dir(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output_root = tmp_path / "existing"
    output_root.mkdir()
    sentinel = output_root / "keep.txt"
    sentinel.write_text("do not delete\n", encoding="utf-8")

    with pytest.raises(ValueError, match="output_root must be empty or not exist"):
        bench.run_benchmark(pdf, [], output_root)

    assert sentinel.read_text(encoding="utf-8") == "do not delete\n"


def test_run_cli_parser_waits_and_closes_streams_on_timeout(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md = tmp_path / "paper.md"
    raw_dir = tmp_path / "raw"
    logs_dir = tmp_path / "logs"
    raw_dir.mkdir()
    logs_dir.mkdir()
    cfg = bench.RunConfig(parser="docling", options={"timeout_sec": 1})

    monkeypatch.setattr(bench, "_build_docling_command", lambda *_args, **_kwargs: ["docling", str(pdf)])

    class FakePipe:
        def __init__(self, fd: int):
            self._fd = fd
            self.closed = False

        def fileno(self) -> int:
            return self._fd

        def close(self) -> None:
            self.closed = True

    class FakeProc:
        def __init__(self):
            self.stdout = FakePipe(10)
            self.stderr = FakePipe(11)
            self.kill_called = False
            self.wait_called = False

        def kill(self) -> None:
            self.kill_called = True

        def wait(self) -> int:
            self.wait_called = True
            return -9

    fake_proc = FakeProc()
    monkeypatch.setattr(bench.subprocess, "Popen", lambda *_args, **_kwargs: fake_proc)

    selector_state = SimpleNamespace(closed=False)

    class FakeSelector:
        def __init__(self):
            self._map: dict[object, object] = {}

        def register(self, fileobj, _event, data) -> None:
            self._map[fileobj] = data

        def unregister(self, fileobj) -> None:
            self._map.pop(fileobj)

        def get_map(self) -> dict[object, object]:
            return self._map

        def select(self, timeout: float = 1.0) -> list[tuple[object, int]]:
            return []

        def close(self) -> None:
            selector_state.closed = True

    monkeypatch.setattr(bench.selectors, "DefaultSelector", FakeSelector)

    monotonic_values = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(bench.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(bench.subprocess.TimeoutExpired):
        bench._run_cli_parser(pdf, md, raw_dir, logs_dir, cfg)

    assert fake_proc.kill_called is True
    assert fake_proc.wait_called is True
    assert fake_proc.stdout.closed is True
    assert fake_proc.stderr.closed is True
    assert selector_state.closed is True
