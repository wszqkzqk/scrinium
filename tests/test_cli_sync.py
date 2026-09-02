"""Tests for the sync command (export/import round-trip, excludes, status diff, local push/pull)."""

from __future__ import annotations

import shutil
import tarfile
from types import SimpleNamespace

import pytest

from scrinium.cli.sync import _excluded, _export, _import, _sources, cmd_sync
from scrinium.config import Config

_RSYNC_AVAILABLE = shutil.which("rsync") is not None


def _make_cfg(tmp_path):
    cfg = Config()
    cfg._root = tmp_path
    cfg.paths.papers_dir = "data/papers"
    return cfg


def _seed_kb(root):
    """Create a minimal knowledge base + workspace in root."""
    (root / "data" / "papers" / "Doe-2023-Test-Paper").mkdir(parents=True)
    (root / "data" / "papers" / "Doe-2023-Test-Paper" / "meta.json").write_text('{"title": "t"}', encoding="utf-8")
    (root / "data" / "papers" / "Doe-2023-Test-Paper" / "paper.md").write_text("# T\n", encoding="utf-8")
    (root / "data" / "tags.yaml").write_text("a: [b]\n", encoding="utf-8")
    (root / "data" / "index.db").write_bytes(b"db")
    (root / "workspace" / "ws1").mkdir(parents=True)
    (root / "workspace" / "ws1" / "papers.json").write_text("[]", encoding="utf-8")
    # Excluded items
    (root / "data" / "inbox").mkdir(parents=True)
    (root / "data" / "inbox" / "x.pdf").write_bytes(b"pdf")
    (root / "data" / "x.log").write_text("log", encoding="utf-8")
    (root / "data" / "trash").mkdir(parents=True)
    (root / "data" / "trash" / "y").write_text("t", encoding="utf-8")
    (root / "data" / "__pycache__").mkdir(parents=True)
    (root / "data" / "__pycache__" / "z.pyc").write_bytes(b"pyc")


def test_export_import_roundtrip(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _seed_kb(src)
    cfg_src = _make_cfg(src)
    out = tmp_path / "sync_backup.tar.gz"

    _export(SimpleNamespace(file=str(out)), cfg_src)
    assert out.exists()

    dst = tmp_path / "dst"
    dst.mkdir()
    cfg_dst = _make_cfg(dst)
    _import(SimpleNamespace(file=str(out)), cfg_dst)

    assert (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "meta.json").exists()
    assert (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "paper.md").exists()
    assert (dst / "data" / "tags.yaml").exists()
    assert (dst / "data" / "index.db").exists()
    assert (dst / "workspace" / "ws1" / "papers.json").exists()


def test_export_excludes_transient_and_junk(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed_kb(src)
    cfg_src = _make_cfg(src)
    out = tmp_path / "sync_backup.tar.gz"
    _export(SimpleNamespace(file=str(out)), cfg_src)

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    assert not any("inbox" in n for n in names)
    assert not any(n.endswith(".log") for n in names)
    assert not any("trash" in n for n in names)
    assert not any("__pycache__" in n for n in names)
    assert not any("metrics.db" in n for n in names)


def test_excluded_rules(tmp_path):
    assert _excluded(tmp_path / "data" / "inbox" / "x.pdf")
    assert _excluded(tmp_path / "data" / "x.log")
    assert _excluded(tmp_path / "data" / "trash" / "y")
    assert _excluded(tmp_path / "data" / "__pycache__" / "z.pyc")
    assert not _excluded(tmp_path / "data" / "papers" / "a" / "paper.md")
    assert not _excluded(tmp_path / "data" / "tags.yaml")


@pytest.mark.skipif(not _RSYNC_AVAILABLE, reason="rsync not available on this platform")
def test_push_updates_old_and_keeps_extra(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _seed_kb(src)
    cfg = _make_cfg(src)

    # 目标端：一个旧文件（将被更新）、一个源端没有的文件（默认 --update 不删）
    (dst / "data" / "papers" / "Doe-2023-Test-Paper").mkdir(parents=True)
    (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "meta.json").write_text('{"title": "old"}', encoding="utf-8")
    (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "paper.md").write_text("# old\n", encoding="utf-8")
    (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "extra.txt").write_text("keep", encoding="utf-8")

    args = SimpleNamespace(target=str(dst), mirror=False, yes=False, sync_action="push")
    cmd_sync(args, cfg)
    # 默认 --update：旧文件被更新，extra.txt 保留不删
    assert (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "paper.md").read_text(encoding="utf-8") == "# T\n"
    assert (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "extra.txt").exists()


@pytest.mark.skipif(not _RSYNC_AVAILABLE, reason="rsync not available on this platform")
def test_push_pull_local_path(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    _seed_kb(src)
    cfg = _make_cfg(src)

    # push：把 src 的内容推到 dst
    args = SimpleNamespace(target=str(dst), mirror=False, yes=False, sync_action="push")
    cmd_sync(args, cfg)
    assert (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "paper.md").exists()
    assert (dst / "workspace" / "ws1" / "papers.json").exists()

    # 修改 dst 后 pull 回 src（验证 pull 语义）
    (dst / "data" / "papers" / "Doe-2023-Test-Paper" / "new.md").write_text("new", encoding="utf-8")
    args_pull = SimpleNamespace(target=str(dst), mirror=False, yes=False, sync_action="pull")
    cmd_sync(args_pull, cfg)
    assert (src / "data" / "papers" / "Doe-2023-Test-Paper" / "new.md").exists()
