"""
metrics.py -- Scrinium 指标采集与持久化
==========================================

三大功能：
  1. MetricsStore — SQLite 持久化（data/metrics.db）
  2. timer / timed — 计时上下文管理器 / 装饰器
  3. call_llm    — 统一 LLM 调用入口，自动追踪 token 用量
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
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from .config import Config, LLMConfig

_log = logging.getLogger(__name__)

# ============================================================================
#  LLMResult
# ============================================================================


@dataclass
class LLMResult:
    """LLM 调用返回值。

    Attributes:
        content: 模型返回的文本内容。
        tokens_in: prompt token 数。
        tokens_out: completion token 数。
        tokens_total: 总 token 数。
        model: 实际使用的模型名。
        duration_s: 调用耗时（秒）。
    """

    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    model: str = ""
    duration_s: float = 0.0


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

    def summary(self, session_id: str | None = None) -> dict:
        """汇总 LLM token 用量。

        Args:
            session_id: 指定会话，默认全部。

        Returns:
            ``{"total_tokens_in": N, "total_tokens_out": N,
            "total_duration_s": N, "call_count": N}``
        """
        clause = "WHERE category = 'llm'"
        params: list[Any] = []
        if session_id:
            clause += " AND session_id = ?"
            params.append(session_id)
        sql = (
            f"SELECT COUNT(*) as cnt, "
            f"COALESCE(SUM(tokens_in), 0), "
            f"COALESCE(SUM(tokens_out), 0), "
            f"COALESCE(SUM(duration_s), 0) "
            f"FROM events {clause}"
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return {
            "call_count": row[0],
            "total_tokens_in": row[1],
            "total_tokens_out": row[2],
            "total_duration_s": round(row[3], 2),
        }

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


# ============================================================================
#  Unified LLM call
# ============================================================================


def call_llm(
    prompt: str,
    config: Config | LLMConfig,
    *,
    api_key: str = "",
    system: str | None = None,
    json_mode: bool = True,
    max_tokens: int = 8000,
    timeout: int | None = None,
    purpose: str = "",
) -> LLMResult:
    """统一 LLM 调用入口。

    根据 ``llm_cfg.backend`` 分发到对应后端：
    - ``"anthropic"``  — 调用 Anthropic 接口；
    - ``"google"``     — 调用 Google Gemini 接口；
    - 其他值           — 视为 OpenAI-compatible，使用 ``/v1/chat/completions`` 端点。

    每个后端都会在可用时解析 token 用量（如 ``response.usage`` 或等价字段），
    并将 token 统计和耗时记录到 MetricsStore。

    ``config`` 可以是完整的 :class:`Config` 或单独的 :class:`LLMConfig`。
    传入 ``LLMConfig`` 时需同时提供 ``api_key``。

    Args:
        prompt: 用户消息内容。
        config: Scrinium 全局配置，或 LLMConfig 实例（包含 ``backend`` / ``model`` 等）。
        api_key: 显式 API 密钥（覆盖 config 中的值）。
        system: 可选的 system message。
        json_mode: 是否启用 JSON 响应格式（仅在后端支持时生效）。
        max_tokens: 最大生成 token 数（按后端语义传递）。
        timeout: 超时秒数，默认使用 ``config.llm.timeout``。
        purpose: 调用用途标识，用于 metrics 记录（如 ``"extract.robust"``）。

    Returns:
        :class:`LLMResult` 包含内容、token 统计和耗时。

    Raises:
        RuntimeError: 未配置 API key。
        各后端 HTTP / SDK 客户端可能抛出的异常（如 ``requests.HTTPError`` 等）。
    """
    # Support both Config (has .llm attr) and LLMConfig (has .base_url directly)
    from .config import LLMConfig

    if isinstance(config, LLMConfig):
        llm_cfg = config
        resolved_key = api_key or llm_cfg.api_key
    else:
        llm_cfg = config.llm
        resolved_key = api_key or config.resolved_api_key()

    if not resolved_key:
        raise RuntimeError("未配置 LLM API key。")

    backend = llm_cfg.backend
    _timeout = timeout or llm_cfg.timeout

    t0 = time.monotonic()
    status = "ok"
    tokens_in = tokens_out = tokens_total = 0
    model_name = llm_cfg.model
    try:
        if backend == "anthropic":
            content, tokens_in, tokens_out, tokens_total, model_name = _call_anthropic(
                prompt,
                llm_cfg,
                resolved_key,
                system=system,
                json_mode=json_mode,
                max_tokens=max_tokens,
                timeout=_timeout,
            )
        elif backend == "google":
            content, tokens_in, tokens_out, tokens_total, model_name = _call_google(
                prompt,
                llm_cfg,
                resolved_key,
                system=system,
                json_mode=json_mode,
                max_tokens=max_tokens,
                timeout=_timeout,
            )
        else:
            content, tokens_in, tokens_out, tokens_total, model_name = _call_openai_compat(
                prompt,
                llm_cfg,
                resolved_key,
                system=system,
                json_mode=json_mode,
                max_tokens=max_tokens,
                timeout=_timeout,
            )
    except Exception:
        status = "error"
        raise
    finally:
        duration = round(time.monotonic() - t0, 3)
        _log.debug(
            "LLM [%s] %d tokens (in=%d out=%d) %.1fs [%s]",
            purpose or "unnamed",
            tokens_total,
            tokens_in,
            tokens_out,
            duration,
            status,
        )
        if _store:
            _store.record(
                "llm",
                purpose or "unnamed",
                duration_s=duration,
                tokens_in=tokens_in if tokens_in is not None else None,
                tokens_out=tokens_out if tokens_out is not None else None,
                model=model_name,
                status=status,
            )

    return LLMResult(
        content=content,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        tokens_total=tokens_total,
        model=model_name,
        duration_s=duration,
    )


def _call_openai_compat(
    prompt: str,
    llm_cfg: LLMConfig,
    api_key: str,
    *,
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    timeout: int,
) -> tuple[str, int, int, int, str]:
    """OpenAI-compatible /v1/chat/completions（DeepSeek / OpenAI / vLLM / Ollama 等）。"""
    url = llm_cfg.base_url.rstrip("/") + "/v1/chat/completions"

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {
        "model": llm_cfg.model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        snippet = _json.dumps(data, ensure_ascii=False)[:300]
        raise ValueError(f"Unexpected API response structure: {e}\n{snippet}") from e
    usage = data.get("usage") or {}
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)
    tokens_total = usage.get("total_tokens", 0)
    model_name = data.get("model", llm_cfg.model)
    return content, tokens_in, tokens_out, tokens_total, model_name


def _call_anthropic(
    prompt: str,
    llm_cfg: LLMConfig,
    api_key: str,
    *,
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    timeout: int,
) -> tuple[str, int, int, int, str]:
    """Anthropic Messages API（/v1/messages）。"""
    url = llm_cfg.base_url.rstrip("/") + "/v1/messages"

    # Anthropic has no response_format; enforce JSON via prompt prefix
    user_content = prompt
    if json_mode:
        user_content = "You MUST respond with valid JSON only. No markdown fencing, no explanation.\n\n" + prompt

    messages: list[dict[str, str]] = [{"role": "user", "content": user_content}]

    payload: dict[str, Any] = {
        "model": llm_cfg.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    if system:
        payload["system"] = system

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # Concatenate all text blocks (Messages API can return multiple content blocks)
    try:
        blocks = data["content"]
        content = "".join(b["text"] for b in blocks if b.get("type") == "text")
    except (KeyError, TypeError) as e:
        snippet = _json.dumps(data, ensure_ascii=False)[:300]
        raise ValueError(f"Unexpected Anthropic response structure: {e}\n{snippet}") from e
    if not content:
        snippet = _json.dumps(data, ensure_ascii=False)[:300]
        raise ValueError(f"Anthropic response has no text blocks:\n{snippet}")
    usage = data.get("usage") or {}
    tokens_in = usage.get("input_tokens", 0)
    tokens_out = usage.get("output_tokens", 0)
    tokens_total = tokens_in + tokens_out
    model_name = data.get("model", llm_cfg.model)
    return content, tokens_in, tokens_out, tokens_total, model_name


def _call_google(
    prompt: str,
    llm_cfg: LLMConfig,
    api_key: str,
    *,
    system: str | None,
    json_mode: bool,
    max_tokens: int,
    timeout: int,
) -> tuple[str, int, int, int, str]:
    """Google Gemini API（/v1beta/models/...）。"""
    base = llm_cfg.base_url.rstrip("/")
    url = f"{base}/v1beta/models/{llm_cfg.model}:generateContent"

    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": prompt}]},
    ]

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        snippet = _json.dumps(data, ensure_ascii=False)[:300]
        raise ValueError(f"Unexpected Gemini response structure: {e}\n{snippet}") from e
    usage = data.get("usageMetadata") or {}
    tokens_in = usage.get("promptTokenCount", 0)
    tokens_out = usage.get("candidatesTokenCount", 0)
    tokens_total = usage.get("totalTokenCount", tokens_in + tokens_out)
    model_name = llm_cfg.model
    return content, tokens_in, tokens_out, tokens_total, model_name
