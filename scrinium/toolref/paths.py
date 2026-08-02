from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .constants import TOOL_REGISTRY

_DEFAULT_TOOLREF_DIR = Path("data/toolref")

if TYPE_CHECKING:
    from scrinium.config import Config


def _toolref_root(cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "toolref"
    return _DEFAULT_TOOLREF_DIR


def _tool_dir(tool: str, cfg: Config | None = None) -> Path:
    return _toolref_root(cfg) / tool


def _version_dir(tool: str, version: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / version


def _current_link(tool: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / "current"


def _db_path(tool: str, cfg: Config | None = None) -> Path:
    return _tool_dir(tool, cfg) / "toolref.db"


def validate_tool_name(name: str) -> bool:
    return name in TOOL_REGISTRY


def _validate_version(version: str) -> bool:
    if not version or os.path.isabs(version):
        return False
    return "/" not in version and "\\" not in version and ".." not in version
