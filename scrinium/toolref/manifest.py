from __future__ import annotations

import json
import logging
import re
import shutil
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from .constants import (
    _BIO_DISCOVERED_PAGE_ALIASES,
    _BIO_DISCOVERY_TIMEOUT,
    _OPENFOAM_DISCOVERY_SEEDS,
    _OPENFOAM_DISCOVERY_TIMEOUT,
    _OPENFOAM_MAX_DISCOVERY_PAGES,
    TOOL_REGISTRY,
)
from .paths import _version_dir

if TYPE_CHECKING:
    from scrinium.config import Config

_log = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return value.strip("-") or "page"


def _manifest_page_count(vdir: Path) -> int:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return 0
    count = 0
    for html_path in pages_dir.glob("*.html"):
        if html_path.with_suffix(".json").exists():
            count += 1
    return count


def _manifest_snapshot_path(vdir: Path) -> Path:
    return vdir / "manifest.json"


def _load_manifest_snapshot(vdir: Path) -> list[dict] | None:
    path = _manifest_snapshot_path(vdir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]


def _write_manifest_snapshot(vdir: Path, manifest: list[dict]) -> None:
    _manifest_snapshot_path(vdir).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_present_page_names(vdir: Path) -> set[str]:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return set()
    names: set[str] = set()
    for meta_path in pages_dir.glob("*.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        page_name = payload.get("page_name")
        if page_name and meta_path.with_suffix(".html").exists():
            names.add(page_name)
    return names


def _manifest_missing_page_names(vdir: Path, manifest: list[dict]) -> list[str]:
    present = _manifest_present_page_names(vdir)
    return [item["page_name"] for item in manifest if item["page_name"] not in present]


def _copy_manifest_page_from_cache(src_vdir: Path, dst_vdir: Path, page_name: str) -> bool:
    src_pages = src_vdir / "pages"
    dst_pages = dst_vdir / "pages"
    if not src_pages.exists() or not dst_pages.exists():
        return False
    for meta_path in src_pages.glob("*.json"):
        html_path = meta_path.with_suffix(".html")
        if not html_path.exists():
            continue
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("page_name") != page_name:
            continue
        shutil.copy2(html_path, dst_pages / html_path.name)
        shutil.copy2(meta_path, dst_pages / meta_path.name)
        return True
    return False


def _load_manifest_cached_html(vdir: Path, page_name: str) -> str | None:
    pages_dir = vdir / "pages"
    if not pages_dir.exists():
        return None
    for meta_path in pages_dir.glob("*.json"):
        html_path = meta_path.with_suffix(".html")
        if not html_path.exists():
            continue
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("page_name") != page_name:
            continue
        try:
            return html_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    return None


def _build_openfoam_manifest(version: str) -> list[dict]:
    base = f"https://doc.openfoam.com/{version}"
    return [
        {
            "program": "simpleFoam",
            "section": "solver",
            "page_name": "openfoam/simpleFoam",
            "title": "simpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/incompressible/simpleFoam/",
        },
        {
            "program": "pimpleFoam",
            "section": "solver",
            "page_name": "openfoam/pimpleFoam",
            "title": "pimpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/incompressible/pimpleFoam/",
        },
        {
            "program": "rhoSimpleFoam",
            "section": "solver",
            "page_name": "openfoam/rhoSimpleFoam",
            "title": "rhoSimpleFoam",
            "url": f"{base}/tools/processing/solvers/rtm/compressible/rhoSimpleFoam/",
        },
        {
            "program": "blockMesh",
            "section": "mesh",
            "page_name": "openfoam/blockMesh",
            "title": "blockMesh",
            "url": f"{base}/tools/pre-processing/mesh/generation/blockMesh/blockmesh/",
        },
        {
            "program": "snappyHexMesh",
            "section": "mesh",
            "page_name": "openfoam/snappyHexMesh",
            "title": "snappyHexMesh",
            "url": f"{base}/tools/pre-processing/mesh/generation/snappyhexmesh/",
        },
        {
            "program": "controlDict",
            "section": "dictionary",
            "page_name": "openfoam/controlDict",
            "title": "controlDict",
            "url": f"{base}/fundamentals/case-structure/controldict/",
        },
        {
            "program": "fvSchemes",
            "section": "dictionary",
            "page_name": "openfoam/fvSchemes",
            "title": "fvSchemes",
            "url": f"{base}/fundamentals/case-structure/fvschemes/",
        },
        {
            "program": "fvSolution",
            "section": "dictionary",
            "page_name": "openfoam/fvSolution",
            "title": "fvSolution",
            "url": f"{base}/fundamentals/case-structure/fvsolution/",
        },
        {
            "program": "kOmegaSST",
            "section": "model",
            "page_name": "openfoam/kOmegaSST",
            "title": "kOmegaSST",
            "url": f"{base}/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/",
        },
        {
            "program": "functionObjects",
            "section": "post-processing",
            "page_name": "openfoam/functionObjects",
            "title": "function objects",
            "url": f"{base}/tools/post-processing/function-objects/",
        },
        {
            "program": "forces",
            "section": "post-processing",
            "page_name": "openfoam/forces",
            "title": "forces",
            "url": f"{base}/tools/post-processing/function-objects/forces/",
        },
        {
            "program": "forceCoeffs",
            "section": "post-processing",
            "page_name": "openfoam/forceCoeffs",
            "title": "forceCoeffs",
            "url": f"{base}/tools/post-processing/function-objects/forces/forceCoeffs/",
        },
        {
            "program": "Q",
            "section": "post-processing",
            "page_name": "openfoam/Q",
            "title": "Q",
            "url": f"{base}/tools/post-processing/function-objects/field/Q/",
        },
        {
            "program": "yPlus",
            "section": "post-processing",
            "page_name": "openfoam/yPlus",
            "title": "yPlus",
            "url": f"{base}/tools/post-processing/function-objects/field/yPlus/",
        },
        {
            "program": "wallShearStress",
            "section": "post-processing",
            "page_name": "openfoam/wallShearStress",
            "title": "wallShearStress",
            "url": f"{base}/tools/post-processing/function-objects/field/wallShearStress/",
        },
        {
            "program": "residuals",
            "section": "solver-control",
            "page_name": "openfoam/residuals",
            "title": "Residuals",
            "url": f"{base}/tools/processing/numerics/solvers/residuals/",
        },
    ]


_OPENFOAM_CORE_PAGE_MAP: dict[str, tuple[str, str, str, str]] = {
    "tools/processing/solvers/rtm/incompressible/simpleFoam/": (
        "openfoam/simpleFoam",
        "simpleFoam",
        "simpleFoam",
        "solver",
    ),
    "tools/processing/solvers/rtm/incompressible/pimpleFoam/": (
        "openfoam/pimpleFoam",
        "pimpleFoam",
        "pimpleFoam",
        "solver",
    ),
    "tools/processing/solvers/rtm/compressible/rhoSimpleFoam/": (
        "openfoam/rhoSimpleFoam",
        "rhoSimpleFoam",
        "rhoSimpleFoam",
        "solver",
    ),
    "tools/pre-processing/mesh/generation/blockMesh/blockmesh/": (
        "openfoam/blockMesh",
        "blockMesh",
        "blockMesh",
        "mesh",
    ),
    "tools/pre-processing/mesh/generation/snappyhexmesh/": (
        "openfoam/snappyHexMesh",
        "snappyHexMesh",
        "snappyHexMesh",
        "mesh",
    ),
    "fundamentals/case-structure/controldict/": ("openfoam/controlDict", "controlDict", "controlDict", "dictionary"),
    "fundamentals/case-structure/fvschemes/": ("openfoam/fvSchemes", "fvSchemes", "fvSchemes", "dictionary"),
    "fundamentals/case-structure/fvsolution/": ("openfoam/fvSolution", "fvSolution", "fvSolution", "dictionary"),
    "tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/": (
        "openfoam/kOmegaSST",
        "kOmegaSST",
        "kOmegaSST",
        "model",
    ),
    "tools/post-processing/function-objects/": (
        "openfoam/functionObjects",
        "functionObjects",
        "function objects",
        "post-processing",
    ),
    "tools/post-processing/function-objects/forces/": ("openfoam/forces", "forces", "forces", "post-processing"),
    "tools/post-processing/function-objects/forces/forceCoeffs/": (
        "openfoam/forceCoeffs",
        "forceCoeffs",
        "forceCoeffs",
        "post-processing",
    ),
    "tools/post-processing/function-objects/field/Q/": ("openfoam/Q", "Q", "Q", "post-processing"),
    "tools/post-processing/function-objects/field/yPlus/": ("openfoam/yPlus", "yPlus", "yPlus", "post-processing"),
    "tools/post-processing/function-objects/field/wallShearStress/": (
        "openfoam/wallShearStress",
        "wallShearStress",
        "wallShearStress",
        "post-processing",
    ),
    "tools/processing/numerics/solvers/residuals/": ("openfoam/residuals", "residuals", "Residuals", "solver-control"),
}


def _normalize_openfoam_doc_url(url: str, version: str, *, base_url: str = "https://doc.openfoam.com") -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = base_url.rstrip("/") + url
    elif not re.match(r"^https?://", url):
        url = base_url.rstrip("/") + "/" + url.lstrip("./")
    if not url.startswith(base_url.rstrip("/") + "/"):
        return None
    url = url.split("#", 1)[0].split("?", 1)[0]
    if not url.endswith("/"):
        url += "/"
    path = url.removeprefix(base_url.rstrip("/")).lstrip("/")
    if not path.startswith(f"{version}/"):
        return None
    rel = path[len(version) + 1 :]
    if not rel or any(rel.endswith(ext) for ext in (".css/", ".js/", ".png/", ".jpg/", ".svg/", ".pdf/", ".txt/")):
        return None
    return base_url.rstrip("/") + "/" + path


def _is_openfoam_doc_path_allowed(rel_path: str) -> bool:
    return bool(rel_path) and any(rel_path.startswith(prefix) for prefix in _OPENFOAM_DISCOVERY_SEEDS)


def _extract_openfoam_doc_links(html: str, version: str, *, base_url: str = "https://doc.openfoam.com") -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"""href=["\']([^"\'#?]+(?:/)?(?:#[^"\']*)?)["\']""", html, re.IGNORECASE):
        normalized = _normalize_openfoam_doc_url(match.group(1), version, base_url=base_url)
        if not normalized:
            continue
        rel = normalized.removeprefix(base_url.rstrip("/") + f"/{version}/")
        if not _is_openfoam_doc_path_allowed(rel):
            continue
        if normalized not in links:
            links.append(normalized)
    return links


def _classify_openfoam_section(rel_path: str) -> str:
    if rel_path.startswith("fundamentals/case-structure/"):
        return "dictionary"
    if rel_path.startswith("fundamentals/"):
        return "fundamentals"
    if rel_path.startswith("tools/pre-processing/mesh/"):
        return "mesh"
    if rel_path.startswith("tools/processing/solvers/"):
        return "solver"
    if rel_path.startswith("tools/processing/models/"):
        return "model"
    if rel_path.startswith("tools/processing/numerics/"):
        return "solver-control"
    if rel_path.startswith("tools/post-processing/"):
        return "post-processing"
    if rel_path.startswith("tools/"):
        return "tool"
    return "general"


def _discover_openfoam_manifest_bundle(version: str, session: requests.Session) -> tuple[list[dict], dict[str, str]]:
    base_url = "https://doc.openfoam.com"
    base_manifest = {item["page_name"]: dict(item) for item in _build_openfoam_manifest(version)}
    queue = [base_url.rstrip("/") + f"/{version}/{seed}" for seed in _OPENFOAM_DISCOVERY_SEEDS]
    seen: set[str] = set()
    discovered: set[str] = set()
    prefetched_html: dict[str, str] = {}
    while queue and len(seen) < _OPENFOAM_MAX_DISCOVERY_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = session.get(url, timeout=_OPENFOAM_DISCOVERY_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            _log.debug("OpenFOAM discovery skip %s: %s", url, e)
            continue
        prefetched_html[url] = resp.text
        rel = url.removeprefix(base_url.rstrip("/") + f"/{version}/")
        if _is_openfoam_doc_path_allowed(rel):
            discovered.add(url)
        for child in _extract_openfoam_doc_links(resp.text, version, base_url=base_url):
            if child not in seen and child not in queue:
                queue.append(child)
    if not discovered:
        return [], {}
    rel_paths = sorted(url.removeprefix(base_url.rstrip("/") + f"/{version}/") for url in discovered)
    slug_counts: dict[str, int] = {}
    for rel_path in rel_paths:
        slug = Path(rel_path.rstrip("/")).name
        slug_counts[slug] = slug_counts.get(slug, 0) + 1
    manifest_by_page = dict(base_manifest)
    for rel_path in rel_paths:
        mapped = _OPENFOAM_CORE_PAGE_MAP.get(rel_path)
        url = base_url.rstrip("/") + f"/{version}/{rel_path}"
        if mapped:
            page_name, program, title, section = mapped
        else:
            slug = Path(rel_path.rstrip("/")).name
            program = slug
            title = slug
            section = _classify_openfoam_section(rel_path)
            if slug_counts.get(slug, 0) == 1 and slug not in {"overview", "index"}:
                page_name = f"openfoam/{slug}"
            else:
                page_name = "openfoam/" + rel_path.rstrip("/").replace("/", "__")
        manifest_by_page[page_name] = {
            "program": program,
            "section": section,
            "page_name": page_name,
            "title": title,
            "url": url,
        }
    manifest = sorted(manifest_by_page.values(), key=lambda item: (item["section"], item["page_name"]))
    return manifest, prefetched_html


def _discover_openfoam_manifest(version: str, session: requests.Session) -> list[dict]:
    manifest, _ = _discover_openfoam_manifest_bundle(version, session)
    return manifest


def _build_bioinformatics_manifest(_version: str) -> list[dict]:
    return [
        {
            "program": "blastn",
            "section": "alignment",
            "page_name": "blast/blastn",
            "title": "BLAST+ user manual",
            "url": "https://www.ncbi.nlm.nih.gov/books/NBK279690/",
        },
        {
            "program": "minimap2",
            "section": "alignment",
            "page_name": "minimap2/manual",
            "title": "minimap2 manual",
            "url": "https://lh3.github.io/minimap2/minimap2.html",
            "fallback_urls": ["https://github.com/lh3/minimap2#readme"],
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/manual",
            "title": "samtools manual",
            "url": "https://www.htslib.org/doc/samtools.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/sort",
            "title": "samtools sort",
            "url": "https://www.htslib.org/doc/samtools-sort.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/view",
            "title": "samtools view",
            "url": "https://www.htslib.org/doc/samtools-view.html",
        },
        {
            "program": "samtools",
            "section": "alignment",
            "page_name": "samtools/index",
            "title": "samtools index",
            "url": "https://www.htslib.org/doc/samtools-index.html",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/manual",
            "title": "bcftools manual",
            "url": "https://samtools.github.io/bcftools/bcftools.html",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/call",
            "title": "bcftools call",
            "url": "https://samtools.github.io/bcftools/bcftools.html#call",
        },
        {
            "program": "bcftools",
            "section": "variant-calling",
            "page_name": "bcftools/mpileup",
            "title": "bcftools mpileup",
            "url": "https://samtools.github.io/bcftools/bcftools.html#mpileup",
        },
        {
            "program": "mafft",
            "section": "phylogenetics",
            "page_name": "mafft/manual",
            "title": "MAFFT manual",
            "url": "https://mafft.cbrc.jp/alignment/software/multithreading.html",
        },
        {
            "program": "iqtree",
            "section": "phylogenetics",
            "page_name": "iqtree/command-reference",
            "title": "IQ-TREE command reference",
            "url": "https://iqtree.github.io/doc/Command-Reference",
        },
        {
            "program": "iqtree",
            "section": "phylogenetics",
            "page_name": "iqtree/ultrafast-bootstrap",
            "title": "IQ-TREE ultrafast bootstrap",
            "url": "https://iqtree.github.io/doc/Command-Reference#ultrafast-bootstrap-parameters",
            "anchor": "ultrafast-bootstrap-parameters",
        },
        {
            "program": "esmfold",
            "section": "protein-structure",
            "page_name": "esmfold/huggingface-doc",
            "title": "ESM / ESMFold documentation",
            "url": "https://huggingface.co/docs/transformers/model_doc/esm",
        },
    ]


def _build_manifest(tool: str, version: str) -> list[dict]:
    info = TOOL_REGISTRY[tool]
    manifest_name = info.get("manifest_name")
    if manifest_name == "openfoam":
        return _build_openfoam_manifest(version)
    if manifest_name == "bioinformatics":
        return _build_bioinformatics_manifest(version)
    raise ValueError(f"{tool} 未定义 manifest")


def _expected_manifest_pages(tool: str, version: str, cfg: Config | None = None) -> int:
    vdir = _version_dir(tool, version, cfg)
    snapshot = _load_manifest_snapshot(vdir)
    if snapshot:
        return len(snapshot)
    return len(_build_manifest(tool, version))


def _has_local_docs(tool: str, version: str, cfg: Config | None = None) -> bool:
    info = TOOL_REGISTRY[tool]
    vdir = _version_dir(tool, version, cfg)
    if not vdir.exists():
        return False
    if info["format"] == "def":
        return any((vdir / "def").glob("INPUT_*.def"))
    if info["format"] == "rst":
        return any((vdir / "src").rglob("*.rst"))
    if info["format"] == "html":
        page_count = (
            _manifest_page_count(vdir)
            if info.get("source_type") == "manifest"
            else len(list((vdir / "pages").glob("*.html")))
        )
        if not page_count:
            return False
        if info.get("source_type") == "manifest":
            expected = _expected_manifest_pages(tool, version, cfg)
            return page_count >= expected
        return True
    return False


def _extract_html_main(text: str) -> str:
    for pattern in (r"<main\b[^>]*>(.*?)</main>", r"<article\b[^>]*>(.*?)</article>", r"<body\b[^>]*>(.*?)</body>"):
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            body = m.group(1)
            h1_pos = body.lower().find("<h1")
            if h1_pos > 0:
                body = body[h1_pos:]
            return body
    return text


def _extract_html_headings_with_ids(html: str, *, min_level: int = 2, max_level: int = 3) -> list[dict]:
    headings: list[dict] = []
    pattern = re.compile(r"<h([1-6])\b[^>]*\bid=[\"']([^\"']+)[\"'][^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html):
        level = int(match.group(1))
        if level < min_level or level > max_level:
            continue
        title = re.sub(r"<[^>]+>", "", unescape(match.group(3)))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        headings.append({"level": level, "id": match.group(2), "title": title})
    return headings


def _extract_html_anchor_fragment(html: str, anchor: str) -> str:
    body = _extract_html_main(html)
    heading_re = re.compile(r"<h([1-6])\b[^>]*\bid=[\"']([^\"']+)[\"'][^>]*>.*?</h\1>", re.IGNORECASE | re.DOTALL)
    matches = list(heading_re.finditer(body))
    for idx, match in enumerate(matches):
        if match.group(2) != anchor:
            continue
        level = int(match.group(1))
        end = len(body)
        for nxt in matches[idx + 1 :]:
            if int(nxt.group(1)) <= level:
                end = nxt.start()
                break
        return body[match.start() : end]
    return body


def _discover_bioinformatics_manifest(
    version: str, session: requests.Session, base_manifest: list[dict], *, cache_vdir: Path | None = None
) -> tuple[list[dict], dict[str, str]]:
    del version
    prefetched_html: dict[str, str] = {}
    manifest_by_page = {item["page_name"]: dict(item) for item in base_manifest}
    for item in base_manifest:
        if item["page_name"] not in {"samtools/manual", "bcftools/manual", "iqtree/command-reference"}:
            continue
        try:
            resp = session.get(item["url"], timeout=_BIO_DISCOVERY_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            _log.debug("Bio discovery skip %s: %s", item["url"], e)
            if cache_vdir is not None:
                cached = _load_manifest_cached_html(cache_vdir, item["page_name"])
                if cached:
                    prefetched_html[item["url"]] = cached
            continue
        prefetched_html[item["url"]] = resp.text
    samtools_html = prefetched_html.get("https://www.htslib.org/doc/samtools.html")
    if samtools_html:
        seen_links: set[str] = set()
        for match in re.finditer(r'href=["\'](samtools-[a-z0-9-]+\.html)["\']', samtools_html, re.IGNORECASE):
            rel = match.group(1)
            if rel in seen_links:
                continue
            seen_links.add(rel)
            subcmd = rel.removeprefix("samtools-").removesuffix(".html")
            page_name = f"samtools/{subcmd}"
            manifest_by_page.setdefault(
                page_name,
                {
                    "program": "samtools",
                    "section": "alignment",
                    "page_name": page_name,
                    "title": f"samtools {subcmd}",
                    "url": f"https://www.htslib.org/doc/{rel}",
                },
            )
    bcftools_html = prefetched_html.get("https://samtools.github.io/bcftools/bcftools.html")
    if bcftools_html:
        for heading in _extract_html_headings_with_ids(bcftools_html):
            hid = heading["id"]
            if hid.startswith("_"):
                continue
            if not (
                heading["title"].lower().startswith("bcftools ")
                or hid in {"common_options", "expressions", "terminology"}
            ):
                continue
            page_name = f"bcftools/{hid.replace('_', '-')}"
            item = manifest_by_page.get(page_name, {})
            item.update(
                {
                    "program": "bcftools",
                    "section": "variant-calling",
                    "page_name": page_name,
                    "title": heading["title"],
                    "url": f"https://samtools.github.io/bcftools/bcftools.html#{hid}",
                    "anchor": hid,
                }
            )
            manifest_by_page[page_name] = item
    iqtree_html = prefetched_html.get("https://iqtree.github.io/doc/Command-Reference")
    if iqtree_html:
        for heading in _extract_html_headings_with_ids(iqtree_html):
            hid = heading["id"]
            if hid in {"command-reference", "example-usages"}:
                continue
            page_name = f"iqtree/{hid.replace('_', '-').replace(' ', '-')}"
            item = manifest_by_page.get(page_name, {})
            item.update(
                {
                    "program": "iqtree",
                    "section": "phylogenetics",
                    "page_name": page_name,
                    "title": heading["title"],
                    "url": f"https://iqtree.github.io/doc/Command-Reference#{hid}",
                    "anchor": hid,
                }
            )
            manifest_by_page[page_name] = item
    for page_name, alias in _BIO_DISCOVERED_PAGE_ALIASES.items():
        if page_name not in manifest_by_page or alias["source_page"] not in manifest_by_page:
            continue
        item = manifest_by_page[page_name]
        source_item = manifest_by_page[alias["source_page"]]
        item["url"] = source_item["url"]
        item["anchor"] = alias["anchor"]
    manifest = sorted(manifest_by_page.values(), key=lambda item: (item["program"], item["page_name"]))
    return manifest, prefetched_html
