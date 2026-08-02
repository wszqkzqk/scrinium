from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from scrinium.log import ui

from . import manifest as manifest_mod
from . import storage as storage_mod
from .constants import _MANIFEST_REQUEST_TIMEOUT, TOOL_REGISTRY
from .indexing import _index_tool
from .paths import _validate_version, _version_dir, validate_tool_name

if TYPE_CHECKING:
    from scrinium.config import Config

_log = logging.getLogger(__name__)


def _indexed_count_unit(info: dict) -> str:
    return "文档页面" if info.get("source_type") == "manifest" else "文档条目"


def _refresh_manifest_meta(tool: str, info: dict, version: str, force: bool, cfg: Config | None = None) -> dict:
    vdir = _version_dir(tool, version, cfg)
    meta_path = vdir / "meta.json"
    meta = {
        "tool": tool,
        "display_name": info["display_name"],
        "version": version,
        "format": info["format"],
        "repo": info.get("repo", ""),
        "source_type": info.get("source_type", "manifest"),
        "force_refreshed": force,
    }
    if meta_path.exists():
        try:
            meta.update(json.loads(meta_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            _log.warning("读取 toolref meta.json 失败，使用默认元数据重建: %s", e)
    fetched_pages = manifest_mod._manifest_page_count(vdir)
    expected_pages = manifest_mod._expected_manifest_pages(tool, version, cfg)
    meta["fetched_pages"] = fetched_pages
    meta["expected_pages"] = expected_pages
    meta["failed_pages"] = max(expected_pages - fetched_pages, 0)
    if "failed_page_names" not in meta:
        meta["failed_page_names"] = []
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def _clone_git_docs(tool: str, info: dict, version: str | None, cfg: Config | None = None) -> str:
    tag = f"{info['tag_prefix']}{version}" if version else None

    with tempfile.TemporaryDirectory(prefix=f"toolref-{tool}-") as tmpdir:
        clone_cmd = ["git", "clone", "--depth", "1"]
        if tag:
            clone_cmd += ["--branch", tag]
        clone_cmd += [info["repo"], tmpdir]

        ui(f"[toolref] 正在拉取 {info['display_name']} {version or 'latest'} 文档...")
        try:
            subprocess.run(clone_cmd, capture_output=True, text=True, check=True, timeout=120)
        except subprocess.CalledProcessError as e:
            _log.error("git clone 失败：%s", e.stderr[:500])
            raise RuntimeError(f"拉取 {tool} 文档失败。请检查版本号和网络。") from e

        resolved_version = version
        if not resolved_version:
            try:
                result = subprocess.run(
                    ["git", "-C", tmpdir, "describe", "--tags", "--abbrev=0"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                detected_tag = result.stdout.strip()
                resolved_version = detected_tag.removeprefix(info["tag_prefix"])
            except subprocess.CalledProcessError:
                resolved_version = "latest"

        vdir = _version_dir(tool, resolved_version, cfg)
        vdir.mkdir(parents=True, exist_ok=True)

        tmppath = Path(tmpdir)
        if info["format"] == "def":
            dest = vdir / "def"
            dest.mkdir(exist_ok=True)
            for file_path in tmppath.rglob(info["doc_glob"]):
                (dest / file_path.name).write_bytes(file_path.read_bytes())
                _log.debug("提取: %s", file_path.name)
        elif info["doc_path"]:
            src = tmppath / info["doc_path"]
            if src.exists():
                dest = vdir / "src"
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
            else:
                _log.warning("文档路径不存在: %s", src)

    return resolved_version or "latest"


def _fetch_manifest_docs(tool: str, info: dict, version: str, force: bool, cfg: Config | None = None) -> None:
    vdir = _version_dir(tool, version, cfg)
    existing_pages = manifest_mod._manifest_page_count(vdir) if vdir.exists() else 0
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Scrinium/1.3 toolref-fetch"})
    manifest = manifest_mod._build_manifest(tool, version)
    prefetched_manifest_pages: dict[str, str] = {}

    if tool == "openfoam" and manifest == manifest_mod._build_openfoam_manifest(version):
        discovered_manifest, prefetched_manifest_pages = manifest_mod._discover_openfoam_manifest_bundle(
            version, session
        )
        if discovered_manifest:
            manifest = discovered_manifest
    elif tool == "bioinformatics" and manifest == manifest_mod._build_bioinformatics_manifest(version):
        discovered_manifest, prefetched_manifest_pages = manifest_mod._discover_bioinformatics_manifest(
            version,
            session,
            manifest,
            cache_vdir=vdir if vdir.exists() else None,
        )
        if discovered_manifest:
            manifest = discovered_manifest

    ui(f"[toolref] 正在拉取 {info['display_name']} {version} 官方文档页...")

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f"toolref-{tool}-") as tmpdir:
        staged_vdir = Path(tmpdir) / version
        dest = staged_vdir / "pages"
        dest.mkdir(parents=True, exist_ok=True)

        for idx, item in enumerate(manifest, start=1):
            urls = [item["url"], *item.get("fallback_urls", [])]
            primary_url = item["url"]
            base_url = primary_url.split("#", 1)[0]
            body_text: str | None = prefetched_manifest_pages.get(primary_url) or prefetched_manifest_pages.get(
                base_url
            )
            successful_url = primary_url if body_text is not None else None
            last_error: Exception | None = None

            if body_text is None:
                for url in urls:
                    try:
                        resp = session.get(url, timeout=_MANIFEST_REQUEST_TIMEOUT)
                        resp.raise_for_status()
                        body_text = resp.text
                        successful_url = url
                        break
                    except requests.RequestException as e:
                        last_error = e
                        _log.warning("拉取失败: %s (%s)", url, e)

            if body_text is None:
                failures.append(item["page_name"])
                continue

            slug = manifest_mod._slugify(item["page_name"])
            html_path = dest / f"{idx:03d}-{slug}.html"
            html_path.write_text(body_text, encoding="utf-8")
            stored_item = dict(item)
            if successful_url and urls[0] != successful_url:
                stored_item["fetched_url"] = successful_url
                if last_error is not None:
                    stored_item["primary_fetch_error"] = str(last_error)
            html_path.with_suffix(".json").write_text(
                json.dumps(stored_item, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        restored_failures: list[str] = []
        if vdir.exists() and failures:
            for page_name in failures:
                if manifest_mod._copy_manifest_page_from_cache(vdir, staged_vdir, page_name):
                    restored_failures.append(page_name)

        fetched_pages = manifest_mod._manifest_page_count(staged_vdir)
        if failures and fetched_pages == 0:
            raise RuntimeError(f"拉取 {tool} 文档页失败：{failures[0]}")

        meta = {
            "tool": tool,
            "display_name": info["display_name"],
            "version": version,
            "format": info["format"],
            "repo": info.get("repo", ""),
            "source_type": info.get("source_type", "git"),
            "force_refreshed": force,
            "fetched_pages": fetched_pages,
            "expected_pages": len(manifest),
            "failed_pages": len(manifest) - fetched_pages,
            "failed_page_names": [name for name in failures if name not in restored_failures],
        }
        if restored_failures:
            meta["last_fetch_failed_page_names"] = failures
            meta["restored_from_cache_page_names"] = restored_failures
        manifest_mod._write_manifest_snapshot(staged_vdir, manifest)
        (staged_vdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        if vdir.exists() and fetched_pages < existing_pages:
            ui(
                f"[toolref] 警告：新抓取仅得到 {fetched_pages}/{len(manifest)} 页，"
                f"低于现有缓存 {existing_pages} 页；保留现有缓存"
            )
            current_missing = manifest_mod._manifest_missing_page_names(vdir, manifest)
            preserved_meta = {
                "tool": tool,
                "display_name": info["display_name"],
                "version": version,
                "format": info["format"],
                "repo": info.get("repo", ""),
                "source_type": info.get("source_type", "git"),
                "force_refreshed": force,
                "fetched_pages": existing_pages,
                "expected_pages": len(manifest),
                "failed_pages": len(current_missing),
                "failed_page_names": current_missing,
                "last_fetch_failed_page_names": failures,
            }
            (vdir / "meta.json").write_text(json.dumps(preserved_meta, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            if vdir.exists():
                shutil.rmtree(vdir)
            vdir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged_vdir), str(vdir))

    if failures and manifest_mod._manifest_page_count(vdir) > 0:
        preview = "、".join(failures[:3])
        suffix = " 等" if len(failures) > 3 else ""
        ui(f"[toolref] 警告：{len(failures)} 个页面拉取失败（{preview}{suffix}），已保留更完整的可用缓存")


def toolref_fetch(
    tool: str,
    *,
    version: str | None = None,
    force: bool = False,
    cfg: Config | None = None,
) -> int:
    if not validate_tool_name(tool):
        raise ValueError(f"未知工具：{tool}。支持的工具：{', '.join(TOOL_REGISTRY)}")

    info = TOOL_REGISTRY[tool]
    source_type = info.get("source_type", "git")

    if version is None:
        version = info.get("default_version")

    if version and not _validate_version(version):
        raise ValueError(f"无效版本号：{version}")

    if version:
        vdir = _version_dir(tool, version, cfg)
        if vdir.exists() and not force:
            if manifest_mod._has_local_docs(tool, version, cfg):
                if source_type == "manifest":
                    _refresh_manifest_meta(tool, info, version, force, cfg)
                ui(f"[toolref] {info['display_name']} {version} 文档已存在，跳过拉取")
                count = _index_tool(tool, version, cfg)
                storage_mod._set_current(tool, version, cfg)
                ui(f"[toolref] {info['display_name']} {version}：已索引 {count} 个{_indexed_count_unit(info)}")
                return count
            ui(f"[toolref] 检测到 {info['display_name']} {version} 残缺目录，重新拉取")
        elif vdir.exists() and force:
            ui(f"[toolref] 强制重新拉取 {info['display_name']} {version}")

    if source_type == "git":
        version = _clone_git_docs(tool, info, version, cfg)
    elif source_type == "manifest":
        version = version or info["default_version"]
        _fetch_manifest_docs(tool, info, version, force, cfg)
    else:
        raise ValueError(f"{tool} 不支持的 source_type: {source_type}")

    vdir = _version_dir(tool, version, cfg)
    meta = {
        "tool": tool,
        "display_name": info["display_name"],
        "version": version,
        "format": info["format"],
        "repo": info.get("repo", ""),
        "source_type": source_type,
        "force_refreshed": force,
    }
    if source_type == "manifest":
        meta = _refresh_manifest_meta(tool, info, version, force, cfg)
    (vdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    storage_mod._set_current(tool, version, cfg)
    count = _index_tool(tool, version, cfg)
    ui(f"[toolref] {info['display_name']} {version}：已索引 {count} 个{_indexed_count_unit(info)}")
    return count
