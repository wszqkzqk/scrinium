"""
si.py — Supporting Information (SI) 检测、获取与挂接
=====================================================

SI 不是独立的库条目，而是主论文的附件，存放在主论文目录的 ``si/`` 子目录中：

    data/papers/<Author-Year-Title>/
    ├── meta.json        # "si" 字段记录 mentioned / files / fetch_status
    ├── paper.md
    └── si/
        ├── <name>.pdf     # 原始文件（PDF/Office/数据文件等，原样保留）
        ├── <name>.md      # MinerU/fallback 转换结果（进 FTS 索引）
        └── images/        # SI 图表资产（多文件合并，MinerU 图片名为哈希不冲突）

meta.json 的 ``si`` 字段::

    {
      "mentioned": true,               # 正文引用了 SI（scan 写入）
      "files": [{"name": ..., "md": "si/<name>.md", "source_url": ...,
                  "attached_by": "pipeline|agent", "attached_at": ...}],
      "fetch_status": "ok|not_found|blocked|mismatch|paywalled|error|exhausted",
      "fetch_note": "...",
      "last_attempt": "..."
    }

自动获取的信任模型：**自动优先，失败抛给模型**。规则链只产出候选 URL，
每个下载件必须通过验证（PDF magic + SI 关键词 + 主文标题/作者命中）
才允许挂接；任何失败都写入 ``fetch_status`` 并输出 handoff hint，
由 agent 通过 ``scrinium attach-si`` 接管（与自动链共用同一入库漏斗）。
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

#: 文件名疑似 SI 的模式（大小写不敏感，匹配 stem）。
_SI_FILENAME_RE = re.compile(
    r"(?:^|[-_])(si|supp|suppl|supporting|supplementary|supplemental|esi|sm)(?:[-_.\d]|$)"
    r"|^mmc\d+$"
    r"|_si_\d+$"
    r"|suppl(?:ementary)?[-_]",
    re.IGNORECASE,
)

#: 首屏文本中的 SI 标志。
_SI_TEXT_RE = re.compile(
    r"supporting\s+information|supplementary\s+(?:material|information|data|methods)"
    r"|electronic\s+supplementary\s+(?:information|material)|supplemental\s+material",
    re.IGNORECASE,
)

#: 正文中"引用了 SI"的信号（用于 scan / audit 的 mentioned 判定）。
_SI_MENTION_RE = re.compile(
    r"supporting\s+information|supplementary\s+(?:materials?|information|data|methods|notes?)"
    r"|electronic\s+supplementary|\bESI\b|see\s+the\s+SI\b|(?:figure|fig\.?|table|scheme)\s+S\d+",
    re.IGNORECASE,
)

#: 疑似 SI 被当作独立论文入库的标题模式（audit 用）。
SUSPECTED_SI_TITLE_RE = re.compile(
    r"^(supporting|supplemental|supplementary|electronic\s+supplementary)\b", re.IGNORECASE
)

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def looks_like_si_filename(name: str) -> bool:
    """按文件名判断是否疑似 SI（``ja9b12345_si_001.pdf``、``mmc1.pdf`` 等）。"""
    stem = Path(name).stem
    return bool(_SI_FILENAME_RE.search(stem))


def looks_like_si_text(text: str) -> bool:
    """按首屏文本判断是否疑似 SI（首页印有 Supporting Information 等字样）。"""
    return bool(_SI_TEXT_RE.search(text[:3000]))


def si_mentioned_in_text(text: str) -> bool:
    """判断正文是否引用了 SI（Figure S1 / see the SI / ESI 等）。"""
    return bool(_SI_MENTION_RE.search(text))


def extract_dois_from_text(text: str) -> list[str]:
    """从文本中提取 DOI 列表（小写、去尾标点，保持出现顺序去重）。"""
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
    """一个候选 SI 下载地址。

    Attributes:
        url: 下载 URL。
        source: 来源标识（``rsc`` / ``science`` / ``plos`` / ``elsevier``
            / ``nature`` / ``acs-figshare`` / ``europepmc``）。
        filename: 建议保存文件名。
        is_zip: 是否为打包文件（Europe PMC supplementaryFiles）。
    """

    url: str
    source: str
    filename: str = ""
    is_zip: bool = False


def _resolve_rsc(doi: str, session=None) -> list[SiCandidate]:
    """RSC (10.1039): suppdata URL 可从 DOI 后缀直接推导。"""
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
    """Science/AAAS (10.1126): suppl_file 命名为 ``<suffix>_sm.pdf``。"""
    suffix = doi.split("/", 1)[1]
    return [
        SiCandidate(
            url=f"https://www.science.org/doi/suppl/{doi}/suppl_file/{suffix}_sm.pdf",
            source="science",
            filename=f"{suffix}_sm.pdf",
        )
    ]


#: PLOS 期刊代码 → 子域名
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
    """PLOS (10.1371): SI 注册为 ``<doi>.sNNN`` 组件，按编号探测前 3 个。"""
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
    """Elsevier (10.1016): 经 Crossref link 拿 PII，再推导 ars.els-cdn mmc 地址。"""
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
    """Nature/Springer (10.1038): 抓文章页提取 ESM 链接（含 zip 包）。"""
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
    """ACS (10.1021): SI 托管在 Figshare，按 resource_doi 检索条目文件。"""
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
    """Europe PMC: 按 DOI 查到记录后取 supplementaryFiles 打包地址。"""
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


#: DOI 前缀 → 出版社规则解析器
_PUBLISHER_RESOLVERS = {
    "10.1021": _resolve_acs_figshare,
    "10.1039": _resolve_rsc,
    "10.1126": _resolve_science,
    "10.1371": _resolve_plos,
    "10.1016": _resolve_elsevier,
    "10.1038": _resolve_nature,
}


def resolve_si_candidates(doi: str, *, session=None) -> list[SiCandidate]:
    """解析链：出版社规则 + Europe PMC（通用结构化渠道），产出候选 SI 地址。

    每个解析器独立容错，任何失败只减少候选数量，不抛出异常。
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
    """校验转换后的 SI 文本是否确实属于主论文。

    三关：含 SI 关键词；主文标题词重合 ≥ 0.3 或第一作者姓命中。
    宁可误判为 mismatch（转交 agent），不可错挂。
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
    """转换前的廉价校验：用 PyMuPDF 抽首页文本跑 verify_si_text。

    PyMuPDF 不可用或抽取失败时放行（``(True, "skipped")``），
    最终把关由转换后的 verify_si_text 完成。
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
#  Conversion (PDF → Markdown)，复用 ingest 的 MinerU/fallback 链
# ============================================================================


def _convert_si_pdf(pdf_path: Path, si_dir: Path, cfg) -> Path | None:
    """把 SI PDF 转成 ``si/<stem>.md``，图片资产合并进 ``si/images/``。

    依次尝试：本地 MinerU → 云端 MinerU → fallback 解析器链。
    全部失败返回 ``None``（原始 PDF 仍保留）。不做长文分片，
    分片场景由 fallback 解析器（本地、不限页数）兜底。
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
#  Attach — 统一入库漏斗（自动链与 agent 接管共用）
# ============================================================================

#: fetch_status 终态；处于这些状态的论文不再自动重试
TERMINAL_STATUSES = frozenset({"ok", "exhausted", "paywalled"})


def _unique_dest(si_dir: Path, name: str) -> Path:
    """避免同名覆盖：``a.pdf`` 已存在时给 ``a-2.pdf``。"""
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
    """把一个文件作为 SI 挂接到论文目录（统一入库漏斗）。

    流程：验证（可选）→ 复制原件到 ``si/`` → PDF 转 Markdown（可选）→
    更新 meta.json 的 ``si`` 字段。索引由调用方批量重建。

    验证策略按来源信任度区分：

    - ``verify=True``（严格，agent 手动挂接的默认）：来源不明，要求 SI
      关键词 + 主文标题/作者命中，失败即 mismatch 不留痕迹。
    - ``verify=False``（DOI 来源绑定的自动链）：URL 由 DOI 推导或文件
      经 DOI 匹配，归属已由来源保证，跳过内容验证（图版 SI 没有可验证
      文本，硬验证只会误杀）；仍记录 ``verify_note`` 供事后抽查。

    Args:
        paper_d: 论文目录。
        src_path: SI 原始文件（PDF/Office/数据文件均可）。
        cfg: 全局配置（convert 需要；纯复制可为 ``None``）。
        md_path: 已转换好的 Markdown（inbox 路由复用，跳过再转换）。
        source_url: 来源 URL（审计追溯）。
        attached_by: ``"pipeline"`` | ``"agent"``。
        convert: 是否转换 PDF 为 Markdown（``--no-convert`` 时只存原件）。
        verify: 是否做严格内容验证。
        dry_run: 预览模式，不写任何文件。

    Returns:
        结果字典 ``{"ok": bool, "status": str, "message": str, "record": dict|None}``。
    """
    src_path = Path(src_path)
    result: dict = {"ok": False, "status": "", "message": "", "record": None}
    try:
        meta = read_meta(paper_d)
    except (ValueError, FileNotFoundError) as exc:
        result.update(status="error", message=f"无法读取 meta.json: {exc}")
        return result

    if dry_run:
        result.update(
            ok=True,
            status="dry_run",
            message=f"[dry-run] 将挂接 {src_path.name} -> {paper_d.name}/si/（attached_by={attached_by}）",
        )
        return result

    # verify first: a mismatch must not leave any files behind
    if verify and md_path is not None and md_path.exists():
        ok, reason = verify_si_text(md_path.read_text(encoding="utf-8", errors="replace"), meta)
        if not ok:
            result.update(status="mismatch", message=f"SI 验证失败: {reason}")
            return result
    if verify and md_path is None and src_path.suffix.lower() == ".pdf":
        ok, reason = _preflight_verify_pdf(src_path, meta)
        if not ok:
            result.update(status="mismatch", message=f"SI 预检失败: {reason}")
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
                result.update(status="mismatch", message=f"SI 验证失败: {reason}")
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

    result.update(ok=True, status="ok", message=f"已挂接 {dest_src.name} -> {paper_d.name}/si/", record=record)
    return result


# ============================================================================
#  Fetch — 自动获取（候选解析 → 下载 → 验证 → 挂接）
# ============================================================================

_DOWNLOAD_TIMEOUT = 30
_MAX_BYTES = 200 * 1024 * 1024  # 200 MB

#: 多个候选都失败时，优先记录最有行动价值的状态
_STATUS_PRIORITY = ("mismatch", "blocked", "paywalled", "error", "not_found")


def _download(url: str, dest: Path, session) -> str:
    """下载 URL 到 dest。返回 ``"ok"`` | ``"blocked"`` | ``"paywalled"`` | ``"error"``。"""
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
    """更新 meta.json 的 si.fetch_status / fetch_note / last_attempt。"""
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


#: zip 内文件名疑似 SI 的模式（Europe PMC 包混有正文图片/主文 PDF，需过滤）
_ZIP_SI_NAME_RE = re.compile(
    r"(?:^|[-_.])(s\d{3}|si|supp|sapp|suppl|supporting|supplementary|supplemental|esi|sm|mmc\d*|esm|additional|appendix|sd)(?:[-_.\d]|$)",
    re.IGNORECASE,
)
_ZIP_SKIP_EXT = frozenset({".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".svg", ".bmp"})


def _attach_zip(zip_path: Path, pdir: Path, cfg, cand: SiCandidate, *, convert: bool) -> int:
    """解开打包文件并逐个挂接，返回成功挂接的文件数。

    只挂接疑似 SI 的成员：PDF 要求文件名命中 SI 模式（``s001.pdf`` 等，
    避免误挂主文 PDF），数据类文件（xlsx/csv/xyz 等）直接收，图片跳过。
    PDF 走转换；其余原样保留。
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
    """对单篇论文跑自动 SI 获取链，返回 fetch_status。

    候选依次尝试：下载 → magic 检查 → 验证 → 挂接；任一候选成功即 ``ok``。
    全部失败时按 _STATUS_PRIORITY 记录最有行动价值的状态并写 meta.json。
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
    """汇总一篇论文的 SI 状态（scan/status 共用）。

    ``mentioned`` 优先读 meta.json 的缓存值，缺失时现场扫描 paper.md。
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
