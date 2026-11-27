"""
papers.py — Single source of truth for the paper directory layout
=================================================================

All modules access paper paths through this module rather than joining paths
themselves.

Directory layout:
    data/papers/<dir_name>/
    ├── meta.json    # contains "id": "<uuid>"
    └── paper.md
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path


def paper_dir(papers_dir: Path, dir_name: str) -> Path:
    """Return the directory path for a paper."""
    return papers_dir / dir_name


def meta_path(papers_dir: Path, dir_name: str) -> Path:
    """Return the meta.json path for a paper."""
    return papers_dir / dir_name / "meta.json"


def md_path(papers_dir: Path, dir_name: str) -> Path:
    """Return the paper.md path for a paper."""
    return papers_dir / dir_name / "paper.md"


def iter_paper_dirs(papers_dir: Path) -> Iterator[Path]:
    """Yield sorted subdirectories containing meta.json.

    Args:
        papers_dir: Root papers directory.

    Yields:
        Path to each paper subdirectory that contains a ``meta.json``.
    """
    if not papers_dir.exists():
        return
    for d in sorted(papers_dir.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            yield d


def generate_uuid() -> str:
    """Generate a new UUID string for a paper."""
    return str(uuid.uuid4())


def best_citation(meta: dict) -> int:
    """Return the maximum value in the ``citation_count`` dict.

    Args:
        meta: Paper metadata dict.

    Returns:
        Highest citation count, or 0 if no data is available.
    """
    cc = meta.get("citation_count")
    if not cc or not isinstance(cc, dict):
        return 0
    vals = [v for v in cc.values() if isinstance(v, (int, float))]
    return int(max(vals)) if vals else 0


def parse_year_range(year: str) -> tuple[int | None, int | None]:
    """Parse a year filter expression and return ``(start, end)``.

    Supported formats: ``"2023"`` (single year), ``"2020-2024"`` (range),
    ``"2020-"`` (from year onward), ``"-2024"`` (up to year).

    Args:
        year: Year filter expression.

    Returns:
        ``(start, end)`` tuple, with ``None`` for an open bound.
        A single year returns ``(2023, 2023)``.
    """
    year = year.strip()
    if "-" in year:
        parts = year.split("-", 1)
        start, end = parts[0].strip(), parts[1].strip()
        try:
            return (int(start) if start else None, int(end) if end else None)
        except ValueError as e:
            raise ValueError(f"Invalid year range: {year!r} (expected: 2020, 2020-2024, 2020-, -2024)") from e
    try:
        y = int(year)
    except ValueError as e:
        raise ValueError(f"Invalid year: {year!r} (expected: 2020, 2020-2024, 2020-, -2024)") from e
    return (y, y)


def read_meta(paper_d: Path) -> dict:
    """Read and parse meta.json from a paper directory.

    Args:
        paper_d: Paper directory path.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If the JSON file is malformed (wraps ``json.JSONDecodeError``
            with the file path for context).
        FileNotFoundError: If meta.json does not exist.
    """
    p = paper_d / "meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in {p}: {e}") from e


def write_meta(paper_d: Path, data: dict) -> None:
    """Atomically write meta.json to a paper directory.

    Writes to a temporary file first, then renames to avoid corruption
    if the process is interrupted mid-write.

    Args:
        paper_d: Paper directory path.
        data: Metadata dict to serialize.
    """
    p = paper_d / "meta.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(p)


def update_meta(paper_d: Path, **fields) -> dict:
    """Read meta.json, merge fields, and atomically write back.

    Args:
        paper_d: Paper directory path.
        **fields: Key-value pairs to merge into the metadata dict.

    Returns:
        The updated metadata dict.
    """
    data = read_meta(paper_d)
    data.update(fields)
    write_meta(paper_d, data)
    return data
