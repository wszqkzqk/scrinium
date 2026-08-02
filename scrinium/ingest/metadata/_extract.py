"""Markdown metadata extraction — regex parsing of title, authors, DOI, year, journal."""

from __future__ import annotations

import re
from pathlib import Path

from ._models import (
    AUTHOR_H1_INDICATORS,
    AUTHOR_STOP,
    DOI_CORE,
    NON_TITLE_H1,
    PaperMetadata,
)

# ============================================================================
#  Public API
# ============================================================================


def extract_metadata_from_markdown(filepath: Path, *, text: str | None = None) -> PaperMetadata:
    """从 MinerU Markdown 文件头部提取论文元数据（纯正则，不调 API）。

    提取字段: title, authors, year, doi, journal。
    无法从正文提取时回退到文件名解析。

    Args:
        filepath: MinerU 输出的 ``.md`` 文件路径。
        text: 预读的文件内容。若为 ``None`` 则从 ``filepath`` 读取。

    Returns:
        填充后的 :class:`PaperMetadata` 实例（部分字段可能为空）。
    """
    if text is None:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header_lines = lines[:60]
    header_text = "\n".join(header_lines)

    meta = PaperMetadata(source_file=filepath.name)

    # Title
    meta.title, title_idx = _extract_title(header_lines)

    # DOI (search wider area)
    meta.doi = _extract_doi("\n".join(lines[:80]))

    # arXiv ID (from text and filename)
    meta.arxiv_id = _extract_arxiv_id("\n".join(lines[:80]), filepath)

    # Authors: try after title first, then check H1 lines before title
    if title_idx >= 0:
        meta.authors = _extract_authors(header_lines, title_idx + 1)
    if not meta.authors and title_idx > 0:
        meta.authors = _extract_authors_from_h1_before_title(header_lines, title_idx)
    if meta.authors:
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)

    # Year
    meta.year = _extract_year_from_text(header_text)

    # Journal
    meta.journal = _extract_journal(header_text)

    # Fallback from filename
    fb = _extract_from_filename(filepath)
    if not meta.title:
        meta.title = fb.title
    if not meta.year:
        meta.year = fb.year
    if not meta.first_author_lastname:
        meta.first_author_lastname = fb.first_author_lastname
    if not meta.first_author:
        meta.first_author = fb.first_author

    return meta


# ============================================================================
#  Title Extraction
# ============================================================================


def _extract_title(lines: list[str]) -> tuple[str, int]:
    """Extract paper title from H1 headings, skipping known non-title H1s."""
    h1_candidates: list[tuple[str, int]] = []

    for i, line in enumerate(lines[:40]):
        if line.startswith("# "):
            text = line[2:].strip()
            if not text:
                continue
            h1_candidates.append((text, i))

    for text, idx in h1_candidates:
        # Skip known non-title patterns
        if any(pat.search(text) for pat in NON_TITLE_H1):
            continue
        # Skip if it looks like an author name: short text with superscript markers
        if any(ind.search(text) for ind in AUTHOR_H1_INDICATORS):
            # But only skip if it's short (< 8 words) — long text with <sup> is likely a title
            if len(text.split()) < 8:
                continue
        # Skip very short text that looks like a person name (2-3 words, all capitalized)
        words = text.split()
        if len(words) <= 3 and all(w[0].isupper() for w in words if w):
            # Could be author name — check if a longer H1 follows soon
            remaining = [(t, j) for t, j in h1_candidates if j > idx]
            has_longer = any(len(t.split()) > 5 for t, _ in remaining)
            if has_longer:
                continue
        return text, idx

    # Fallback: take the longest H1
    if h1_candidates:
        best = max(h1_candidates, key=lambda x: len(x[0]))
        return best
    return "", -1


# ============================================================================
#  Author Extraction
# ============================================================================


def _extract_authors(lines: list[str], start_idx: int) -> list[str]:
    """Extract author names from lines following the title."""
    author_text_parts: list[str] = []

    # Lines to skip (metadata, not authors, but not stop-worthy)
    SKIP_LINES = [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"^Cite\s+as",
            r"^Submitted",
            r"^Published\s+Online",
            r"^Accepted",
            r"^Received",
            r"^Available\s+online",
        ]
    ]

    for i in range(start_idx, min(start_idx + 20, len(lines))):
        line = lines[i].strip()
        if not line:
            if author_text_parts:
                break  # blank line after some author text = end of author block
            continue
        # Skip metadata lines but keep scanning
        if any(pat.search(line) for pat in SKIP_LINES):
            continue
        # Check stop markers
        if any(pat.search(line) for pat in AUTHOR_STOP):
            break
        # Skip image lines
        if line.startswith("!["):
            if author_text_parts:
                break
            continue
        # Skip lines that are H1 section headers (e.g., "# ABSTRACT", "# 1 Introduction")
        if line.startswith("# "):
            break
        # Skip very long lines (likely abstract paragraphs, not author lists)
        if len(line) > 300:
            break
        author_text_parts.append(line)

    if not author_text_parts:
        return []

    raw = " ".join(author_text_parts)
    # Clean and split
    authors = _split_authors(raw)
    return [a for a in authors if a]


def _extract_authors_from_h1_before_title(lines: list[str], title_idx: int) -> list[str]:
    """Extract authors from H1 headings that appear before the title (ASME/JFEG format)."""
    authors = []
    for i in range(title_idx):
        line = lines[i].strip()
        if line.startswith("# "):
            text = line[2:].strip()
            if not text:
                continue
            # Skip known non-title patterns
            if any(pat.search(text) for pat in NON_TITLE_H1):
                continue
            # Short text (1-4 words) that looks like a person name
            words = text.split()
            if 1 <= len(words) <= 5:
                cleaned = _clean_author_name(text)
                if cleaned:
                    authors.append(cleaned)
    return authors


def _split_authors(raw: str) -> list[str]:
    """Split raw author text into individual names."""
    # Remove H1 markers if present
    raw = re.sub(r"^#+\s*", "", raw)
    # Clean markers
    raw = _clean_author_text(raw)
    # Split on common delimiters (IGNORECASE to handle "AND" from spaced-out OCR)
    parts = re.split(r"\s*(?:,\s*and\s+|,\s+and\s+|\band\b|;\s*|，\s*|、)\s*", raw, flags=re.IGNORECASE)
    # Also split on remaining commas
    result = []
    for p in parts:
        # If a part still has commas and looks like multiple names, split further
        if "," in p:
            subparts = [s.strip() for s in p.split(",")]
            # Only split if each subpart looks like a name (has capital letter)
            if all(re.search(r"[A-Z\u4e00-\u9fff]", s) for s in subparts if s):
                result.extend(subparts)
            else:
                result.append(p.strip())
        else:
            result.append(p.strip())
    # Final cleanup
    return [_clean_author_name(a) for a in result if a.strip()]


def _clean_author_text(raw: str) -> str:
    """Remove markup from author text block."""
    # Remove HTML superscripts
    raw = re.sub(r"<sup>[^<]*</sup>", "", raw)
    # Extract visible letters from inline LaTeX math (e.g., $\mathbf{D}^{1}$ → D)
    raw = re.sub(r"\$([^$]*)\$", lambda m: _extract_text_from_latex(m.group(1)), raw)
    # Remove bare superscript numbers after names (with or without space)
    raw = re.sub(r"\s*\d{1,3}(?=[,\s]|$)", "", raw)
    # Normalize spaced-out "A N D" delimiter to lowercase before collapsing,
    # so it won't be merged with adjacent spaced-out name letters
    raw = re.sub(r"(?<=\s)A N D(?=\s)", "and", raw)
    # Collapse OCR spaced-out letters: "B I J L A R D" → "BIJLARD"
    # Requires 3+ consecutive single uppercase letters separated by single spaces
    # (won't touch initials with periods like "M. J." or lowercase "and")
    raw = re.sub(
        r"(?<![A-Za-z])([A-Z] ){2,}[A-Z](?![A-Za-z.])",
        lambda m: m.group(0).replace(" ", ""),
        raw,
    )
    # Remove ORCID icons and links
    raw = re.sub(r"\\textcircled\{[^}]*\}", "", raw)
    raw = re.sub(r"https?://orcid\.org/\S+", "", raw)
    # Remove email addresses
    raw = re.sub(r"\S+@\S+\.\S+", "", raw)
    # Remove remaining LaTeX commands (e.g. \oplus)
    raw = re.sub(r"\\[a-zA-Z]+", "", raw)
    return raw


def _extract_text_from_latex(latex: str) -> str:
    """Extract visible text letters from inline LaTeX math.

    E.g., ``\\mathbf{D}^{1}`` → ``D`` (keeps the letter, drops superscript).
    """
    # Remove superscripts: ^{...} or ^x (with optional spaces around braces)
    s = re.sub(r"\^\s*(?:\{[^}]*\}|.)", "", latex)
    # Remove subscripts: _{...} or _x
    s = re.sub(r"_\s*(?:\{[^}]*\}|.)", "", s)
    # Extract content from commands like \mathbf{D} → D
    s = re.sub(r"\\[a-zA-Z]+\s*\{([^}]*)\}", r"\1", s)
    # Remove remaining backslash commands
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    # Keep only letters
    s = re.sub(r"[^A-Za-z]", "", s)
    return s


def _clean_author_name(name: str) -> str:
    """Clean individual author name."""
    # Remove symbols
    name = re.sub(r"[*†‡§¶✉⇑∗⊕]", "", name)
    # Remove "By " prefix
    name = re.sub(r"^By\s+", "", name, flags=re.IGNORECASE)
    # Remove parenthetical affiliations
    name = re.sub(r"\([^)]*\)", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Remove trailing/leading punctuation
    name = name.strip("., ")
    return name


# ============================================================================
#  DOI / Year / Journal
# ============================================================================


def _extract_doi(text: str) -> str:
    """Extract DOI from header text using multiple patterns."""
    # Collapse split-line DOIs (Chinese papers)
    text_c = re.sub(r"(文献DOI\s*[:：]?\s*)\n", r"\1", text)
    text_c = re.sub(r"(10\.\d{4,}[./])\n\s*", r"\1", text_c)

    patterns = [
        r"https?://(?:dx\.)?doi\.org/(" + DOI_CORE + r")",
        r"(?:DOI|doi)\s*[:：]\s*(" + DOI_CORE + r")",
        r"\[DOI:\s*(" + DOI_CORE + r")\]",
        r"(?:article's\s+doi|文献DOI)\s*[:：]?\s*(" + DOI_CORE + r")",
        r"^(" + DOI_CORE + r")\s*$",
    ]
    # DOIs to reject (data repositories, not the paper itself)
    REJECT_DOI_PREFIXES = (
        "10.17632/",  # Mendeley Data
        "10.5281/",  # Zenodo
        "10.6084/",  # figshare
        "10.5061/",  # Dryad
        "10.7910/",  # Harvard Dataverse
    )

    for pat in patterns:
        m = re.search(pat, text_c, re.MULTILINE | re.IGNORECASE)
        if m:
            doi = m.group(1).rstrip(".;,")
            if any(doi.startswith(prefix) for prefix in REJECT_DOI_PREFIXES):
                continue  # skip data repository DOIs
            return doi
    return ""


# arXiv archive prefixes (old format, pre-April 2007)
_ARXIV_OLD_ARCHIVES = (
    "astro-ph|cond-mat|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math-ph|"
    "nlin|nucl-ex|nucl-th|physics|quant-ph|math|cs|q-bio|q-fin|stat"
)

# New format: YYMM.NNNN or YYMM.NNNNN (4 or 5 digits, Apr 2007+)
# Old format: archive/YYMMNNN (pre-Apr 2007)
_ARXIV_NEW_RE = re.compile(r"\d{4}\.\d{4,5}")
_ARXIV_OLD_RE = re.compile(rf"(?:{_ARXIV_OLD_ARCHIVES})(?:\.[A-Za-z-]+)?/\d{{7}}")


def _extract_arxiv_id(text: str, filepath: Path | None = None) -> str:
    """Extract arXiv ID from text content and/or filename.

    Searches for patterns like ``arXiv:2401.12345``, ``arxiv.org/abs/2401.12345``,
    or bare IDs in the header. Also checks the filename for arXiv ID patterns.
    Returns the ID without version suffix (e.g. ``2401.12345``, not ``2401.12345v2``).
    """
    # 1. Explicit arXiv references in text (highest confidence)
    patterns = [
        # arXiv:YYMM.NNNNN or arXiv:YYMM.NNNNNvN
        rf"arXiv\s*[:]\s*({_ARXIV_NEW_RE.pattern}|{_ARXIV_OLD_RE.pattern})(?:v\d+)?",
        # arxiv.org/abs/YYMM.NNNNN
        rf"arxiv\.org/abs/({_ARXIV_NEW_RE.pattern}|{_ARXIV_OLD_RE.pattern})(?:v\d+)?",
        # arxiv.org/pdf/YYMM.NNNNN
        rf"arxiv\.org/pdf/({_ARXIV_NEW_RE.pattern}|{_ARXIV_OLD_RE.pattern})(?:v\d+)?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)

    # 2. Check filename (e.g. 0906.2569v2.pdf → 0906.2569)
    if filepath:
        stem = filepath.stem
        # New format in filename
        m = re.fullmatch(rf"({_ARXIV_NEW_RE.pattern})(?:v\d+)?", stem)
        if m:
            return m.group(1)
        # Old format in filename (e.g. hep-th_9901001.pdf — underscore variant)
        m = re.fullmatch(
            rf"({_ARXIV_OLD_RE.pattern.replace('/', '/')})(?:v\d+)?",
            stem.replace("_", "/"),
        )
        if m:
            return m.group(1)

    return ""


def _extract_year_from_text(text: str) -> int | None:
    """Extract publication year from header text."""
    patterns = [
        r"(?:Annu\.?\s*Rev\.?|Annual\s+Review)[^.]*?(\d{4})",
        r"Cite\s+as:.*?(\d{4})",
        r"(?:Copyright|©)\s*(?:©\s*)?(\d{4})",
        r"(?:published\s+(?:online\s+)?|Available\s+online\s+)\S+\s+\S+\s+(\d{4})",
        r"(?:Received|accepted)\s+[^;.]*?(\d{4})",
        r"\b((?:19|20)\d{2})\.\s+\d+\s*[:(.]\s*\d+",
        r"Vol(?:ume)?\.?\s*\d+.*?((?:19|20)\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 1950 <= year <= 2030:
                return year
    return None


def _extract_journal(text: str) -> str:
    """Extract journal name from header text."""
    patterns = [
        r"(Annu(?:al)?\.?\s+Rev(?:iew)?\.?\s+(?:of\s+)?Fluid\s+Mech(?:anics)?\.?)",
        r"(Annual\s+Review\s+of\s+\w[\w\s]+)",
        r"(Phys(?:ics)?\.?\s+(?:of\s+)?Fluids?)",
        r"(Phys(?:ical)?\.?\s+Rev(?:iew)?\.?\s+\w+)",
        r"(J(?:ournal)?\.?\s+(?:of\s+)?Fluid\s+Mech(?:anics)?\.?)",
        r"(J(?:ournal)?\.?\s+(?:of\s+)?Comput(?:ational)?\.?\s+Phys(?:ics)?\.?)",
        r"(Int(?:ernational)?\.?\s+J(?:ournal)?\.?\s+(?:of\s+)?Multiphase\s+Flow)",
        r"(Comput(?:ers)?\.?\s+(?:and|&)\s+Fluids)",
        r"(Flow,?\s+Turbulence\s+and\s+Combustion)",
        r"(Nature\s+(?:Physics|Materials|Communications|Reviews?\s+\w+))",
        r"(Science\s+(?:Advances|Robotics))",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


# ============================================================================
#  Filename Fallback
# ============================================================================


def _extract_from_filename(filepath: Path) -> PaperMetadata:
    """Fallback: parse metadata from MinerU filename."""
    name = filepath.stem
    meta = PaperMetadata()

    # Standard: MinerU_markdown_{Author}-{Year}-{Title}_{hash}
    m = re.match(r"^MinerU_markdown_(.+?)-(\d{4})-(.+?)_(\d{10,})$", name)
    if m:
        author_part, year_str, title_part, _ = m.groups()
        meta.year = int(year_str)
        # For Chinese names keep as-is; for Western names replace hyphens with spaces
        meta.first_author = (
            author_part.replace("-", " ") if not re.search(r"[\u4e00-\u9fff]", author_part) else author_part
        )
        meta.first_author_lastname = _extract_lastname(meta.first_author)
        meta.title = title_part.replace("_", " ")
        return meta

    # Slug style: MinerU_markdown_slug-slug-2024-title-title_{hash}
    m = re.match(r"^MinerU_markdown_(.+?)_(\d{10,})$", name)
    if m:
        slug = m.group(1)
        year_match = re.search(r"-(\d{4})-", slug)
        if year_match:
            meta.year = int(year_match.group(1))
            before_year = slug[: year_match.start()]
            after_year = slug[year_match.end() :]
            meta.first_author_lastname = before_year.split("-")[0].capitalize()
            meta.first_author = meta.first_author_lastname
            meta.title = after_year.replace("-", " ").replace("_", " ")

    return meta


def _extract_lastname(full_name: str) -> str:
    """Extract last name from a full author name."""
    if not full_name:
        return ""
    name = full_name.strip()

    # Chinese name: first character is surname
    if re.search(r"[\u4e00-\u9fff]", name):
        return name[0]

    parts = name.split()
    if not parts:
        return ""

    # "de Vanna", "van Dyke" — particles
    particles = {"de", "van", "von", "del", "della", "di", "le", "la"}

    # If all parts except last are initials (e.g., "S. Balachandar", "J. K. Eaton")
    if len(parts) >= 2:
        if all(len(p.rstrip(".")) <= 2 for p in parts[:-1]):
            return parts[-1]

    # General: last token is surname, unless preceded by a particle
    if len(parts) >= 3 and parts[-2].lower() in particles:
        return parts[-2].capitalize() + " " + parts[-1]

    return parts[-1]
