"""Robustness tests for the CLI entry point and insights failure diagnosis."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scholaraio import cli, insights, metrics
from scholaraio.index import build_index

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_main_cfg(tmp_path: Path, index_db: Path) -> SimpleNamespace:
    """Minimal cfg for cli.main(): real log.setup, stubbed metrics/network."""
    return SimpleNamespace(
        ensure_dirs=lambda: None,
        metrics_db_path=str(tmp_path / "metrics.db"),
        ingest=SimpleNamespace(contact_email=""),
        resolved_s2_api_key=lambda: "",
        log_file=tmp_path / "logs" / "scholaraio.log",
        log=SimpleNamespace(max_bytes=1_000_000, backup_count=1, level="INFO"),
        index_db=index_db,
        search=SimpleNamespace(top_k=10),
    )


class TestMainValueError:
    def test_bad_year_prints_message_without_traceback(self, tmp_papers, tmp_db, tmp_path, monkeypatch, capsys):
        from scholaraio import log

        build_index(tmp_papers, tmp_db)

        log.reset()
        monkeypatch.setattr(cli, "load_config", lambda: _fake_main_cfg(tmp_path, tmp_db))
        monkeypatch.setattr("scholaraio.metrics.init", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("scholaraio.ingest.metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scholaraio.ingest.metadata._models.configure_s2_session", lambda *_: None)
        monkeypatch.setattr(sys, "argv", ["scholaraio", "search", "RNA", "--year", "abc"])

        with pytest.raises(SystemExit) as exc_info:
            try:
                cli.main()
            finally:
                log.reset()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "无法解析年份" in combined
        assert "Traceback" not in combined


class TestVersionFlag:
    def test_version_flag_prints_version_and_exits_zero(self, capsys):
        from scholaraio import __version__

        parser = cli._build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert f"scholaraio {__version__}" in out


class TestBrokenPipe:
    def test_cli_with_closed_pipe_exits_zero_without_traceback(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)  # no reader: the first flush triggers EPIPE
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.argv = ['scholaraio', 'style', 'list']; from scholaraio.cli import main; main()",
                ],
                stdout=write_fd,
                stderr=subprocess.PIPE,
                timeout=120,
                cwd=_REPO_ROOT,
            )
        finally:
            os.close(write_fd)

        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        assert b"Traceback" not in proc.stderr


def _make_papers(tmp_path: Path, papers: dict[str, dict]) -> Path:
    papers_dir = tmp_path / "papers"
    for name, meta in papers.items():
        paper_dir = papers_dir / name
        paper_dir.mkdir(parents=True)
        (paper_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return papers_dir


class _FakeStore:
    """Stand-in for the metrics store: fixed read history, nothing else read."""

    def __init__(self, read_names: list[str]):
        self._read_names = read_names

    def query(self, category, since=None, limit=None):
        assert category == "read"
        return [{"name": name, "detail": ""} for name in self._read_names]

    def query_distinct_names(self, category):
        assert category == "read"
        return set(self._read_names)


def _raise(exc: Exception):
    def _raiser(*_args, **_kwargs):
        raise exc

    return _raiser


class TestRecommendUnreadNeighborsDiagnosis:
    def test_empty_vector_index_raises_not_ready(self, tmp_path, monkeypatch):
        papers_dir = _make_papers(tmp_path, {"Paper-A": {"title": "T", "abstract": "a"}})
        monkeypatch.setattr(
            "scholaraio.vectors.vsearch",
            _raise(FileNotFoundError("向量索引为空，请先运行 `scholaraio embed`")),
        )
        cfg = SimpleNamespace(papers_dir=papers_dir, index_db=tmp_path / "index.db")

        with pytest.raises(insights.VectorIndexNotReady):
            insights.recommend_unread_neighbors(_FakeStore(["Paper-A"]), cfg)

    def test_embedding_failure_raises_backend_unavailable(self, tmp_path, monkeypatch):
        papers_dir = _make_papers(tmp_path, {"Paper-A": {"title": "T", "abstract": "a"}})
        monkeypatch.setattr(
            "scholaraio.vectors.vsearch",
            _raise(RuntimeError("Hugging Face is unreachable and no local embedding model was found")),
        )
        cfg = SimpleNamespace(papers_dir=papers_dir, index_db=tmp_path / "index.db")

        with pytest.raises(insights.EmbeddingBackendUnavailable) as exc_info:
            insights.recommend_unread_neighbors(_FakeStore(["Paper-A"]), cfg)

        assert "RuntimeError" in str(exc_info.value)

    def test_import_error_still_propagates(self, tmp_path, monkeypatch):
        papers_dir = _make_papers(tmp_path, {"Paper-A": {"title": "T", "abstract": "a"}})
        monkeypatch.setattr("scholaraio.vectors.vsearch", _raise(ImportError("No module named 'faiss'")))
        cfg = SimpleNamespace(papers_dir=papers_dir, index_db=tmp_path / "index.db")

        with pytest.raises(ImportError):
            insights.recommend_unread_neighbors(_FakeStore(["Paper-A"]), cfg)

    def test_no_unread_neighbors_returns_empty(self, tmp_path, monkeypatch):
        papers_dir = _make_papers(tmp_path, {"Paper-A": {"title": "T", "abstract": "a"}})
        monkeypatch.setattr(
            "scholaraio.vectors.vsearch",
            lambda *a, **k: [{"dir_name": "Paper-A", "score": 0.9}],  # already read -> filtered
        )
        cfg = SimpleNamespace(papers_dir=papers_dir, index_db=tmp_path / "index.db")

        assert insights.recommend_unread_neighbors(_FakeStore(["Paper-A"]), cfg) == []

    def test_partial_embedding_failure_still_recommends(self, tmp_path, monkeypatch):
        papers_dir = _make_papers(
            tmp_path,
            {
                "Paper-A": {"title": "TA", "abstract": "a"},
                "Paper-B": {"title": "TB", "abstract": "b"},
                "Paper-C": {"title": "TC", "abstract": "c"},
            },
        )
        calls = {"n": 0}

        def fake_vsearch(query, db_path, top_k, cfg):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient embedding failure")
            return [{"dir_name": "Paper-C", "score": 0.8}]

        monkeypatch.setattr("scholaraio.vectors.vsearch", fake_vsearch)
        cfg = SimpleNamespace(papers_dir=papers_dir, index_db=tmp_path / "index.db")

        recommendations = insights.recommend_unread_neighbors(_FakeStore(["Paper-A", "Paper-B"]), cfg)

        assert [(pid, score) for pid, _title, score in recommendations] == [("Paper-C", 0.8)]


def _run_cmd_insights(tmp_path: Path, monkeypatch, vsearch_impl) -> list[str]:
    """Run cmd_insights with one read event and a stubbed vsearch; return ui messages."""
    papers_dir = _make_papers(tmp_path, {"Paper-A": {"title": "T", "abstract": "a"}})

    store = metrics.init(tmp_path / "metrics.db", "test-session")
    store.record("read", "Paper-A", detail={"title": "T"})

    messages: list[str] = []
    monkeypatch.setattr(cli, "ui", lambda msg="": messages.append(msg))
    monkeypatch.setattr("scholaraio.vectors.vsearch", vsearch_impl)

    cfg = SimpleNamespace(_root=tmp_path, papers_dir=papers_dir, index_db=tmp_path / "index.db")
    try:
        cli.cmd_insights(Namespace(days=30), cfg)
    finally:
        metrics.reset()
    return messages


class TestInsightsNeighborMessage:
    def test_embedding_failure_message_names_model_not_index(self, tmp_path, monkeypatch):
        messages = _run_cmd_insights(tmp_path, monkeypatch, _raise(RuntimeError("embedding API failed: 403")))

        joined = "\n".join(messages)
        assert "嵌入模型未下载或不可用" in joined
        assert "embed.provider" in joined
        assert "可能向量索引未建立" not in joined

    def test_empty_index_message_points_to_embed(self, tmp_path, monkeypatch):
        messages = _run_cmd_insights(
            tmp_path,
            monkeypatch,
            _raise(FileNotFoundError("向量索引为空，请先运行 `scholaraio embed`")),
        )

        joined = "\n".join(messages)
        assert "向量索引为空" in joined
        assert "scholaraio embed" in joined
        assert "嵌入模型未下载或不可用" not in joined
