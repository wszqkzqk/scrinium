"""
loader.py — 分层内容加载 + TOC 提取（纯规则）
====================================================

L1: title / authors / year / journal / doi  ← JSON 字段
L2: abstract                                ← JSON 字段
L3: conclusion                              ← JSON 字段（由 agent 分析后写入）
L4: full markdown                           ← 读 .md 文件

TOC 提取（enrich_toc）
-----------------------
纯规则提取：regex 提取所有 # 标题 + 行号，过滤 running headers、
期刊名、论文标题重复等噪声，并按编号推断层级（level）。
结果写入 JSON["toc"]：[{"line": N, "level": N, "title": "..."}]
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

_log = logging.getLogger(__name__)

# Strict pattern for language codes — prevents path traversal via lang parameter
_LANG_CODE_RE = re.compile(r"^[a-z]{2,5}$")


def validate_lang(lang: str) -> str:
    """Validate, normalize, and return a safe language code.

    Normalizes to lowercase and strips whitespace before validation,
    so config values like ``"ZH"`` or ``" zh "`` are accepted.

    Raises:
        ValueError: If ``lang`` is not a string, or doesn't match the
            ``[a-z]{2,5}`` pattern (ISO 639-1/3) after normalization.
    """
    if not isinstance(lang, str):
        raise ValueError(f"invalid language code type: {type(lang).__name__} (expected string)")
    lang = lang.lower().strip()
    if not _LANG_CODE_RE.match(lang):
        raise ValueError(f"invalid language code: {lang!r} (expected 2-5 lowercase letters)")
    return lang


# ============================================================================
#  Public load functions (L1–L4)
# ============================================================================


def load_l1(json_path: Path) -> dict:
    """加载 L1 层元数据（标题、作者、年份、期刊、DOI）。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        包含 ``paper_id``, ``title``, ``authors``, ``year``,
        ``journal``, ``doi`` 的字典。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "paper_id": data.get("id") or json_path.parent.name,
        "title": data.get("title") or "",
        "authors": data.get("authors") or [],
        "year": data.get("year"),
        "journal": data.get("journal") or "",
        "doi": data.get("doi") or "",
        "paper_type": data.get("paper_type") or "",
        "citation_count": data.get("citation_count") or {},
        "ids": data.get("ids") or {},
    }


def load_l2(json_path: Path) -> str:
    """加载 L2 层摘要文本。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        摘要文本，无摘要时返回 ``"[No abstract available]"``。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data.get("abstract") or "[No abstract available]"


def load_l3(json_path: Path) -> str | None:
    """加载 L3 层结论文本。

    结论由 agent 阅读全文后写入 ``l3_conclusion`` 字段。

    Args:
        json_path: 论文 JSON 元数据文件路径。

    Returns:
        结论文本，尚未写入时返回 ``None``。
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data.get("l3_conclusion") or None


def load_l4(md_path: Path, *, lang: str | None = None) -> str:
    """加载 L4 层全文 Markdown，可选加载翻译版本。

    当指定 ``lang`` 时，优先加载 ``paper_{lang}.md``（如 ``paper_zh.md``），
    不存在则回退到原文 ``paper.md``。

    Args:
        md_path: MinerU 输出的 ``.md`` 文件路径。
        lang: 目标语言代码（如 ``"zh"``），为 ``None`` 时加载原文。

    Returns:
        完整 Markdown 文本。
    """
    if lang:
        # Normalize + validate lang to prevent path traversal
        try:
            lang = validate_lang(lang)
        except ValueError:
            _log.warning("invalid lang code %r, falling back to original", lang)
            lang = None
        else:
            translated = md_path.parent / f"paper_{lang}.md"
            if translated.exists():
                return translated.read_text(encoding="utf-8", errors="replace")
    return md_path.read_text(encoding="utf-8", errors="replace")


# ============================================================================
#  Agent notes (T2 persistent analysis notes)
# ============================================================================

_NOTES_FILENAME = "notes.md"


def load_notes(paper_dir: Path) -> str | None:
    """加载论文的 agent 分析笔记。

    笔记文件 (``notes.md``) 由 agent 在分析论文时自动创建和追加，
    用于跨会话、跨工作区复用分析结论。

    Args:
        paper_dir: 论文目录路径（包含 ``meta.json`` 的目录）。

    Returns:
        笔记文本，不存在时返回 ``None``。
    """
    notes_path = paper_dir / _NOTES_FILENAME
    if notes_path.exists():
        text = notes_path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return text
    return None


def append_notes(paper_dir: Path, section: str) -> None:
    """向论文笔记文件追加一条分析记录。

    如果 ``notes.md`` 不存在则创建。每条记录之间用空行分隔。

    Args:
        paper_dir: 论文目录路径。
        section: 要追加的笔记内容（Markdown 格式，建议以 ``## 日期 | 来源`` 开头）。
    """
    notes_path = paper_dir / _NOTES_FILENAME
    section = section.rstrip("\n")
    if notes_path.exists():
        # Only add enough newlines to get exactly one blank line separator
        tail = b""
        try:
            with open(notes_path, "rb") as f:
                f.seek(0, 2)
                pos = f.tell()
                n = min(pos, 4)
                f.seek(pos - n)
                tail = f.read(n)
        except OSError:
            pass
        trailing = 0
        for i in range(len(tail) - 1, -1, -1):
            if tail[i : i + 1] == b"\n":
                trailing += 1
            else:
                break
        prefix = "\n" * max(0, 2 - trailing)
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(prefix + section + "\n")
    else:
        notes_path.write_text(section + "\n", encoding="utf-8")
    _log.debug("appended notes to %s", notes_path)


# ============================================================================
#  TOC extraction (rule-based)
# ============================================================================


def enrich_toc(
    json_path: Path,
    md_path: Path,
    *,
    force: bool = False,
) -> bool:
    """纯规则提取论文目录结构，写入 ``JSON["toc"]``。

    从 Markdown 中提取所有 ``#`` 标题，用规则过滤 running headers、
    期刊名、作者名等噪声，并按编号推断层级。

    Args:
        json_path: 论文 JSON 元数据文件路径（结果写回此文件）。
        md_path: 论文 Markdown 文件路径。
        force: 为 ``True`` 时覆盖已有 TOC。

    Returns:
        提取成功返回 ``True``，失败返回 ``False``。
    """
    from scrinium.papers import read_meta, write_meta

    paper_d = json_path.parent
    data = read_meta(paper_d)

    if data.get("toc") and not force:
        _log.debug("existing TOC (%d entries), skipping", len(data["toc"]))
        return True

    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    raw_headers = _extract_headers(lines)

    _log.debug("regex found %d headers", len(raw_headers))

    title = data.get("title", "")
    toc = _toc_from_rules(raw_headers, title)
    if toc:
        _log.debug("rule-based extraction: %d entries", len(toc))

    if not toc:
        _log.error("could not extract TOC (rule-based extraction failed)")
        return False

    _log.debug("final TOC: %d entries", len(toc))
    for entry in toc:
        indent = "  " * (entry.get("level", 1) - 1)
        _log.debug("  line %4d  %s%s", entry["line"], indent, entry["title"])

    data["toc"] = toc
    data["toc_extracted_at"] = datetime.now().isoformat(timespec="seconds")
    write_meta(paper_d, data)
    _log.debug("TOC written to JSON")
    return True


def _extract_headers(lines: list[str]) -> list[dict]:
    """提取所有 # 标题及行号（1-indexed）。"""
    headers = []
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^(#{1,4})\s+(.+)", line.rstrip())
        if m:
            headers.append({"line": i, "level": len(m.group(1)), "text": m.group(2).strip()})
    return headers


# -- regex-based TOC extraction ----------------------------------------------

# Numbered section pattern: "1", "1.2", "1.2.3", with optional trailing dot
# Also matches "1.", "2.1.", "1.2.3." (common in some journals/books)
# Allows number followed by space, CJK char, or dot-then-space
_RE_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?(?:\s|(?=[一-鿿]))")
# "Chapter 1 Title" or Chinese "第一章" / "第1章" pattern
_RE_CHAPTER = re.compile(r"^Chapter\s+(\d+)\b", re.IGNORECASE)
_RE_CHAPTER_ZH = re.compile(r"^第\s*([一二三四五六七八九十百\d]+)\s*章")
# TOC-area entries have trailing page numbers like "Title 123" or "Title . 123"
# Require >= 2 digits to avoid matching "Chapter 1", "Part 2", etc.
_RE_TRAILING_PAGE = re.compile(r"[.\s]\s*\d{2,4}\s*$")
# Well-known structural sections (unnumbered)
_KNOWN_SECTIONS = {
    "abstract",
    "introduction",
    "preface",
    "foreword",
    "conclusion",
    "conclusions",
    "concluding remarks",
    "summary",
    "references",
    "bibliography",
    "index",
    "acknowledgments",
    "acknowledgements",
    "funding",
    "appendix",
    "glossary",
    "nomenclature",
    "notation",
}


def _toc_from_rules(raw_headers: list[dict], title: str) -> list[dict] | None:
    """Try to build TOC purely from rules. Returns list of toc entries or None.

    Strategy:
    1. Detect and skip a TOC area (headers with trailing page numbers).
    2. Filter noise: repeated paper title, author lines, metadata lines.
    3. Infer level from numbering (1 → l1, 1.2 → l2, 1.2.3 → l3).
    4. Keep well-known unnumbered sections as level 1.
    """
    if not raw_headers:
        return None

    # normalised title words for matching
    title_lower = title.lower().strip() if title else ""

    # --- pass 1: skip TOC/front-matter area ---
    # PDF books have a printed table-of-contents with trailing page numbers
    # ("1.2 Title ... 23"), followed by front-matter (preface, notation,
    # etc.) before the real body starts.  We find the last page-number
    # header in the first 10% of lines, then advance past any remaining
    # front-matter until we hit a real body-start marker.
    total_lines = raw_headers[-1]["line"] if raw_headers else 1
    toc_cutoff_line = max(total_lines * 0.10, 500)
    page_indices = [
        idx for idx, h in enumerate(raw_headers) if h["line"] <= toc_cutoff_line and _RE_TRAILING_PAGE.search(h["text"])
    ]
    if len(page_indices) >= 5:
        body_start = page_indices[-1] + 1
    else:
        body_start = 0

    # Advance past remaining front-matter noise until we hit a body-start
    # marker: "Chapter 1", numbered section "1" or "1.1", or known
    # front-matter sections (Preface, Foreword, Introduction, Notation).
    for idx in range(body_start, len(raw_headers)):
        h = raw_headers[idx]
        text = h["text"]
        text_lower = text.lower().strip()
        # "Chapter 1" or "Chapter N" or "第一章"
        if _RE_CHAPTER.match(text) or _RE_CHAPTER_ZH.match(text):
            body_start = idx
            break
        # Numbered section starting from "1" (top-level chapter)
        m = _RE_NUMBERED.match(text)
        if m and m.group(1).split(".")[0] == "1":
            body_start = idx
            break
        # Known front-matter sections that appear before Chapter 1
        if (
            text_lower.split(" to ")[0].strip().rstrip("s")
            in (
                "preface",
                "foreword",
                "notation",
                "symbol",
                "acknowledgment",
                "acknowledgement",
            )
            or text_lower.startswith("preface")
            or text_lower
            in (
                "摘要",
                "前言",
                "序言",
                "绪论",
            )
        ):
            body_start = idx
            break
    body_headers = raw_headers[body_start:]

    if not body_headers:
        body_headers = raw_headers  # fallback: no TOC area detected

    # --- pass 2: detect running headers (appear >= 3 times) ---
    from collections import Counter

    text_counts = Counter(h["text"].lower().strip() for h in body_headers)
    running_headers = {t for t, c in text_counts.items() if c >= 3}

    # --- pass 3: filter noise ---
    toc = []
    for h in body_headers:
        text = h["text"]
        text_lower = text.lower().strip()

        # skip running headers (repeated page headers from PDF)
        if text_lower in running_headers:
            continue

        # skip if it matches the paper/book title
        if title_lower and _similar_title(text_lower, title_lower):
            continue
        # skip common metadata noise
        if text_lower in (
            "contents",
            "table of contents",
            "acronyms",
            "abbreviations",
            "articleinfo",
            "affiliations",
            "目录",
            "插图目录",
            "表格目录",
        ):
            continue

        # --- infer level ---
        m_num = _RE_NUMBERED.match(text)
        m_chap = _RE_CHAPTER.match(text)
        m_chap_zh = _RE_CHAPTER_ZH.match(text)
        if m_chap:
            # "Chapter 3 Title" → level 1, strip "Chapter N" prefix for clean title
            clean = text[m_chap.end() :].strip()
            num = m_chap.group(1)
            final_title = f"{num} {clean}" if clean else f"Chapter {num}"
            toc.append({"line": h["line"], "level": 1, "title": final_title})
        elif m_chap_zh:
            # "第一章 绪论" → level 1, keep original text
            toc.append({"line": h["line"], "level": 1, "title": text})
        elif m_num:
            num_str = m_num.group(1)
            depth = num_str.count(".") + 1  # "1"→1, "1.2"→2, "1.2.3"→3
            level = min(depth, 3)
            # strip trailing page-number-like remnants (shouldn't exist in body, but be safe)
            clean_text = _RE_TRAILING_PAGE.sub("", text).strip().rstrip(".")
            toc.append({"line": h["line"], "level": level, "title": clean_text})
        elif (
            text_lower.split(",")[0].strip() in _KNOWN_SECTIONS
            or any(text_lower.startswith(s) for s in ("appendix",))
            or text
            in (
                "摘要",
                "前言",
                "绪论",
                "结论",
                "总结",
                "参考文献",
                "致谢",
                "附录",
            )
        ):
            toc.append({"line": h["line"], "level": 1, "title": text})
        # else: skip (unnumbered, unknown → likely noise)

    return toc if toc else None


def _similar_title(a: str, b: str) -> bool:
    """Check if two titles are similar enough to be considered duplicates."""
    # simple: one contains the other, or >80% word overlap
    if a == b or a in b or b in a:
        return True
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / max(len(wa), len(wb))
    return overlap > 0.8
