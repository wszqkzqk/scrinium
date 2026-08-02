"""Contract tests for the agent-curated tag system.

Verifies: taxonomy persistence and alias resolution, paper tag read/write,
CLI tag/tags commands, FTS schema migration for the tags column, the
paper_tags filter table, --tag exact filtering (AND semantics), and the
audit ``untagged`` rule.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from argparse import Namespace
from types import SimpleNamespace

import pytest

from scrinium import cli
from scrinium.audit import audit_papers
from scrinium.index import build_index, paper_ids_for_tags, search, unified_search
from scrinium.search_common import fts_create_sql
from scrinium.tags import (
    all_tags_with_counts,
    load_taxonomy,
    normalize_tag,
    paper_tags,
    register_tag,
    resolve_tag,
    set_paper_tags,
)
from scrinium.workspace import add, create

_SMITH = "Smith-2023-Turbulence"
_WANG = "Wang-2024-DeepLearning"

#: Pre-tags FTS layout (v0): no ``tags`` column.
_OLD_SCHEMA = fts_create_sql(
    "papers",
    [
        ("paper_id", False),
        ("title", True),
        ("authors", True),
        ("year", True),
        ("journal", True),
        ("abstract", True),
        ("conclusion", True),
        ("doi", False),
        ("paper_type", False),
        ("citation_count", False),
        ("md_path", False),
    ],
)


def _cfg(tmp_path, tmp_papers, tmp_db=None):
    return SimpleNamespace(
        _root=tmp_path,
        papers_dir=tmp_papers,
        index_db=tmp_db or (tmp_path / "index.db"),
        search=SimpleNamespace(top_k=10),
    )


def _create_old_db(db_path):
    """Create a v0 index DB: old FTS layout, no tags column, no user_version."""
    conn = sqlite3.connect(db_path)
    conn.execute(_OLD_SCHEMA)
    conn.execute("CREATE TABLE papers_hash (paper_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL)")
    conn.commit()
    conn.close()


def _user_version(db_path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class TestTaxonomy:
    def test_load_missing_returns_empty(self, tmp_path, tmp_papers):
        cfg = _cfg(tmp_path, tmp_papers)
        assert load_taxonomy(cfg) == {"tags": {}}

    def test_register_persists_and_resolves_aliases(self, tmp_path, tmp_papers):
        cfg = _cfg(tmp_path, tmp_papers)
        assert register_tag(cfg, "Force Field", description="分子力场相关", aliases=["FF", "力场"]) is True

        tax = load_taxonomy(cfg)
        entry = tax["tags"]["force-field"]
        assert entry["description"] == "分子力场相关"
        assert "FF" in entry["aliases"]

        # Case-insensitive, canonical and alias forms
        assert resolve_tag(cfg, "force-field") == "force-field"
        assert resolve_tag(cfg, "Force Field") == "force-field"
        assert resolve_tag(cfg, "ff") == "force-field"
        assert resolve_tag(cfg, "FF") == "force-field"
        assert resolve_tag(cfg, "力场") == "force-field"
        assert resolve_tag(cfg, "unknown-tag") is None

    def test_register_idempotent(self, tmp_path, tmp_papers):
        cfg = _cfg(tmp_path, tmp_papers)
        assert register_tag(cfg, "force-field") is True
        assert register_tag(cfg, "force-field") is False
        assert register_tag(cfg, "Force Field") is False  # same canonical form

    def test_register_alias_hit_is_not_new(self, tmp_path, tmp_papers):
        cfg = _cfg(tmp_path, tmp_papers)
        assert register_tag(cfg, "force-field", aliases=["FF"]) is True
        assert register_tag(cfg, "FF") is False

    def test_register_blank_name_raises(self, tmp_path, tmp_papers):
        cfg = _cfg(tmp_path, tmp_papers)
        with pytest.raises(ValueError):
            register_tag(cfg, "   ")

    def test_normalize_tag(self):
        assert normalize_tag("Force  Field_X") == "force-field-x"
        assert normalize_tag("  MD--Simulation ") == "md-simulation"


class TestPaperTags:
    def test_default_empty(self, tmp_papers):
        assert paper_tags(tmp_papers / _SMITH) == []

    def test_set_dedup_preserves_order(self, tmp_papers):
        d = tmp_papers / _SMITH
        set_paper_tags(d, ["md", "force-field", "md"])
        assert paper_tags(d) == ["md", "force-field"]
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert meta["tags"] == ["md", "force-field"]

    def test_all_tags_with_counts(self, tmp_path, tmp_papers):
        set_paper_tags(tmp_papers / _SMITH, ["md", "force-field"])
        set_paper_tags(tmp_papers / _WANG, ["md"])
        cfg = _cfg(tmp_path, tmp_papers)
        counts = all_tags_with_counts(cfg)
        assert counts == {"md": 2, "force-field": 1}


class TestCliTag:
    def test_add_tags_auto_registers(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(paper_id=_SMITH, tags=["Force Field", "MD"], remove=False, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tag(args, cfg)

        out = caplog.text
        assert "新标签已加入词表: force-field" in out
        assert "新标签已加入词表: md" in out
        assert paper_tags(tmp_papers / _SMITH) == ["force-field", "md"]
        assert resolve_tag(cfg, "Force Field") == "force-field"

    def test_add_alias_resolves_to_canonical(self, tmp_path, tmp_papers, capsys):
        cfg = _cfg(tmp_path, tmp_papers)
        register_tag(cfg, "force-field", aliases=["FF"])
        args = Namespace(paper_id=_SMITH, tags=["ff"], remove=False, json=True)
        cli.cmd_tag(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload["tags"] == ["force-field"]
        assert payload["added"] == ["force-field"]
        assert payload["new_tags"] == []  # alias hit, nothing registered

    def test_show_current_tags(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        set_paper_tags(tmp_papers / _SMITH, ["md"])
        args = Namespace(paper_id=_SMITH, tags=[], remove=False, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tag(args, cfg)
        assert "md" in caplog.text

    def test_show_empty_tags(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(paper_id=_WANG, tags=[], remove=False, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tag(args, cfg)
        assert "暂无标签" in caplog.text

    def test_remove_tags(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        register_tag(cfg, "force-field", aliases=["FF"])
        set_paper_tags(tmp_papers / _SMITH, ["force-field", "md"])
        args = Namespace(paper_id=_SMITH, tags=["ff"], remove=True, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tag(args, cfg)

        assert "已移除标签: force-field" in caplog.text
        assert paper_tags(tmp_papers / _SMITH) == ["md"]

    def test_json_add_output(self, tmp_path, tmp_papers, capsys):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(paper_id=_SMITH, tags=["md"], remove=False, json=True)
        cli.cmd_tag(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload["paper"] == _SMITH
        assert payload["tags"] == ["md"]
        assert payload["added"] == ["md"]
        assert payload["new_tags"] == ["md"]
        assert payload["removed"] == []


class TestCliTags:
    def test_lists_aliases_counts_and_total(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        register_tag(cfg, "force-field", aliases=["FF"], description="分子力场相关")
        register_tag(cfg, "md")
        set_paper_tags(tmp_papers / _SMITH, ["force-field", "md"])
        set_paper_tags(tmp_papers / _WANG, ["md"])

        args = Namespace(json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tags(args, cfg)

        out = caplog.text
        assert "force-field（别名: FF）: 1 篇" in out
        assert "md: 2 篇" in out
        assert "总计: 2 个标签，3 次标注" in out

    def test_json_output(self, tmp_path, tmp_papers, capsys):
        cfg = _cfg(tmp_path, tmp_papers)
        register_tag(cfg, "md")
        set_paper_tags(tmp_papers / _SMITH, ["md"])

        args = Namespace(json=True)
        cli.cmd_tags(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload["count"] == 1
        entry = payload["tags"][0]
        assert entry["name"] == "md"
        assert entry["count"] == 1
        assert entry["aliases"] == []

    def test_empty_taxonomy(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_tags(args, cfg)
        assert "标签词表为空" in caplog.text


class TestTagSearchFilter:
    @pytest.fixture()
    def tagged_index(self, tmp_path, tmp_papers, tmp_db):
        """Library with tags indexed: Smith=[force-field, md], Wang=[md]."""
        register_tag(_cfg(tmp_path, tmp_papers), "force-field", aliases=["FF"])
        register_tag(_cfg(tmp_path, tmp_papers), "md")
        set_paper_tags(tmp_papers / _SMITH, ["force-field", "md"])
        set_paper_tags(tmp_papers / _WANG, ["md"])
        build_index(tmp_papers, tmp_db)
        return _cfg(tmp_path, tmp_papers, tmp_db)

    def test_search_tag_filter(self, tagged_index, tmp_db):
        results = search("for", tmp_db, top_k=10, tags=["force-field"])
        assert [r["dir_name"] for r in results] == [_SMITH]
        assert results[0]["tags"] == ["force-field", "md"]

    def test_tag_filter_and_semantics(self, tagged_index, tmp_db):
        both = search("for", tmp_db, top_k=10, tags=["md"])
        assert {r["dir_name"] for r in both} == {_SMITH, _WANG}
        intersection = search("for", tmp_db, top_k=10, tags=["md", "force-field"])
        assert [r["dir_name"] for r in intersection] == [_SMITH]

    def test_paper_ids_for_tags(self, tagged_index, tmp_db):
        assert paper_ids_for_tags(tmp_db, ["md"]) == {"aaaa-1111", "bbbb-2222"}
        assert paper_ids_for_tags(tmp_db, ["md", "force-field"]) == {"aaaa-1111"}
        assert paper_ids_for_tags(tmp_db, ["nonexistent"]) == set()

    def test_unified_search_tag_filter(self, tagged_index, tmp_db):
        results = unified_search("for", tmp_db, top_k=10, tags=["force-field"])
        assert [r["dir_name"] for r in results] == [_SMITH]

    def test_cmd_search_unknown_tag_raises(self, tagged_index):
        args = Namespace(query=["for"], top=None, year=None, journal=None, paper_type=None, tags=["nope"], json=False)
        with pytest.raises(ValueError, match="未知标签"):
            cli.cmd_search(args, tagged_index)

    def test_cmd_search_alias_and_json_tags(self, tagged_index, capsys):
        args = Namespace(query=["for"], top=None, year=None, journal=None, paper_type=None, tags=["FF"], json=True)
        cli.cmd_search(args, tagged_index)

        payload = json.loads(capsys.readouterr().out)
        assert payload["count"] == 1
        result = payload["results"][0]
        assert result["dir_name"] == _SMITH
        assert result["tags"] == ["force-field", "md"]

    def test_ws_search_tag_filter(self, tagged_index, tmp_path, tmp_db, caplog):
        ws_dir = tmp_path / "workspace" / "ws1"
        create(ws_dir)
        add(ws_dir, ["aaaa-1111", "bbbb-2222"], tmp_db)
        args = Namespace(
            ws_action="search",
            name="ws1",
            query=["for"],
            top=None,
            mode="keyword",
            year=None,
            journal=None,
            paper_type=None,
            tags=["force-field"],
        )
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_ws(args, tagged_index)

        out = caplog.text
        assert _SMITH in out
        assert _WANG not in out


class TestFtsMigration:
    def test_old_db_migrates_on_build(self, tmp_path, tmp_papers, tmp_db):
        _create_old_db(tmp_db)
        set_paper_tags(tmp_papers / _SMITH, ["zz-curated-tag"])

        count = build_index(tmp_papers, tmp_db)
        assert count == 2  # full reindex after migration
        assert _user_version(tmp_db) == 1

        # tags column exists and is searchable
        results = search("zz-curated-tag", tmp_db, top_k=10)
        assert [r["dir_name"] for r in results] == [_SMITH]
        # paper_tags table synced
        assert paper_ids_for_tags(tmp_db, ["zz-curated-tag"]) == {"aaaa-1111"}

    def test_old_db_migrates_on_search(self, tmp_path, tmp_papers, tmp_db):
        _create_old_db(tmp_db)
        results = search("turbulence", tmp_db, top_k=10)
        assert results == []  # FTS table recreated empty by migration
        assert _user_version(tmp_db) == 1
        # A later build repopulates the migrated schema
        build_index(tmp_papers, tmp_db)
        assert len(search("turbulence", tmp_db, top_k=10)) == 1

    def test_tag_edit_triggers_incremental_reindex(self, tmp_path, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)
        assert paper_ids_for_tags(tmp_db, ["newtag"]) == set()

        set_paper_tags(tmp_papers / _SMITH, ["newtag"])
        count = build_index(tmp_papers, tmp_db)
        assert count == 1  # only the changed paper reindexed

        assert paper_ids_for_tags(tmp_db, ["newtag"]) == {"aaaa-1111"}
        results = search("newtag", tmp_db, top_k=10)
        assert [r["dir_name"] for r in results] == [_SMITH]


class TestShowHeader:
    def test_l1_header_shows_tags(self, tmp_path, tmp_papers, caplog):
        set_paper_tags(tmp_papers / _SMITH, ["force-field", "md"])
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(paper_id=_SMITH, layer=1, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_show(args, cfg)

        assert "标签     : force-field, md" in caplog.text

    def test_l1_header_omits_tags_when_empty(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(paper_id=_SMITH, layer=1, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_show(args, cfg)
        assert "标签" not in caplog.text


class TestAuditUntagged:
    def test_untagged_papers_reported(self, tmp_papers):
        issues = audit_papers(tmp_papers)
        untagged = [i for i in issues if i.rule == "untagged"]
        assert {i.paper_id for i in untagged} == {_SMITH, _WANG}
        assert all(i.severity == "info" for i in untagged)
        assert all("scrinium tag" in i.message for i in untagged)

    def test_tagged_paper_not_reported(self, tmp_papers):
        set_paper_tags(tmp_papers / _SMITH, ["md"])
        issues = audit_papers(tmp_papers)
        untagged = [i for i in issues if i.rule == "untagged"]
        assert {i.paper_id for i in untagged} == {_WANG}
