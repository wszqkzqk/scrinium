"""
extractor.py — 论文元数据提取器
================================

Stage-1 元数据提取（从 MinerU markdown 提取 title/authors/year/doi/journal）。
框架内只保留 RegexExtractor（纯正则，零模型调用）；规则失败的疑难件
转入 pending 队列，由 agent/subagent 审查接管。

用法
----
    from scrinium.config import load_config
    from scrinium.ingest.extractor import get_extractor

    config = load_config()
    extractor = get_extractor(config)
    meta = extractor.extract(Path("paper.md"))
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scrinium.config import Config
    from scrinium.ingest.metadata import PaperMetadata


# ============================================================================
#  Protocol
# ============================================================================


@runtime_checkable
class MetadataExtractor(Protocol):
    """元数据提取器协议，所有提取器必须实现此接口。"""

    def extract(self, filepath: Path) -> PaperMetadata:
        """从 Markdown 文件提取论文元数据。

        Args:
            filepath: MinerU 输出的 ``.md`` 文件路径。

        Returns:
            填充后的 :class:`~scrinium.ingest.metadata.PaperMetadata` 实例。
        """
        ...


# ============================================================================
#  Regex extractor (wraps existing metadata.py logic, zero changes there)
# ============================================================================


class RegexExtractor:
    """纯正则元数据提取器。

    封装 ``metadata.py`` 中的正则提取逻辑，不调用 LLM。
    速度最快，适用于 OCR 质量好的论文。
    """

    def extract(self, filepath: Path) -> PaperMetadata:
        from scrinium.ingest.metadata import extract_metadata_from_markdown

        # Read file once; pass text to both metadata extraction and patent check
        text = filepath.read_text(encoding="utf-8", errors="replace")
        meta = extract_metadata_from_markdown(filepath, text=text)
        _extract_patent_number(meta, text)
        return meta


# ============================================================================
#  Patent number extraction
# ============================================================================


def _extract_patent_number(meta, text: str) -> None:
    """Extract patent publication number from text and set paper_type if patent."""
    from scrinium.ingest.metadata._models import PATENT_NUMBER_RE

    m = PATENT_NUMBER_RE.search(text[:10000])
    if m and not meta.publication_number:
        meta.publication_number = m.group(1).upper()
    # Heuristic: if publication_number found and no DOI, likely a patent
    if meta.publication_number and not meta.doi:
        if not meta.paper_type or meta.paper_type in ("", "article"):
            meta.paper_type = "patent"


# ============================================================================
#  Factory
# ============================================================================


def get_extractor(config: Config) -> MetadataExtractor:
    """返回元数据提取器实例（恒为 :class:`RegexExtractor`）。

    Args:
        config: 全局配置（保留参数；LLM 提取模式已移除，
            非 regex 的 ``ingest.extractor`` 配置在加载时触发 deprecation warning）。

    Returns:
        :class:`RegexExtractor` 实例。
    """
    return RegexExtractor()
