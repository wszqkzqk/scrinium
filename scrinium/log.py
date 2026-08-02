"""
log.py -- Scrinium 日志初始化
=================================

提供三层输出：
  1. 文件日志（RotatingFileHandler）— DEBUG 级别，完整记录
  2. 控制台输出（StreamHandler）— INFO 级别，格式等同 print
  3. ``ui()`` 函数 — print() 的 drop-in 替代，同时写文件和控制台
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
    """初始化 root logger，返回本次会话的 session_id。

    Args:
        cfg: Scrinium 全局配置。

    Returns:
        UUID4 格式的 session_id，用于关联本次所有 metrics 事件。
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
    for name in ("httpx", "urllib3", "httpcore", "sentence_transformers", "faiss"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("modelscope").setLevel(logging.ERROR)

    _initialized = True
    logging.getLogger(__name__).debug("session %s started", _session_id)
    return _session_id


def set_console_stream(stream) -> None:
    """把控制台 StreamHandler 重定向到 *stream*。

    ``--json`` 模式下把控制台日志改道 stderr，保持 stdout 只输出 JSON。
    """
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setStream(stream)


def get_session_id() -> str:
    """返回当前会话 ID（setup 之前为空字符串）。"""
    return _session_id


def get_logger(name: str) -> logging.Logger:
    """``logging.getLogger(name)`` 的快捷方式。

    Args:
        name: logger 名称，通常传 ``__name__``。

    Returns:
        对应的 Logger 实例。
    """
    return logging.getLogger(name)


def ui(msg: str = "", *args, logger: logging.Logger | None = None) -> None:
    """用户界面输出 — ``print()`` 的 drop-in 替代。

    同时写入控制台和日志文件。迁移时将 ``print(x)`` 改为
    ``ui(x)`` 即可，行为不变。支持无参调用 ``ui()`` 输出空行。

    Args:
        msg: 消息字符串，支持 ``%`` 格式化占位符。默认空字符串。
        *args: 格式化参数。
        logger: 指定 logger，默认使用 ``scrinium.ui``。
    """
    _logger = logger or logging.getLogger("scrinium.ui")
    _logger.info(msg, *args)


def reset() -> None:
    """重置日志状态（仅供测试使用）。"""
    global _session_id, _initialized
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    _session_id = ""
    _initialized = False
