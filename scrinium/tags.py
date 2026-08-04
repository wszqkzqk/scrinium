"""
tags.py — Agent 策展标签系统
=============================

标签是 agent 策展的受控词表（controlled vocabulary），用于补偿纯关键词
检索的词汇鸿沟。标签即主题：不做第二个主题系统。

- 受控词表存 ``<root>/data/tags.yaml``（canonical 名 + 别名 + 描述）；
- 论文标签存各自 ``meta.json`` 的 ``"tags"`` 字段（canonical 名列表）；
- 标签随 ``build_index`` 进入 FTS5（``tags`` 列）与 ``paper_tags`` 过滤表。

词表格式::

    tags:
      force-field:
        aliases: [forcefield, FF, 力场]
        description: 分子力场相关
        added_by: agent

用法::

    from scrinium.tags import paper_tags, register_tag, resolve_tag, set_paper_tags

    canonical = resolve_tag(cfg, "FF")          # -> "force-field"
    register_tag(cfg, "enhanced-sampling")      # -> True（新增）
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
    """加载受控词表；文件不存在或为空时返回空词表。

    Args:
        cfg: 全局配置（词表路径为 ``<root>/data/tags.yaml``）。

    Returns:
        ``{"tags": {canonical: {"aliases": [...], "description": str, ...}}}``。
    """
    path = _taxonomy_path(cfg)
    if not path.exists():
        return {"tags": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tags = data.get("tags")
    return {"tags": tags if isinstance(tags, dict) else {}}


def save_taxonomy(cfg: Config, tax: dict) -> None:
    """将受控词表写回 tags.yaml（canonical 名按字母序）。"""
    path = _taxonomy_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(tax, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def normalize_tag(name: str) -> str:
    """规范化标签名为 canonical 形式：小写、空白/下划线转连字符。

    Args:
        name: 原始标签名（如 ``"Force Field"``）。

    Returns:
        canonical 名（如 ``"force-field"``）；全空白输入返回空字符串。
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
    """将标签名（canonical 或别名）解析为 canonical 名。

    大小写不敏感，同时尝试原样小写与连字符规范化两种形式。

    Args:
        cfg: 全局配置。
        name: 用户输入的标签名。

    Returns:
        canonical 名；未知名返回 ``None``。
    """
    lookup = _alias_lookup(load_taxonomy(cfg))
    return lookup.get(name.strip().lower()) or lookup.get(normalize_tag(name))


def unknown_tag_message(cfg: Config, tag: str) -> str:
    """Build the unknown-tag error message listing the current vocabulary."""
    known = sorted((load_taxonomy(cfg).get("tags") or {}).keys())
    hint = f"；当前词表: {', '.join(known)}" if known else "（词表为空，可先用 scrinium tag 打标）"
    return f"未知标签: {tag}{hint}"


def register_tag(
    cfg: Config,
    name: str,
    *,
    added_by: str = "agent",
    description: str = "",
    aliases: tuple[str, ...] | list[str] = (),
) -> bool:
    """注册新标签到受控词表。

    canonical 名规范化为小写连字符式。名称命中既有 canonical 或别名时
    视为已存在，不重复注册。

    Args:
        cfg: 全局配置。
        name: 标签名。
        added_by: 注册来源标记（默认 ``"agent"``）。
        description: 标签描述。
        aliases: 别名列表。

    Returns:
        新增返回 ``True``，已存在返回 ``False``。

    Raises:
        ValueError: 标签名规范化后为空。
    """
    canonical = normalize_tag(name)
    if not canonical:
        raise ValueError(f"非法标签名: {name!r}")
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
    """读取论文标签（``meta.json["tags"]``）；无字段时返回 ``[]``。"""
    meta = read_meta(paper_dir)
    return [t for t in (meta.get("tags") or []) if isinstance(t, str)]


def set_paper_tags(paper_dir: Path, tags: list[str]) -> None:
    """写入论文标签（去重保序），经原子写更新 meta.json。"""
    meta = read_meta(paper_dir)
    meta["tags"] = list(dict.fromkeys(tags))
    write_meta(paper_dir, meta)


def all_tags_with_counts(cfg: Config) -> dict[str, int]:
    """扫描全库 meta.json，统计每个标签标注了多少篇论文。

    Returns:
        ``{tag: 论文数}`` 字典（未排序）。
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
    """返回带有指定标签的论文目录与 meta（别名自动归一）。

    标签先经 :func:`resolve_tag` 解析为 canonical 名；词表中不存在时
    回退到 :func:`normalize_tag`（论文可能带有未注册进词表的标签）。

    Args:
        cfg: 全局配置。
        tag: 标签名（canonical 或别名）。

    Returns:
        ``[(paper_dir, meta), ...]``，按目录名排序。
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
    """聚合标签主题总览：词表 + 计数 + 占比 + 未打标论文数。

    标签即主题——不做第二个主题系统。词表 canonical 名与论文实际使用
    的标签取并集。

    Returns:
        ``{"total_papers": int, "untagged_papers": int, "topics": [...]}``；
        每个主题含 ``tag`` / ``description`` / ``aliases`` / ``count`` /
        ``share``（占全库论文比例），按 ``count`` 降序、同名按字典序。
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
