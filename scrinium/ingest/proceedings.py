"""Proceedings detection and writeout helpers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from scrinium.index import build_proceedings_index
from scrinium.ingest.metadata import _clean_title_for_filename, _sanitize_for_filename
from scrinium.papers import generate_uuid

_DOI_RE = re.compile(r"10\.\d{4,}/[^\s)]+", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_TOP_LEVEL_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_CONTENTS_HEADING_RE = re.compile(r"^#\s+(?:table of contents|contents)\s*$", re.MULTILINE | re.IGNORECASE)


def _slugify(text: str) -> str:
    cleaned = _clean_title_for_filename(text)
    return _sanitize_for_filename(cleaned, max_bytes=80) or "untitled"


def _normalize_title_key(text: str) -> str:
    lowered = text.casefold()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _normalize_title_match_key(text: str) -> str:
    lowered = text.casefold()
    lowered = re.sub(r"[^\w\u4e00-\u9fff]+", "", lowered, flags=re.UNICODE)
    return lowered


def _extract_volume_title(text: str, fallback: str) -> str:
    for match in _TOP_LEVEL_HEADING_RE.finditer(text):
        heading = match.group(1).strip()
        if "proceedings of" in heading.lower():
            return heading
    for match in _TOP_LEVEL_HEADING_RE.finditer(text):
        heading = match.group(1).strip()
        if heading and not heading.lower().endswith("editors"):
            return heading
    return fallback


def _extract_authors_and_abstract(chunk: str, title: str) -> tuple[list[str], str]:
    body = chunk.strip()
    lines = [line.strip() for line in body.splitlines()]
    if lines and lines[0].startswith("#"):
        first_heading = lines[0].lstrip("#").strip()
        if _normalize_title_match_key(first_heading.rstrip(".?")) == _normalize_title_match_key(title.rstrip(".?")):
            lines = lines[1:]

    author_lines: list[str] = []
    abstract_lines: list[str] = []
    section = "authors"
    for line in lines:
        if not line:
            if section == "abstract" and abstract_lines:
                break
            if section == "authors" and author_lines:
                section = "affiliations"
            continue
        normalized_line = line.lstrip("#").strip()
        if normalized_line.lower().startswith("abstract"):
            section = "abstract"
            abstract_lines.append(re.sub(r"^Abstract\.?\s*", "", normalized_line, flags=re.IGNORECASE).strip())
            continue
        if line.startswith("#"):
            break
        if section == "authors" and line.casefold().startswith("comment"):
            continue
        if section == "abstract":
            if line.lower().startswith("keywords"):
                continue
            abstract_lines.append(line)
        elif section == "authors":
            author_lines.append(line)
        else:
            continue

    authors = [line for line in author_lines[:5] if line]
    abstract = "\n".join(line for line in abstract_lines if line).strip()
    return authors, abstract


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _extract_heading_outline(text: str) -> list[dict]:
    headings: list[dict] = []
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        heading_text = match.group(2).strip()
        window = [candidate.strip() for candidate in lines[line_no : min(len(lines), line_no + 6)] if candidate.strip()]
        headings.append(
            {
                "level": level,
                "line": line_no,
                "text": heading_text,
                "normalized_text": _normalize_title_key(heading_text),
                "window": window,
            }
        )
    return headings


def _extract_contents_titles(text: str) -> list[str]:
    contents_heading = _CONTENTS_HEADING_RE.search(text)
    if not contents_heading:
        return []

    first_paper_heading = re.search(r"^#\s+[^\n]+\n\n[^\n]+\n\nAbstract\.", text, flags=re.MULTILINE)
    end = first_paper_heading.start() if first_paper_heading else len(text)
    contents_block = text[contents_heading.end() : end]
    entries = [entry.strip().replace("\n", " ") for entry in re.split(r"\n\s*\n", contents_block) if entry.strip()]

    titles: list[str] = []
    for entry in entries:
        if entry.lower().startswith("author index"):
            continue
        cleaned = re.sub(r"\s+", " ", entry)
        cleaned = re.sub(r"\s+\d+\s+[A-Z].*$", "", cleaned).strip(" .")
        if cleaned:
            titles.append(cleaned)
    return titles


def _extract_contents_excerpt(text: str) -> str:
    contents_heading = _CONTENTS_HEADING_RE.search(text)
    if not contents_heading:
        return ""

    lines = text[contents_heading.end() :].splitlines()
    excerpt: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        if stripped.startswith("# ") and excerpt:
            break
        excerpt.append(stripped)
        if len(excerpt) >= 80:
            break
    return "\n".join(excerpt).strip()


def _build_split_candidates(text: str) -> dict:
    fallback_title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.strip()), "untitled")
    contents_titles = _extract_contents_titles(text)
    return {
        "volume_title_hint": _extract_volume_title(text, fallback_title),
        "contents_excerpt": _extract_contents_excerpt(text),
        "contents_titles": contents_titles,
        "normalized_contents_titles": [_normalize_title_key(title) for title in contents_titles],
        "headings": _extract_heading_outline(text),
    }


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    return "\n".join(lines[start_idx:end_idx]).strip()


def _papers_from_split_plan(text: str, plan: dict) -> list[dict]:
    lines = text.splitlines()
    papers: list[dict] = []
    for paper in plan.get("papers", []):
        title = paper["title"]
        chunk = _slice_lines(lines, int(paper["start_line"]), int(paper["end_line"]))
        if not chunk:
            continue
        if not chunk.lstrip().startswith("#"):
            chunk = f"# {title}\n\n{chunk}".strip()
        authors, abstract = _extract_authors_and_abstract(chunk, title)
        doi_match = _DOI_RE.search(chunk)
        papers.append(
            {
                "title": title,
                "authors": authors,
                "doi": doi_match.group(0) if doi_match else "",
                "abstract": abstract,
                "paper_type": "conference-paper",
                "markdown": chunk,
            }
        )
    return papers


def _paper_headings(markdown: str) -> list[str]:
    return [match.group(2).strip() for match in _HEADING_RE.finditer(markdown)]


def _paper_opening_lines(markdown: str, n: int = 8) -> list[str]:
    return [line.strip() for line in markdown.splitlines() if line.strip()][:n]


def _paper_closing_lines(markdown: str, n: int = 6) -> list[str]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    return lines[-n:]


def _remove_bogus_heading_lines(markdown: str, remove_headings: list[str]) -> str:
    if not remove_headings:
        return markdown

    targets = {_normalize_title_match_key(text) for text in remove_headings if str(text).strip()}
    if not targets:
        return markdown

    cleaned_lines: list[str] = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            heading = line.lstrip("#").strip()
            if _normalize_title_match_key(heading) in targets:
                continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def _candidate_signals(title: str, markdown: str, meta: dict) -> list[str]:
    lowered_title = title.casefold()
    opening = _paper_opening_lines(markdown, n=12)
    signals: list[str] = []
    if not meta.get("authors"):
        signals.append("missing_authors")
    if not meta.get("abstract"):
        signals.append("missing_abstract")
    if not meta.get("doi"):
        signals.append("missing_doi")
    if lowered_title.startswith("discussion of"):
        signals.append("discussion_title")
    if any(line.casefold().startswith("comment") for line in opening[1:4]):
        signals.append("comment_label")
    if any("reporter" in line.casefold() for line in opening[:5]):
        signals.append("reporter_line")
    if any(re.match(r"^\d+[\.\)]", line) for line in opening[:3]):
        signals.append("starts_with_numbered_section")
    return signals


def build_proceedings_clean_candidates(proceeding_dir: Path) -> Path:
    papers_dir = proceeding_dir / "papers"
    if not papers_dir.exists():
        raise FileNotFoundError(f"papers directory not found: {papers_dir}")

    meta_path = proceeding_dir / "meta.json"
    proceeding_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    candidates: list[dict] = []
    for paper_dir in sorted(path for path in papers_dir.iterdir() if path.is_dir()):
        paper_meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))
        markdown = (paper_dir / "paper.md").read_text(encoding="utf-8", errors="replace")
        candidates.append(
            {
                "paper_dir": paper_dir.name,
                "title": paper_meta.get("title", paper_dir.name),
                "normalized_title": _normalize_title_key(paper_meta.get("title", paper_dir.name)),
                "paper_type": paper_meta.get("paper_type", "conference-paper"),
                "authors": paper_meta.get("authors", []),
                "abstract_present": bool((paper_meta.get("abstract") or "").strip()),
                "doi_present": bool((paper_meta.get("doi") or "").strip()),
                "signals": _candidate_signals(paper_meta.get("title", paper_dir.name), markdown, paper_meta),
                "opening_lines": _paper_opening_lines(markdown),
                "closing_lines": _paper_closing_lines(markdown),
                "headings": _paper_headings(markdown)[:12],
            }
        )

    payload = {
        "volume_title": proceeding_meta.get("title", proceeding_dir.name),
        "proceeding_dir": proceeding_dir.name,
        "paper_count": len(candidates),
        "papers": candidates,
    }
    out_path = proceeding_dir / "clean_candidates.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _match_clean_entry(candidates: dict[str, Path], entry: dict) -> Path | None:
    raw = str(entry.get("paper", "")).strip()
    key = _normalize_title_key(raw)
    match_key = _normalize_title_match_key(raw)
    if not key:
        return None
    return candidates.get(key) or candidates.get(match_key)


def apply_proceedings_clean_plan(proceeding_dir: Path, clean_plan: dict | Path) -> Path:
    if isinstance(clean_plan, Path):
        plan = _parse_json(clean_plan.read_text(encoding="utf-8"))
    else:
        plan = clean_plan

    papers_dir = proceeding_dir / "papers"
    if not papers_dir.exists():
        raise FileNotFoundError(f"papers directory not found: {papers_dir}")

    candidate_map: dict[str, Path] = {}
    for paper_dir in sorted(path for path in papers_dir.iterdir() if path.is_dir()):
        paper_meta = json.loads((paper_dir / "meta.json").read_text(encoding="utf-8"))
        candidate_map[_normalize_title_key(paper_meta.get("title", paper_dir.name))] = paper_dir
        candidate_map[_normalize_title_match_key(paper_meta.get("title", paper_dir.name))] = paper_dir
        candidate_map[_normalize_title_key(paper_dir.name)] = paper_dir
        candidate_map[_normalize_title_match_key(paper_dir.name)] = paper_dir

    for entry in plan.get("papers", []):
        paper_dir = _match_clean_entry(candidate_map, entry)
        if paper_dir is None or not paper_dir.exists():
            continue

        action = str(entry.get("action", "keep")).strip().lower()
        if action == "drop":
            shutil.rmtree(paper_dir)
            continue

        meta_path = paper_dir / "meta.json"
        paper_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        paper_md_path = paper_dir / "paper.md"
        paper_md = paper_md_path.read_text(encoding="utf-8", errors="replace")
        if entry.get("title"):
            paper_meta["title"] = str(entry["title"]).strip()
        if entry.get("paper_type"):
            paper_meta["paper_type"] = str(entry["paper_type"]).strip()
        meta_path.write_text(json.dumps(paper_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if entry.get("remove_headings"):
            paper_md = _remove_bogus_heading_lines(paper_md, list(entry.get("remove_headings", [])))
            paper_md_path.write_text(paper_md, encoding="utf-8")

        if action == "rename" and paper_meta.get("title"):
            new_dir = paper_dir.parent / _slugify(str(paper_meta["title"]))
            if new_dir != paper_dir:
                if new_dir.exists():
                    raise FileExistsError(f"target proceedings paper dir already exists: {new_dir}")
                paper_dir.rename(new_dir)

    remaining = sorted(path for path in papers_dir.iterdir() if path.is_dir())
    meta_path = proceeding_dir / "meta.json"
    proceeding_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    updated_volume_title = None
    if plan.get("volume_title"):
        updated_volume_title = str(plan["volume_title"]).strip()
        proceeding_meta["title"] = updated_volume_title
    proceeding_meta["child_paper_count"] = len(remaining)
    proceeding_meta["clean_status"] = "applied"
    meta_path.write_text(json.dumps(proceeding_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if updated_volume_title:
        for paper_dir in remaining:
            paper_meta_path = paper_dir / "meta.json"
            paper_meta = json.loads(paper_meta_path.read_text(encoding="utf-8"))
            paper_meta["proceeding_title"] = updated_volume_title
            paper_meta_path.write_text(json.dumps(paper_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (proceeding_dir / "clean_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    build_proceedings_index(proceeding_dir.parent, proceeding_dir.parent / "proceedings.db", rebuild=False)
    return proceeding_dir


def apply_proceedings_split_plan(proceeding_dir: Path, split_plan: dict | Path) -> Path:
    """Apply a human/agent-authored split plan to an existing proceedings directory."""
    if isinstance(split_plan, Path):
        plan = _parse_json(split_plan.read_text(encoding="utf-8"))
    else:
        plan = split_plan

    proceeding_md = proceeding_dir / "proceeding.md"
    if not proceeding_md.exists():
        raise FileNotFoundError(f"proceeding.md not found: {proceeding_md}")

    text = proceeding_md.read_text(encoding="utf-8", errors="replace")
    child_papers = _papers_from_split_plan(text, plan)
    if not child_papers:
        raise ValueError("split plan did not produce any child papers")
    papers_dir = proceeding_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    for existing in papers_dir.iterdir():
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()

    meta_path = proceeding_dir / "meta.json"
    proceeding_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if plan.get("volume_title"):
        proceeding_meta["title"] = str(plan["volume_title"]).strip()
    proceeding_meta["child_paper_count"] = len(child_papers)
    proceeding_meta["split_status"] = "applied"
    meta_path.write_text(json.dumps(proceeding_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (proceeding_dir / "split_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    for paper in child_papers:
        paper_dir = papers_dir / _slugify(paper["title"])
        paper_dir.mkdir(parents=True, exist_ok=True)
        paper_meta = {
            "id": generate_uuid(),
            "title": paper["title"],
            "authors": paper["authors"],
            "year": "",
            "journal": "",
            "doi": paper["doi"],
            "abstract": paper["abstract"],
            "paper_type": paper["paper_type"],
            "proceeding_id": proceeding_meta["id"],
            "proceeding_title": proceeding_meta["title"],
            "proceeding_dir": proceeding_dir.name,
        }
        (paper_dir / "meta.json").write_text(json.dumps(paper_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        (paper_dir / "paper.md").write_text(paper["markdown"], encoding="utf-8")

    build_proceedings_index(proceeding_dir.parent, proceeding_dir.parent / "proceedings.db", rebuild=False)
    return proceeding_dir


def ingest_proceedings_markdown(
    proceedings_root: Path,
    md_path: Path,
    *,
    source_name: str = "",
) -> Path:
    """Write a proceedings volume shell under data/proceedings and wait for split review."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fallback_title = lines[0].lstrip("# ").strip() if lines else md_path.stem
    split_candidates = _build_split_candidates(text)
    title = _extract_volume_title(text, fallback_title)

    proceeding_dir = proceedings_root / _slugify(title)
    suffix = 2
    while proceeding_dir.exists():
        proceeding_dir = proceedings_root / f"{_slugify(title)}-{suffix}"
        suffix += 1
    (proceeding_dir / "papers").mkdir(parents=True)

    proceeding_meta = {
        "id": generate_uuid(),
        "title": title,
        "source_file": source_name or md_path.name,
        "child_paper_count": 0,
        "split_status": "pending_review",
    }
    (proceeding_dir / "meta.json").write_text(
        json.dumps(proceeding_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (proceeding_dir / "proceeding.md").write_text(text, encoding="utf-8")
    (proceeding_dir / "split_candidates.json").write_text(
        json.dumps(split_candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    build_proceedings_index(proceedings_root, proceedings_root / "proceedings.db", rebuild=False)
    return proceeding_dir
