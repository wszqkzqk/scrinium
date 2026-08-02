"""Helpers for proceedings library storage and iteration."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def proceedings_db_path(root: Path) -> Path:
    return root / "data" / "proceedings" / "proceedings.db"


def iter_proceedings_dirs(proceedings_root: Path) -> Iterator[Path]:
    if not proceedings_root.exists():
        return
    for proceeding_dir in sorted(proceedings_root.iterdir()):
        if proceeding_dir.is_dir():
            yield proceeding_dir


def iter_proceedings_papers(proceedings_root: Path) -> Iterator[dict]:
    """Yield child-paper rows enriched with proceeding metadata."""
    for proceeding_dir in iter_proceedings_dirs(proceedings_root):
        meta_path = proceeding_dir / "meta.json"
        papers_dir = proceeding_dir / "papers"
        if not meta_path.exists() or not papers_dir.is_dir():
            continue

        proceeding_meta = read_json(meta_path)
        proceeding_title = proceeding_meta.get("title") or proceeding_dir.name
        proceeding_id = proceeding_meta.get("id") or proceeding_dir.name

        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            paper_meta_path = paper_dir / "meta.json"
            if not paper_meta_path.exists():
                continue
            paper_meta = read_json(paper_meta_path)
            yield {
                "paper_id": paper_meta.get("id") or paper_dir.name,
                "title": paper_meta.get("title") or "",
                "authors": ", ".join(paper_meta.get("authors") or []),
                "year": str(paper_meta.get("year") or ""),
                "journal": paper_meta.get("journal") or "",
                "abstract": paper_meta.get("abstract") or "",
                "conclusion": paper_meta.get("l3_conclusion") or "",
                "doi": paper_meta.get("doi") or "",
                "paper_type": paper_meta.get("paper_type") or "",
                "citation_count": "",
                "md_path": str((paper_dir / "paper.md").resolve()) if (paper_dir / "paper.md").exists() else "",
                "dir_name": paper_dir.name,
                "proceeding_id": proceeding_id,
                "proceeding_dir": proceeding_dir.name,
                "proceeding_title": paper_meta.get("proceeding_title") or proceeding_title,
            }
