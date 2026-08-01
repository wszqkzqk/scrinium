"""
extractor.py — 论文元数据提取器
================================

提供四种 Stage-1 实现（从 MinerU markdown 提取 title/authors/year/doi/journal）：

  RegexExtractor    — 调用 metadata.py 中的正则提取逻辑（默认）
  LLMExtractor      — 调用 LLM API（OpenAI 兼容协议），适合正则失败的边界 case
  FallbackExtractor — 先 regex，失败时 fallback 到 LLM（auto 模式）
  RobustExtractor   — regex + LLM 双跑，LLM 校正 OCR 错误 + multi-DOI 检测（robust 模式）

用法
----
    from scholaraio.config import load_config
    from scholaraio.ingest.extractor import get_extractor

    config = load_config()
    extractor = get_extractor(config)
    meta = extractor.extract(Path("paper.md"))
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from scholaraio.prompts import PROMPTS, parse_llm_json

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scholaraio.config import Config, LLMConfig
    from scholaraio.ingest.metadata import PaperMetadata


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
            填充后的 :class:`~scholaraio.ingest.metadata.PaperMetadata` 实例。
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
        from scholaraio.ingest.metadata import extract_metadata_from_markdown

        # Read file once; pass text to both metadata extraction and patent check
        text = filepath.read_text(encoding="utf-8", errors="replace")
        meta = extract_metadata_from_markdown(filepath, text=text)
        _extract_patent_number(meta, text)
        return meta


# ============================================================================
#  LLM extractor (OpenAI-compatible API)
# ============================================================================


def _clean_llm_str(val) -> str:
    """LLM 有时返回字符串 "null"/"None" 而非 JSON null，统一清洗。"""
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("null", "none", "n/a", ""):
        return ""
    return s


class LLMExtractor:
    """纯 LLM 元数据提取器（OpenAI 兼容协议）。

    将 Markdown 前 50000 字符发送给 LLM，由 LLM 直接返回结构化元数据。
    API 调用失败时自动降级为正则提取。

    Args:
        llm_config: LLM 后端配置。
        api_key: API 密钥，为空时从 ``llm_config.api_key`` 读取。
    """

    def __init__(self, llm_config: LLMConfig, api_key: str = ""):
        self._config = llm_config
        self._api_key = api_key or llm_config.api_key

    def extract(self, filepath: Path) -> PaperMetadata:
        from scholaraio.ingest.metadata import (
            PaperMetadata,
            _extract_from_filename,
            _extract_lastname,
            extract_metadata_from_markdown,
        )

        text = filepath.read_text(encoding="utf-8", errors="replace")
        header = text[:50000]
        regex_meta = extract_metadata_from_markdown(filepath, text=text)

        try:
            raw_json = self._call_api(header)
            data = parse_llm_json(raw_json)
            if data is None:
                raise ValueError("LLM returned unparseable JSON")
        except Exception as e:
            _log.debug("[LLM] extraction failed: %s, falling back to regex", e)
            from scholaraio.ingest.metadata import extract_metadata_from_markdown

            return extract_metadata_from_markdown(filepath)

        meta = PaperMetadata(source_file=filepath.name)
        meta.title = _clean_llm_str(data.get("title"))
        meta.authors = [a for a in (data.get("authors") or []) if a]
        meta.year = data.get("year") if isinstance(data.get("year"), int) else None
        meta.doi = _guard_llm_doi(_clean_llm_str(data.get("doi")), regex_meta.doi, text, tag="LLM")
        meta.journal = _clean_llm_str(data.get("journal"))
        meta.arxiv_id = regex_meta.arxiv_id

        if meta.authors:
            meta.first_author = meta.authors[0]
            meta.first_author_lastname = _extract_lastname(meta.first_author)

        # Filename fallback for any missing fields
        fb = _extract_from_filename(filepath)
        if not meta.title:
            meta.title = fb.title
        if not meta.year:
            meta.year = fb.year
        if not meta.first_author_lastname:
            meta.first_author_lastname = fb.first_author_lastname
        if not meta.first_author:
            meta.first_author = fb.first_author

        # Patent number extraction from full text
        _extract_patent_number(meta, text)

        return meta

    def _call_api(self, header_text: str) -> str:
        """POST to OpenAI-compatible chat completions endpoint."""
        from scholaraio.metrics import call_llm

        result = call_llm(
            PROMPTS["extract.llm"].render(header=header_text),
            self._config,
            api_key=self._api_key,
            purpose="extract.llm",
        )
        return result.content


# ============================================================================
#  Fallback extractor (regex → LLM if title missing)
# ============================================================================


class FallbackExtractor:
    """Regex 优先、LLM 兜底的元数据提取器（``auto`` 模式）。

    先用正则提取；若关键字段缺失（title 为空，或 author 和 year
    同时为空），再调 LLM 补救。

    Args:
        llm_config: LLM 后端配置。
        api_key: API 密钥。

    Raises:
        RuntimeError: title 缺失且未配置 API key 时抛出。
    """

    def __init__(self, llm_config: LLMConfig, api_key: str):
        self._regex = RegexExtractor()
        self._llm_config = llm_config
        self._api_key = api_key

    def extract(self, filepath: Path) -> PaperMetadata:
        meta = self._regex.extract(filepath)

        needs_llm = not meta.title or (not meta.first_author and not meta.year)
        if not needs_llm:
            return meta

        reason = "title empty" if not meta.title else "author and year both empty"
        _log.debug("[extractor] regex incomplete (%s), trying LLM", reason)
        if not self._api_key:
            if meta.title:
                # title present but author/year missing: degrade to regex result
                _log.debug("[extractor] no LLM API key, using regex result")
                return meta
            raise RuntimeError(
                "regex 提取 title 失败，需要 LLM 兜底，但未配置 LLM API key。\n"
                "请在 config.local.yaml 中设置 llm.api_key，"
                "或设置环境变量 SCHOLARAIO_LLM_API_KEY / DEEPSEEK_API_KEY。"
            )
        return LLMExtractor(self._llm_config, api_key=self._api_key).extract(filepath)


# ============================================================================
#  Robust extractor (regex + LLM always)
# ============================================================================


class RobustExtractor:
    """Regex + LLM 双跑元数据提取器（``robust`` 模式）。

    始终先运行正则提取，再将正则结果和 Markdown 头部一起发给 LLM
    校正 OCR 错误并补全缺失字段。每篇论文消耗一次 LLM 调用。
    LLM 调用失败时降级返回正则结果。

    Args:
        llm_config: LLM 后端配置。
        api_key: API 密钥。
    """

    def __init__(self, llm_config: LLMConfig, api_key: str):
        self._regex = RegexExtractor()
        self._llm_config = llm_config
        self._api_key = api_key

    def extract(self, filepath: Path) -> PaperMetadata:
        from scholaraio.ingest.metadata import (
            PaperMetadata,
            _extract_lastname,
        )

        # Step 1: regex
        regex_meta = self._regex.extract(filepath)

        # Step 2: LLM with regex results + paper content (up to 50k chars)
        text = filepath.read_text(encoding="utf-8", errors="replace")
        header = text[:50000]

        prompt = PROMPTS["extract.robust"].render(
            regex_title=regex_meta.title or "(未提取到)",
            regex_authors=", ".join(regex_meta.authors) if regex_meta.authors else "(未提取到)",
            regex_year=regex_meta.year or "(未提取到)",
            regex_doi=regex_meta.doi or "(未提取到)",
            regex_journal=regex_meta.journal or "(未提取到)",
            header=header,
        )

        try:
            raw_json = self._call_api(prompt)
            data = parse_llm_json(raw_json)
            if data is None:
                raise ValueError("LLM returned unparseable JSON")
        except Exception as e:
            _log.debug("[robust] LLM correction failed: %s, using regex result", e)
            return regex_meta

        # Build metadata from LLM response (with null-string cleanup)
        meta = PaperMetadata(source_file=filepath.name)
        meta.title = _clean_llm_str(data.get("title")) or regex_meta.title or ""
        meta.authors = [a for a in (data.get("authors") or []) if a] or regex_meta.authors
        llm_year = data.get("year")
        meta.year = (llm_year if isinstance(llm_year, int) else None) or regex_meta.year
        # DOI: multi-DOI or hallucination guard
        meta.doi = _guard_llm_doi(_clean_llm_str(data.get("doi")), regex_meta.doi, text, tag="robust")
        meta.journal = _clean_llm_str(data.get("journal")) or regex_meta.journal or ""
        meta.arxiv_id = regex_meta.arxiv_id

        if meta.authors:
            meta.first_author = meta.authors[0]
            meta.first_author_lastname = _extract_lastname(meta.first_author)

        # Filename fallback for anything still missing
        fb = regex_meta
        if not meta.title:
            meta.title = fb.title
        if not meta.year:
            meta.year = fb.year
        if not meta.first_author_lastname:
            meta.first_author_lastname = fb.first_author_lastname
        if not meta.first_author:
            meta.first_author = fb.first_author

        # Patent number extraction from full text
        _extract_patent_number(meta, text)

        return meta

    def _call_api(self, prompt: str) -> str:
        from scholaraio.metrics import call_llm

        result = call_llm(
            prompt,
            self._llm_config,
            api_key=self._api_key,
            purpose="extract.robust",
        )
        return result.content


# ============================================================================
#  DOI hallucination guard (shared by LLM-based extractors)
# ============================================================================

_DOI_SCAN_RE = re.compile(r"10\.\d{4,}/[^\s)]+")


def _guard_llm_doi(llm_doi: str, regex_doi: str, text: str, *, tag: str) -> str:
    """Validate an LLM-returned DOI against the source text.

    - Multiple distinct DOIs in the fulltext indicate a multi-paper PDF;
      no DOI is trustworthy, so discard.
    - An LLM DOI that appears nowhere in the text and was not found by
      regex either is likely a hallucination, so discard.

    Returns:
        The DOI to keep (LLM result, else regex fallback), or ``""``.
    """
    all_dois = set(_DOI_SCAN_RE.findall(text))
    if len(all_dois) > 1:
        _log.debug("[%s] found %d different DOIs in fulltext, discarding for title search", tag, len(all_dois))
        return ""
    if llm_doi and not regex_doi and llm_doi not in text:
        _log.debug("[%s] LLM DOI not found in source text, suspected hallucination, discarding", tag)
        return ""
    return llm_doi or regex_doi or ""


# ============================================================================
#  Patent number extraction
# ============================================================================


def _extract_patent_number(meta, text: str) -> None:
    """Extract patent publication number from text and set paper_type if patent."""
    from scholaraio.ingest.metadata._models import PATENT_NUMBER_RE

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
    """根据配置返回对应的元数据提取器实例。

    Args:
        config: 全局配置，从 ``config.ingest.extractor`` 读取模式。

    Returns:
        实现 :class:`MetadataExtractor` 协议的提取器实例。

    Raises:
        RuntimeError: ``robust`` 或 ``llm`` 模式缺少 API key 时抛出。

    支持的模式:
        - ``regex``: 纯正则，最快，不调 LLM。
        - ``auto``: regex 优先，关键字段缺失时 LLM 兜底。
        - ``robust``: regex + LLM 始终双跑，LLM 校正 OCR 错误。
        - ``llm``: 纯 LLM，不跑 regex。
    """
    mode = config.ingest.extractor

    if mode == "llm":
        api_key = config.resolved_api_key()
        if not api_key:
            _log.warning("[LLM] no API key found; set SCHOLARAIO_LLM_API_KEY or llm.api_key in config.local.yaml")
        return LLMExtractor(config.llm, api_key=api_key)

    if mode == "robust":
        api_key = config.resolved_api_key()
        if not api_key:
            raise RuntimeError(
                "robust 模式需要 LLM API key。\n"
                "请在 config.local.yaml 中设置 llm.api_key，"
                "或设置环境变量 SCHOLARAIO_LLM_API_KEY / DEEPSEEK_API_KEY。"
            )
        return RobustExtractor(config.llm, api_key=api_key)

    if mode == "auto":
        return FallbackExtractor(config.llm, api_key=config.resolved_api_key())

    return RegexExtractor()
