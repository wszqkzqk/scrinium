"""
search_common.py — FTS5 / RRF 公共检索构件
==========================================

主库（``index.py``）与探索库（``explore.py``）共享的检索基础设施：

- :func:`sanitize_fts_query` — 统一的 FTS5 查询净化策略；
- :func:`rrf_merge` — 唯一的 RRF（Reciprocal Rank Fusion）融合实现；
- :func:`fts_create_sql` — 参数化的 FTS5 建表语句生成器，
  两边各自保留自己的 schema（字段集合/顺序不变），只收敛 SQL 样板。

用法::

    from scholaraio.search_common import fts_create_sql, rrf_merge, sanitize_fts_query
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence

#: RRF 标准常数（Cormack et al., 2009），主库与探索库统一使用。
RRF_K = 60


def _paper_id(result: dict) -> str:
    """Default merge key: the main-library ``paper_id`` field."""
    return result.get("paper_id", "")


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


def rrf_merge(
    fts_results: Iterable[dict],
    vec_results: Iterable[dict],
    *,
    k: int = RRF_K,
    get_id: Callable[[dict], str] | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """将 FTS5 与向量两路检索结果按 RRF 融合排序。

    RRF 得分为各路 ``1/(k + rank)`` 之和（rank 从 1 起计）。同时被两路
    命中的条目得分叠加，``match`` 标记为 ``"both"``；单路命中标记为
    ``"fts"`` / ``"vec"``。

    Args:
        fts_results: FTS5 命中列表，按相关性降序。
        vec_results: 向量命中列表，按相关性降序。
        k: RRF 常数（默认 :data:`RRF_K` = 60）。
        get_id: 从结果字典中提取合并键的函数；缺省取
            ``result["paper_id"]``。键为空的条目被跳过。
        top_k: 截断返回条数；``None`` 表示不截断。

    Returns:
        融合后的字典列表，按 RRF 得分降序；每项含 ``score`` 与
        ``match``（``"fts"`` / ``"vec"`` / ``"both"``）。得分相同保持
        FTS 在前、向量在后的插入顺序。
    """
    if get_id is None:
        get_id = _paper_id

    merged: dict[str, dict] = {}

    for rank, r in enumerate(fts_results):
        pid = get_id(r)
        if not pid:
            continue
        merged[pid] = {**r, "score": 1.0 / (k + rank + 1), "match": "fts"}

    for rank, r in enumerate(vec_results):
        pid = get_id(r)
        if not pid:
            continue
        rrf_score = 1.0 / (k + rank + 1)
        if pid in merged:
            merged[pid]["score"] += rrf_score
            merged[pid]["match"] = "both"
        else:
            merged[pid] = {**r, "score": rrf_score, "match": "vec"}

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    if top_k is not None:
        results = results[:top_k]
    return results
