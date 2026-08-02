"""Tests for scrinium.log — logging setup, session ID, ui()."""

from __future__ import annotations

import io
import logging
import sys

import pytest

from scrinium.config import _build_config
from scrinium.log import get_logger, get_session_id, reset, setup, ui


@pytest.fixture(autouse=True)
def _reset_log():
    """Reset log module state between tests."""
    reset()
    yield
    reset()


class TestSetup:
    def test_returns_session_id(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert len(sid) == 12
        assert sid.isalnum()

    def test_idempotent(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid1 = setup(cfg)
        sid2 = setup(cfg)
        assert sid1 == sid2

    def test_creates_log_file_parent(self, tmp_path):
        cfg = _build_config(
            {"logging": {"file": "logs/deep/app.log"}},
            tmp_path,
        )
        setup(cfg)
        assert (tmp_path / "logs" / "deep").exists()

    def test_get_session_id_before_setup(self):
        assert get_session_id() == ""

    def test_get_session_id_after_setup(self, tmp_path):
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert get_session_id() == sid

    def test_stdio_reconfigured_to_utf8(self, tmp_path):
        """After setup, reconfigurable stdio streams must use UTF-8."""
        cfg = _build_config({}, tmp_path)
        setup(cfg)
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure") and stream.encoding:
                assert stream.encoding.lower().replace("-", "") == "utf8"

    def test_setup_tolerates_non_reconfigurable_stdio(self, tmp_path, monkeypatch):
        """StringIO-style streams without reconfigure must not break setup."""
        monkeypatch.setattr(sys, "stdout", io.StringIO())
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert len(sid) == 12

    def test_setup_tolerates_failing_reconfigure(self, tmp_path, monkeypatch):
        """A stream whose reconfigure raises must be skipped silently."""

        class BrokenStream(io.StringIO):
            def reconfigure(self, **kwargs):
                raise ValueError("cannot reconfigure")

        monkeypatch.setattr(sys, "stdout", BrokenStream())
        monkeypatch.setattr(sys, "stderr", BrokenStream())
        cfg = _build_config({}, tmp_path)
        sid = setup(cfg)
        assert len(sid) == 12


class TestGetLogger:
    def test_returns_logger(self):
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"


class TestUI:
    def test_ui_no_args(self, caplog):
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            ui()
        # Should not crash

    def test_ui_with_message(self, caplog):
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            ui("hello %s", "world")
        assert "hello world" in caplog.text

    def test_ui_custom_logger(self, caplog):
        custom = logging.getLogger("custom.test")
        with caplog.at_level(logging.INFO, logger="custom.test"):
            ui("test msg", logger=custom)
        assert "test msg" in caplog.text
