from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from . import manifest as manifest_mod
from .constants import TOOL_REGISTRY
from .paths import _current_link, _toolref_root, _validate_version, _version_dir, validate_tool_name

if TYPE_CHECKING:
    from scrinium.config import Config

_PAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS toolref_pages (
    id INTEGER PRIMARY KEY,
    tool TEXT NOT NULL,
    version TEXT NOT NULL,
    program TEXT,
    section TEXT,
    page_name TEXT NOT NULL,
    title TEXT,
    category TEXT,
    var_type TEXT,
    default_val TEXT,
    synopsis TEXT,
    content TEXT,
    UNIQUE(tool, version, page_name)
);
CREATE INDEX IF NOT EXISTS idx_toolref_tool_version ON toolref_pages(tool, version);
CREATE INDEX IF NOT EXISTS idx_toolref_page_name ON toolref_pages(page_name);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS toolref_fts USING fts5(
    page_name,
    title,
    synopsis,
    content,
    content='toolref_pages',
    content_rowid='id'
);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS toolref_pages_ai AFTER INSERT ON toolref_pages BEGIN
    INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
    VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
END;
CREATE TRIGGER IF NOT EXISTS toolref_pages_ad AFTER DELETE ON toolref_pages BEGIN
    INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
    VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
END;
CREATE TRIGGER IF NOT EXISTS toolref_pages_au AFTER UPDATE ON toolref_pages BEGIN
    INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
    VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
    INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
    VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
END;
"""


def _ensure_db(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        DROP TRIGGER IF EXISTS toolref_ai;
        DROP TRIGGER IF EXISTS toolref_ad;
        DROP TRIGGER IF EXISTS toolref_au;
        """
    )
    conn.executescript(_PAGES_SCHEMA)
    conn.executescript(_FTS_SCHEMA)
    conn.executescript(_FTS_TRIGGERS)
    return conn


def _set_current(tool: str, version: str, cfg: Config | None = None) -> None:
    link = _current_link(tool, cfg)
    if link.is_symlink() or link.exists():
        link.unlink()
    try:
        # target_is_directory is required on Windows; ignored elsewhere.
        link.symlink_to(version, target_is_directory=True)
    except OSError:
        # Native Windows needs admin rights or Developer Mode for symlinks
        # (WinError 1314); fall back to a plain text marker file.
        link.write_text(version, encoding="utf-8")
        logging.getLogger(__name__).warning(
            "无法创建符号链接（Windows 需要管理员权限或开发者模式），已改用文本文件记录当前版本"
        )


def _get_current(tool: str, cfg: Config | None = None) -> str | None:
    """Return the current version of *tool*, or None when unset/unreadable.

    Reads both the symlink form and the plain-text fallback written on
    Windows when symlink creation is not permitted. Callers treat None as
    "no pinned version" and degrade to searching all versions.
    """
    link = _current_link(tool, cfg)
    if link.is_symlink():
        return link.resolve().name
    if link.is_file():
        try:
            version = link.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return version or None
    return None


def toolref_use(tool: str, version: str, *, cfg: Config | None = None) -> None:
    from scrinium.log import ui

    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}")
    if not _validate_version(version):
        raise ValueError(f"非法版本号：{version}")
    vdir = _version_dir(tool, version, cfg)
    if not vdir.exists():
        raise FileNotFoundError(
            f"{tool} 版本 {version} 未找到。请先运行 `scrinium toolref fetch {tool} --version {version}`"
        )
    _set_current(tool, version, cfg)
    display_name = TOOL_REGISTRY.get(tool, {}).get("display_name", tool)
    ui(f"[toolref] {display_name} 当前版本已切换为 {version}")


def toolref_list(tool: str | None = None, *, cfg: Config | None = None) -> list[dict]:
    root = _toolref_root(cfg)
    results: list[dict] = []

    tools = [tool] if tool else list(TOOL_REGISTRY.keys())
    for t in tools:
        tdir = root / t
        if not tdir.exists():
            continue

        current_version = _get_current(t, cfg)

        for vdir in sorted(tdir.iterdir()):
            if vdir.name == "current" or not vdir.is_dir():
                if vdir.name == "toolref.db":
                    continue
                continue
            db = tdir / "toolref.db"
            page_count = 0
            meta: dict = {}
            if db.exists():
                try:
                    conn = sqlite3.connect(db)
                    try:
                        row = conn.execute(
                            "SELECT COUNT(*) FROM toolref_pages WHERE tool=? AND version=?",
                            (t, vdir.name),
                        ).fetchone()
                        page_count = row[0] if row else 0
                    finally:
                        conn.close()
                except Exception:
                    pass
            meta_path = vdir / "meta.json"
            if meta_path.exists():
                try:
                    import json

                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            if meta.get("source_type") == "manifest":
                page_count = meta.get("fetched_pages", page_count)
                expected_pages = meta.get("expected_pages")
                actual_expected_pages = max(manifest_mod._expected_manifest_pages(t, vdir.name, cfg), page_count)
                if expected_pages is None or expected_pages < actual_expected_pages:
                    expected_pages = actual_expected_pages
                failed_pages = max(expected_pages - page_count, 0)
            else:
                expected_pages = meta.get("expected_pages")
                failed_pages = meta.get("failed_pages")

            results.append(
                {
                    "tool": t,
                    "display_name": TOOL_REGISTRY.get(t, {}).get("display_name", t),
                    "version": vdir.name,
                    "is_current": vdir.name == current_version,
                    "page_count": page_count,
                    "source_type": meta.get("source_type", TOOL_REGISTRY.get(t, {}).get("source_type", "git")),
                    "expected_pages": expected_pages,
                    "failed_pages": failed_pages,
                }
            )

    return results
