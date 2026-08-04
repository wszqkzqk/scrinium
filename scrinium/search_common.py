"""
search_common.py — FTS5 公共检索构件
=====================================

主库（``index.py``）与探索库（``explore.py``）共享的检索基础设施：

- :func:`sanitize_fts_query` — 统一的 FTS5 查询净化策略；
- :func:`fts_create_sql` — 参数化的 FTS5 建表语句生成器，
  两边各自保留自己的 schema（字段集合/顺序不变），只收敛 SQL 样板。

用法::

    from scrinium.search_common import fts_create_sql, sanitize_fts_query
"""

from __future__ import annotations

import re
from collections.abc import Sequence


def sanitize_fts_query(query: str) -> str:
    """净化 FTS5 查询文本，去除特殊字符，避免 MATCH 语法错误。

    将所有非单词、非空白字符替换为空格并去除首尾空白。净化结果为空
    字符串表示查询中没有可用词项，调用方应跳过 MATCH（空查询会触发
    FTS5 语法错误）。

    Args:
        query: 用户输入的原始查询文本。

    Returns:
        净化后的查询字符串（可能为空）。
    """
    return re.sub(r"[^\w\s]", " ", query).strip()


def fts_create_sql(
    table: str,
    fields: Sequence[tuple[str, bool]],
    *,
    tokenizer: str = "unicode61",
) -> str:
    """生成 ``CREATE VIRTUAL TABLE IF NOT EXISTS ... USING fts5(...)`` 语句。

    Args:
        table: FTS5 表名（内部常量，非用户输入）。
        fields: 有序的 ``(列名, 是否索引)`` 列表；``indexed=False`` 的列
            标记为 ``UNINDEXED``。列顺序原样保留，以便与既有数据库的
            列布局保持一致。
        tokenizer: FTS5 分词器规格。

    Returns:
        建表 SQL 语句（含末尾分号）。
    """
    cols = ",\n    ".join(name if indexed else f"{name} UNINDEXED" for name, indexed in fields)
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(\n    {cols},\n    tokenize = '{tokenizer}'\n);"
