"""Robustness tests for the CLI entry point."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from scrinium import cli
from scrinium.index import build_index

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_main_cfg(tmp_path: Path, index_db: Path) -> SimpleNamespace:
    """Minimal cfg for cli.main(): real log.setup, stubbed metrics/network."""
    return SimpleNamespace(
        ensure_dirs=lambda: None,
        metrics_db_path=str(tmp_path / "metrics.db"),
        ingest=SimpleNamespace(contact_email=""),
        resolved_s2_api_key=lambda: "",
        log_file=tmp_path / "logs" / "scrinium.log",
        log=SimpleNamespace(max_bytes=1_000_000, backup_count=1, level="INFO"),
        index_db=index_db,
        search=SimpleNamespace(top_k=10),
    )


class TestMainValueError:
    def test_bad_year_prints_message_without_traceback(self, tmp_papers, tmp_db, tmp_path, monkeypatch, capsys):
        from scrinium import log

        build_index(tmp_papers, tmp_db)

        log.reset()
        monkeypatch.setattr(cli, "load_config", lambda: _fake_main_cfg(tmp_path, tmp_db))
        monkeypatch.setattr("scrinium.metrics.init", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("scrinium.ingest.metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scrinium.ingest.metadata._models.configure_s2_session", lambda *_: None)
        monkeypatch.setattr(sys, "argv", ["scrinium", "search", "RNA", "--year", "abc"])

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


class TestMainPipelineError:
    def test_pipeline_error_prints_message_without_traceback(self, tmp_path, monkeypatch, capsys):
        from scrinium import log
        from scrinium.ingest.pipeline import PipelineError

        log.reset()
        monkeypatch.setattr(cli, "load_config", lambda: _fake_main_cfg(tmp_path, tmp_path / "index.db"))
        monkeypatch.setattr("scrinium.metrics.init", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("scrinium.ingest.metadata._models.configure_session", lambda *_: None)
        monkeypatch.setattr("scrinium.ingest.metadata._models.configure_s2_session", lambda *_: None)

        def fake_run_pipeline(*_args, **_kwargs):
            raise PipelineError("MinerU 不可达且未配置 MinerU token")

        monkeypatch.setattr("scrinium.ingest.pipeline.run_pipeline", fake_run_pipeline)
        monkeypatch.setattr(sys, "argv", ["scrinium", "pipeline", "full", "--dry-run"])

        with pytest.raises(SystemExit) as exc_info:
            try:
                cli.main()
            finally:
                log.reset()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "错误: MinerU 不可达且未配置 MinerU token" in combined
        assert "Traceback" not in combined


class TestVersionFlag:
    def test_version_flag_prints_version_and_exits_zero(self, capsys):
        from scrinium import __version__

        parser = cli._build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert f"scrinium {__version__}" in out


class TestBrokenPipe:
    def test_cli_with_closed_pipe_exits_zero_without_traceback(self):
        read_fd, write_fd = os.pipe()
        os.close(read_fd)  # no reader: the first flush triggers EPIPE
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.argv = ['scrinium', 'style', 'list']; from scrinium.cli import main; main()",
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

    def test_main_treats_windows_einval_as_broken_pipe(self):
        # Windows raises OSError(EINVAL) instead of BrokenPipeError on closed pipes
        def fake_flush():
            raise OSError(errno.EINVAL, "Invalid argument")

        # Context-scoped patches restore before pytest's capture teardown flushes
        with (
            mock.patch.object(sys, "argv", ["scrinium", "style", "list"]),
            mock.patch.object(os, "open", lambda *a, **k: 999),
            mock.patch.object(os, "dup2", lambda a, b: None),
            mock.patch.object(sys.stdout, "flush", fake_flush),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli.main()
        assert exc_info.value.code == 0
