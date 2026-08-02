"""
workspace.py — 工作区论文子集管理
===================================

每个工作区是 ``workspace/<name>/`` 目录，内含 ``papers.json`` 索引文件
指向 ``data/papers/`` 中的论文。工作区内可自由存放笔记、代码、草稿等。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


# ============================================================================
#  Internal helpers
# ============================================================================


def _papers_json(ws_dir: Path) -> Path:
    return ws_dir / "papers.json"


def _read(ws_dir: Path) -> list[dict]:
    pj = _papers_json(ws_dir)
    if not pj.exists():
        return []
    try:
        raw = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"papers.json 格式损坏，操作中止: {pj}") from e
    if not isinstance(raw, list):
        raise RuntimeError(f"papers.json 格式异常（期望 list，实际 {type(raw).__name__}）: {pj}")
    # Filter out malformed entries missing required "id" field
    valid = [e for e in raw if isinstance(e, dict) and "id" in e]
    if len(valid) < len(raw):
        _log.warning("papers.json 中有 %d 条缺少 id 的记录已跳过 (%s)", len(raw) - len(valid), pj)
    return valid


def _write(ws_dir: Path, entries: list[dict]) -> None:
    pj = _papers_json(ws_dir)
    tmp = pj.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(pj)


# ============================================================================
#  Public API
# ============================================================================


def create(ws_dir: Path) -> Path:
    """创建工作区目录并初始化空 papers.json。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        papers.json 文件路径。
    """
    ws_dir.mkdir(parents=True, exist_ok=True)
    pj = _papers_json(ws_dir)
    if not pj.exists():
        _write(ws_dir, [])
    return pj


def add(
    ws_dir: Path,
    paper_refs: list[str],
    db_path: Path,
    *,
    resolved: list[dict] | None = None,
    unresolved: list[str] | None = None,
) -> list[dict]:
    """添加论文到工作区。

    通过 UUID、目录名或 DOI 解析论文，去重后追加到 papers.json。

    当调用方已持有解析好的论文信息时，可通过 *resolved* 参数直接传入，
    跳过逐个 ``lookup_paper()`` 查询（避免 O(N) 次 DB 连接开销）。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
            当 *resolved* 不为 ``None`` 时本参数被忽略。
        db_path: index.db 路径，用于 lookup_paper。
        resolved: 预解析的论文列表，每个元素须含 ``"id"`` 和
            ``"dir_name"`` 键。提供时跳过 lookup_paper 查询。
        unresolved: 可选的输出列表；无法解析的引用会被追加进去，
            供调用方向用户逐条报告。

    Returns:
        新增条目列表。
    """
    entries = _read(ws_dir)
    existing_ids = {e["id"] for e in entries}
    added: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    if resolved is not None:
        required_keys = {"id", "dir_name"}
        for idx, rec in enumerate(resolved):
            if not isinstance(rec, dict):
                raise ValueError(
                    f"resolved[{idx}] must be a dict with keys {sorted(required_keys)}, got {type(rec).__name__!s}"
                )
            missing = required_keys.difference(rec.keys())
            if missing:
                raise ValueError(f"resolved[{idx}] is missing required keys {sorted(missing)}: {rec!r}")
            uid = rec["id"]
            if uid in existing_ids:
                continue
            entry = {"id": uid, "dir_name": rec["dir_name"], "added_at": now}
            entries.append(entry)
            existing_ids.add(uid)
            added.append(entry)
    else:
        from scrinium.index import lookup_paper

        for ref in paper_refs:
            record = lookup_paper(db_path, ref)
            if record is None:
                _log.warning("无法解析论文引用: %s", ref)
                if unresolved is not None:
                    unresolved.append(ref)
                continue
            uid = record["id"]
            if uid in existing_ids:
                _log.debug("已存在，跳过: %s", ref)
                continue
            entry = {"id": uid, "dir_name": record["dir_name"], "added_at": now}
            entries.append(entry)
            existing_ids.add(uid)
            added.append(entry)

    if added:
        _write(ws_dir, entries)
    return added


def remove(ws_dir: Path, paper_refs: list[str], db_path: Path) -> list[dict]:
    """从工作区移除论文。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
        db_path: index.db 路径。

    Returns:
        被移除的条目列表。
    """
    from scrinium.index import lookup_paper

    entries = _read(ws_dir)
    remove_ids: set[str] = set()
    remove_dir_names: set[str] = set()
    entry_ids = {e["id"] for e in entries}
    entry_dir_names = {e.get("dir_name") for e in entries}
    for ref in paper_refs:
        try:
            record = lookup_paper(db_path, ref)
        except sqlite3.Error as exc:
            _log.warning("lookup_paper 失败，回退到工作区可见标识: %s", exc)
            record = None
        if record:
            remove_ids.add(record["id"])
        else:
            # Fall back to exact workspace-visible identifiers when the index is stale
            # or unavailable, so users can still remove items they see in `ws show`.
            if ref in entry_ids:
                remove_ids.add(ref)
            elif ref in entry_dir_names:
                remove_dir_names.add(ref)

    removed = [e for e in entries if e["id"] in remove_ids or e.get("dir_name") in remove_dir_names]
    if removed:
        entries = [e for e in entries if e["id"] not in remove_ids and e.get("dir_name") not in remove_dir_names]
        _write(ws_dir, entries)
    return removed


def list_workspaces(ws_root: Path) -> list[str]:
    """列出所有含 papers.json 的工作区。

    Args:
        ws_root: workspace/ 根目录。

    Returns:
        工作区名称列表（排序）。
    """
    if not ws_root.is_dir():
        return []
    return sorted(d.name for d in ws_root.iterdir() if d.is_dir() and _papers_json(d).exists())


def validate_workspace_name(name: str) -> bool:
    """Return True if *name* is a safe workspace identifier.

    Rejects empty names, ``.``/``..`` names, leading/trailing whitespace,
    absolute paths, path separators, Windows drive-like names (``:``),
    and any name containing ``..`` to prevent path traversal outside
    ``workspace/``.

    Args:
        name: Candidate workspace name from user input.

    Returns:
        ``True`` when the name is safe for path construction.
    """
    if not name:
        return False
    normalized = name.strip()
    if not normalized:
        return False
    # Reject names with leading/trailing whitespace to avoid ambiguity.
    if normalized != name:
        return False
    if normalized in {".", ".."}:
        return False
    import os

    if os.path.isabs(normalized):
        return False
    # Reject Windows drive-like paths (e.g., C:foo).
    if ":" in normalized:
        return False
    if "/" in normalized or "\\" in normalized:
        return False
    return ".." not in normalized


def show(ws_dir: Path, db_path: Path) -> list[dict]:
    """查看工作区论文列表，刷新过期的 dir_name。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        论文条目列表（含最新 dir_name）。
    """
    from scrinium.index import lookup_paper

    entries = _read(ws_dir)
    changed = False
    for e in entries:
        record = lookup_paper(db_path, e["id"])
        if record and record["dir_name"] != e.get("dir_name"):
            e["dir_name"] = record["dir_name"]
            changed = True
    if changed:
        _write(ws_dir, entries)
    return entries


def read_paper_ids(ws_dir: Path) -> set[str]:
    """返回工作区中所有论文的 UUID 集合。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        UUID 字符串集合，用于搜索过滤。
    """
    return {e["id"] for e in _read(ws_dir)}


def rename(ws_root: Path, old_name: str, new_name: str) -> Path:
    """重命名工作区。

    Args:
        ws_root: workspace/ 根目录。
        old_name: 当前工作区名称。
        new_name: 新工作区名称。

    Returns:
        重命名后的工作区目录路径。

    Raises:
        ValueError: 工作区名称非法（路径穿越/绝对路径等）。
        FileNotFoundError: 源工作区不存在。
        FileExistsError: 目标工作区已存在。
    """
    if not validate_workspace_name(old_name):
        raise ValueError(f"非法工作区名称: {old_name}")
    if not validate_workspace_name(new_name):
        raise ValueError(f"非法工作区名称: {new_name}")
    old_dir = ws_root / old_name
    new_dir = ws_root / new_name
    if not old_dir.exists():
        raise FileNotFoundError(f"工作区不存在: {old_name}")
    if not old_dir.is_dir():
        raise ValueError(f"不是有效工作区目录: {old_name}")
    if not _papers_json(old_dir).exists():
        raise ValueError(f"缺少 papers.json，无法重命名工作区: {old_name}")
    if new_dir.exists():
        raise FileExistsError(f"目标工作区已存在: {new_name}")
    old_dir.rename(new_dir)
    return new_dir


def read_dir_names(ws_dir: Path, db_path: Path) -> set[str]:
    """返回工作区中所有论文的当前目录名集合。

    从 papers_registry 查找最新 dir_name（处理 rename 后的情况）。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        目录名字符串集合，用于导出过滤。
    """
    from scrinium.index import lookup_paper

    names: set[str] = set()
    for e in _read(ws_dir):
        record = lookup_paper(db_path, e["id"])
        if record:
            names.add(record["dir_name"])
        elif e.get("dir_name"):
            names.add(e["dir_name"])
    return names
