"""Abstract extraction — regex and DOI fetch, plus batch backfill."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

_log = logging.getLogger(__name__)


# ============================================================================
#  Main Entry Point
# ============================================================================


def extract_abstract_from_md(md_path: Path) -> str | None:
    """从 MinerU 解析的 markdown 文件中提取 Abstract 段落（纯正则）。

    规则提取失败时返回 ``None``；调用方应输出 handoff hint，
    由 agent 阅读原文后直接写 ``meta.json`` 的 ``abstract`` 字段。

    Args:
        md_path: MinerU 输出的 ``.md`` 文件路径。

    Returns:
        提取到的 abstract 文本，无法提取时返回 ``None``。
    """
    text = md_path.read_text(encoding="utf-8")
    head = text[:8000]
    return _regex_extract_abstract(head)


# ============================================================================
#  Regex Extraction
# ============================================================================


def _regex_extract_abstract(head: str) -> str | None:
    """Regex-based abstract extraction from markdown header (patterns 1-3)."""
    # --- Pattern 1: heading (# Abstract / # a b s t r a c t / # A B S T R A C T) ---
    m = re.search(
        r"^#{1,3}\s*(?:a\s*b\s*s\s*t\s*r\s*a\s*c\s*t|abstract)\s*$",
        head,
        re.MULTILINE | re.IGNORECASE,
    )
    if m:
        after = head[m.end() :].lstrip("\n")
        end = re.search(r"^#{1,3}\s+\S", after, re.MULTILINE)
        block = after[: end.start()].strip() if end else after.strip()
        # Strip leading "Keywords:" block
        block = re.sub(
            r"^Keywords?\s*:?\s*(?:\n.*?(?=\n\n)|\S[^\n]*)\s*\n\s*\n",
            "",
            block,
            count=1,
            flags=re.DOTALL,
        )
        result = _clean_abstract(block.strip())
        if result:
            return result

    # --- Pattern 2: inline prefix (Abstract. / Abstract: / Abstract + uppercase) ---
    m = re.search(
        r"^Abstract(?:[.:\s—–-]+)([A-Z])",
        head,
        re.MULTILINE,
    )
    if m:
        line_start = head.rfind("\n", 0, m.start()) + 1
        after = head[line_start:]
        end = re.search(r"\n#{1,3}\s+\S", after)
        block = after[: end.start()].strip() if end else after.strip()
        block = re.sub(r"^Abstract[.:\s—–-]+", "", block)
        result = _clean_abstract(block)
        if result:
            return result

    # --- Pattern 3: gap text between author block and first section heading ---
    short_head = head[:4000]
    section_m = re.search(
        r"^#{1,3}\s+(?:\d+[.\s]|Introduction|INTRODUCTION)",
        short_head,
        re.MULTILINE,
    )
    if section_m:
        preamble = short_head[: section_m.start()]
        paragraphs = re.split(r"\n\s*\n", preamble)
        for para in reversed(paragraphs):
            para = para.strip()
            if len(para) < 100:
                continue
            if para.startswith("#") or para.startswith("!["):
                continue
            if re.match(
                r"^(?:Received|Accepted|Available|Keywords?|Key\s*Words?|"
                r"E-mail|Article\s+history|Department|University|"
                r"The research.*(?:support|funded|grant)|"
                r"This page|Academic Press|Edited by|"
                r"\$[a-z])",
                para,
                re.IGNORECASE,
            ):
                continue
            result = _clean_abstract(para)
            if result:
                return result

    return None


def _clean_abstract(text: str) -> str | None:
    """Clean extracted abstract text, return None if too short or invalid."""
    # Remove image tags
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Remove copyright lines
    text = re.sub(r"(?:©|\(c\)|\\circledcirc)\s*\d{4}.*$", "", text, flags=re.MULTILINE)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Sanity check: abstract should be 50-5000 chars
    if len(text) < 50 or len(text) > 5000:
        return None
    return text


# ============================================================================
#  DOI Fetch
# ============================================================================


def fetch_abstract_by_doi(doi: str) -> str | None:
    """通过 DOI 从出版商落地页抓取 abstract。

    先用 ``requests`` 访问 ``https://doi.org/<doi>`` 并跟随重定向，
    从 HTML meta 标签提取 abstract。若遭遇 Cloudflare 403，
    回退到 ``curl_cffi``（模拟浏览器 TLS 指纹）重试。

    Args:
        doi: 论文 DOI，如 ``"10.1017/jfm.2024.1191"``。

    Returns:
        提取到的 abstract 文本，失败时返回 ``None``。
    """
    if not doi or doi == "null":
        return None

    url = f"https://doi.org/{doi}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    html = None
    # Round 1: plain requests (works for Cambridge, Annual Reviews)
    try:
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            html = r.text
    except Exception as e:
        _log.debug("DOI fetch (requests) failed for %s: %s", url, e)

    # Round 2: curl_cffi if 403 or no html (Cloudflare bypass)
    if html is None or "cloudflare" in (html[:2000]).lower():
        try:
            from curl_cffi import requests as cffi_requests

            r = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=15, allow_redirects=True)
            if r.status_code == 200:
                html = r.text
        except Exception as e:
            _log.debug("DOI fetch (curl_cffi) failed for %s: %s", url, e)

    if not html:
        return None

    return _extract_abstract_from_html(html)


def _extract_abstract_from_html(html: str) -> str | None:
    """从出版商 HTML 页面提取 abstract。"""
    # Strategy 1: meta tags (Cambridge, Annual Reviews, ASME, etc.)
    for tag in ("citation_abstract", "dc.description", "og:description", "description"):
        pat = rf'<meta\s+(?:name|property)="{re.escape(tag)}"\s+content="(.*?)"'
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m and len(m.group(1)) > 50:
            return _clean_abstract(m.group(1))

    # Strategy 2: Elsevier/ScienceDirect <div class="abstract ...">
    m = re.search(r'class="abstract[^"]*"[^>]*>(.*?)</div', html, re.IGNORECASE | re.DOTALL)
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if len(text) > 50:
            return _clean_abstract(text)

    return None


# ============================================================================
#  Backfill
# ============================================================================


def backfill_abstracts(papers_dir: Path, *, dry_run: bool = False, doi_fetch: bool = False) -> dict:
    """批量补全或更新论文 abstract（纯正则 + DOI 抓取）。

    扫描 ``papers_dir`` 下所有 JSON：

    - **默认模式**：只处理缺 abstract 的论文，从 ``.md`` 纯正则提取。
    - **``doi_fetch=True``**：对所有有 DOI 的论文尝试从出版商网页抓取官方
      abstract。成功则覆盖现有 abstract（官方源优先）；失败则保留原有值，
      仅对仍无 abstract 的论文 fallback 到 ``.md`` 提取。

    Args:
        papers_dir: 已入库论文目录。
        dry_run: 为 ``True`` 时只预览，不写文件。
        doi_fetch: 为 ``True`` 时启用 DOI 网页抓取（官方源优先）。

    Returns:
        统计字典：``{"filled": N, "skipped": N, "failed": N, "updated": N,
        "failed_dirs": [...]}``。``failed_dirs`` 列出正则未命中的论文目录名，
        供调用方输出 agent 接管 hint。
    """
    from scrinium.papers import iter_paper_dirs

    stats: dict = {"filled": 0, "skipped": 0, "failed": 0, "updated": 0, "failed_dirs": []}

    for pdir in iter_paper_dirs(papers_dir):
        json_path = pdir / "meta.json"
        try:
            from scrinium.papers import read_meta

            data = read_meta(pdir)
        except (ValueError, FileNotFoundError) as e:
            _log.debug("failed to read meta.json in %s: %s", pdir.name, e)
            stats["failed"] += 1
            continue
        existing = (data.get("abstract") or "").strip()
        doi = (data.get("doi") or "").strip()

        # DOI fetch mode: try official source for ALL papers with DOI
        if doi_fetch and doi and doi != "null":
            fetched = fetch_abstract_by_doi(doi)
            if fetched:
                if existing and fetched != existing:
                    stats["updated"] += 1
                    _write_abstract(json_path, data, fetched, dry_run, label="官方覆盖")
                elif not existing:
                    stats["filled"] += 1
                    _write_abstract(json_path, data, fetched, dry_run, label="DOI 抓取")
                else:
                    stats["skipped"] += 1
                continue
            # DOI fetch failed — fall through to .md extraction if needed

        if existing and not doi_fetch:
            stats["skipped"] += 1
            continue

        # Already have abstract (DOI fetch was attempted but failed)
        if existing:
            stats["skipped"] += 1
            continue

        # .md extraction fallback
        md_path = json_path.parent / "paper.md"
        if not md_path.exists():
            stats["skipped"] += 1
            continue

        abstract = extract_abstract_from_md(md_path)

        if not abstract:
            _log.debug("no abstract extracted: %s", json_path.stem)
            stats["failed"] += 1
            stats["failed_dirs"].append(pdir.name)
            continue

        stats["filled"] += 1
        _write_abstract(json_path, data, abstract, dry_run, label=".md 提取")

    return stats


def _write_abstract(json_path: Path, data: dict, abstract: str, dry_run: bool, *, label: str = "") -> None:
    """Write abstract to JSON file (or preview in dry-run mode)."""
    from scrinium.papers import write_meta

    preview = abstract[:80] + ("..." if len(abstract) > 80 else "")
    tag = f"[{label}] " if label else ""
    if dry_run:
        _log.debug("[preview] %s%s %s", tag, json_path.stem, preview)
    else:
        data["abstract"] = abstract
        write_meta(json_path.parent, data)
        _log.debug("%s%s %s", tag, json_path.stem, preview)
