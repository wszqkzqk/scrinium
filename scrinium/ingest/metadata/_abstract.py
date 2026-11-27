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
    """Extract the Abstract section from MinerU-parsed markdown (regex only).

    Returns ``None`` when rule-based extraction fails; the caller should emit
    a handoff hint so an agent can read the original text and write the
    ``abstract`` field in ``meta.json`` directly.

    Args:
        md_path: Path to the ``.md`` file produced by MinerU.

    Returns:
        Extracted abstract text, or ``None`` if extraction fails.
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
    """Fetch the abstract from the publisher landing page via DOI.

    First requests ``https://doi.org/<doi>`` with ``requests`` (following
    redirects) and extracts the abstract from HTML meta tags. If Cloudflare
    returns 403, retries with ``curl_cffi`` (browser TLS fingerprint).

    Args:
        doi: Paper DOI, e.g. ``"10.1017/jfm.2024.1191"``.

    Returns:
        Extracted abstract text, or ``None`` on failure.
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
    """Extract the abstract from a publisher HTML page."""
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
    """Backfill or update paper abstracts in batch (regex + DOI fetch).

    Scans all JSON files under ``papers_dir``:

    - **Default mode**: only processes papers missing an abstract, extracting
      it from ``.md`` via regex.
    - **``doi_fetch=True``**: tries to fetch the official abstract from the
      publisher page for every paper with a DOI. On success, overwrites any
      existing abstract (official source wins); on failure, keeps the existing
      value and falls back to ``.md`` extraction only if still missing.

    Args:
        papers_dir: Directory of ingested papers.
        dry_run: Preview only without writing files when ``True``.
        doi_fetch: Enable DOI web fetching (official source preferred) when ``True``.

    Returns:
        Stats dict ``{"filled": N, "skipped": N, "failed": N, "updated": N,
        "failed_dirs": [...]}``. ``failed_dirs`` lists paper directory names
        where regex found no abstract, so the caller can emit an agent hint.
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
                    _write_abstract(json_path, data, fetched, dry_run, label="official override")
                elif not existing:
                    stats["filled"] += 1
                    _write_abstract(json_path, data, fetched, dry_run, label="DOI fetch")
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
        _write_abstract(json_path, data, abstract, dry_run, label=".md extraction")

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
