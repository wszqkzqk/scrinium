from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

_log = logging.getLogger(__name__)


def convert_pdf_with_fallback(
    pdf_path: Path,
    md_path: Path,
    parser_order: Iterable[str] | None = None,
    *,
    auto_detect: bool = True,
) -> tuple[bool, str | None, str | None]:
    """在 MinerU 不可用时，尝试替代 PDF 解析器。

    Args:
        pdf_path: 输入 PDF 路径。
        md_path: 目标 Markdown 路径。
        parser_order: 解析器尝试顺序（例如 ``["docling", "pymupdf"]``）。
            支持 ``auto`` 占位符（展开为本机可用解析器）。
        auto_detect: 是否启用自动检测。开启后 ``auto`` 会展开为可用解析器列表。

    Returns:
        三元组 ``(ok, parser_name, error)``：
        - ok: 是否成功输出 Markdown。
        - parser_name: 成功时实际使用的解析器。
        - error: 全部失败时的汇总错误信息。
    """
    order = resolve_parser_order(parser_order, auto_detect=auto_detect)
    if not order:
        return False, None, "未配置可用的 fallback 解析器"

    errors: list[str] = []

    for parser in order:
        try:
            if parser == "docling":
                ok, err = _run_docling(pdf_path, md_path)
            elif parser == "pymupdf":
                ok, err = run_pymupdf(pdf_path, md_path)
            else:
                ok, err = False, f"未知解析器: {parser}"
        except Exception as exc:
            ok, err = False, f"{parser} 异常: {exc}"

        if ok:
            return True, parser, None
        if err:
            errors.append(err)

    return False, None, " | ".join(errors) if errors else "所有 fallback 解析器均失败"


def resolve_parser_order(parser_order: Iterable[str] | None, *, auto_detect: bool = True) -> list[str]:
    """解析用户配置的降级链，支持 ``auto`` 自动展开与去重。"""
    raw: list[str] = []
    for parser in parser_order or ["auto"]:
        if parser is None or not isinstance(parser, str):
            continue
        normalized = parser.lower().strip()
        if normalized:
            raw.append(normalized)
    if not raw:
        raw = ["auto"]

    detected = detect_available_parsers() if auto_detect else []
    order: list[str] = []

    for parser in raw:
        if parser == "auto":
            order.extend(detected if detected else ["pymupdf"])
        else:
            order.append(parser)

    deduped: list[str] = []
    seen: set[str] = set()
    for parser in order:
        if parser not in seen:
            deduped.append(parser)
            seen.add(parser)
    return deduped


def preferred_parser_order(
    preferred_parser: str | None,
    parser_order: Iterable[str] | None,
    *,
    auto_detect: bool = True,
) -> list[str]:
    """Build an effective parser order with an optional preferred parser prepended."""
    preferred = str(preferred_parser or "").lower().strip()
    if preferred and preferred != "mineru":
        raw_order = [preferred, *(parser_order or [])]
        return resolve_parser_order(raw_order, auto_detect=auto_detect)
    return resolve_parser_order(parser_order, auto_detect=auto_detect)


def prefers_fallback_parser(preferred_parser: str | None) -> bool:
    """Return True when the configured preferred parser should bypass MinerU."""
    preferred = str(preferred_parser or "").lower().strip()
    return preferred in {"docling", "pymupdf"}


def detect_available_parsers() -> list[str]:
    """自动检测本机可用的 fallback 解析器。"""
    available: list[str] = []
    if shutil.which("docling"):
        available.append("docling")
    try:
        import fitz  # noqa: F401

        available.append("pymupdf")
    except ImportError:
        pass
    return available


def _run_docling(pdf_path: Path, md_path: Path) -> tuple[bool, str | None]:
    cmd = shutil.which("docling")
    if not cmd:
        return False, "docling 未安装（缺少 docling CLI）"

    with tempfile.TemporaryDirectory(prefix="scrinium-docling-") as tmp:
        out_dir = Path(tmp)
        proc = subprocess.run(
            [cmd, str(pdf_path), "--output", str(out_dir), "--to", "md"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            return False, f"docling 失败: {proc.stderr.strip()[:120] or proc.stdout.strip()[:120]}"
        return pick_and_write_md(out_dir, md_path, "docling")


def run_pymupdf(pdf_path: Path, md_path: Path) -> tuple[bool, str | None]:
    try:
        import fitz
    except ImportError:
        return False, "PyMuPDF 未安装（pip install 'scrinium[pdf]'）"

    try:
        parts: list[str] = []
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc, start=1):
                txt = (page.get_text("text") or "").strip()
                if txt:
                    parts.append(f"## Page {i}\n\n{txt}")
        if not parts:
            return False, "PyMuPDF 未提取到文本（可能是扫描版 PDF）"
        md_path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        return True, None
    except Exception as exc:
        return False, f"PyMuPDF 解析失败: {exc}"


def pick_and_write_md(out_dir: Path, md_path: Path, parser_name: str) -> tuple[bool, str | None]:
    candidates = list(out_dir.rglob("*.md"))
    if not candidates:
        return False, f"{parser_name} 未生成 markdown 输出"

    selected = max(candidates, key=lambda p: p.stat().st_size)
    content = selected.read_text(encoding="utf-8", errors="ignore")
    if not content.strip():
        return False, f"{parser_name} 生成 markdown 为空"

    copy_parser_assets(selected, md_path)
    md_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    _log.info("fallback parser %s -> %s", parser_name, md_path.name)
    return True, None


def copy_parser_assets(selected_md: Path, md_path: Path) -> None:
    """Copy assets emitted alongside parser markdown output.

    Many parsers write markdown plus sibling asset directories (for example
    ``images/``). Replace only those emitted asset paths so stale parser
    outputs get refreshed without deleting unrelated paper files that share
    the same destination directory.
    """
    src_dir = selected_md.parent
    dst_dir = md_path.parent
    dst_dir.mkdir(parents=True, exist_ok=True)

    if src_dir.resolve() == dst_dir.resolve():
        return

    with tempfile.TemporaryDirectory(prefix="scrinium-parser-assets-") as tmp:
        staging_dir = Path(tmp)
        for item in src_dir.iterdir():
            if item == selected_md:
                continue
            staged = staging_dir / item.name
            if item.is_dir():
                shutil.copytree(item, staged)
            else:
                shutil.copy2(item, staged)

        for item in staging_dir.iterdir():
            target = dst_dir / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)


_run_pymupdf = run_pymupdf
_pick_and_write_md = pick_and_write_md
_copy_parser_assets = copy_parser_assets
