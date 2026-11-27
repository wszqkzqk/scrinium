"""
log.py -- Scrinium logging initialization.

Three output layers:
  1. Rotating file handler (DEBUG, full record)
  2. Console stream handler (INFO, bare print-style message)
  3. ``ui()`` -- drop-in replacement for ``print()`` writing to both console and file
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

_session_id: str = ""
_initialized: bool = False

# Format: file handler gets timestamp+module+level; console gets bare message
_FILE_FMT = "%(asctime)s %(name)-24s %(levelname)-5s %(message)s"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"
_CONSOLE_FMT = "%(message)s"


def _reconfigure_stdio() -> None:
    """Force UTF-8 on stdout/stderr.

    On Windows, redirected stdout/stderr (pipe or file) use the system ANSI
    code page (cp936/cp1252), which crashes or mangles CJK JSON output and
    unicode symbols. Reconfiguring to UTF-8 is a no-op on macOS/Linux and
    does not affect the real Windows console (WriteConsoleW path). Streams
    that cannot be reconfigured (StringIO test doubles, closed pipes) are
    left untouched.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            continue


def setup(cfg: Config) -> str:
    """Initialize the root logger and return the session ID for this run.

    Args:
        cfg: Scrinium global configuration.

    Returns:
        Short UUID4 session ID correlating all metrics events in this run.
    """
    global _session_id, _initialized
    _reconfigure_stdio()
    if _initialized:
        return _session_id

    _session_id = uuid.uuid4().hex[:12]

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # -- File handler (DEBUG, rotating) --
    log_path = cfg.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=cfg.log.max_bytes,
        backupCount=cfg.log.backup_count,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT))
    root.addHandler(fh)

    # -- Console handler (INFO, bare message) --
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(getattr(logging, cfg.log.level.upper(), logging.INFO))
    ch.setFormatter(logging.Formatter(_CONSOLE_FMT))
    root.addHandler(ch)

    # Suppress noisy third-party loggers
    for name in ("httpx", "urllib3", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _initialized = True
    logging.getLogger(__name__).debug("session %s started", _session_id)
    return _session_id


def set_console_stream(stream) -> None:
    """Redirect the console StreamHandler to *stream*.

    In ``--json`` mode, console logs are routed to stderr so stdout stays pure JSON.
    """
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setStream(stream)


def get_session_id() -> str:
    """Return the current session ID (empty string before ``setup()``)."""
    return _session_id


def get_logger(name: str) -> logging.Logger:
    """Shorthand for ``logging.getLogger(name)``.

    Args:
        name: Logger name, usually ``__name__``.

    Returns:
        The corresponding Logger instance.
    """
    return logging.getLogger(name)


def ui(msg: str = "", *args, logger: logging.Logger | None = None) -> None:
    """User-facing UI output -- drop-in replacement for ``print()``.

    Writes to both the console and the log file. Calling ``ui()`` with no
    arguments prints a blank line.

    Args:
        msg: Message string supporting ``%``-style placeholders (default empty).
        *args: Formatting arguments.
        logger: Optional logger (defaults to ``scrinium.ui``).
    """
    _logger = logger or logging.getLogger("scrinium.ui")
    _logger.info(msg, *args)


def reset() -> None:
    """Reset logging state (test helper only)."""
    global _session_id, _initialized
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    _session_id = ""
    _initialized = False
