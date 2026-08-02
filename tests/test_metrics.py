"""Tests for scrinium.metrics — MetricsStore, timer, timed."""

from __future__ import annotations

import json
import time

import pytest

from scrinium.metrics import (
    LLMResult,
    MetricsStore,
    TimerResult,
    get_store,
    init,
    reset,
    timed,
    timer,
)


@pytest.fixture()
def store():
    """In-memory MetricsStore for testing."""
    s = MetricsStore(":memory:", session_id="test-session")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_global():
    """Ensure global store is reset between tests."""
    yield
    reset()


class TestLLMResult:
    def test_defaults(self):
        r = LLMResult(content="hello")
        assert r.content == "hello"
        assert r.tokens_in == 0
        assert r.tokens_out == 0
        assert r.tokens_total == 0
        assert r.model == ""
        assert r.duration_s == 0.0


class TestTimerResult:
    def test_initial_elapsed_zero(self):
        t = TimerResult()
        assert t.elapsed == 0.0

    def test_elapsed_after_set(self):
        t = TimerResult()
        t.elapsed = 1.5
        assert t.elapsed == 1.5

    def test_elapsed_during_timing(self, monkeypatch):
        monkeypatch.setattr(time, "monotonic", lambda: 100.0)
        t = TimerResult()
        t._t0 = 99.5
        assert t.elapsed == 0.5


class TestMetricsStore:
    def test_record_and_query(self, store):
        store.record("llm", "test-call", duration_s=1.5, tokens_in=100, tokens_out=50)
        results = store.query(category="llm")
        assert len(results) == 1
        assert results[0]["name"] == "test-call"
        assert results[0]["tokens_in"] == 100

    def test_query_no_match(self, store):
        store.record("step", "embed")
        results = store.query(category="llm")
        assert len(results) == 0

    def test_query_limit(self, store):
        for i in range(10):
            store.record("llm", f"call-{i}")
        results = store.query(category="llm", limit=3)
        assert len(results) == 3

    def test_query_ordering_desc(self, store):
        store.record("llm", "first")
        store.record("llm", "second")
        results = store.query(category="llm")
        assert results[0]["name"] == "second"  # most recent first

    def test_summary_aggregation(self, store):
        store.record("llm", "a", tokens_in=100, tokens_out=50, duration_s=1.0)
        store.record("llm", "b", tokens_in=200, tokens_out=80, duration_s=2.0)
        store.record("step", "c", tokens_in=999)  # different category
        s = store.summary()
        assert s["call_count"] == 2
        assert s["total_tokens_in"] == 300
        assert s["total_tokens_out"] == 130
        assert s["total_duration_s"] == 3.0

    def test_summary_by_session(self, store):
        store.record("llm", "a", tokens_in=10)
        s = store.summary(session_id="test-session")
        assert s["call_count"] == 1
        s2 = store.summary(session_id="other-session")
        assert s2["call_count"] == 0

    def test_query_distinct_names(self, store):
        store.record("read", "paper-A")
        store.record("read", "paper-A")
        store.record("read", "paper-B")
        names = store.query_distinct_names("read")
        assert names == {"paper-A", "paper-B"}

    def test_query_distinct_names_empty(self, store):
        names = store.query_distinct_names("nonexistent")
        assert names == set()

    def test_record_with_detail(self, store):
        store.record("llm", "test", detail={"key": "value", "num": 42})
        results = store.query(category="llm")
        detail = json.loads(results[0]["detail"])
        assert detail["key"] == "value"
        assert detail["num"] == 42

    def test_record_with_status(self, store):
        store.record("llm", "test", status="error")
        results = store.query()
        assert results[0]["status"] == "error"


class TestGlobalStore:
    def test_init_and_get(self, tmp_path):
        db = tmp_path / "metrics.db"
        s = init(db, "sess-1")
        assert get_store() is s
        assert s.session_id == "sess-1"

    def test_reset_clears_store(self, tmp_path):
        init(tmp_path / "metrics.db", "sess-1")
        reset()
        assert get_store() is None

    def test_init_creates_parent_dir(self, tmp_path):
        db = tmp_path / "sub" / "dir" / "metrics.db"
        init(db, "s")
        assert db.parent.exists()


class TestTimer:
    def test_timer_records_event(self, tmp_path, monkeypatch):
        s = init(tmp_path / "m.db", "s")
        # Deterministic clock: wall-clock timing asserts are flaky on Windows CI
        clock = iter([100.0, 100.5])
        monkeypatch.setattr("scrinium.metrics.time.monotonic", lambda: next(clock))
        with timer("test-op", category="step") as t:
            pass
        assert t.elapsed == 0.5
        events = s.query(category="step")
        assert len(events) == 1
        assert events[0]["name"] == "test-op"
        assert events[0]["status"] == "ok"
        assert events[0]["duration_s"] == 0.5

    def test_timer_records_error(self, tmp_path):
        s = init(tmp_path / "m.db", "s")
        with pytest.raises(ValueError), timer("fail-op"):
            raise ValueError("boom")
        events = s.query(category="step")
        assert events[0]["status"] == "error"

    def test_timer_without_store(self):
        # No global store — should not crash
        reset()
        with timer("no-store") as t:
            pass
        assert t.elapsed >= 0


class TestTimed:
    def test_timed_decorator(self, tmp_path):
        s = init(tmp_path / "m.db", "s")

        @timed("decorated-fn", category="step")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        events = s.query(category="step")
        assert len(events) == 1
        assert events[0]["name"] == "decorated-fn"

    def test_timed_auto_name(self, tmp_path):
        init(tmp_path / "m.db", "s")

        @timed()
        def another_func():
            pass

        another_func()
        events = get_store().query(category="step")
        assert "another_func" in events[0]["name"]
