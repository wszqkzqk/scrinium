"""Research behavior analytics helpers used by the insights CLI."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "with",
    "by",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "have",
    "has",
    "do",
    "does",
    "this",
    "that",
    "it",
    "its",
    "from",
    "as",
    "via",
    "using",
    "based",
}


def extract_hot_keywords(search_events: list[dict], *, top_k: int = 10) -> list[tuple[str, int]]:
    """Return the most frequent non-stopword tokens from search events."""
    word_counts: Counter[str] = Counter()
    for ev in search_events:
        detail_raw = ev.get("detail") or ""
        if not detail_raw:
            continue
        try:
            detail = json.loads(detail_raw)
        except Exception:
            continue
        query = detail.get("query", "")
        if not query:
            continue
        for word in query.lower().split():
            word = word.strip("\"',.:;!?()[]{}")
            if word and word not in STOPWORDS and len(word) > 1:
                word_counts[word] += 1
    return word_counts.most_common(top_k)


def aggregate_most_read_titles(read_events: list[dict], papers_dir: Path, *, top_k: int = 10) -> list[tuple[str, int]]:
    """Aggregate read counts by resolved paper title."""
    name_counts: Counter[str] = Counter()
    name_to_detail_title: dict[str, str] = {}

    for ev in read_events:
        name = ev.get("name", "")
        if not name:
            continue
        name_counts[name] += 1
        if name not in name_to_detail_title and ev.get("detail"):
            try:
                detail = json.loads(ev["detail"])
            except Exception:
                continue
            title = detail.get("title", "")
            if title:
                name_to_detail_title[name] = title

    pid_to_title: dict[str, str] = dict(name_to_detail_title)
    for name in name_counts:
        if pid_to_title.get(name):
            continue
        meta_path = papers_dir / name / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = meta.get("title", "")
        if title:
            pid_to_title[name] = title

    title_counts: Counter[str] = Counter()
    for name, count in name_counts.items():
        title_key = pid_to_title.get(name) or name
        title_counts[title_key] += count
    return title_counts.most_common(top_k)


def build_weekly_read_trend(read_events: list[dict]) -> list[tuple[str, int]]:
    """Group read events by ISO year-week key."""
    week_counts: Counter[str] = Counter()
    for ev in read_events:
        timestamp = ev.get("timestamp", "")
        if not timestamp:
            continue
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except Exception:
            continue
        iso = dt.isocalendar()
        week_counts[f"{iso.year}-W{iso.week:02d}"] += 1
    return sorted(week_counts.items())


def recent_unique_read_names(read_events: list[dict], *, limit: int = 5) -> list[str]:
    """Return recent unique paper names preserving newest-first order."""
    seen: set[str] = set()
    names: list[str] = []
    for ev in read_events:
        name = ev.get("name")
        if name and name not in seen:
            seen.add(name)
            names.append(name)
        if len(names) >= limit:
            break
    return names


def list_workspace_counts(ws_root: Path) -> list[tuple[str, int]]:
    """Return workspace names with paper counts."""
    from scrinium.workspace import list_workspaces

    items: list[tuple[str, int]] = []
    for ws_name in list_workspaces(ws_root):
        papers_json = ws_root / ws_name / "papers.json"
        try:
            count = len(json.loads(papers_json.read_text(encoding="utf-8")))
        except Exception:
            count = 0
        items.append((ws_name, count))
    return items
