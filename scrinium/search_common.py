"""
search_common.py — Shared FTS5 search building blocks
=====================================================

Search infrastructure shared by the main library (``index.py``) and the
exploration library (``explore.py``):

- :func:`sanitize_fts_query` — unified FTS5 query sanitization strategy;
- :func:`fts_create_sql` — parameterized FTS5 CREATE TABLE statement builder;
  each library keeps its own schema (field set/order unchanged) while sharing
  the SQL boilerplate.

Usage::

    from scrinium.search_common import fts_create_sql, sanitize_fts_query
"""

from __future__ import annotations

import re
from collections.abc import Sequence


def sanitize_fts_query(query: str) -> str:
    """Sanitize FTS5 query text by stripping special characters to avoid MATCH syntax errors.

    Replaces every non-word, non-whitespace character with a space and trims
    leading/trailing whitespace. An empty result means the query has no usable
    terms and the caller should skip MATCH (an empty query raises an FTS5 error).

    Args:
        query: Raw query text entered by the user.

    Returns:
        Sanitized query string (possibly empty).
    """
    return re.sub(r"[^\w\s]", " ", query).strip()


def fts_create_sql(
    table: str,
    fields: Sequence[tuple[str, bool]],
    *,
    tokenizer: str = "unicode61",
) -> str:
    """Build a ``CREATE VIRTUAL TABLE IF NOT EXISTS ... USING fts5(...)`` statement.

    Args:
        table: FTS5 table name (internal constant, not user input).
        fields: Ordered ``(column_name, indexed)`` pairs; columns with
            ``indexed=False`` are marked ``UNINDEXED``. Column order is preserved
            so existing database layouts stay compatible.
        tokenizer: FTS5 tokenizer specification.

    Returns:
        CREATE TABLE SQL statement (with trailing semicolon).
    """
    cols = ",\n    ".join(name if indexed else f"{name} UNINDEXED" for name, indexed in fields)
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(\n    {cols},\n    tokenize = '{tokenizer}'\n);"
