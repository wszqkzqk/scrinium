"""Shared fixtures for Scrinium tests.

Provides temporary paper directories and sample metadata so that tests
are fully isolated from user data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_papers(tmp_path: Path) -> Path:
    """Create a temporary papers directory with two sample papers."""
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()

    # Paper A — typical journal article
    pa = papers_dir / "Smith-2023-Turbulence"
    pa.mkdir()
    (pa / "meta.json").write_text(
        json.dumps(
            {
                "id": "aaaa-1111",
                "title": "Turbulence modeling in boundary layers",
                "authors": ["John Smith", "Jane Doe"],
                "first_author_lastname": "Smith",
                "year": 2023,
                "journal": "Journal of Fluid Mechanics",
                "doi": "10.1234/jfm.2023.001",
                "abstract": "We propose a novel turbulence model for boundary layers.",
                "paper_type": "journal-article",
                "citation_count": {"crossref": 10, "s2": 12},
                "volume": "950",
                "issue": "2",
                "pages": "100-120",
                "publisher": "Cambridge University Press",
                "issn": "0022-1120",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pa / "paper.md").write_text(
        "# Turbulence modeling in boundary layers\n\nFull text here.",
        encoding="utf-8",
    )

    # Paper B — thesis without DOI
    pb = papers_dir / "Wang-2024-DeepLearning"
    pb.mkdir()
    (pb / "meta.json").write_text(
        json.dumps(
            {
                "id": "bbbb-2222",
                "title": "Deep learning for fluid dynamics",
                "authors": ["Wei Wang"],
                "first_author_lastname": "Wang",
                "year": 2024,
                "journal": "",
                "doi": "",
                "abstract": "This thesis explores deep learning approaches.",
                "paper_type": "thesis",
                "citation_count": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pb / "paper.md").write_text(
        "# Deep learning for fluid dynamics\n\nThesis content.",
        encoding="utf-8",
    )

    return papers_dir


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return a path for a temporary SQLite database."""
    return tmp_path / "index.db"
