"""
audit.py — 已入库论文数据质量审计
====================================

扫描 data/papers/ 中的所有论文，检查元数据完整性、数据质量
和内容一致性问题。返回结构化的问题报告供用户审阅。

规则化检查（无需 LLM）：
  - 关键字段缺失（doi, abstract, year, authors, journal）
  - 配对完整性（目录内 meta.json / paper.md 是否齐全）
  - 文件名规范性（目录名不符合 Author-Year-Title 格式）
  - DOI 重复检测
  - arXiv DOI 与 arxiv_id 配对（缺失时预印本去重会漏）
  - MD 内容过短（可能转换失败）
  - JSON title 与 MD 首个 H1 不一致
  - 策展标签缺失（untagged，所有 paper_type 均提示）
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
    """单个审计问题。

    Attributes:
        paper_id: 论文 ID（目录名）。
        severity: 严重程度，``"error"`` | ``"warning"`` | ``"info"``。
        rule: 检查规则名称。
        message: 问题描述。
    """

    paper_id: str
    severity: str  # "error" | "warning" | "info"
    rule: str
    message: str


def audit_papers(papers_dir: Path) -> list[Issue]:
    """对论文目录执行全量数据质量审计。

    Args:
        papers_dir: 已入库论文目录（每篇一目录结构）。

    Returns:
        按严重程度排序的问题列表（error 在前）。
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
            issues.append(Issue(pid, "error", "invalid_json", f"JSON 解析失败: {e}"))
            continue

        # -- Missing fields --
        _check_missing(issues, pid, data)

        # -- File pairing --
        if not md_file.exists():
            issues.append(Issue(pid, "error", "missing_md", "缺少 paper.md 文件"))
        else:
            _check_content_consistency(issues, pid, data, md_file)

        # -- Directory name format --
        _check_filename(issues, pid, data)

        # -- DOI tracking --
        doi = (data.get("doi") or "").strip().lower()
        if doi:
            doi_map.setdefault(doi, []).append(pid)

        # -- arXiv id backfill check (preprint dedup relies on it) --
        if "10.48550/arxiv." in doi and not (data.get("arxiv_id") or (data.get("ids") or {}).get("arxiv")):
            issues.append(
                Issue(pid, "warning", "arxiv_id_missing", "有 arXiv DOI 但缺 arxiv_id，预印本去重不会命中")
            )

    # DOI duplicates
    for doi, pids in doi_map.items():
        if len(pids) > 1:
            for pid in pids:
                others = [p for p in pids if p != pid]
                issues.append(Issue(pid, "error", "duplicate_doi", f"DOI 重复: {doi} (同: {', '.join(others)})"))

    # Sort: error > warning > info
    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: (severity_order.get(x.severity, 9), x.paper_id))
    return issues


def _check_missing(issues: list[Issue], pid: str, data: dict) -> None:
    """Check for missing critical fields."""
    from scrinium.ingest.metadata._models import DOCUMENT_TYPES

    paper_type = data.get("paper_type", "")
    if not data.get("doi") and paper_type not in DOCUMENT_TYPES:
        issues.append(Issue(pid, "warning", "missing_doi", "缺少 DOI"))
    if not data.get("abstract"):
        issues.append(Issue(pid, "warning", "missing_abstract", "缺少摘要"))
    if not data.get("year"):
        issues.append(Issue(pid, "warning", "missing_year", "缺少年份"))
    if not data.get("authors"):
        issues.append(Issue(pid, "warning", "missing_authors", "缺少作者"))
    if not data.get("journal"):
        issues.append(Issue(pid, "warning", "missing_journal", "缺少期刊名"))
    if not data.get("title"):
        issues.append(Issue(pid, "error", "missing_title", "缺少标题"))
    if not data.get("tags"):
        issues.append(Issue(pid, "info", "untagged", "未打策展标签"))


def _check_content_consistency(
    issues: list[Issue],
    pid: str,
    data: dict,
    md_path: Path,
) -> None:
    """Check consistency between JSON metadata and MD content."""
    try:
        md_text = md_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        _log.debug("failed to read paper.md for %s: %s", pid, e)
        issues.append(Issue(pid, "error", "unreadable_md", "无法读取 paper.md 文件"))
        return

    # MD too short (likely conversion failure)
    if len(md_text.strip()) < 200:
        issues.append(
            Issue(pid, "warning", "short_md", f"paper.md 文件过短 ({len(md_text.strip())} 字符)，可能转换失败")
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
                            f"JSON 标题与 MD H1 不一致\n"
                            f"  JSON: {data['title'][:80]}\n"
                            f"  MD H1: {h1_match.group(1).strip()[:80]}",
                        )
                    )


def _check_filename(issues: list[Issue], pid: str, data: dict) -> None:
    """Check directory name format compliance."""
    # Expected: Author-Year-Title
    m = re.match(r"^(.+?)-(\d{4})-(.+)$", pid)
    if not m:
        issues.append(Issue(pid, "info", "nonstandard_filename", "目录名不符合 Author-Year-Title 格式"))
        return

    file_year = int(m.group(2))
    json_year = data.get("year")
    if json_year and file_year != json_year:
        issues.append(
            Issue(
                pid, "warning", "filename_year_mismatch", f"目录名年份 ({file_year}) 与 JSON 年份 ({json_year}) 不一致"
            )
        )


def format_report(issues: list[Issue]) -> str:
    """将审计结果格式化为可读报告。

    问题条目附修复建议（handoff hint），指向 agent 修复工作流：
    框架只诊断，修复由 agent/subagent 读原文核对后直改 meta.json 完成。

    Args:
        issues: :func:`audit_papers` 返回的问题列表。

    Returns:
        格式化的文本报告。
    """
    if not issues:
        return "审计通过，未发现问题。"

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    lines = [f"审计完成: {len(errors)} 个错误, {len(warnings)} 个警告, {len(infos)} 个提示\n"]

    if errors:
        lines.append("=" * 60)
        lines.append("错误 (需要修复)")
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
        lines.append("警告 (建议关注)")
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
        lines.append("提示 (参考信息)")
        lines.append("· " * 30)
        for i in infos:
            lines.append(f"  [{i.rule}] {i.paper_id}")
            lines.append(f"    {i.message}")
            hint = _RULE_HINTS.get(i.rule)
            if hint:
                lines.append(f"    hint: {hint}")

    lines.append("")
    lines.append("hint: 以上问题建议派 subagent 读原文核对后直接修改 meta.json（audit 修复工作流），必要时运行 scrinium repair / scrinium rename")
    return "\n".join(lines)


# Recommended fix per audit rule (handoff hints for agents)
_RULE_HINTS = {
    "invalid_json": "派 subagent 检查该 meta.json 语法并直接修复",
    "missing_md": "派 subagent 确认 PDF 来源后用 scrinium attach-pdf 补全 paper.md",
    "missing_title": "派 subagent 读原文确认标题后直写 meta.json title，或 scrinium repair",
    "missing_doi": "派 subagent 读原文找到 DOI 后直写 meta.json doi，并 scrinium refresh 补全元数据",
    "missing_abstract": "运行 scrinium enrich abstract，仍缺则由 agent 读原文直写 meta.json abstract",
    "missing_year": "派 subagent 读原文确认年份后直写 meta.json year",
    "missing_authors": "派 subagent 读原文确认作者后直写 meta.json authors",
    "missing_journal": "运行 scrinium refresh 补全期刊信息，或 agent 直写 meta.json journal",
    "duplicate_doi": "派 subagent 对比重复条目后决定去留（保留一篇，删除多余目录）",
    "title_mismatch": "派 subagent 读原文核对正确标题后直写 meta.json title",
    "short_md": "检查 PDF 转换是否失败；必要时重新转换或 scrinium attach-pdf",
    "unreadable_md": "检查 paper.md 文件编码/权限",
    "nonstandard_filename": "运行 scrinium rename 规范目录名",
    "filename_year_mismatch": "确认正确年份后直写 meta.json year 并 scrinium rename",
    "arxiv_id_missing": "从 arXiv DOI 派生 arxiv_id 直写 meta.json ids.arxiv（如 10.48550/arxiv.2510.16510 → 2510.16510），纯机械操作无需读原文",
    "untagged": "运行 curate 工作流或 scrinium tag 补充策展标签",
}
