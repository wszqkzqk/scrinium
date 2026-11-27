"""
audit.py — Data quality audit for ingested papers
=================================================

Scan all papers in data/papers/ for metadata completeness, data quality,
and content consistency issues, and return a structured issue report.

Rule-based checks (no LLM required):
  - Missing critical fields (doi, abstract, year, authors, journal)
  - File pairing (meta.json / paper.md present in each paper directory)
  - Directory naming compliance (Author-Year-Title format)
  - Duplicate DOI detection
  - arXiv DOI / arxiv_id pairing (missing arxiv_id breaks preprint dedup)
  - Overly short paper.md (possible conversion failure)
  - Mismatch between JSON title and first Markdown H1
  - Missing curated tags (untagged, reported for all paper_types)
  - SI checks (suspected standalone SI entries; SI cited in text but unattached)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from scrinium.papers import iter_paper_dirs

_log = logging.getLogger(__name__)


@dataclass
class Issue:
    """A single audit issue.

    Attributes:
        paper_id: Paper ID (directory name).
        severity: Severity level: ``"error"`` | ``"warning"`` | ``"info"``.
        rule: Audit rule name.
        message: Human-readable description of the issue.
    """

    paper_id: str
    severity: str  # "error" | "warning" | "info"
    rule: str
    message: str


def audit_papers(papers_dir: Path) -> list[Issue]:
    """Run a full data quality audit over a papers directory.

    Args:
        papers_dir: Ingested papers directory (one subdirectory per paper).

    Returns:
        Issues sorted by severity (errors first).
    """
    issues: list[Issue] = []

    # DOI duplicate detection
    doi_map: dict[str, list[str]] = {}

    for pdir in iter_paper_dirs(papers_dir):
        pid = pdir.name
        meta_file = pdir / "meta.json"
        md_file = pdir / "paper.md"

        try:
            from scrinium.papers import read_meta

            data = read_meta(pdir)
        except Exception as e:
            issues.append(Issue(pid, "error", "invalid_json", f"Failed to parse JSON: {e}"))
            continue

        # -- Missing fields --
        _check_missing(issues, pid, data)

        # -- File pairing --
        if not md_file.exists():
            issues.append(Issue(pid, "error", "missing_md", "Missing paper.md file"))
        else:
            try:
                md_text = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                _log.debug("failed to read paper.md for %s: %s", pid, e)
                issues.append(Issue(pid, "error", "unreadable_md", "Unable to read paper.md file"))
                md_text = None
            if md_text is not None:
                _check_content_consistency(issues, pid, data, md_text)
                _check_si(issues, pid, data, md_text)

        # -- Directory name format --
        _check_filename(issues, pid, data)

        # -- DOI tracking --
        doi = (data.get("doi") or "").strip().lower()
        if doi:
            doi_map.setdefault(doi, []).append(pid)

        # -- arXiv id backfill check (preprint dedup relies on it) --
        if "10.48550/arxiv." in doi and not (data.get("arxiv_id") or (data.get("ids") or {}).get("arxiv")):
            issues.append(
                Issue(
                    pid,
                    "warning",
                    "arxiv_id_missing",
                    "Has arXiv DOI but missing arxiv_id; preprint dedup will miss it",
                )
            )

    # DOI duplicates
    for doi, pids in doi_map.items():
        if len(pids) > 1:
            for pid in pids:
                others = [p for p in pids if p != pid]
                issues.append(
                    Issue(pid, "error", "duplicate_doi", f"Duplicate DOI: {doi} (also in: {', '.join(others)})")
                )

    # Sort: error > warning > info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.paper_id))
    return issues


def _check_missing(issues: list[Issue], pid: str, data: dict) -> None:
    """Check for missing critical fields."""
    from scrinium.ingest.metadata._models import DOCUMENT_TYPES

    paper_type = data.get("paper_type", "")
    if not data.get("doi") and paper_type not in DOCUMENT_TYPES:
        issues.append(Issue(pid, "warning", "missing_doi", "Missing DOI"))
    if not data.get("abstract"):
        issues.append(Issue(pid, "warning", "missing_abstract", "Missing abstract"))
    if not data.get("year"):
        issues.append(Issue(pid, "warning", "missing_year", "Missing year"))
    if not data.get("authors"):
        issues.append(Issue(pid, "warning", "missing_authors", "Missing authors"))
    if not data.get("journal"):
        issues.append(Issue(pid, "warning", "missing_journal", "Missing journal name"))
    if not data.get("title"):
        issues.append(Issue(pid, "error", "missing_title", "Missing title"))
    if not data.get("tags"):
        issues.append(Issue(pid, "info", "untagged", "No curated tags"))


def _check_content_consistency(
    issues: list[Issue],
    pid: str,
    data: dict,
    md_text: str,
) -> None:
    """Check consistency between JSON metadata and MD content."""
    # MD too short (likely conversion failure)
    if len(md_text.strip()) < 200:
        issues.append(
            Issue(
                pid,
                "warning",
                "short_md",
                f"paper.md is too short ({len(md_text.strip())} chars); conversion may have failed",
            )
        )

    # Title vs first H1 mismatch
    json_title = (data.get("title") or "").strip().lower()
    if json_title:
        h1_match = re.search(r"^#\s+(.+)", md_text, re.MULTILINE)
        if h1_match:
            md_title = h1_match.group(1).strip().lower()
            # Fuzzy: check if they share significant words
            json_words = set(re.findall(r"\w{4,}", json_title))
            md_words = set(re.findall(r"\w{4,}", md_title))
            if json_words and md_words:
                overlap = len(json_words & md_words) / max(len(json_words), 1)
                if overlap < 0.3:
                    issues.append(
                        Issue(
                            pid,
                            "warning",
                            "title_mismatch",
                            f"JSON title does not match Markdown H1\n"
                            f"  JSON: {data['title'][:80]}\n"
                            f"  MD H1: {h1_match.group(1).strip()[:80]}",
                        )
                    )


def _check_si(issues: list[Issue], pid: str, data: dict, md_text: str) -> None:
    """Check for standalone SI entries and unattached SI cited in the text."""
    from scrinium.si import SUSPECTED_SI_TITLE_RE, TERMINAL_STATUSES, si_mentioned_in_text

    title = (data.get("title") or "").strip()
    if SUSPECTED_SI_TITLE_RE.match(title):
        issues.append(
            Issue(
                pid,
                "warning",
                "suspected_si",
                "Title looks like Supporting Information; should be attached to the main paper's si/ rather than ingested standalone",
            )
        )
        return  # Do not also report missing_si for a suspected SI entry
    si = data.get("si") or {}
    if si.get("files") or si.get("fetch_status") in TERMINAL_STATUSES:
        return
    if si_mentioned_in_text(md_text):
        issues.append(Issue(pid, "info", "missing_si", "Text mentions SI but none is attached (si/ is empty)"))


def _check_filename(issues: list[Issue], pid: str, data: dict) -> None:
    """Check directory name format compliance."""
    # Expected: Author-Year-Title
    m = re.match(r"^(.+?)-(\d{4})-(.+)$", pid)
    if not m:
        issues.append(
            Issue(pid, "info", "nonstandard_filename", "Directory name does not follow Author-Year-Title format")
        )
        return

    file_year = int(m.group(2))
    json_year = data.get("year")
    if json_year and file_year != json_year:
        issues.append(
            Issue(
                pid,
                "warning",
                "filename_year_mismatch",
                f"Directory year ({file_year}) does not match JSON year ({json_year})",
            )
        )


def format_report(issues: list[Issue]) -> str:
    """Format audit results as a readable report.

    Each issue includes a repair suggestion (handoff hint) pointing to the
    agent repair workflow: the framework only diagnoses; an agent/subagent
    verifies against the original text and edits meta.json directly.

    Args:
        issues: Issue list returned by :func:`audit_papers`.

    Returns:
        Formatted text report.
    """
    if not issues:
        return "Audit passed: no issues found."

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    lines = [f"Audit complete: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info(s)\n"]

    if errors:
        lines.append("=" * 60)
        lines.append("Errors (require fixes)")
        lines.append("=" * 60)
        for i in errors:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")
            hint = _RULE_HINTS.get(i.rule)
            if hint:
                lines.append(f"    hint: {hint}")

    if warnings:
        lines.append("")
        lines.append("-" * 60)
        lines.append("Warnings (review recommended)")
        lines.append("-" * 60)
        for i in warnings:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")
            hint = _RULE_HINTS.get(i.rule)
            if hint:
                lines.append(f"    hint: {hint}")

    if infos:
        lines.append("")
        lines.append("· " * 30)
        lines.append("Info (for reference)")
        lines.append("· " * 30)
        for i in infos:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")
            hint = _RULE_HINTS.get(i.rule)
            if hint:
                lines.append(f"    hint: {hint}")

    lines.append("")
    lines.append(
        "hint: Dispatch a subagent to verify against the original text and edit meta.json directly "
        "(audit repair workflow); run scrinium repair / scrinium rename if needed"
    )
    return "\n".join(lines)


# Recommended fix per audit rule (handoff hints for agents)
_RULE_HINTS = {
    "invalid_json": "Dispatch a subagent to check the meta.json syntax and fix it directly",
    "missing_md": "Dispatch a subagent to locate the source PDF and run scrinium attach-pdf to regenerate paper.md",
    "missing_title": "Dispatch a subagent to read the paper, confirm the title, and write meta.json title (or run scrinium repair)",
    "missing_doi": "Dispatch a subagent to find the DOI in the paper, write meta.json doi, and run scrinium refresh",
    "missing_abstract": "Run scrinium enrich abstract; if still missing, have the agent read the paper and write meta.json abstract",
    "missing_year": "Dispatch a subagent to confirm the publication year from the paper and write meta.json year",
    "missing_authors": "Dispatch a subagent to confirm the authors from the paper and write meta.json authors",
    "missing_journal": "Run scrinium refresh to backfill the journal, or have the agent write meta.json journal directly",
    "duplicate_doi": "Dispatch a subagent to compare the duplicate entries and keep one, removing the redundant directory",
    "title_mismatch": "Dispatch a subagent to verify the correct title against the paper and write meta.json title",
    "short_md": "Check whether PDF conversion failed; re-convert or run scrinium attach-pdf if needed",
    "unreadable_md": "Check paper.md file encoding and permissions",
    "nonstandard_filename": "Run scrinium rename to normalize the directory name",
    "filename_year_mismatch": "Confirm the correct year, write meta.json year, and run scrinium rename",
    "arxiv_id_missing": "Derive arxiv_id from the arXiv DOI and write meta.json ids.arxiv (e.g. 10.48550/arxiv.2510.16510 → 2510.16510); no paper reading needed",
    "untagged": "Run the curate workflow or scrinium tag to add curated tags",
    "suspected_si": "Dispatch a subagent to locate the main paper, migrate this entry into its si/ via scrinium attach-si, and delete the standalone entry",
    "missing_si": "Run scrinium si fetch <paper-id>; if it fails, dispatch a subagent to find the SI manually and attach it via scrinium attach-si",
}
