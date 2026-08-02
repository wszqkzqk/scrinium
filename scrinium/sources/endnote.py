"""sources/endnote.py — 解析 Endnote XML 和 RIS 文件，转换为 PaperMetadata"""

from __future__ import annotations

import importlib
import logging
import re
from pathlib import Path

from scrinium.ingest.metadata._extract import _extract_lastname
from scrinium.ingest.metadata._models import PaperMetadata

_log = logging.getLogger(__name__)

# ref_type string → Crossref-style paper_type
_REF_TYPE_MAP: dict[str, str] = {
    "Journal Article": "journal-article",
    "Conference Paper": "conference-paper",
    "Conference Proceedings": "conference-paper",
    "Book": "book",
    "Book Section": "book-chapter",
    "Thesis": "thesis",
    "Report": "report",
    "Generic": "",
}

# ref_types where isbn actually represents an ISSN (serial publications)
_JOURNAL_REF_TYPES = {"Journal Article", "Conference Paper", "Conference Proceedings"}

_DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_INTERNAL_PDF_RE = re.compile(r"^internal-pdf://(\d+)/(.+)$")
_SI_PATTERN = re.compile(
    r"(?:^|[-_ ])(?:SI|[Ss]uppl(?:ement(?:ary)?)?|[Ss]upporting)"
    r"|[-_ ](?:S\d+|Table\s*S\d+|Figure\s*S\d+)\.pdf$",
)


def _load_endnote_core():
    """Load ``endnote_utils.core`` lazily so import extras stay optional."""
    return importlib.import_module("endnote_utils.core")


# ============================================================================
#  Internal helpers
# ============================================================================


def _normalize_author_name(name: str) -> str:
    """Convert "Last, First" to "First Last"; pass through if no comma."""
    if "," in name:
        parts = name.split(",", 1)
        return f"{parts[1].strip()} {parts[0].strip()}"
    return name


def _normalise_paper_type(ref_type: str) -> str:
    """Map Endnote ref_type to Crossref-style paper_type."""
    if ref_type in _REF_TYPE_MAP:
        return _REF_TYPE_MAP[ref_type]
    return ref_type.lower().replace(" ", "-")


def _clean_doi(raw: str) -> str:
    """Strip URL prefix from DOI, return bare DOI."""
    if not raw:
        return ""
    return _DOI_PREFIX_RE.sub("", raw).strip()


def _resolve_pdf_candidates(elem, data_dir: Path, ns: str) -> list[Path]:
    """Extract all existing PDF paths from an XML record element."""
    candidates: list[Path] = []
    for url_el in elem.findall(".//" + ns + "pdf-urls/" + ns + "url"):
        text = (url_el.text or "").strip()
        m = _INTERNAL_PDF_RE.match(text)
        if not m:
            continue
        numeric_id, filename = m.group(1), m.group(2)
        pdf_path = data_dir / numeric_id / filename
        if pdf_path.exists():
            candidates.append(pdf_path)
    return candidates


def _pick_main_pdf(candidates: list[Path]) -> Path | None:
    """From multiple PDF candidates, pick the main paper (skip SI/supplement).

    Heuristic:
    1. Filter out files matching SI/supplement patterns
    2. If any remain, take the largest (most likely the main paper)
    3. If all filtered out, take the largest of all candidates
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    non_si = [p for p in candidates if not _SI_PATTERN.search(p.name)]
    pool = non_si if non_si else candidates
    return max(pool, key=lambda p: p.stat().st_size)


def _record_to_meta(record: dict, source_file: str) -> PaperMetadata:
    """Convert an endnote-utils flat dict to PaperMetadata.

    Args:
        record: Flat dict produced by ``process_record_xml`` or
            ``iter_records_ris``.
        source_file: Filename of the source XML/RIS file.

    Returns:
        Populated ``PaperMetadata`` instance.
    """
    # authors: "; "-separated string → list
    # Endnote exports "Last, First" format; normalize to "First Last" for consistency
    raw_authors = record.get("authors", "")
    authors_raw = [a.strip() for a in raw_authors.split("; ") if a.strip()] if raw_authors else []
    authors = [_normalize_author_name(a) for a in authors_raw]

    first_author = authors[0] if authors else ""
    first_author_lastname = _extract_lastname(first_author) if first_author else ""

    # year
    year_str = record.get("year", "")
    year: int | None = None
    if year_str:
        try:
            year = int(year_str)
        except ValueError:
            _log.debug("无法解析年份: %r", year_str)

    ref_type = record.get("ref_type", "")
    paper_type = _normalise_paper_type(ref_type)

    # isbn → issn only for journal-like types
    issn = ""
    if ref_type in _JOURNAL_REF_TYPES:
        issn = record.get("isbn", "")

    return PaperMetadata(
        title=record.get("title", ""),
        authors=authors,
        first_author=first_author,
        first_author_lastname=first_author_lastname,
        year=year,
        doi=_clean_doi(record.get("doi", "")),
        journal=record.get("journal", ""),
        abstract=record.get("abstract", ""),
        paper_type=paper_type,
        volume=record.get("volume", ""),
        issue=record.get("number", ""),
        pages=record.get("pages", ""),
        publisher=record.get("publisher", ""),
        issn=issn,
        source_file=source_file,
        extraction_method="endnote",
    )


# ============================================================================
#  Public API
# ============================================================================


def parse_endnote(paths: list[Path]) -> list[PaperMetadata]:
    """解析 Endnote 导出文件（XML 或 RIS），返回 PaperMetadata 列表。

    根据文件扩展名自动选择解析器：``.xml`` 使用 XML 解析，
    ``.ris`` 使用 RIS 解析。其他扩展名会被跳过并记录警告。

    Args:
        paths: Endnote 导出文件路径列表（支持 ``.xml`` 和 ``.ris``）。

    Returns:
        所有文件中解析出的 ``PaperMetadata`` 列表。
    """
    results: list[PaperMetadata] = []
    core = _load_endnote_core()

    for path in paths:
        suffix = path.suffix.lower()
        source_file = path.name

        if suffix == ".xml":
            _log.info("解析 Endnote XML: %s", path)
            for elem in core.iter_records_xml(path):
                rec = core.process_record_xml(elem, "endnote")
                results.append(_record_to_meta(rec, source_file))

        elif suffix == ".ris":
            _log.info("解析 Endnote RIS: %s", path)
            for rec in core.iter_records_ris(path):
                results.append(_record_to_meta(rec, source_file))

        else:
            _log.warning("不支持的文件格式，跳过: %s", path)

    _log.info("共解析 %d 条记录", len(results))
    return results


def parse_endnote_full(
    paths: list[Path],
) -> tuple[list[PaperMetadata], list[Path | None]]:
    """解析 Endnote 文件，同时提取 PDF 路径（与记录一一对齐）。

    对 XML 文件：解析元数据 + 从 ``<pdf-urls>`` 提取 ``internal-pdf://``
    链接并解析为实际文件路径。多个 PDF 时自动排除 SI/补充材料，选主文件。

    对 RIS 文件：仅解析元数据，PDF 路径为 ``None``。

    Args:
        paths: Endnote 导出文件路径列表。

    Returns:
        ``(records, pdf_paths)``，两个列表长度相同、索引对齐。
    """
    records: list[PaperMetadata] = []
    pdf_paths: list[Path | None] = []
    core = _load_endnote_core()

    for path in paths:
        suffix = path.suffix.lower()
        source_file = path.name

        if suffix == ".xml":
            _log.info("解析 Endnote XML: %s", path)
            data_dir = path.parent / f"{path.stem}.Data" / "PDF"
            has_data_dir = data_dir.exists()
            if not has_data_dir:
                _log.debug("Endnote Data 目录不存在: %s", data_dir)

            for elem in core.iter_records_xml(path):
                rec = core.process_record_xml(elem, "endnote")
                records.append(_record_to_meta(rec, source_file))

                # Extract PDF path from same element
                if has_data_dir:
                    candidates = _resolve_pdf_candidates(elem, data_dir, "")
                    pdf_paths.append(_pick_main_pdf(candidates))
                else:
                    pdf_paths.append(None)

        elif suffix == ".ris":
            _log.info("解析 Endnote RIS: %s", path)
            for rec in core.iter_records_ris(path):
                records.append(_record_to_meta(rec, source_file))
                pdf_paths.append(None)

        else:
            _log.warning("不支持的文件格式，跳过: %s", path)

    n_pdfs = sum(1 for p in pdf_paths if p is not None)
    _log.info("共解析 %d 条记录，%d 个可匹配 PDF", len(records), n_pdfs)
    return records, pdf_paths


def extract_pdf_map(xml_paths: list[Path]) -> dict[str, Path]:
    """从 Endnote XML 中提取 DOI → PDF 路径映射（便捷接口）。

    Args:
        xml_paths: Endnote XML 文件路径列表。

    Returns:
        ``{doi: pdf_path}`` 映射，仅包含 DOI 和 PDF 均存在的记录。
    """
    records, pdf_paths = parse_endnote_full(xml_paths)
    return {r.doi: p for r, p in zip(records, pdf_paths) if r.doi and p is not None}
