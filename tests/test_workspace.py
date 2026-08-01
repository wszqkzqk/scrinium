"""Contract tests for workspace management.

Verifies: create initializes workspace, read_paper_ids returns correct set,
internal consistency of papers.json is maintained.
"""

from __future__ import annotations

import json
import sqlite3
from argparse import Namespace
from types import SimpleNamespace

import pytest

from scholaraio import cli
from scholaraio.cli import ws as cli_ws
from scholaraio.index import build_index
from scholaraio.workspace import add, create, list_workspaces, read_paper_ids, remove, rename, validate_workspace_name


class TestWorkspaceCreate:
    """Workspace creation contract."""

    def test_create_initializes_directory(self, tmp_path):
        ws_dir = tmp_path / "workspace" / "test-ws"
        create(ws_dir)
        assert ws_dir.is_dir()
        assert (ws_dir / "papers.json").exists()

    def test_create_idempotent(self, tmp_path):
        ws_dir = tmp_path / "workspace" / "test-ws"
        create(ws_dir)
        create(ws_dir)
        # Should not corrupt existing papers.json
        data = json.loads((ws_dir / "papers.json").read_text())
        assert data == []


class TestReadPaperIds:
    """read_paper_ids contract: returns set of UUIDs from papers.json."""

    def test_empty_workspace(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        assert read_paper_ids(ws_dir) == set()

    def test_reads_ids_from_papers_json(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        # Write entries directly to simulate add()
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "papers.json").write_text(json.dumps(entries))

        ids = read_paper_ids(ws_dir)
        assert ids == {"aaaa-1111", "bbbb-2222"}

    def test_nonexistent_workspace_returns_empty(self, tmp_path):
        ids = read_paper_ids(tmp_path / "nonexistent")
        assert ids == set()


class TestAddResolved:
    """add(resolved=...) contract: batch-add pre-resolved papers."""

    def test_adds_and_deduplicates(self, tmp_path):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        resolved = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test"},
        ]
        added = add(ws_dir, [], tmp_path / "unused.db", resolved=resolved)
        assert len(added) == 2
        assert read_paper_ids(ws_dir) == {"aaaa-1111", "bbbb-2222"}

        # Second call with overlap — only new paper added
        resolved2 = [
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test"},
            {"id": "cccc-3333", "dir_name": "Li-2025-New"},
        ]
        added2 = add(ws_dir, [], tmp_path / "unused.db", resolved=resolved2)
        assert len(added2) == 1
        assert added2[0]["id"] == "cccc-3333"
        assert read_paper_ids(ws_dir) == {"aaaa-1111", "bbbb-2222", "cccc-3333"}


class TestRemove:
    def test_remove_falls_back_to_workspace_dir_name_when_lookup_misses(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        monkeypatch.setattr("scholaraio.index.lookup_paper", lambda db_path, ref: None)

        removed = remove(ws_dir, ["Smith-2023-Test"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Smith-2023-Test"]
        assert read_paper_ids(ws_dir) == {"bbbb-2222"}

    def test_remove_lookup_miss_does_not_delete_uuid_collision_entry(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "real-uuid-1", "dir_name": "SharedRef", "added_at": "2024-01-01"},
            {"id": "SharedRef", "dir_name": "Other-Paper", "added_at": "2024-01-01"},
        ]
        (ws_dir / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        monkeypatch.setattr("scholaraio.index.lookup_paper", lambda db_path, ref: None)

        removed = remove(ws_dir, ["SharedRef"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Other-Paper"]
        assert read_paper_ids(ws_dir) == {"real-uuid-1"}

    def test_remove_falls_back_when_lookup_raises_sqlite_error(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        entries = [
            {"id": "aaaa-1111", "dir_name": "Smith-2023-Test", "added_at": "2024-01-01"},
            {"id": "bbbb-2222", "dir_name": "Wang-2024-Test", "added_at": "2024-01-01"},
        ]
        (ws_dir / "papers.json").write_text(json.dumps(entries), encoding="utf-8")

        def fail_lookup(db_path, ref):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("scholaraio.index.lookup_paper", fail_lookup)

        removed = remove(ws_dir, ["Smith-2023-Test"], tmp_path / "index.db")

        assert [e["dir_name"] for e in removed] == ["Smith-2023-Test"]
        assert read_paper_ids(ws_dir) == {"bbbb-2222"}


class TestListWorkspaces:
    """list_workspaces contract: discovers workspace directories."""

    def test_lists_created_workspaces(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "alpha")
        create(ws_root / "beta")

        names = list_workspaces(ws_root)
        assert set(names) == {"alpha", "beta"}

    def test_ignores_dirs_without_papers_json(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "real")
        (ws_root / "fake").mkdir(parents=True)

        names = list_workspaces(ws_root)
        assert names == ["real"]


class TestRenameWorkspace:
    """rename contract: moves workspace and validates source/target."""

    def test_rename_success(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        new_dir = rename(ws_root, "old", "new")

        assert new_dir == ws_root / "new"
        assert (ws_root / "new" / "papers.json").exists()
        assert not (ws_root / "old").exists()

    def test_rename_missing_source_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir(parents=True, exist_ok=True)

        with pytest.raises(FileNotFoundError, match="工作区不存在"):
            rename(ws_root, "missing", "new")

    def test_rename_target_exists_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")
        create(ws_root / "new")

        with pytest.raises(FileExistsError, match="目标工作区已存在"):
            rename(ws_root, "old", "new")

    def test_rename_source_is_not_directory_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir(parents=True, exist_ok=True)
        (ws_root / "old").write_text("not a directory", encoding="utf-8")

        with pytest.raises(ValueError, match="不是有效工作区目录"):
            rename(ws_root, "old", "new")

    def test_rename_source_without_papers_json_raises(self, tmp_path):
        ws_root = tmp_path / "workspace"
        (ws_root / "old").mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValueError, match=r"缺少 papers\.json"):
            rename(ws_root, "old", "new")

    def test_rename_rejects_invalid_old_name(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        with pytest.raises(ValueError, match="非法工作区名称"):
            rename(ws_root, "../old", "new")

    def test_rename_rejects_invalid_new_name(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "old")

        with pytest.raises(ValueError, match="非法工作区名称"):
            rename(ws_root, "old", "../new")


class TestValidateWorkspaceName:
    def test_accepts_regular_name(self):
        assert validate_workspace_name("my-ws_2026")

    def test_rejects_empty_or_path_like_name(self):
        assert not validate_workspace_name("")
        assert not validate_workspace_name("   ")
        assert not validate_workspace_name(".")
        assert not validate_workspace_name("../foo")
        assert not validate_workspace_name("foo/bar")
        assert not validate_workspace_name("foo\\bar")
        assert not validate_workspace_name("C:foo")
        assert not validate_workspace_name(" ws ")


def _ws_args(**kw) -> Namespace:
    base = dict(ws_action="add", name="ws", paper_refs=[], add_all=False, add_topic=None, add_search=None)
    base.update(kw)
    return Namespace(**base)


def _ws_cfg(tmp_path, db=None) -> SimpleNamespace:
    return SimpleNamespace(_root=tmp_path, index_db=db or (tmp_path / "index.db"))


class TestCmdWsMissingWorkspace:
    """cmd_ws guard: add/show on a nonexistent workspace fails instead of
    silently creating it or reporting an empty list."""

    def test_add_missing_workspace_raises_and_does_not_create(self, tmp_path):
        ws_root = tmp_path / "workspace"
        create(ws_root / "alpha")

        with pytest.raises(ValueError, match="工作区不存在: typo-ws") as exc_info:
            cli.cmd_ws(_ws_args(name="typo-ws", paper_refs=["some-ref"]), _ws_cfg(tmp_path))

        msg = str(exc_info.value)
        assert "scholaraio ws init typo-ws" in msg
        assert "alpha" in msg
        assert not (ws_root / "typo-ws").exists()

    def test_add_missing_workspace_without_any_workspace(self, tmp_path):
        with pytest.raises(ValueError, match="工作区不存在: ws") as exc_info:
            cli.cmd_ws(_ws_args(paper_refs=["some-ref"]), _ws_cfg(tmp_path))

        assert "scholaraio ws init ws" in str(exc_info.value)

    def test_show_missing_workspace_raises(self, tmp_path):
        create(tmp_path / "workspace" / "alpha")

        with pytest.raises(ValueError, match="工作区不存在: ghost") as exc_info:
            cli.cmd_ws(_ws_args(ws_action="show", name="ghost"), _ws_cfg(tmp_path))

        assert "alpha" in str(exc_info.value)

    def test_show_existing_empty_workspace_is_not_an_error(self, tmp_path, monkeypatch):
        create(tmp_path / "workspace" / "ws")
        messages: list[str] = []
        monkeypatch.setattr(cli_ws, "ui", lambda msg="": messages.append(msg))

        cli.cmd_ws(_ws_args(ws_action="show"), _ws_cfg(tmp_path))

        assert any("0 篇论文" in m for m in messages)


class TestCmdWsAddUnresolvedRefs:
    """cmd_ws add: unresolvable refs are reported per ref; rc!=0 when all fail."""

    def _run_add(self, tmp_path, tmp_db, refs, monkeypatch) -> list[str]:
        messages: list[str] = []
        monkeypatch.setattr(cli_ws, "ui", lambda msg="": messages.append(msg))
        cli.cmd_ws(_ws_args(paper_refs=refs), _ws_cfg(tmp_path, db=tmp_db))
        return messages

    def test_partial_failure_reports_each_unresolved_ref(self, tmp_papers, tmp_db, tmp_path, monkeypatch):
        build_index(tmp_papers, tmp_db)
        create(tmp_path / "workspace" / "ws")

        messages = self._run_add(tmp_path, tmp_db, ["Smith-2023-Turbulence", "bogus-ref"], monkeypatch)

        assert any("已添加 1 篇论文" in m for m in messages)
        assert "无法解析: bogus-ref" in messages

    def test_all_unresolved_raises(self, tmp_papers, tmp_db, tmp_path, monkeypatch):
        build_index(tmp_papers, tmp_db)
        create(tmp_path / "workspace" / "ws")
        monkeypatch.setattr(cli_ws, "ui", lambda msg="": None)

        with pytest.raises(ValueError, match="无法解析"):
            cli.cmd_ws(_ws_args(paper_refs=["bogus-1", "bogus-2"]), _ws_cfg(tmp_path, db=tmp_db))

    def test_add_collects_unresolved_via_out_param(self, tmp_path, monkeypatch):
        ws_dir = tmp_path / "ws"
        create(ws_dir)
        monkeypatch.setattr("scholaraio.index.lookup_paper", lambda db_path, ref: None)

        unresolved: list[str] = []
        added = add(ws_dir, ["ghost"], tmp_path / "index.db", unresolved=unresolved)

        assert added == []
        assert unresolved == ["ghost"]
