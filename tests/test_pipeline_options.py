"""Tests for PipelineOptions, PipelineError boundaries, and dedup failure reporting."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scrinium.config import Config
from scrinium.ingest.pipeline import (
    DedupIndex,
    PipelineError,
    PipelineOptions,
    _collect_existing_ids,
    _process_inbox,
    run_pipeline,
)


class TestPipelineOptions:
    def test_defaults_match_legacy_dict_get(self):
        opts = PipelineOptions()
        assert opts.dry_run is False
        assert opts.no_api is False
        assert opts.force is False
        assert opts.inspect is False
        assert opts.max_retries == 2
        assert opts.rebuild is False
        assert opts.inbox_dir is None
        assert opts.papers_dir is None
        assert opts.include_aux_inboxes is True
        assert opts.translate_lang is None
        assert opts.office_path is None

    def test_from_mapping_roundtrip(self):
        opts = PipelineOptions.from_mapping({"dry_run": True, "no_api": True, "max_retries": 5})
        assert opts.dry_run is True
        assert opts.no_api is True
        assert opts.max_retries == 5
        assert opts.include_aux_inboxes is True  # untouched field keeps default

    def test_from_mapping_rejects_unknown_keys(self):
        with pytest.raises(TypeError, match="unknown pipeline option"):
            PipelineOptions.from_mapping({"dry_rnu": True})

    def test_dict_style_read_compat(self):
        opts = PipelineOptions(dry_run=True)
        assert opts["dry_run"] is True
        assert opts.get("no_api") is False
        assert opts.get("missing", "fallback") == "fallback"
        with pytest.raises(KeyError):
            opts["missing"]


class TestPipelineErrorBoundary:
    def test_run_pipeline_unknown_step_raises_instead_of_exit(self, tmp_path):
        cfg = SimpleNamespace(translate=SimpleNamespace(auto_translate=False))
        with pytest.raises(PipelineError, match="未知步骤"):
            run_pipeline(["no_such_step"], cfg, {})

    def test_process_inbox_mineru_unreachable_raises_instead_of_exit(self, tmp_path, monkeypatch):
        inbox_dir = tmp_path / "inbox"
        inbox_dir.mkdir()
        (inbox_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n")

        cfg = Config()
        cfg._root = tmp_path
        monkeypatch.setattr(cfg, "resolved_mineru_api_key", lambda: "")

        import scrinium.ingest.mineru as mineru

        monkeypatch.setattr(mineru, "check_server", lambda *_: False)

        with pytest.raises(PipelineError, match="MinerU 不可达"):
            _process_inbox(
                inbox_dir,
                tmp_path / "papers",
                tmp_path / "pending",
                {},
                ["mineru", "extract"],
                cfg,
                {},
                False,
                [],
            )


class TestCollectExistingIdsFailures:
    def test_failed_reads_are_reported(self, tmp_path, caplog):
        papers_dir = tmp_path / "papers"
        good = papers_dir / "Smith-2023-Good"
        good.mkdir(parents=True)
        (good / "meta.json").write_text(json.dumps({"doi": "10.1/x"}), encoding="utf-8")
        bad = papers_dir / "Broken-2023-Bad"
        bad.mkdir()
        (bad / "meta.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="scrinium.ingest.pipeline"):
            collected = _collect_existing_ids(papers_dir)

        assert isinstance(collected, DedupIndex)
        assert collected.dois == {"10.1/x": good / "meta.json"}
        assert collected.failed == [bad / "meta.json"]
        assert any("dedup may miss" in r.message for r in caplog.records)

        # Legacy three-way unpacking still works.
        dois, pub_nums, arxiv_ids = collected
        assert dois == {"10.1/x": good / "meta.json"}
        assert pub_nums == {}
        assert arxiv_ids == {}

    def test_run_pipeline_warns_when_dedup_incomplete(self, tmp_path, monkeypatch):
        cfg = SimpleNamespace(
            translate=SimpleNamespace(auto_translate=False),
            _root=tmp_path,
            papers_dir=tmp_path / "papers",
        )
        messages: list[str] = []
        monkeypatch.setattr("scrinium.ingest.pipeline.ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr(
            "scrinium.ingest.pipeline._collect_existing_ids",
            lambda *_: DedupIndex(
                dois={},
                pub_nums={},
                arxiv_ids={},
                failed=[tmp_path / "papers" / "Broken-2023-Bad" / "meta.json"],
            ),
        )
        monkeypatch.setattr("scrinium.ingest.pipeline._process_inbox", lambda *_args, **_kwargs: None)

        run_pipeline(["extract"], cfg, {})

        assert any("去重可能不完整" in m for m in messages)

    def test_run_pipeline_no_warning_when_all_readable(self, tmp_path, monkeypatch):
        cfg = SimpleNamespace(
            translate=SimpleNamespace(auto_translate=False),
            _root=tmp_path,
            papers_dir=tmp_path / "papers",
        )
        messages: list[str] = []
        monkeypatch.setattr("scrinium.ingest.pipeline.ui", lambda msg="": messages.append(msg))
        monkeypatch.setattr("scrinium.ingest.pipeline._process_inbox", lambda *_args, **_kwargs: None)

        run_pipeline(["extract"], cfg, {})

        assert not any("去重可能不完整" in m for m in messages)


class TestInboxCtxOptsCoercion:
    def test_legacy_dict_opts_are_coerced(self, tmp_path):
        from scrinium.ingest.pipeline import InboxCtx

        ctx = InboxCtx(
            pdf_path=None,
            inbox_dir=tmp_path,
            papers_dir=tmp_path / "papers",
            existing_dois={},
            cfg=SimpleNamespace(_root=tmp_path),
            opts={"dry_run": True, "no_api": True},
        )
        assert isinstance(ctx.opts, PipelineOptions)
        assert ctx.opts.dry_run is True
        assert ctx.opts.no_api is True

    def test_unknown_opts_key_raises(self, tmp_path):
        from scrinium.ingest.pipeline import InboxCtx

        with pytest.raises(TypeError, match="unknown pipeline option"):
            InboxCtx(
                pdf_path=None,
                inbox_dir=tmp_path,
                papers_dir=tmp_path / "papers",
                existing_dois={},
                cfg=SimpleNamespace(_root=tmp_path),
                opts={"dry_rnu": True},
            )
