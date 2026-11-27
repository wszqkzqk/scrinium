"""
si.py — Supporting Information (SI) detection, fetching, and attachment
========================================================================

SI is not a standalone library entry; it is an attachment of a parent paper,
stored in the parent paper's ``si/`` subdirectory:

    data/papers/<Author-Year-Title>/
    ├── meta.json        # "si" field records mentioned / files / fetch_status
    ├── paper.md
    └── si/
        ├── <name>.pdf     # Original file (PDF/Office/data files kept as-is)
        ├── <name>.md      # MinerU/fallback conversion result (indexed in FTS)
        └── images/        # SI figure assets (merged; MinerU hash names never collide)

The ``si`` field in meta.json::

    {
      "mentioned": true,               # Main text references SI (written by scan)
      "files": [{"name": ..., "md": "si/<name>.md", "source_url": ...,
                  "attached_by": "pipeline|agent", "attached_at": ...}],
      "fetch_status": "ok|not_found|blocked|mismatch|paywalled|error|exhausted",
      "fetch_note": "...",
      "last_attempt": "..."
    }

Trust model for auto-fetching: **automatic first, hand failures to the model**.
The rule chain only produces candidate URLs; every download must pass verification
(PDF magic + SI keywords + parent title/author match) before it can be attached.
Any failure is recorded in ``fetch_status`` with a handoff hint so an agent can
take over via ``scrinium attach-si`` (sharing the same ingest funnel).
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from scrinium.papers import read_meta, write_meta

if TYPE_CHECKING:
    from scrinium.config import Config

_log = logging.getLogger(__name__)

# ============================================================================
#  Detection
# ============================================================================

#: Filename patterns that look like SI (case-insensitive, matched against stem).
_SI_FILENAME_RE = re.compile(
    r"(?:^|[-_])(si|supp|suppl|supporting|supplementary|supplemental|esi|sm)(?:[-_.\d]|$)"
    r"|^mmc\d+$"
    r"|_si_\d+$"
    r"|suppl(?:ementary)?[-_]",
    re.IGNORECASE,
)

#: SI markers in first-page text.
_SI_TEXT_RE = re.compile(
    r"supporting\s+information|supplementary\s+(?:material|information|data|methods)"
    r"|electronic\s+supplementary\s+(?:information|material)|supplemental\s+material",
    re.IGNORECASE,
)

#: Signals that the main text references SI (used for scan / audit "mentioned" checks).
_SI_MENTION_RE = re.compile(
    r"supporting\s+information|supplementary\s+(?:materials?|information|data|methods|notes?)"
    r"|electronic\s+supplementary|\bESI\b|see\s+the\s+SI\b|(?:figure|fig\.?|table|scheme)\s+S\d+",
    re.IGNORECASE,
)

#: Title pattern for suspected SI ingested as a standalone paper (used by audit).
SUSPECTED_SI_TITLE_RE = re.compile(
    r"^(supporting|supplemental|supplementary|electronic\s+supplementary)\b", re.IGNORECASE
)

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def looks_like_si_filename(name: str) -> bool:
    """Check by filename whether a file looks like SI (``ja9b12345_si_001.pdf``, ``mmc1.pdf``, etc.)."""
    stem = Path(name).stem
    return bool(_SI_FILENAME_RE.search(stem))


def looks_like_si_text(text: str) -> bool:
    """Check by first-page text whether a file looks like SI (prints "Supporting Information", etc.)."""
    return bool(_SI_TEXT_RE.search(text[:3000]))


def si_mentioned_in_text(text: str) -> bool:
    """Check whether the main text references SI (Figure S1 / see the SI / ESI, etc.)."""
    return bool(_SI_MENTION_RE.search(text))


def extract_dois_from_text(text: str) -> list[str]:
    """Extract DOIs from text (lowercased, trailing punctuation stripped, deduplicated in order)."""
    out: list[str] = []
    for m in _DOI_RE.finditer(text):
        doi = m.group(0).rstrip(".,;)]}").lower()
        if doi not in out:
            out.append(doi)
    return out


# ============================================================================
#  Candidate resolvers (DOI → candidate SI URLs)
# ============================================================================


@dataclass
class SiCandidate:
    """A candidate SI download URL.

    Attributes:
        url: Download URL.
        source: Source identifier (``rsc`` / ``science`` / ``plos`` / ``elsevier``
            / ``nature`` / ``acs-figshare`` / ``europepmc``).
        filename: Suggested filename to save as.
        is_zip: Whether the download is a zip archive (Europe PMC supplementaryFiles).
    """

    url: str
    source: str
    filename: str = ""
    is_zip: bool = False


def _resolve_rsc(doi: str, session=None) -> list[SiCandidate]:
    """RSC (10.1039): the suppdata URL can be derived directly from the DOI suffix."""
    pii = doi.split("/", 1)[1].lower()
    return [
        SiCandidate(
            url=f"https://www.rsc.org/suppdata/{pii[:2]}/{pii[2:4]}/{pii}/{pii}1.pdf",
            source="rsc",
            filename=f"{pii}1.pdf",
        ),
        # flat path variant also works for some eras
        SiCandidate(url=f"https://www.rsc.org/suppdata/{pii}/{pii}1.pdf", source="rsc", filename=f"{pii}1.pdf"),
    ]


def _resolve_science(doi: str, session=None) -> list[SiCandidate]:
    """Science/AAAS (10.1126): suppl_file is named ``<suffix>_sm.pdf``."""
    suffix = doi.split("/", 1)[1]
    return [
        SiCandidate(
            url=f"https://www.science.org/doi/suppl/{doi}/suppl_file/{suffix}_sm.pdf",
            source="science",
            filename=f"{suffix}_sm.pdf",
        )
    ]


#: PLOS journal code -> subdomain
_PLOS_SUBDOMAINS = {
    "pone": "plosone",
    "pbio": "plosbiology",
    "pmed": "plosmedicine",
    "pcbi": "ploscompbiol",
    "ppat": "plospathogens",
    "pgen": "plosgenetics",
    "pntd": "plosntds",
}


def _resolve_plos(doi: str, session=None) -> list[SiCandidate]:
    """PLOS (10.1371): SI is registered as ``<doi>.sNNN`` components; probes the first 3."""
    parts = doi.split("/", 1)[1].split(".")
    sub = _PLOS_SUBDOMAINS.get(parts[1]) if len(parts) >= 2 and parts[0] == "journal" else None
    if not sub:
        return []
    return [
        SiCandidate(
            url=f"https://journals.plos.org/{sub}/article/file?type=supplementary&id=info:doi/{doi}.s{i:03d}",
            source="plos",
            filename=f"{parts[-1]}.s{i:03d}.pdf",
        )
        for i in range(1, 4)
    ]


def _resolve_elsevier(doi: str, session=None) -> list[SiCandidate]:
    """Elsevier (10.1016): resolves the PII via Crossref links, then builds ars.els-cdn mmc URLs."""
    try:
        resp = session.get(f"https://api.crossref.org/works/{doi}", timeout=20)
        if resp.status_code != 200:
            return []
        links = (resp.json().get("message") or {}).get("link") or []
    except Exception as exc:
        _log.debug("elsevier resolver crossref failed for %s: %s", doi, exc)
        return []
    pii = ""
    for link in links:
        url = str(link.get("URL") or "")
        m = re.search(r"(?:pii[/:]|1-s2\.0-)([A-Za-z0-9]+)", url, re.IGNORECASE)
        if m:
            pii = m.group(1)
            break
    if not pii:
        return []
    return [
        SiCandidate(
            url=f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-mmc{i}.pdf",
            source="elsevier",
            filename=f"1-s2.0-{pii}-mmc{i}.pdf",
        )
        for i in range(1, 4)
    ]


def _resolve_nature(doi: str, session=None) -> list[SiCandidate]:
    """Nature/Springer (10.1038): scrapes the article page for ESM links (including zip archives)."""
    aid = doi.split("/", 1)[1]
    try:
        resp = session.get(f"https://www.nature.com/articles/{aid}", timeout=25, headers={"Accept": "text/html"})
        if resp.status_code != 200:
            return []
        html = resp.text
    except Exception as exc:
        _log.debug("nature resolver page fetch failed for %s: %s", doi, exc)
        return []
    urls = re.findall(
        r"https://(?:media\.springernature\.com/original/springer-static|static-content\.springer\.com)"
        r"/esm/[^\"'<>\s]+?\.(?:pdf|zip)",
        html,
    )
    out: list[SiCandidate] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            fname = url.rsplit("/", 1)[-1]
            out.append(SiCandidate(url=url, source="nature", filename=fname, is_zip=fname.lower().endswith(".zip")))
    return out


def _resolve_acs_figshare(doi: str, session=None) -> list[SiCandidate]:
    """ACS (10.1021): SI is hosted on Figshare; searches article files by resource_doi."""
    try:
        resp = session.post("https://api.figshare.com/v2/articles/search", json={"resource_doi": doi}, timeout=20)
        if resp.status_code != 200:
            return []
        articles = resp.json() or []
    except Exception as exc:
        _log.debug("acs figshare search failed for %s: %s", doi, exc)
        return []
    out: list[SiCandidate] = []
    for art in articles[:3]:
        try:
            detail = session.get(f"https://api.figshare.com/v2/articles/{art['id']}", timeout=20)
            if detail.status_code != 200:
                continue
            for f in (detail.json() or {}).get("files") or []:
                url = f.get("download_url")
                if url:
                    out.append(SiCandidate(url=url, source="acs-figshare", filename=f.get("name") or ""))
        except Exception as exc:
            _log.debug("acs figshare detail failed: %s", exc)
    return out


def _resolve_europepmc(doi: str, session=None) -> list[SiCandidate]:
    """Europe PMC: looks up the record by DOI and returns the supplementaryFiles zip URL."""
    try:
        resp = session.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f'DOI:"{doi}"', "format": "json", "resultType": "core"},
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        results = ((resp.json() or {}).get("resultList") or {}).get("result") or []
    except Exception as exc:
        _log.debug("europepmc resolver failed for %s: %s", doi, exc)
        return []
    if not results:
        return []
    rec = results[0]
    pmcid = rec.get("pmcid") or ""
    if not pmcid or rec.get("isOpenAccess") != "Y":
        # supplementaryFiles endpoint only serves the OA subset
        return []
    return [
        SiCandidate(
            url=f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles",
            source="europepmc",
            filename="europepmc_supplementary.zip",
            is_zip=True,
        )
    ]


#: DOI prefix -> publisher rule resolver
_PUBLISHER_RESOLVERS = {
    "10.1021": _resolve_acs_figshare,
    "10.1039": _resolve_rsc,
    "10.1126": _resolve_science,
    "10.1371": _resolve_plos,
    "10.1016": _resolve_elsevier,
    "10.1038": _resolve_nature,
}


def resolve_si_candidates(doi: str, *, session=None) -> list[SiCandidate]:
    """Resolution chain: publisher rules + Europe PMC (generic structured source).

    Each resolver is fault-isolated; any failure only reduces the candidate count
    without raising an exception.
    """
    if session is None:
        from scrinium.ingest.metadata._models import SESSION

        session = SESSION
    doi = (doi or "").strip()
    if not doi:
        return []
    resolver = _PUBLISHER_RESOLVERS.get(doi.split("/", 1)[0].lower())
    candidates: list[SiCandidate] = []
    if resolver is not None:
        try:
            candidates.extend(resolver(doi, session))
        except Exception as exc:
            _log.debug("resolver %s failed for %s: %s", resolver.__name__, doi, exc)
    try:
        candidates.extend(_resolve_europepmc(doi, session))
    except Exception as exc:
        _log.debug("europepmc resolver failed for %s: %s", doi, exc)
    return candidates


# ============================================================================
#  Verification
# ============================================================================


def verify_si_text(md_text: str, meta: dict) -> tuple[bool, str]:
    """Verify that converted SI text actually belongs to the parent paper.

    Three checks: contains an SI keyword; parent title word overlap >= 0.3 or
    first-author surname hit. Prefer a false mismatch (handed to the agent)
    over a wrong attachment.
    """
    head = md_text[:4000].lower()
    kw = _SI_TEXT_RE.search(head)
    title_words = set(re.findall(r"[a-z0-9]{4,}", (meta.get("title") or "").lower()))
    head_words = set(re.findall(r"[a-z0-9]{4,}", head))
    overlap = len(title_words & head_words) / max(len(title_words), 1) if title_words else 0.0
    title_hit = overlap >= 0.3
    author = (meta.get("first_author_lastname") or "").lower()
    if not author:
        authors = meta.get("authors") or []
        author = authors[0].split()[-1].lower() if authors else ""
    author_hit = bool(author) and author in head
    if kw and (title_hit or author_hit):
        return True, "ok"
    if not kw:
        return False, "no_si_keyword"
    return False, f"parent_mismatch(title_overlap={overlap:.2f}, author_hit={author_hit})"


def _preflight_verify_pdf(pdf_path: Path, meta: dict) -> tuple[bool, str]:
    """Cheap pre-conversion check: extract first-page text with PyMuPDF and run verify_si_text.

    Allows the file through (``(True, "skipped")``) when PyMuPDF is unavailable
    or extraction fails; verify_si_text after conversion remains the final gate.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return True, "skipped"
    try:
        with fitz.open(str(pdf_path)) as doc:
            text = "\n".join(doc[i].get_text() for i in range(min(2, len(doc))))
    except Exception as exc:
        _log.debug("preflight text extraction failed for %s: %s", pdf_path, exc)
        return True, "skipped"
    if not text.strip():
        return True, "skipped"
    return verify_si_text(text, meta)


# ============================================================================
#  Conversion (PDF -> Markdown), reusing ingest's MinerU/fallback chain
# ============================================================================


def _convert_si_pdf(pdf_path: Path, si_dir: Path, cfg) -> Path | None:
    """Convert an SI PDF to ``si/<stem>.md`` and merge image assets into ``si/images/``.

    Tries in order: local MinerU -> cloud MinerU -> fallback parser chain.
    Returns ``None`` if all fail (the original PDF is still kept). Does not chunk
    long PDFs; fallback parsers (local, no page limit) handle large files.
    """
    from scrinium.ingest.mineru import ConvertOptions, check_server, convert_pdf, convert_pdf_cloud
    from scrinium.ingest.pdf_fallback import convert_pdf_with_fallback, preferred_parser_order

    stem = pdf_path.stem
    md_dest = si_dir / f"{stem}.md"
    ingest_cfg = cfg.ingest

    with tempfile.TemporaryDirectory(prefix="scrinium_si_") as tmp:
        tmp_dir = Path(tmp)
        mineru_opts = ConvertOptions(
            api_url=ingest_cfg.mineru_endpoint,
            output_dir=tmp_dir,
            backend=ingest_cfg.mineru_backend_local,
            cloud_model_version=ingest_cfg.mineru_model_version_cloud,
            lang=ingest_cfg.mineru_lang,
            parse_method=ingest_cfg.mineru_parse_method,
            formula_enable=ingest_cfg.mineru_enable_formula,
            table_enable=ingest_cfg.mineru_enable_table,
            upload_workers=ingest_cfg.mineru_upload_workers,
            upload_retries=ingest_cfg.mineru_upload_retries,
            download_retries=ingest_cfg.mineru_download_retries,
            poll_timeout=ingest_cfg.mineru_poll_timeout,
        )
        result = None
        if check_server(ingest_cfg.mineru_endpoint):
            result = convert_pdf(pdf_path, mineru_opts)
        else:
            api_key = cfg.resolved_mineru_api_key()
            if api_key:
                try:
                    result = convert_pdf_cloud(
                        pdf_path, mineru_opts, api_key=api_key, cloud_url=ingest_cfg.mineru_cloud_url
                    )
                except Exception as exc:
                    _log.debug("cloud MinerU failed for SI %s: %s", pdf_path.name, exc)

        if result is not None and result.success and result.md_path and result.md_path.exists():
            shutil.move(str(result.md_path), str(md_dest))
            # MinerU image filenames are content hashes, so merging multiple
            # SI files into one si/images/ is collision-safe; the md's
            # relative "images/..." references stay valid under si/.
            for cand in (tmp_dir / "images", tmp_dir / f"{stem}_images"):
                if cand.is_dir():
                    images_dst = si_dir / "images"
                    images_dst.mkdir(exist_ok=True)
                    for child in cand.iterdir():
                        if not (images_dst / child.name).exists():
                            shutil.move(str(child), str(images_dst / child.name))
                    break
        else:
            fallback_order = preferred_parser_order(
                getattr(ingest_cfg, "pdf_preferred_parser", "mineru"),
                getattr(ingest_cfg, "pdf_fallback_order", None),
                auto_detect=getattr(ingest_cfg, "pdf_fallback_auto_detect", True),
            )
            ok, parser_name, err = convert_pdf_with_fallback(pdf_path, md_dest, parser_order=fallback_order)
            if not ok:
                _log.debug("SI conversion failed for %s: %s", pdf_path.name, err)
                return None
            _log.debug("SI %s converted via fallback parser %s", pdf_path.name, parser_name)

    return md_dest if md_dest.exists() else None


# ============================================================================
#  Attach — shared ingest funnel (used by both the auto chain and agent takeover)
# ============================================================================

#: Terminal fetch_status values; papers in these states are not retried automatically
TERMINAL_STATUSES = frozenset({"ok", "exhausted", "paywalled"})


def _unique_dest(si_dir: Path, name: str) -> Path:
    """Avoid overwriting an existing name: returns ``a-2.pdf`` when ``a.pdf`` exists."""
    dest = si_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while (si_dir / f"{stem}-{i}{suffix}").exists():
        i += 1
    return si_dir / f"{stem}-{i}{suffix}"


def attach_si(
    paper_d: Path,
    src_path: Path,
    cfg: Config | None = None,
    *,
    md_path: Path | None = None,
    source_url: str = "",
    attached_by: str = "agent",
    convert: bool = True,
    verify: bool = True,
    dry_run: bool = False,
) -> dict:
    """Attach a file as SI to a paper directory (shared ingest funnel).

    Flow: verify (optional) -> copy original into ``si/`` -> convert PDF to
    Markdown (optional) -> update the ``si`` field in meta.json. The caller
    rebuilds the index in batch.

    Verification strategy depends on source trust:

    - ``verify=True`` (strict; default for manual agent attachment): unknown
      source, so require SI keyword + parent title/author match; any failure is
      a mismatch and leaves no files behind.
    - ``verify=False`` (DOI-bound auto chain): the URL is derived from the DOI
      or the file matched by DOI, so provenance already guarantees ownership;
      skips content verification (figure-only SI has no text to verify, so hard
      verification would only cause false rejections). Still records
      ``verify_note`` for spot checks.

    Args:
        paper_d: Paper directory.
        src_path: Original SI file (PDF, Office, or data file).
        cfg: Global configuration (required for conversion; may be ``None`` for copy-only).
        md_path: Already-converted Markdown (reused by inbox routing to skip reconversion).
        source_url: Source URL (for audit traceability).
        attached_by: ``"pipeline"`` | ``"agent"``.
        convert: Convert PDF to Markdown (``--no-convert`` stores only the original).
        verify: Perform strict content verification.
        dry_run: Preview mode without writing any files.

    Returns:
        Result dict ``{"ok": bool, "status": str, "message": str, "record": dict|None}``.
    """
    src_path = Path(src_path)
    result: dict = {"ok": False, "status": "", "message": "", "record": None}
    try:
        meta = read_meta(paper_d)
    except (ValueError, FileNotFoundError) as exc:
        result.update(status="error", message=f"Cannot read meta.json: {exc}")
        return result

    if dry_run:
        result.update(
            ok=True,
            status="dry_run",
            message=f"[dry-run] Would attach {src_path.name} -> {paper_d.name}/si/ (attached_by={attached_by})",
        )
        return result

    # verify first: a mismatch must not leave any files behind
    if verify and md_path is not None and md_path.exists():
        ok, reason = verify_si_text(md_path.read_text(encoding="utf-8", errors="replace"), meta)
        if not ok:
            result.update(status="mismatch", message=f"SI verification failed: {reason}")
            return result
    if verify and md_path is None and src_path.suffix.lower() == ".pdf":
        ok, reason = _preflight_verify_pdf(src_path, meta)
        if not ok:
            result.update(status="mismatch", message=f"SI preflight check failed: {reason}")
            return result

    si_dir = paper_d / "si"
    si_dir.mkdir(exist_ok=True)
    dest_src = _unique_dest(si_dir, src_path.name)
    shutil.copy2(str(src_path), str(dest_src))

    md_dest: Path | None = None
    if md_path is not None and md_path.exists():
        md_dest = _unique_dest(si_dir, f"{dest_src.stem}.md")
        shutil.copy2(str(md_path), str(md_dest))
    elif convert and src_path.suffix.lower() == ".pdf" and cfg is not None:
        md_dest = _convert_si_pdf(dest_src, si_dir, cfg)
        if md_dest is not None and verify:
            ok, reason = verify_si_text(md_dest.read_text(encoding="utf-8", errors="replace"), meta)
            if not ok:
                dest_src.unlink(missing_ok=True)
                md_dest.unlink(missing_ok=True)
                result.update(status="mismatch", message=f"SI verification failed: {reason}")
                return result

    record = {
        "name": dest_src.name,
        "md": f"si/{md_dest.name}" if md_dest else "",
        "source_url": source_url,
        "attached_by": attached_by,
        "attached_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    md_for_note = md_dest or (md_path if md_path and md_path.exists() else None)
    if md_for_note is not None:
        note_text = md_for_note.read_text(encoding="utf-8", errors="replace")
        record["verify_note"] = (
            f"kw={bool(_SI_TEXT_RE.search(note_text[:20000]))},parent={verify_si_text(note_text, meta)[0]}"
        )
    si = meta.get("si") or {}
    files = [f for f in (si.get("files") or []) if isinstance(f, dict)]
    files.append(record)
    si["files"] = files
    si["fetch_status"] = "ok"
    meta["si"] = si
    write_meta(paper_d, meta)

    result.update(ok=True, status="ok", message=f"Attached {dest_src.name} -> {paper_d.name}/si/", record=record)
    return result


# ============================================================================
#  Fetch — automatic retrieval (resolve candidates -> download -> verify -> attach)
# ============================================================================

_DOWNLOAD_TIMEOUT = 30
_MAX_BYTES = 200 * 1024 * 1024  # 200 MB

#: When multiple candidates fail, record the most actionable status first
_STATUS_PRIORITY = ("mismatch", "blocked", "paywalled", "error", "not_found")


def _download(url: str, dest: Path, session) -> str:
    """Download URL to dest. Returns ``"ok"`` | ``"blocked"`` | ``"paywalled"`` | ``"error"``."""
    try:
        with session.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as resp:
            if resp.status_code in (401, 403, 429):
                return "blocked"
            if resp.status_code == 402:
                return "paywalled"
            if resp.status_code == 404:
                return "not_found"
            if resp.status_code != 200:
                return "error"
            total = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        return "error"
                    fh.write(chunk)
    except Exception as exc:
        _log.debug("download failed %s: %s", url, exc)
        return "error"
    return "ok"


def _looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(5) == b"%PDF-"
    except OSError:
        return False


def _set_fetch_status(paper_d: Path, status: str, note: str = "") -> None:
    """Update si.fetch_status / fetch_note / last_attempt in meta.json."""
    try:
        meta = read_meta(paper_d)
    except (ValueError, FileNotFoundError):
        return
    si = meta.get("si") or {}
    si["fetch_status"] = status
    si["fetch_note"] = note
    si["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["si"] = si
    write_meta(paper_d, meta)


#: Filename patterns for suspected SI members inside a zip (Europe PMC zips mix in main figures/PDFs)
_ZIP_SI_NAME_RE = re.compile(
    r"(?:^|[-_.])(s\d{3}|si|supp|sapp|suppl|supporting|supplementary|supplemental|esi|sm|mmc\d*|esm|additional|appendix|sd)(?:[-_.\d]|$)",
    re.IGNORECASE,
)
_ZIP_SKIP_EXT = frozenset({".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".svg", ".bmp"})


def _attach_zip(zip_path: Path, pdir: Path, cfg, cand: SiCandidate, *, convert: bool) -> int:
    """Extract a zip archive and attach its members one by one; returns the number attached.

    Attaches only suspected SI members: PDFs must match the SI filename pattern
    (``s001.pdf``, etc., to avoid attaching the main PDF); data files (xlsx/csv/xyz,
    etc.) are accepted directly; images are skipped. PDFs are converted; other
    files are kept as-is.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/") and not Path(n).name.startswith(".")]
            zf.extractall(zip_path.parent / "extracted", members=names)
    except (zipfile.BadZipFile, OSError) as exc:
        _log.debug("zip extract failed for %s: %s", zip_path, exc)
        return 0
    attached = 0
    for name in names:
        member = zip_path.parent / "extracted" / name
        if not member.exists():
            continue
        ext = member.suffix.lower()
        if ext in _ZIP_SKIP_EXT and not _ZIP_SI_NAME_RE.search(member.stem):
            continue  # article figure junk; SI-named images (s001.tif) are kept
        if ext == ".pdf" and not _ZIP_SI_NAME_RE.search(member.stem):
            continue
        res = attach_si(
            pdir,
            member,
            cfg,
            source_url=cand.url,
            attached_by="pipeline",
            convert=convert and ext == ".pdf",
            verify=False,
        )
        if res["ok"]:
            attached += 1
        else:
            _log.debug("zip member %s not attached: %s", name, res["message"])
    return attached


def fetch_si_for_paper(
    pdir: Path, cfg: Config, *, convert: bool = True, dry_run: bool = False, force: bool = False
) -> str:
    """Run the automatic SI fetch chain for a single paper and return fetch_status.

    Tries each candidate in turn: download -> magic check -> verify -> attach;
    returns ``ok`` as soon as one succeeds. When all fail, records the most
    actionable status per _STATUS_PRIORITY in meta.json.
    """
    try:
        meta = read_meta(pdir)
    except (ValueError, FileNotFoundError) as exc:
        _log.debug("fetch_si skip %s: %s", pdir.name, exc)
        return "error"

    si = meta.get("si") or {}
    if si.get("files") and not force:
        return "skip"
    if si.get("fetch_status") in TERMINAL_STATUSES and not force:
        return "skip"

    doi = (meta.get("doi") or "").strip()
    if not doi:
        if not dry_run:
            _set_fetch_status(pdir, "not_found", "no doi")
        return "not_found"

    candidates = resolve_si_candidates(doi)
    if not candidates:
        if not dry_run:
            _set_fetch_status(pdir, "not_found", "no candidate url")
        return "not_found"

    if dry_run:
        for c in candidates:
            _log.debug("[dry-run] candidate: %s (%s)", c.url, c.source)
        return "dry_run"

    from scrinium.ingest.metadata._models import SESSION

    seen: list[str] = []
    with tempfile.TemporaryDirectory(prefix="scrinium_si_dl_") as tmp:
        tmp_dir = Path(tmp)
        for cand in candidates:
            dest = tmp_dir / (cand.filename or "si_download")
            status = _download(cand.url, dest, SESSION)
            if status != "ok":
                seen.append(status)
                continue
            if cand.is_zip:
                with open(dest, "rb") as fh:
                    is_zip_file = fh.read(4) == b"PK\x03\x04"
                if not is_zip_file:
                    # e.g. Europe PMC returns an XML error for non-OA articles
                    seen.append("not_found")
                    continue
                if _attach_zip(dest, pdir, cfg, cand, convert=convert) > 0:
                    return "ok"
                seen.append("mismatch")
                continue
            if not _looks_like_pdf(dest):
                # 200 but HTML error page — the URL guess was wrong
                seen.append("not_found")
                continue
            res = attach_si(pdir, dest, cfg, source_url=cand.url, attached_by="pipeline", convert=convert, verify=False)
            if res["ok"]:
                return "ok"
            seen.append(res["status"] or "error")

    final = next((s for s in _STATUS_PRIORITY if s in seen), "not_found")
    _set_fetch_status(pdir, final, f"{len(candidates)} candidates tried")
    return final


# ============================================================================
#  Scan / status helpers
# ============================================================================


def paper_si_state(pdir: Path) -> dict:
    """Summarize a paper's SI state (shared by scan/status).

    ``mentioned`` prefers the cached value in meta.json, falling back to a live
    scan of paper.md when absent.
    """
    try:
        meta = read_meta(pdir)
    except (ValueError, FileNotFoundError):
        return {"paper_id": pdir.name, "error": True}
    si = meta.get("si") or {}
    files = [f for f in (si.get("files") or []) if isinstance(f, dict)]
    mentioned = si.get("mentioned")
    md = pdir / "paper.md"
    if mentioned is None and md.exists():
        try:
            mentioned = si_mentioned_in_text(md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            mentioned = False
    return {
        "paper_id": pdir.name,
        "doi": meta.get("doi") or "",
        "mentioned": bool(mentioned),
        "present": bool(files),
        "n_files": len(files),
        "fetch_status": si.get("fetch_status") or ("ok" if files else ""),
        "fetch_note": si.get("fetch_note") or "",
    }
