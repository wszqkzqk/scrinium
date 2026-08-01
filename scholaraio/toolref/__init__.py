"""Scientific tool documentation knowledge base.

Public entry points for the CLI and skills. Implementation details live in the
submodules: ``constants``, ``paths``, ``parsers``, ``manifest``, ``fetch``,
``indexing``, ``storage`` and ``search``.
"""

from __future__ import annotations

from .constants import TOOL_REGISTRY
from .fetch import toolref_fetch
from .paths import validate_tool_name
from .search import toolref_search, toolref_show
from .storage import toolref_list, toolref_use

__all__ = [
    "TOOL_REGISTRY",
    "toolref_fetch",
    "toolref_list",
    "toolref_search",
    "toolref_show",
    "toolref_use",
    "validate_tool_name",
]
