"""
citation_check.py — 引用验证
=============================

从文本中提取学术引用，与本地知识库交叉核验。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
#  Citation extraction
# ---------------------------------------------------------------------------

# Patterns for in-text citations (author-year style)
# Matches: Author (Year), Author & Author (Year), Author et al. (Year)
_RE_NARRATIVE = re.compile(
    r"""
    (?P<author>
        [A-Z][a-zA-ZÀ-ÿ\-']+          # first author surname
        (?:                              # optional second author
            \s+(?:and|&|et)\s+
            [A-Z][a-zA-ZÀ-ÿ\-']+
        )?
        (?:\s+et\s+al\.)?               # optional et al.
    )
    \s*
    \((?P<year>\d{4})\)                 # (Year)
    """,
    re.VERBOSE,
)

# Matches: (Author, Year), (Author & Author, Year), (Author et al., Year)
# Also handles multiple citations: (Author, Year; Author, Year)
_RE_PARENTHETICAL = re.compile(
    r"""
    \(
    (?P<body>
        [A-Z][a-zA-ZÀ-ÿ\-'\s&,;.]+    # author+year content
        \d{4}                            # must contain a year
        [a-zA-ZÀ-ÿ\-'\s&,;.0-9]*       # trailing content (e.g. second citation)
    )
    \)
    """,
    re.VERBOSE,
)

# Split individual citations within parenthetical groups
_RE_PAREN_SINGLE = re.compile(
    r"""
    (?P<author>
        [A-Z][a-zA-ZÀ-ÿ\-']+          # first author surname
        (?:                              # optional second author
            \s+(?:and|&|et)\s+
            [A-Z][a-zA-ZÀ-ÿ\-']+
        )?
        (?:\s+et\s+al\.)?               # optional et al.
    )
    ,?\s*
    (?P<year>\d{4})
    """,
    re.VERBOSE,
)


def extract_citations(text: str) -> list[dict]:
    """Extract author-year citations from text.

    Args:
        text: Input text containing academic citations.

    Returns:
        List of dicts with keys ``author``, ``year``, ``raw``.
        Duplicates (same author+year) are removed.
    """
    seen: set[tuple[str, str]] = set()
    results: list[dict] = []

    def _add(author: str, year: str, raw: str) -> None:
        # Normalise whitespace in author
        author = " ".join(author.split())
        key = (author.lower(), year)
        if key not in seen:
            seen.add(key)
            results.append({"author": author, "year": year, "raw": raw.strip()})

    # 1) Narrative citations: Author (Year)
    for m in _RE_NARRATIVE.finditer(text):
        _add(m.group("author"), m.group("year"), m.group(0))

    # 2) Parenthetical citations: (Author, Year) / (Author, Year; Author, Year)
    for m in _RE_PARENTHETICAL.finditer(text):
        body = m.group("body")
        for sm in _RE_PAREN_SINGLE.finditer(body):
            raw = sm.group(0).strip()
            _add(sm.group("author"), sm.group("year"), f"({raw})")

    return results


# ---------------------------------------------------------------------------
#  Citation verification
# ---------------------------------------------------------------------------


def check_citations(
    citations: list[dict],
    db_path: Path,
    *,
    paper_ids: set[str] | None = None,
) -> list[dict]:
    """Verify each citation against the local knowledge base.

    Args:
        citations: Output of :func:`extract_citations`.
        db_path: Path to ``index.db``.
        paper_ids: Optional paper-ID whitelist (workspace filter).

    Returns:
        List of dicts, each being the original citation dict augmented with
        ``status`` (``VERIFIED`` / ``NOT_IN_LIBRARY`` / ``AMBIGUOUS``) and
        ``matches`` (list of matching paper dicts).
    """
    from scrinium.index import search_author

    results: list[dict] = []

    for cite in citations:
        entry = {**cite, "status": "NOT_IN_LIBRARY", "matches": []}

        # Extract the primary surname for author search
        author_query = cite["author"]
        # Strip "et al." for search
        author_query = re.sub(r"\s+et\s+al\.?", "", author_query)
        # For "Author & Author", search by first author
        author_query = re.split(r"\s+(?:and|&|et)\s+", author_query)[0].strip()

        if not author_query:
            results.append(entry)
            continue

        try:
            hits = search_author(
                author_query,
                db_path,
                top_k=10,
                year=cite["year"],
                paper_ids=paper_ids,
            )
        except FileNotFoundError:
            results.append(entry)
            continue

        if not hits:
            results.append(entry)
            continue

        # Filter by exact year match
        year_matches = [h for h in hits if str(h.get("year", "")) == cite["year"]]
        if not year_matches:
            results.append(entry)
            continue

        entry["matches"] = year_matches
        if len(year_matches) == 1:
            entry["status"] = "VERIFIED"
        else:
            entry["status"] = "AMBIGUOUS"

        results.append(entry)

    return results
