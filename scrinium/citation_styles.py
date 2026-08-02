"""Citation style management for Markdown reference export.

Built-in styles: apa, vancouver, chicago-author-date, mla
Custom styles: loaded dynamically from data/citation_styles/<name>.py

Formatter interface (every style file must implement):

    def format_ref(meta: dict, idx: int | None = None) -> str:
        '''Return a single formatted reference line (Markdown).

        Args:
            meta: Paper metadata dict (title, authors, year, journal,
                  volume, issue, pages, doi, publisher, paper_type, ...)
            idx: 1-based index for numbered lists; None for bullet lists.
        Returns:
            Formatted reference string, e.g. "1. Smith et al. (2023). ..."
        '''

Agent workflow for fetching a new style
----------------------------------------
1. Agent calls ``scrinium style list`` — if target style missing, proceed.
2. Agent fetches the journal's official citation guide or CSL file:
   - CSL repo (10,000+ styles):
     https://raw.githubusercontent.com/citation-style-language/styles/master/<slug>.csl
   - Journal instructions page (Google: "<journal name> citation style guide")
3. Agent writes a Python formatter file to data/citation_styles/<name>.py
   following the interface above.
4. Agent runs ``scrinium export markdown --all --style <name>``
5. Style is now cached; future calls skip steps 1-3.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scrinium.config import Config

FormatterFn = Callable[[dict, int | None], str]


# ─────────────────────────────────────────────────────────────────────────────
# Built-in styles
# ─────────────────────────────────────────────────────────────────────────────


def _fmt_apa(meta: dict, idx: int | None = None) -> str:
    """APA 7th edition (author-date, ampersand, italicised journal+volume)."""
    authors = meta.get("authors") or []
    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        author_str = authors[0]
    elif len(authors) <= 3:
        author_str = ", ".join(authors[:-1]) + f", & {authors[-1]}"
    else:
        author_str = f"{authors[0]} et al."

    year = meta.get("year") or "n.d."
    title = meta.get("title") or "Untitled"
    journal = meta.get("journal") or ""
    volume = meta.get("volume") or ""
    issue = meta.get("issue") or ""
    pages = meta.get("pages") or ""
    doi = meta.get("doi") or ""

    journal_part = ""
    if journal:
        journal_part = f"*{journal}*"
        if volume:
            journal_part += f", *{volume}*"
            if issue:
                journal_part += f"({issue})"
        if pages:
            journal_part += f", {pages}"

    ref = f"{author_str} ({year}). {title}."
    if journal_part:
        ref += f" {journal_part}."
    if doi:
        ref += f" https://doi.org/{doi}"

    prefix = f"{idx}. " if idx is not None else "- "
    return prefix + ref


def _fmt_vancouver(meta: dict, idx: int | None = None) -> str:
    """Vancouver / ICMJE numbered style (used by most biomedical journals)."""
    authors = meta.get("authors") or []

    def _initials(name: str) -> str:
        parts = name.split(",", 1)
        if len(parts) == 2:
            last, first = parts[0].strip(), parts[1].strip()
            initials = "".join(w[0] for w in first.split() if w)
            return f"{last} {initials}"
        return name

    if not authors:
        author_str = "Unknown"
    elif len(authors) <= 6:
        author_str = ", ".join(_initials(a) for a in authors)
    else:
        author_str = ", ".join(_initials(a) for a in authors[:6]) + ", et al"

    year = meta.get("year") or "n.d."
    title = meta.get("title") or "Untitled"
    journal = meta.get("journal") or ""
    volume = meta.get("volume") or ""
    issue = meta.get("issue") or ""
    pages = meta.get("pages") or ""
    doi = meta.get("doi") or ""

    ref = f"{author_str}. {title}."
    if journal:
        ref += f" {journal}."
    if year:
        ref += f" {year}"
    if volume:
        ref += f";{volume}"
    if issue:
        ref += f"({issue})"
    if pages:
        ref += f":{pages}"
    ref = ref.rstrip(";:") + "."
    if doi:
        ref += f" doi:{doi}"

    prefix = f"{idx}. " if idx is not None else "- "
    return prefix + ref


def _fmt_chicago_author_date(meta: dict, idx: int | None = None) -> str:
    """Chicago 17th ed. Author-Date (common in humanities/social sciences)."""
    authors = meta.get("authors") or []

    def _chicago_author(name: str, first: bool) -> str:
        # First author: Last, First; subsequent: First Last
        parts = name.split(",", 1)
        if len(parts) == 2:
            last, given = parts[0].strip(), parts[1].strip()
            return f"{last}, {given}" if first else f"{given} {last}"
        return name

    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        author_str = _chicago_author(authors[0], first=True)
    elif len(authors) <= 3:
        formatted = [_chicago_author(authors[0], first=True)]
        formatted += [_chicago_author(a, first=False) for a in authors[1:]]
        author_str = ", ".join(formatted[:-1]) + f", and {formatted[-1]}"
    else:
        author_str = _chicago_author(authors[0], first=True).rstrip(".") + " et al."

    year = meta.get("year") or "n.d."
    title = meta.get("title") or "Untitled"
    journal = meta.get("journal") or ""
    volume = meta.get("volume") or ""
    issue = meta.get("issue") or ""
    pages = meta.get("pages") or ""
    doi = meta.get("doi") or ""

    ref = f'{author_str.rstrip(".")}. {year}. "{title}."'
    if journal:
        ref += f" *{journal}*"
    if volume:
        ref += f" {volume}"
    if issue:
        ref += f" ({issue})"
    if pages:
        ref += f": {pages}"
    ref = ref.rstrip(":") + "."
    if doi:
        ref += f" https://doi.org/{doi}"

    prefix = f"{idx}. " if idx is not None else "- "
    return prefix + ref


def _fmt_mla(meta: dict, idx: int | None = None) -> str:
    """MLA 9th edition (humanities, container model)."""
    authors = meta.get("authors") or []

    def _mla_author(name: str, reverse: bool) -> str:
        parts = name.split(",", 1)
        if len(parts) == 2:
            last, given = parts[0].strip(), parts[1].strip()
            return f"{last}, {given}" if reverse else f"{given} {last}"
        return name

    if len(authors) == 1:
        author_str = _mla_author(authors[0], reverse=True)
    elif len(authors) == 2:
        author_str = f"{_mla_author(authors[0], reverse=True)}, and {_mla_author(authors[1], reverse=False)}"
    elif authors:
        author_str = _mla_author(authors[0], reverse=True).rstrip(".") + ", et al."
    else:
        author_str = "Unknown"

    title = meta.get("title") or "Untitled"
    journal = meta.get("journal") or ""
    volume = meta.get("volume") or ""
    issue = meta.get("issue") or ""
    year = meta.get("year") or "n.d."
    pages = meta.get("pages") or ""
    doi = meta.get("doi") or ""

    ref = f'{author_str.rstrip(".")}. "{title}."'
    if journal:
        ref += f" *{journal}*"
    if volume:
        ref += f", vol. {volume}"
    if issue:
        ref += f", no. {issue}"
    if year:
        ref += f", {year}"
    if pages:
        ref += f", pp. {pages}"
    ref = ref.rstrip(",") + "."
    if doi:
        ref += f" https://doi.org/{doi}"

    prefix = f"{idx}. " if idx is not None else "- "
    return prefix + ref


BUILTIN_STYLES: dict[str, FormatterFn] = {
    "apa": _fmt_apa,
    "vancouver": _fmt_vancouver,
    "chicago-author-date": _fmt_chicago_author_date,
    "mla": _fmt_mla,
}

# Human-readable descriptions shown in `style list`
BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "apa": "APA 第七版（作者-年份，默认）",
    "vancouver": "Vancouver / ICMJE 编号格式（生物医学期刊）",
    "chicago-author-date": "Chicago 第十七版作者-年份格式（人文社科）",
    "mla": "MLA 第九版（人文学科，容器模型）",
}


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic cache loading
# ─────────────────────────────────────────────────────────────────────────────


def styles_dir(cfg: Config) -> Path:
    """Return the citation styles cache directory (data/citation_styles/)."""
    return cfg.papers_dir.parent / "citation_styles"


def list_styles(cfg: Config) -> list[dict]:
    """Return all available styles as a list of dicts with name/source/description.

    Args:
        cfg: Project configuration (used to resolve data/citation_styles/ path).

    Returns:
        List of dicts, each with keys ``name``, ``source`` (``"built-in"`` or
        ``"custom"``), and ``description``.
    """
    results = []
    for name, desc in BUILTIN_DESCRIPTIONS.items():
        results.append({"name": name, "source": "built-in", "description": desc})

    d = styles_dir(cfg)
    if d.exists():
        for py_file in sorted(d.glob("*.py")):
            name = py_file.stem
            if name in BUILTIN_STYLES:
                continue  # don't shadow built-ins
            meta_file = d / f"{name}.json"
            desc = ""
            source = "custom"
            if meta_file.exists():
                try:
                    m = json.loads(meta_file.read_text(encoding="utf-8"))
                    desc = m.get("description", "")
                    source = m.get("source", "custom")
                except Exception:
                    pass
            results.append({"name": name, "source": source, "description": desc})

    return results


def get_formatter(name: str, cfg: Config) -> FormatterFn:
    """Load a formatter by style name.

    Checks built-in styles first, then dynamic cache at data/citation_styles/<name>.py.

    Args:
        name: Citation style name (e.g. ``"apa"``, ``"vancouver"``).
        cfg: Project configuration (used to resolve the style cache directory).

    Returns:
        A callable ``(meta: dict, idx: int | None) -> str`` that formats one reference.

    Raises:
        ValueError: If ``name`` contains invalid characters or a path traversal is detected.
        FileNotFoundError: If the style is not found in built-ins or the cache.
        ImportError: If the custom style file cannot be imported or executed.
        AttributeError: If the style file does not define a ``format_ref`` function.
    """
    if name in BUILTIN_STYLES:
        return BUILTIN_STYLES[name]

    import re

    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise ValueError(f"引用格式名称无效 '{name}'：只允许字母、数字、连字符和下划线。")

    style_file = styles_dir(cfg) / f"{name}.py"
    if not style_file.resolve().is_relative_to(styles_dir(cfg).resolve()):
        raise ValueError(f"引用格式名称无效 '{name}'：检测到路径穿越攻击。")
    if not style_file.exists():
        available = ", ".join(s["name"] for s in list_styles(cfg))
        raise FileNotFoundError(
            f"引用格式 '{name}' 不存在。\n"
            f"可用格式：{available}\n"
            f"如需添加新格式，请告诉 agent：'帮我获取 {name} 的引用格式'"
        )

    spec = importlib.util.spec_from_file_location(f"_csl_{name}", style_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载引用格式 '{name}'：导入机制未返回有效 spec/loader（{style_file}）")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:
        raise ImportError(f"加载引用格式 '{name}' 失败（{style_file}）：{exc}") from exc
    if not hasattr(mod, "format_ref"):
        raise AttributeError(f"格式文件 {style_file} 必须定义 `format_ref(meta, idx)` 函数。")
    return mod.format_ref


def show_style(name: str, cfg: Config) -> str:
    """Return the source code of a custom style, or a description comment for built-ins.

    Args:
        name: Citation style name.
        cfg: Project configuration (used to resolve the style cache directory).

    Returns:
        Source code string of the style file, or a comment block for built-in styles.

    Raises:
        ValueError: If ``name`` contains invalid characters or a path traversal is detected.
        FileNotFoundError: If the custom style file does not exist.
    """
    if name in BUILTIN_STYLES:
        desc = BUILTIN_DESCRIPTIONS.get(name, "")
        return f"# 内置格式：{name}\n# {desc}\n# （实现位于 scrinium/citation_styles.py）"

    import re as _re

    if not _re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise ValueError(f"引用格式名称无效 '{name}'：只允许字母、数字、连字符和下划线。")

    style_file = styles_dir(cfg) / f"{name}.py"
    if not style_file.resolve().is_relative_to(styles_dir(cfg).resolve()):
        raise ValueError(f"引用格式名称无效 '{name}'：检测到路径穿越攻击。")
    if not style_file.exists():
        raise FileNotFoundError(f"引用格式 '{name}' 不存在。")
    return style_file.read_text(encoding="utf-8")
