"""Shared arXiv Atom API helpers used by CLI, ingest, and federated search."""

from __future__ import annotations

import logging
import re
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import defusedxml.ElementTree as ET
import requests
from urllib3.util.retry import Retry

_log = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ARXIV_LIST_RECENT_URL = "https://arxiv.org/list/{category}/recent"
_ARXIV_NEW_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_ARXIV_OLD_ID_RE = re.compile(r"^[a-z\-]+(?:\.[a-z\-]+)?/\d{7}$", re.IGNORECASE)


def _user_agent() -> str:
    try:
        from scrinium import __version__
    except Exception:
        __version__ = "unknown"
    return f"scrinium/{__version__} (https://github.com/wszqkzqk/scrinium)"


_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": _user_agent()})
_retry = requests.adapters.HTTPAdapter(
    max_retries=Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["GET"],
    )
)
_SESSION.mount("https://", _retry)
_SESSION.mount("http://", _retry)


def normalize_arxiv_ref(ref: str) -> str:
    """Normalize an arXiv identifier / URL to a canonical ID without version suffix.

    Args:
        ref: Bare arXiv ID, ``arXiv:<id>``, or ``arxiv.org/abs|pdf/...`` URL.

    Returns:
        Canonical arXiv ID without version suffix, or an empty string if invalid.
    """
    raw = (ref or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered.startswith("arxiv:"):
        raw = raw.split(":", 1)[1].strip()
    elif lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        if path.startswith("abs/"):
            raw = path[len("abs/") :]
        elif path.startswith("pdf/"):
            raw = path[len("pdf/") :]
            if raw.lower().endswith(".pdf"):
                raw = raw[:-4]
        else:
            return ""

    raw = raw.strip().rstrip("/")
    raw = re.sub(r"v\d+$", "", raw, flags=re.IGNORECASE)
    if _ARXIV_NEW_ID_RE.fullmatch(raw) or _ARXIV_OLD_ID_RE.fullmatch(raw):
        return raw
    return ""


def _pdf_filename_for_arxiv_id(arxiv_id: str) -> str:
    """Map a canonical arXiv ID to a flat PDF filename."""
    return arxiv_id.replace("/", "_") + ".pdf"


def _parse_entry(entry: ET.Element) -> dict:
    title_el = entry.find("atom:title", _NS)
    title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""

    summary_el = entry.find("atom:summary", _NS)
    abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""

    year = ""
    pub_el = entry.find("atom:published", _NS)
    if pub_el is not None and pub_el.text:
        year = pub_el.text[:4]

    authors: list[str] = []
    for author_el in entry.findall("atom:author", _NS):
        name_el = author_el.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            authors.append(name_el.text)

    arxiv_id = ""
    id_el = entry.find("atom:id", _NS)
    if id_el is not None and id_el.text:
        arxiv_id = id_el.text.strip().split("/abs/")[-1]

    doi = ""
    doi_el = entry.find("arxiv:doi", _NS)
    if doi_el is not None and doi_el.text:
        doi = doi_el.text.strip()

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "doi": doi,
    }


def _query_arxiv_api(params: dict[str, str | int]) -> list[dict]:
    try:
        resp = _SESSION.get(_ARXIV_API_URL, params=params, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv API 不可用: %s", e)
        return []

    try:
        root = ET.fromstring(resp.text)
    except Exception as e:
        _log.warning("arXiv XML 解析失败: %s", e)
        return []

    return [_parse_entry(entry) for entry in root.findall("atom:entry", _NS)]


def _build_search_query(query: str, category: str) -> str:
    parts: list[str] = []
    query = (query or "").strip()
    category = (category or "").strip()
    if query:
        parts.append(f"all:{query}")
    if category:
        parts.append(f"cat:{category}")
    return " AND ".join(parts)


def _guess_year_from_arxiv_id(arxiv_id: str) -> str:
    if _ARXIV_NEW_ID_RE.fullmatch(arxiv_id or ""):
        return f"20{arxiv_id[:2]}"
    return ""


def _load_beautiful_soup():
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as e:
        _log.warning("缺少 beautifulsoup4，无法解析 arXiv recent 页面: %s", e)
        return None
    return BeautifulSoup


def _search_arxiv_recent_page(query: str, category: str, top_k: int) -> list[dict]:
    if not category:
        return []
    try:
        resp = _SESSION.get(_ARXIV_LIST_RECENT_URL.format(category=category), timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv recent 页面不可用: %s", e)
        return []

    beautiful_soup = _load_beautiful_soup()
    if beautiful_soup is None:
        return []

    soup = beautiful_soup(resp.text, "html.parser")
    items: list[dict] = []
    for dt, dd in zip(soup.find_all("dt"), soup.find_all("dd"), strict=False):
        id_link = dt.find("a", href=re.compile(r"^/abs/"))
        if not id_link:
            continue
        arxiv_id = normalize_arxiv_ref(id_link.get_text(" ", strip=True))
        if not arxiv_id:
            href = id_link.get("href", "")
            arxiv_id = normalize_arxiv_ref(f"https://arxiv.org{href}")
        if not arxiv_id:
            continue

        title_div = dd.find("div", class_="list-title")
        authors_div = dd.find("div", class_="list-authors")
        if not title_div:
            continue
        title = title_div.get_text(" ", strip=True).replace("Title:", "", 1).strip()
        authors = [a.get_text(" ", strip=True) for a in authors_div.find_all("a")] if authors_div else []

        haystack = " ".join([title, *authors]).lower()
        if query and query.lower() not in haystack:
            continue

        items.append(
            {
                "title": title,
                "authors": authors,
                "year": _guess_year_from_arxiv_id(arxiv_id),
                "abstract": "",
                "arxiv_id": arxiv_id,
                "doi": "",
            }
        )
        if len(items) >= top_k:
            break
    return items


def _fetch_arxiv_abs_page(arxiv_id: str) -> dict:
    """Fetch metadata from the official arXiv abstract page as a fallback."""
    url = f"https://arxiv.org/abs/{arxiv_id}"
    try:
        resp = _SESSION.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv abs 页面不可用: %s", e)
        return {}

    html = resp.text
    meta_pairs = re.findall(r'<meta\s+name="([^"]+)"\s+content="([^"]*)"', html, flags=re.IGNORECASE)
    if not meta_pairs:
        return {}

    meta_map: dict[str, list[str]] = {}
    for name, content in meta_pairs:
        meta_map.setdefault(name.lower(), []).append(unescape(content).strip())

    title = (meta_map.get("citation_title") or [""])[0]
    authors = [a for a in meta_map.get("citation_author", []) if a]
    date = (meta_map.get("citation_date") or [""])[0]
    abstract = (meta_map.get("citation_abstract") or [""])[0]
    page_arxiv_id = (meta_map.get("citation_arxiv_id") or [""])[0]
    doi = (meta_map.get("citation_doi") or [""])[0]

    if not any([title, authors, date, abstract, page_arxiv_id, doi]):
        return {}

    year = ""
    if date:
        year = date[:4]

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "arxiv_id": page_arxiv_id or arxiv_id,
        "doi": doi,
    }


def get_arxiv_paper(arxiv_ref: str) -> dict:
    """Fetch authoritative metadata for a single arXiv paper via the Atom API.

    Args:
        arxiv_ref: arXiv ID or URL.

    Returns:
        Simplified paper dict with keys ``title``, ``authors``, ``year``,
        ``abstract``, ``arxiv_id``, ``doi``. Returns an empty dict on failure.
    """
    canonical_id = normalize_arxiv_ref(arxiv_ref)
    if not canonical_id:
        return {}
    results = _query_arxiv_api({"id_list": canonical_id})
    if results:
        return results[0]
    return _fetch_arxiv_abs_page(canonical_id)


def search_arxiv(query: str = "", top_k: int = 10, *, category: str = "", sort: str = "relevance") -> list[dict]:
    """Query the arXiv Atom API and return a list of simplified paper dicts.

    Args:
        query: Free-text search query.
        top_k: Maximum number of results to return.
        category: Optional arXiv category, e.g. ``physics.flu-dyn``.
        sort: ``"relevance"`` or ``"recent"``.

    Returns:
        List of dicts with keys: title, authors, year, abstract, arxiv_id, doi.
        Returns an empty list on network failure or XML parse error.
    """
    search_query = _build_search_query(query, category)
    if not search_query:
        return []
    sort_by = "submittedDate" if sort == "recent" else "relevance"
    params: dict[str, str | int] = {"search_query": search_query, "max_results": top_k, "sortBy": sort_by}
    results = _query_arxiv_api(params)
    if results or sort != "recent":
        return results
    return _search_arxiv_recent_page(query, category, top_k)


def download_arxiv_pdf(arxiv_ref: str, dest_dir: str | Path, *, overwrite: bool = False) -> Path:
    """Download an arXiv PDF to *dest_dir* and return the local file path."""
    canonical_id = normalize_arxiv_ref(arxiv_ref)
    if not canonical_id:
        raise ValueError(f"无效的 arXiv 标识: {arxiv_ref}")

    dest_root = Path(dest_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    out_path = dest_root / _pdf_filename_for_arxiv_id(canonical_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在: {out_path}")
    tmp_path = out_path.with_name(out_path.name + ".part")
    tmp_path.unlink(missing_ok=True)

    url = f"https://arxiv.org/pdf/{canonical_id}.pdf"
    resp = _SESSION.get(url, timeout=30, stream=True)
    resp.raise_for_status()
    try:
        with tmp_path.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
        tmp_path.replace(out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return out_path
