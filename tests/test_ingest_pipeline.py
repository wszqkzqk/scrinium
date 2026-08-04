"""Regression tests for ingest pipeline edge cases."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scrinium.ingest.metadata._api import query_semantic_scholar
from scrinium.ingest.metadata._models import PaperMetadata
from scrinium.ingest.pipeline import (
    DedupIndex,
    InboxCtx,
    StepResult,
    _collect_existing_ids,
    run_pipeline,
    step_dedup,
    step_extract,
    step_office_convert,
)


class _DummyResponse:
    status_code = 404
    headers: dict[str, str]

    def __init__(self) -> None:
        self.headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {}


def test_query_semantic_scholar_encodes_old_style_arxiv_id(monkeypatch):
    seen: dict[str, str] = {}

    def fake_get(url: str, timeout: int):
        seen["url"] = url
        return _DummyResponse()

    monkeypatch.setattr("scrinium.ingest.metadata._api.SESSION.get", fake_get)

    query_semantic_scholar(arxiv_id="hep-th/9901001")

    assert seen["url"] == (
        "https://api.semanticscholar.org/graph/v1/paper/"
        "arXiv%3Ahep-th%2F9901001?fields="
        "title,abstract,citationCount,year,externalIds,authors,venue,"
        "publicationTypes,references.externalIds"
    )


def test_query_semantic_scholar_encodes_doi_path_segment(monkeypatch):
    seen: dict[str, str] = {}

    def fake_get(url: str, timeout: int):
        seen["url"] = url
        return _DummyResponse()

    monkeypatch.setattr("scrinium.ingest.metadata._api.SESSION.get", fake_get)

    query_semantic_scholar(doi="10.1017/S0022112094000431")

    assert seen["url"] == (
        "https://api.semanticscholar.org/graph/v1/paper/"
        "DOI%3A10.1017%2FS0022112094000431?fields="
        "title,abstract,citationCount,year,externalIds,authors,venue,"
        "publicationTypes,references.externalIds"
    )


def test_collect_existing_ids_includes_arxiv_ids(tmp_path: Path):
    papers_dir = tmp_path / "papers"
    paper_dir = papers_dir / "Imamura-1999-String-Junctions"
    paper_dir.mkdir(parents=True)
    (paper_dir / "meta.json").write_text(
        json.dumps(
            {
                "title": "String Junctions and Their Duals in Heterotic String Theory",
                "doi": "",
                "ids": {"arxiv": "hep-th/9901001v3"},
            }
        ),
        encoding="utf-8",
    )

    collected = _collect_existing_ids(papers_dir)

    assert collected.dois == {}
    assert collected.pub_nums == {}
    assert collected.arxiv_ids["hep-th/9901001"] == paper_dir / "meta.json"


def test_step_dedup_rejects_duplicate_arxiv_only_preprint(tmp_path: Path, monkeypatch):
    existing_json = tmp_path / "papers" / "Imamura-1999-String-Junctions" / "meta.json"
    existing_json.parent.mkdir(parents=True)
    existing_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("scrinium.ingest.metadata.enrich_metadata", lambda meta: meta)
    monkeypatch.setattr("scrinium.ingest.pipeline._detect_patent", lambda ctx: False)
    monkeypatch.setattr("scrinium.ingest.pipeline._detect_thesis", lambda ctx: False)
    monkeypatch.setattr("scrinium.ingest.pipeline._detect_book", lambda ctx: False)

    moved: dict[str, object] = {}

    def fake_move_to_pending(ctx, *, issue="no_doi", message="", extra=None):
        moved["issue"] = issue
        moved["extra"] = extra or {}

    monkeypatch.setattr("scrinium.ingest.pipeline._move_to_pending", fake_move_to_pending)

    ctx = InboxCtx(
        pdf_path=None,
        inbox_dir=tmp_path / "inbox",
        papers_dir=tmp_path / "papers",
        existing_dois={},
        existing_pub_nums={},
        cfg=SimpleNamespace(_root=tmp_path),
        opts={"no_api": False, "dry_run": False},
        pending_dir=tmp_path / "pending",
        md_path=None,
        meta=PaperMetadata(
            title="String Junctions and Their Duals in Heterotic String Theory",
            arxiv_id="hep-th/9901001v1",
        ),
    )
    ctx.existing_arxiv_ids = {"hep-th/9901001": existing_json}

    result = step_dedup(ctx)

    assert result == StepResult.FAIL
    assert ctx.status == "duplicate"
    assert moved["issue"] == "duplicate"
    assert moved["extra"] == {
        "duplicate_of": "Imamura-1999-String-Junctions",
        "arxiv_id": "hep-th/9901001",
    }


def test_step_dedup_rejects_duplicate_when_existing_preprint_has_only_arxiv_id_but_new_record_gets_doi(
    tmp_path: Path, monkeypatch
):
    existing_json = tmp_path / "papers" / "Imamura-1999-String-Junctions" / "meta.json"
    existing_json.parent.mkdir(parents=True)
    existing_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("scrinium.ingest.pipeline._detect_patent", lambda ctx: False)
    monkeypatch.setattr("scrinium.ingest.pipeline._detect_thesis", lambda ctx: False)
    monkeypatch.setattr("scrinium.ingest.pipeline._detect_book", lambda ctx: False)

    def fake_enrich(meta):
        meta.doi = "10.1000/test-preprint"
        return meta

    monkeypatch.setattr("scrinium.ingest.metadata.enrich_metadata", fake_enrich)

    moved: dict[str, object] = {}

    def fake_move_to_pending(ctx, *, issue="no_doi", message="", extra=None):
        moved["issue"] = issue
        moved["extra"] = extra or {}

    monkeypatch.setattr("scrinium.ingest.pipeline._move_to_pending", fake_move_to_pending)

    ctx = InboxCtx(
        pdf_path=None,
        inbox_dir=tmp_path / "inbox",
        papers_dir=tmp_path / "papers",
        existing_dois={},
        existing_pub_nums={},
        cfg=SimpleNamespace(_root=tmp_path),
        opts={"no_api": False, "dry_run": False},
        pending_dir=tmp_path / "pending",
        md_path=None,
        meta=PaperMetadata(
            title="String Junctions and Their Duals in Heterotic String Theory",
            arxiv_id="hep-th/9901001v2",
        ),
    )
    ctx.existing_arxiv_ids = {"hep-th/9901001": existing_json}

    result = step_dedup(ctx)

    assert result == StepResult.FAIL
    assert ctx.status == "duplicate"
    assert moved["issue"] == "duplicate"
    assert moved["extra"] == {
        "duplicate_of": "Imamura-1999-String-Junctions",
        "arxiv_id": "hep-th/9901001",
    }


def test_step_office_convert_reports_scrinium_office_extra(tmp_path: Path, monkeypatch):
    office_path = tmp_path / "report.docx"
    office_path.write_text("dummy", encoding="utf-8")

    errors: list[str] = []
    monkeypatch.setattr(
        "scrinium.ingest.pipeline._log.error", lambda msg, *args: errors.append(msg % args if args else msg)
    )

    import builtins

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "markitdown":
            raise ModuleNotFoundError("No module named 'markitdown'", name="markitdown")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ctx = InboxCtx(
        pdf_path=None,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=SimpleNamespace(_root=tmp_path),
        opts={"office_path": office_path, "dry_run": False},
    )

    result = step_office_convert(ctx)

    assert result == StepResult.FAIL
    assert ctx.status == "failed"
    assert any("pip install scrinium[office]" in msg for msg in errors)


def test_step_extract_labels_arxiv_id_as_generic_id(tmp_path: Path, monkeypatch):
    md_path = tmp_path / "paper.md"
    md_path.write_text("# test", encoding="utf-8")

    messages: list[str] = []

    class DummyExtractor:
        def extract(self, _path: Path) -> PaperMetadata:
            return PaperMetadata(
                title="String Junctions and Their Duals in Heterotic String Theory",
                first_author_lastname="Imamura",
                year=1999,
                arxiv_id="hep-th/9901001",
            )

    monkeypatch.setattr("scrinium.ingest.pipeline.ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr("scrinium.ingest.extractor.get_extractor", lambda cfg: DummyExtractor())

    ctx = InboxCtx(
        pdf_path=None,
        inbox_dir=tmp_path,
        papers_dir=tmp_path / "papers",
        existing_dois={},
        cfg=SimpleNamespace(_root=tmp_path),
        opts={"dry_run": False},
        md_path=md_path,
    )

    result = step_extract(ctx)

    assert result == StepResult.OK
    assert any("ID: arXiv:hep-th/9901001" in msg for msg in messages)
    assert all("DOI: arXiv:" not in msg for msg in messages)


def test_run_pipeline_executes_scopes_in_order(tmp_path: Path, monkeypatch):
    """Inbox steps run per-file, then papers steps, then global steps."""
    cfg = SimpleNamespace(
        _root=tmp_path,
        papers_dir=tmp_path / "data" / "papers",
    )

    seen_steps: list[str] = []

    def fake_process_inbox(
        inbox_dir,
        papers_dir,
        pending_dir,
        existing_dois,
        inbox_steps,
        cfg,
        opts,
        dry_run,
        ingested_jsons,
        **kwargs,
    ):
        seen_steps.extend(inbox_steps)
        paper_dir = papers_dir / "Smith-2024-Test"
        paper_dir.mkdir(parents=True, exist_ok=True)
        meta_json = paper_dir / "meta.json"
        meta_json.write_text("{}", encoding="utf-8")
        (paper_dir / "paper.md").write_text("content", encoding="utf-8")
        ingested_jsons.append(meta_json)

    monkeypatch.setattr(
        "scrinium.ingest.pipeline._collect_existing_ids",
        lambda *_: DedupIndex(dois={}, pub_nums={}, arxiv_ids={}),
    )
    monkeypatch.setattr("scrinium.ingest.pipeline._process_inbox", fake_process_inbox)

    paper_calls: list[str] = []

    def fake_abstract(json_path, cfg, opts):
        paper_calls.append("abstract")
        return StepResult.OK

    def fake_toc(json_path, cfg, opts):
        paper_calls.append("toc")
        return StepResult.OK

    def fake_index(papers_dir, cfg, opts):
        paper_calls.append("index")
        return StepResult.OK

    monkeypatch.setattr(
        "scrinium.ingest.pipeline.STEPS",
        {
            "mineru": SimpleNamespace(scope="inbox", fn=lambda ctx: StepResult.OK, desc=""),
            "extract": SimpleNamespace(scope="inbox", fn=lambda ctx: StepResult.OK, desc=""),
            "dedup": SimpleNamespace(scope="inbox", fn=lambda ctx: StepResult.OK, desc=""),
            "ingest": SimpleNamespace(scope="inbox", fn=lambda ctx: StepResult.OK, desc=""),
            "abstract": SimpleNamespace(scope="papers", fn=fake_abstract, desc=""),
            "toc": SimpleNamespace(scope="papers", fn=fake_toc, desc=""),
            "index": SimpleNamespace(scope="global", fn=fake_index, desc=""),
        },
    )

    run_pipeline(["mineru", "extract", "dedup", "ingest", "abstract", "toc", "index"], cfg, {})

    assert seen_steps == ["mineru", "extract", "dedup", "ingest"]
    assert paper_calls == ["abstract", "toc", "index"]
