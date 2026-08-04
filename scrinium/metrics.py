"""
metrics.py -- Scrinium 指标采集与持久化
==========================================

两大功能：
  1. MetricsStore — SQLite 持久化（data/metrics.db）
  2. timer / timed — 计时上下文管理器 / 装饰器
"""

from __future__ import annotations

import json as _json
import logging
import sqlite3
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# ============================================================================
#  TimerResult
# ============================================================================


@dataclass
class TimerResult:
    """计时结果，由 :func:`timer` 上下文管理器 yield。

    在 ``with`` 块内部读取 ``elapsed`` 返回实时耗时；
    退出后返回最终耗时。
    """

    def __init__(self) -> None:
        self._t0: float = 0.0
        self._final: float | None = None

    @property
    def elapsed(self) -> float:
        if self._final is not None:
            return self._final
        if self._t0:
            return time.monotonic() - self._t0
        return 0.0

    @elapsed.setter
    def elapsed(self, value: float) -> None:
        self._final = value


# ============================================================================
#  MetricsStore
# ============================================================================


_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    duration_s REAL,
    tokens_in  INTEGER,
    tokens_out INTEGER,
    model      TEXT,
    status     TEXT    DEFAULT 'ok',
    detail     TEXT
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);",
    "CREATE INDEX IF NOT EXISTS idx_events_cat_name ON events(category, name);",
]


class MetricsStore:
    """SQLite-backed metrics store.

    Args:
        db_path: 数据库文件路径，传 ``":memory:"`` 用于测试。
        session_id: 当前会话 ID。
    """

    def __init__(self, db_path: Path | str, session_id: str) -> None:
        self._session_id = session_id
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        for idx_sql in _CREATE_INDEXES:
            self._conn.execute(idx_sql)
        self._conn.commit()

    @property
    def session_id(self) -> str:
        return self._session_id

    def record(
        self,
        category: str,
        name: str,
        *,
        duration_s: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        model: str | None = None,
        status: str = "ok",
        detail: dict | None = None,
    ) -> None:
        """写入一条 metrics 事件。

        Args:
            category: 事件类别，如 ``"llm"``、``"api"``、``"step"``。
            name: 事件名称，如 ``"extract.robust"``、``"enrich_toc"``。
            duration_s: 耗时（秒）。
            tokens_in: prompt token 数。
            tokens_out: completion token 数。
            model: 模型名。
            status: ``"ok"`` | ``"error"`` | ``"skip"``。
            detail: 额外信息（序列化为 JSON）。
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (session_id, timestamp, category, name, "
                "duration_s, tokens_in, tokens_out, model, status, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._session_id,
                    datetime.now(timezone.utc).isoformat(),
                    category,
                    name,
                    duration_s,
                    tokens_in,
                    tokens_out,
                    model,
                    status,
                    _json.dumps(detail, ensure_ascii=False) if detail else None,
                ),
            )
            self._conn.commit()

    def query(
        self,
        category: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """查询 metrics 事件。

        Args:
            category: 按类别过滤。
            since: 起始时间（ISO 8601）。
            until: 结束时间（ISO 8601）。
            limit: 最大返回数。

        Returns:
            事件字典列表，按时间倒序。
        """
        clauses = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            cur = self._conn.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def query_distinct_names(self, category: str) -> set[str]:
        """Return all distinct event names ever recorded for a category.

        Unlike :meth:`query`, this issues a ``SELECT DISTINCT`` projection
        rather than paginating full rows, so memory usage scales with the
        number of *unique* names rather than total event count.  A composite
        ``(category, name)`` index makes the scan efficient for typical
        library sizes.

        Args:
            category: Event category to filter on (e.g. ``"read"``).

        Returns:
            Set of distinct ``name`` values (empty strings excluded).
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT name FROM events WHERE category = ? AND name IS NOT NULL AND name != ''",
                (category,),
            )
            return {row[0] for row in cur.fetchall()}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ============================================================================
#  Module-level singleton
# ============================================================================

_store: MetricsStore | None = None


def init(db_path: Path | str, session_id: str) -> MetricsStore:
    """初始化全局 MetricsStore 单例。

    Args:
        db_path: SQLite 数据库路径。
        session_id: 当前会话 ID。

    Returns:
        初始化后的 MetricsStore 实例。
    """
    global _store
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    _store = MetricsStore(db, session_id)
    _log.debug("metrics store initialized: %s (session %s)", db, session_id)
    return _store


def get_store() -> MetricsStore | None:
    """返回全局 MetricsStore 实例，未初始化时返回 None。"""
    return _store


def reset() -> None:
    """关闭并重置全局 store（仅供测试使用）。"""
    global _store
    if _store:
        _store.close()
    _store = None


# ============================================================================
#  Timing utilities
# ============================================================================


@contextmanager
def timer(name: str, category: str = "step") -> Generator[TimerResult, None, None]:
    """计时上下文管理器，自动记录到 MetricsStore。

    Args:
        name: 事件名称。
        category: 事件类别。

    Yields:
        :class:`TimerResult`，退出时 ``elapsed`` 已填充。

    Example::

        with timer("mineru.cloud", category="api") as t:
            do_something()
        print(f"耗时 {t.elapsed:.1f}s")
    """
    result = TimerResult()
    result._t0 = time.monotonic()
    try:
        yield result
        status = "ok"
    except Exception:
        status = "error"
        raise
    finally:
        result.elapsed = time.monotonic() - result._t0
        if _store:
            _store.record(category, name, duration_s=result.elapsed, status=status)


def timed(name: str = "", category: str = "step"):
    """计时装饰器。

    Args:
        name: 事件名称，默认为函数全限定名。
        category: 事件类别。
    """

    def decorator(fn):
        event_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with timer(event_name, category):
                return fn(*args, **kwargs)

        return wrapper

    return decorator
