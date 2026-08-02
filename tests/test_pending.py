"""Tests for the `scrinium pending` command."""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from scrinium import cli
from scrinium.cli import ingest as cli_ingest


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
        assert "补全 DOI 后将文件放回 data/inbox/ 重新 ingest" in out
        assert "确认重复后可删除该目录" in out
        assert "共 3 项" in out

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
