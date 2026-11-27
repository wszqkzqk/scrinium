"""
tags.py — Agent-curated tag system
==================================

Tags form an agent-curated controlled vocabulary that bridges the lexical gap
of pure keyword search. Tags are topics: there is no separate topic system.

- The controlled vocabulary lives in ``<root>/data/tags.yaml`` (canonical name
  + aliases + description);
- Paper tags live in each paper's ``meta.json`` under ``"tags"`` (canonical names);
- ``build_index`` indexes tags into FTS5 (``tags`` column) and the ``paper_tags``
  filter table.

Vocabulary format::

    tags:
      force-field:
        aliases: [forcefield, FF, 力场]
        description: 分子力场相关
        added_by: agent

Usage::

    from scrinium.tags import paper_tags, register_tag, resolve_tag, set_paper_tags

    canonical = resolve_tag(cfg, "FF")          # -> "force-field"
    register_tag(cfg, "enhanced-sampling")      # -> True (newly added)
    set_paper_tags(paper_dir, ["force-field"])
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from scrinium.papers import iter_paper_dirs, read_meta, write_meta

if TYPE_CHECKING:
    from scrinium.config import Config


def _taxonomy_path(cfg: Config) -> Path:
    """Return the tags.yaml path under the config root."""
    return cfg._root / "data" / "tags.yaml"


def load_taxonomy(cfg: Config) -> dict:
    """Load the controlled vocabulary; return an empty taxonomy if missing or empty.

    Args:
        cfg: Global configuration (vocabulary path is ``<root>/data/tags.yaml``).

    Returns:
        ``{"tags": {canonical: {"aliases": [...], "description": str, ...}}}``.
    """
    path = _taxonomy_path(cfg)
    if not path.exists():
        return {"tags": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tags = data.get("tags")
    return {"tags": tags if isinstance(tags, dict) else {}}


def save_taxonomy(cfg: Config, tax: dict) -> None:
    """Write the controlled vocabulary back to tags.yaml (sorted by canonical name)."""
    path = _taxonomy_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(tax, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def normalize_tag(name: str) -> str:
    """Normalize a tag name to canonical form: lowercase, whitespace/underscores to hyphens.

    Args:
        name: Raw tag name (e.g. ``"Force Field"``).

    Returns:
        Canonical name (e.g. ``"force-field"``); empty string for all-whitespace input.
    """
    text = name.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def _alias_lookup(tax: dict) -> dict[str, str]:
    """Build a case-insensitive lookup from canonical/alias to canonical."""
    lookup: dict[str, str] = {}
    for canonical, entry in (tax.get("tags") or {}).items():
        canonical = str(canonical)
        entry = entry or {}
        lookup[canonical.lower()] = canonical
        lookup[normalize_tag(canonical)] = canonical
        for alias in entry.get("aliases") or []:
            alias = str(alias)
            lookup[alias.lower()] = canonical
            lookup[normalize_tag(alias)] = canonical
    return lookup


def resolve_tag(cfg: Config, name: str) -> str | None:
    """Resolve a tag name (canonical or alias) to its canonical name.

    Case-insensitive; tries both verbatim lowercase and hyphen-normalized forms.

    Args:
        cfg: Global configuration.
        name: User-supplied tag name.

    Returns:
        Canonical name, or ``None`` if unknown.
    """
    lookup = _alias_lookup(load_taxonomy(cfg))
    return lookup.get(name.strip().lower()) or lookup.get(normalize_tag(name))


def unknown_tag_message(cfg: Config, tag: str) -> str:
    """Build the unknown-tag error message listing the current vocabulary."""
    known = sorted((load_taxonomy(cfg).get("tags") or {}).keys())
    hint = (
        f"; current vocabulary: {', '.join(known)}"
        if known
        else " (vocabulary is empty; add tags first with scrinium tag)"
    )
    return f"Unknown tag: {tag}{hint}"


def register_tag(
    cfg: Config,
    name: str,
    *,
    added_by: str = "agent",
    description: str = "",
    aliases: tuple[str, ...] | list[str] = (),
) -> bool:
    """Register a new tag in the controlled vocabulary.

    The canonical name is normalized to lowercase hyphenated form. If the name
    matches an existing canonical name or alias, it is treated as already
    registered.

    Args:
        cfg: Global configuration.
        name: Tag name.
        added_by: Registration source marker (default ``"agent"``).
        description: Tag description.
        aliases: List of aliases.

    Returns:
        ``True`` if newly registered, ``False`` if already present.

    Raises:
        ValueError: Tag name is empty after normalization.
    """
    canonical = normalize_tag(name)
    if not canonical:
        raise ValueError(f"Invalid tag name: {name!r}")
    tax = load_taxonomy(cfg)
    if resolve_tag(cfg, name) is not None:
        return False
    tax["tags"][canonical] = {
        "aliases": [str(a) for a in aliases],
        "description": description,
        "added_by": added_by,
    }
    save_taxonomy(cfg, tax)
    return True


def paper_tags(paper_dir: Path) -> list[str]:
    """Read paper tags (``meta.json["tags"]``); return ``[]`` if the field is absent."""
    meta = read_meta(paper_dir)
    return [t for t in (meta.get("tags") or []) if isinstance(t, str)]


def set_paper_tags(paper_dir: Path, tags: list[str]) -> None:
    """Write paper tags (deduplicated, order-preserving) to meta.json atomically."""
    meta = read_meta(paper_dir)
    meta["tags"] = list(dict.fromkeys(tags))
    write_meta(paper_dir, meta)


def all_tags_with_counts(cfg: Config) -> dict[str, int]:
    """Scan all meta.json files in the library and count papers per tag.

    Returns:
        Unsorted ``{tag: paper_count}`` dict.
    """
    counts: dict[str, int] = {}
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            tags = paper_tags(pdir)
        except (ValueError, FileNotFoundError):
            continue
        for tag in dict.fromkeys(tags):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def papers_with_tag(cfg: Config, tag: str) -> list[tuple[Path, dict]]:
    """Return ``(paper_dir, meta)`` pairs carrying the given tag (aliases resolved).

    The tag is first resolved to its canonical name via :func:`resolve_tag`;
    when absent from the vocabulary it falls back to :func:`normalize_tag`
    (papers may carry tags not yet registered in the vocabulary).

    Args:
        cfg: Global configuration.
        tag: Tag name (canonical or alias).

    Returns:
        ``[(paper_dir, meta), ...]`` sorted by directory name.
    """
    canonical = resolve_tag(cfg, tag) or normalize_tag(tag)
    if not canonical:
        return []
    results: list[tuple[Path, dict]] = []
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            tags = paper_tags(pdir)
        except (ValueError, FileNotFoundError):
            continue
        if canonical in tags:
            results.append((pdir, read_meta(pdir)))
    return sorted(results, key=lambda item: item[0].name)


def topic_overview(cfg: Config) -> dict:
    """Aggregate the tag-based topic overview: vocabulary + counts + shares + untagged count.

    Tags are topics — there is no second topic system. Canonical names in the
    vocabulary and tags actually used on papers are combined as a union.

    Returns:
        ``{"total_papers": int, "untagged_papers": int, "topics": [...]}``;
        each topic has ``tag`` / ``description`` / ``aliases`` / ``count`` /
        ``share`` (fraction of all library papers), sorted by ``count`` desc
        then ``tag`` alphabetically.
    """
    tax = load_taxonomy(cfg).get("tags") or {}
    counts = all_tags_with_counts(cfg)
    total = 0
    untagged = 0
    for pdir in iter_paper_dirs(cfg.papers_dir):
        try:
            tags = paper_tags(pdir)
        except (ValueError, FileNotFoundError):
            continue
        total += 1
        if not tags:
            untagged += 1
    topics = []
    for name in sorted(set(tax) | set(counts), key=lambda n: (-counts.get(n, 0), n)):
        entry = tax.get(name) or {}
        count = counts.get(name, 0)
        topics.append(
            {
                "tag": name,
                "description": entry.get("description") or "",
                "aliases": entry.get("aliases") or [],
                "count": count,
                "share": (count / total) if total else 0.0,
            }
        )
    return {"total_papers": total, "untagged_papers": untagged, "topics": topics}
