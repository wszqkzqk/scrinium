"""Contract tests for the tag-based ``scrinium topics`` command.

Tags are topics: the overview aggregates the curated taxonomy with paper
counts, shares, and the untagged backlog; ``topics <tag>`` drills down into
one topic. Also covers ``workspace add --tag`` (the former ``--topic``).
"""

from __future__ import annotations

import json
import logging
from argparse import Namespace
from types import SimpleNamespace

import pytest

from scrinium import cli
from scrinium.index import build_index
from scrinium.tags import papers_with_tag, register_tag, set_paper_tags, topic_overview
from scrinium.workspace import create, read_paper_ids

_SMITH = "Smith-2023-Turbulence"
_WANG = "Wang-2024-DeepLearning"


def _cfg(tmp_path, tmp_papers, tmp_db=None):
    return SimpleNamespace(
        _root=tmp_path,
        papers_dir=tmp_papers,
        index_db=tmp_db or (tmp_path / "index.db"),
        search=SimpleNamespace(top_k=10),
    )


@pytest.fixture()
def tagged_lib(tmp_path, tmp_papers):
    """Library: Smith=[force-field, md], Wang=[md]; taxonomy has aliases."""
    cfg = _cfg(tmp_path, tmp_papers)
    register_tag(cfg, "force-field", aliases=["FF"], description="分子力场相关")
    register_tag(cfg, "md")
    set_paper_tags(tmp_papers / _SMITH, ["force-field", "md"])
    set_paper_tags(tmp_papers / _WANG, ["md"])
    return cfg


class TestTopicOverview:
    def test_counts_share_and_untagged(self, tagged_lib, tmp_papers):
        overview = topic_overview(tagged_lib)

        assert overview["total_papers"] == 2
        assert overview["untagged_papers"] == 0
        topics = {t["tag"]: t for t in overview["topics"]}
        assert topics["md"]["count"] == 2
        assert topics["md"]["share"] == pytest.approx(1.0)
        assert topics["force-field"]["count"] == 1
        assert topics["force-field"]["share"] == pytest.approx(0.5)
        assert topics["force-field"]["description"] == "分子力场相关"
        assert topics["force-field"]["aliases"] == ["FF"]
        # Sorted by count desc.
        assert [t["tag"] for t in overview["topics"]] == ["md", "force-field"]

    def test_untagged_papers_counted(self, tagged_lib, tmp_papers):
        set_paper_tags(tmp_papers / _WANG, [])
        overview = topic_overview(tagged_lib)

        assert overview["untagged_papers"] == 1

    def test_taxonomy_and_usage_union(self, tagged_lib):
        # A tag used on papers but never registered still appears as a topic.
        cfg = tagged_lib
        set_paper_tags(cfg.papers_dir / _WANG, ["unregistered-tag"])
        overview = topic_overview(cfg)

        tags = {t["tag"] for t in overview["topics"]}
        assert "unregistered-tag" in tags

    def test_no_tags_anywhere(self, tmp_path, tmp_papers):
        # Papers exist but nothing is tagged and the taxonomy is empty.
        cfg = _cfg(tmp_path, tmp_papers)
        overview = topic_overview(cfg)

        assert overview == {"total_papers": 2, "untagged_papers": 2, "topics": []}


class TestPapersWithTag:
    def test_alias_resolves_to_canonical(self, tagged_lib):
        tagged = papers_with_tag(tagged_lib, "FF")

        assert [pdir.name for pdir, _ in tagged] == [_SMITH]

    def test_unregistered_tag_falls_back_to_normalized(self, tagged_lib):
        set_paper_tags(tagged_lib.papers_dir / _WANG, ["loose-tag"])
        tagged = papers_with_tag(tagged_lib, "Loose Tag")

        assert [pdir.name for pdir, _ in tagged] == [_WANG]

    def test_unknown_tag_returns_empty(self, tagged_lib):
        assert papers_with_tag(tagged_lib, "nope") == []


class TestCmdTopicsOverview:
    def test_text_output(self, tagged_lib, caplog):
        args = Namespace(tag=None, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, tagged_lib)

        out = caplog.text
        assert "主题总览：2 篇论文，2 个主题" in out
        assert "md（2 篇, 100.0%）" in out
        assert "force-field（1 篇, 50.0%）  分子力场相关" in out

    def test_text_output_shows_untagged_hint(self, tagged_lib, tmp_papers, caplog):
        set_paper_tags(tmp_papers / _WANG, [])
        args = Namespace(tag=None, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, tagged_lib)

        assert "未打标: 1 篇" in caplog.text

    def test_json_output(self, tagged_lib, capsys):
        args = Namespace(tag=None, json=True)
        cli.cmd_topics(args, tagged_lib)

        payload = json.loads(capsys.readouterr().out)
        assert payload["total_papers"] == 2
        assert payload["untagged_papers"] == 0
        assert payload["topics"][0]["tag"] == "md"
        assert payload["topics"][1]["tag"] == "force-field"

    def test_empty_taxonomy_text(self, tmp_path, tmp_papers, caplog):
        cfg = _cfg(tmp_path, tmp_papers)
        args = Namespace(tag=None, json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, cfg)

        assert "主题词表为空" in caplog.text


class TestCmdTopicsDrilldown:
    def test_lists_papers_of_topic(self, tagged_lib, caplog):
        args = Namespace(tag="md", json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, tagged_lib)

        out = caplog.text
        assert "主题 md: 2 篇论文" in out
        assert "Turbulence modeling in boundary layers" in out
        assert _SMITH in out
        assert _WANG in out

    def test_alias_drilldown_uses_canonical_name(self, tagged_lib, caplog):
        args = Namespace(tag="FF", json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, tagged_lib)

        out = caplog.text
        assert "主题 force-field: 1 篇论文" in out
        assert _SMITH in out
        assert _WANG not in out

    def test_json_drilldown(self, tagged_lib, capsys):
        args = Namespace(tag="md", json=True)
        cli.cmd_topics(args, tagged_lib)

        payload = json.loads(capsys.readouterr().out)
        assert payload["topic"] == "md"
        assert payload["count"] == 2
        names = {p["dir_name"] for p in payload["papers"]}
        assert names == {_SMITH, _WANG}
        # Newest year first.
        assert payload["papers"][0]["year"] == 2024

    def test_unknown_tag_raises_with_taxonomy_hint(self, tagged_lib):
        args = Namespace(tag="nope", json=False)
        with pytest.raises(ValueError, match="未知标签: nope") as exc_info:
            cli.cmd_topics(args, tagged_lib)

        assert "force-field" in str(exc_info.value)

    def test_known_topic_without_papers(self, tagged_lib, caplog):
        set_paper_tags(tagged_lib.papers_dir / _SMITH, ["md"])
        args = Namespace(tag="force-field", json=False)
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_topics(args, tagged_lib)

        assert "主题 force-field 下没有论文" in caplog.text


class TestWorkspaceAddTag:
    """``workspace add --tag`` replaces the removed ``--topic`` flag."""

    def _ws_args(self, tag):
        return Namespace(
            ws_action="add",
            name="ws",
            paper_refs=[],
            add_all=False,
            add_tag=tag,
            add_search=None,
        )

    def test_add_by_tag(self, tagged_lib, tmp_path, tmp_db, caplog):
        build_index(tagged_lib.papers_dir, tmp_db)
        cfg = _cfg(tmp_path, tagged_lib.papers_dir, tmp_db)
        ws_dir = tmp_path / "workspace" / "ws"
        create(ws_dir)

        args = self._ws_args("md")
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_ws(args, cfg)

        assert read_paper_ids(ws_dir) == {"aaaa-1111", "bbbb-2222"}
        assert "主题 md: 找到 2 篇论文" in caplog.text

    def test_add_by_tag_alias(self, tagged_lib, tmp_path, tmp_db, caplog):
        build_index(tagged_lib.papers_dir, tmp_db)
        cfg = _cfg(tmp_path, tagged_lib.papers_dir, tmp_db)
        ws_dir = tmp_path / "workspace" / "ws"
        create(ws_dir)

        args = self._ws_args("FF")
        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_ws(args, cfg)

        assert read_paper_ids(ws_dir) == {"aaaa-1111"}
        assert "主题 force-field: 找到 1 篇论文" in caplog.text

    def test_add_unknown_tag_raises_and_does_not_add(self, tagged_lib, tmp_path, tmp_db):
        build_index(tagged_lib.papers_dir, tmp_db)
        cfg = _cfg(tmp_path, tagged_lib.papers_dir, tmp_db)
        ws_dir = tmp_path / "workspace" / "ws"
        create(ws_dir)

        args = self._ws_args("nope")
        with pytest.raises(ValueError, match="未知标签: nope") as exc_info:
            cli.cmd_ws(args, cfg)

        assert read_paper_ids(ws_dir) == set()
        assert "force-field" in str(exc_info.value)  # taxonomy hint lists known tags

    def test_parser_accepts_add_tag(self):
        args = cli._build_parser().parse_args(["workspace", "add", "ws", "--tag", "md"])
        assert args.add_tag == "md"

    def test_parser_rejects_removed_topic_flag(self):
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(["workspace", "add", "ws", "--topic", "3"])
