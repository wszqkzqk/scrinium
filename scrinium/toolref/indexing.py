from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .constants import TOOL_REGISTRY
from .parsers import _parse_gromacs_rst, _parse_lammps_rst, _parse_manifest_html, _parse_qe_def
from .paths import _db_path, _version_dir
from .storage import _ensure_db

if TYPE_CHECKING:
    from scrinium.config import Config

_log = logging.getLogger(__name__)


def _index_tool(tool: str, version: str, cfg: Config | None = None) -> int:
    vdir = _version_dir(tool, version, cfg)
    db = _db_path(tool, cfg)
    conn = _ensure_db(db)
    conn.execute("PRAGMA integrity_check")

    conn.execute("DELETE FROM toolref_pages WHERE tool = ? AND version = ?", (tool, version))

    records: list[dict] = []
    info = TOOL_REGISTRY[tool]

    if info["format"] == "def":
        def_dir = vdir / "def"
        if def_dir.exists():
            for file_path in sorted(def_dir.glob("INPUT_*.def")):
                try:
                    parsed = _parse_qe_def(file_path)
                    records.extend(parsed)
                    _log.debug("解析 %s: %d 条记录", file_path.name, len(parsed))
                except Exception as e:
                    _log.warning("解析 %s 失败: %s", file_path.name, e)

    elif info["format"] == "rst" and tool == "lammps":
        src_dir = vdir / "src"
        if src_dir.exists():
            for file_path in sorted(src_dir.glob("*.rst")):
                try:
                    parsed = _parse_lammps_rst(file_path)
                    records.extend(parsed)
                except Exception as e:
                    _log.debug("跳过 %s: %s", file_path.name, e)

    elif info["format"] == "rst" and tool == "gromacs":
        src_dir = vdir / "src"
        if src_dir.exists():
            for file_path in sorted(src_dir.rglob("*.rst")):
                try:
                    parsed = _parse_gromacs_rst(file_path)
                    records.extend(parsed)
                except Exception as e:
                    _log.debug("跳过 %s: %s", file_path.name, e)

    elif info["format"] == "html":
        pages_dir = vdir / "pages"
        if pages_dir.exists():
            for file_path in sorted(pages_dir.glob("*.html")):
                try:
                    parsed = _parse_manifest_html(file_path)
                    records.extend(parsed)
                except Exception as e:
                    _log.warning("解析 %s 失败: %s", file_path.name, e)

    for record in records:
        conn.execute(
            """INSERT OR REPLACE INTO toolref_pages
               (tool, version, program, section, page_name, title,
                category, var_type, default_val, synopsis, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tool,
                version,
                record.get("program", ""),
                record.get("section", ""),
                record["page_name"],
                record.get("title", ""),
                record.get("category", ""),
                record.get("var_type", ""),
                record.get("default_val", ""),
                record.get("synopsis", ""),
                record["content"],
            ),
        )

    conn.commit()
    row = conn.execute(
        "SELECT COUNT(*) FROM toolref_pages WHERE tool = ? AND version = ?",
        (tool, version),
    ).fetchone()
    conn.close()
    return row[0] if row else 0
