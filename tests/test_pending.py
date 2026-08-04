"""Tests for the `scrinium pending` command and pending.json handoff hints."""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from scrinium import cli
from scrinium.cli import ingest as cli_ingest
from scrinium.ingest.pipeline import (
    HINT_DUPLICATE,
    HINT_NO_DOI,
    HINT_NO_PUB_NUM,
    InboxCtx,
    _move_to_pending,
)


def _run_pending(tmp_path, monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(cli_ingest, "ui", lambda msg="": messages.append(msg))
    cfg = SimpleNamespace(_root=tmp_path)
    cli.cmd_pending(Namespace(), cfg)
    return messages


def _write_pending(root, name, payload):
    d = root / "data" / "pending" / name
    d.mkdir(parents=True)
    (d / "pending.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return d


class TestCmdPending:
    def test_empty_outputs_no_pending(self, tmp_path, monkeypatch):
        messages = _run_pending(tmp_path, monkeypatch)

        assert messages == ["无待确认项"]

    def test_groups_by_issue_with_counts_and_suggestions(self, tmp_path, monkeypatch):
        _write_pending(
            tmp_path,
            "paper-a",
            {"issue": "no_doi", "message": "m", "extracted_metadata": {"title": "Paper A"}},
        )
        _write_pending(
            tmp_path,
            "paper-b",
            {
                "issue": "duplicate",
                "message": "m",
                "duplicate_of": "Smith-2023-X",
                "extracted_metadata": {"title": "Paper B"},
            },
        )
        dup = tmp_path / "data" / "duplicates" / "Wang-2024-Y"
        dup.mkdir(parents=True)
        (dup / "meta.json").write_text(json.dumps({"title": "Legacy Dup"}), encoding="utf-8")

        out = "\n".join(_run_pending(tmp_path, monkeypatch))

        assert "[no_doi] 1 项" in out
        assert "[duplicate] 2 项" in out
        assert "paper-a" in out
        assert "标题: Paper A" in out
        assert "重复于: Smith-2023-X" in out
        assert "Legacy Dup" in out
        # Handoff hints: each group carries the takeover suggestion for its issue.
        assert HINT_NO_DOI in out
        assert HINT_DUPLICATE in out
        assert "共 3 项" in out
        assert "hint: 以上条目建议派 subagent" in out

    def test_no_pub_num_suggestion_points_to_patent_inbox(self, tmp_path, monkeypatch):
        _write_pending(
            tmp_path,
            "patent-a",
            {"issue": "no_pub_num", "message": "m", "extracted_metadata": {"title": "Patent A"}},
        )

        out = "\n".join(_run_pending(tmp_path, monkeypatch))

        assert "[no_pub_num] 1 项" in out
        assert "data/inbox-patent/" in out

    def test_dir_without_marker_is_skipped(self, tmp_path, monkeypatch):
        (tmp_path / "data" / "pending" / "stray").mkdir(parents=True)

        messages = _run_pending(tmp_path, monkeypatch)

        assert messages == ["无待确认项"]


class TestPendingMarkerHint:
    """_move_to_pending writes a handoff hint into pending.json."""

    def _make_ctx(self, tmp_path, stem="some-paper"):
        from scrinium.ingest.metadata._models import PaperMetadata

        inbox_dir = tmp_path / f"inbox-{stem}"
        inbox_dir.mkdir()
        pdf = inbox_dir / f"{stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return InboxCtx(
            pdf_path=pdf,
            inbox_dir=inbox_dir,
            papers_dir=tmp_path / "papers",
            existing_dois={},
            cfg=SimpleNamespace(_root=tmp_path),
            opts={"dry_run": False},
            pending_dir=tmp_path / "pending",
            meta=PaperMetadata(title="Some Paper"),
        )

    def test_hint_written_per_issue(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        _move_to_pending(ctx, issue="no_doi")

        marker = json.loads((tmp_path / "pending" / "some-paper" / "pending.json").read_text(encoding="utf-8"))
        assert marker["issue"] == "no_doi"
        assert marker["hint"] == HINT_NO_DOI
        assert marker["extracted_metadata"]["title"] == "Some Paper"

    def test_hint_for_duplicate_and_no_pub_num(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        _move_to_pending(ctx, issue="duplicate", extra={"duplicate_of": "Smith-2023-X"})
        marker = json.loads((tmp_path / "pending" / "some-paper" / "pending.json").read_text(encoding="utf-8"))
        assert marker["hint"] == HINT_DUPLICATE
        assert marker["duplicate_of"] == "Smith-2023-X"

        ctx2 = self._make_ctx(tmp_path, stem="other-patent")
        _move_to_pending(ctx2, issue="no_pub_num")
        marker2 = json.loads((tmp_path / "pending" / "other-patent" / "pending.json").read_text(encoding="utf-8"))
        assert marker2["hint"] == HINT_NO_PUB_NUM

    def test_unknown_issue_gets_fallback_hint(self, tmp_path):
        ctx = self._make_ctx(tmp_path)
        _move_to_pending(ctx, issue="mystery")
        marker = json.loads((tmp_path / "pending" / "some-paper" / "pending.json").read_text(encoding="utf-8"))
        assert marker["hint"] == "建议派 subagent 审查后处理"


class TestCmdPendingHintOutput:
    def test_pending_output_shows_stored_hint(self, tmp_path, monkeypatch):
        _write_pending(
            tmp_path,
            "paper-a",
            {
                "issue": "no_doi",
                "message": "m",
                "hint": HINT_NO_DOI,
                "extracted_metadata": {"title": "Paper A"},
            },
        )

        out = "\n".join(_run_pending(tmp_path, monkeypatch))

        assert f"hint: {HINT_NO_DOI}" in out

    def test_pending_output_falls_back_to_issue_suggestion_without_stored_hint(self, tmp_path, monkeypatch):
        # Legacy markers without a hint field still get the per-issue suggestion.
        _write_pending(
            tmp_path,
            "paper-a",
            {"issue": "no_doi", "message": "m", "extracted_metadata": {"title": "Paper A"}},
        )

        out = "\n".join(_run_pending(tmp_path, monkeypatch))

        assert f"hint: {HINT_NO_DOI}" in out
