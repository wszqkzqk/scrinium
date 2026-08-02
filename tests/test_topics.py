from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pandas as pd

from scrinium import cli
from scrinium.cli import misc as cli_misc
from scrinium.index import build_index
from scrinium.topics import get_outliers, get_topic_overview, get_topic_papers


class _FakeTopicModel:
    def __init__(self):
        self._topics = [0, 1, 0, -1]
        self._metas = [
            {
                "paper_id": "p1",
                "title": "Wave propagation in porous media",
                "authors": "Alice Zheng",
                "year": 2024,
                "journal": "JFM",
                "citation_count": {"openalex": 12},
            },
            {
                "paper_id": "p2",
                "title": "Shock response of cellular materials",
                "authors": "Bo Li",
                "year": 2023,
                "journal": "PoF",
                "citation_count": {"openalex": 8},
            },
            {
                "paper_id": "p3",
                "title": "Granular damping in porous waves",
                "authors": "Chen Wang",
                "year": 2022,
                "journal": "JFM",
                "citation_count": {"openalex": 20},
            },
            {
                "paper_id": "p4",
                "title": "Unclustered note",
                "authors": "Dana Xu",
                "year": 2021,
                "journal": "",
                "citation_count": {},
            },
        ]

    def get_topic_info(self):
        return pd.DataFrame(
            [
                {"Topic": 0, "Count": 2, "Name": "Topic 0"},
                {"Topic": 1, "Count": 1, "Name": "Topic 1"},
                {"Topic": -1, "Count": 1, "Name": "Outliers"},
            ]
        )

    def get_topic(self, topic_id: int):
        mapping = {
            0: [("granular", 0.9), ("porous", 0.8), ("waves", 0.7)],
            1: [("shock", 0.9), ("cellular", 0.8), ("impact", 0.7)],
        }
        return mapping.get(topic_id, [])


def test_get_topic_overview_sorts_topics_and_representative_papers_by_count_and_citations():
    model = _FakeTopicModel()

    overview = get_topic_overview(model)

    assert [item["topic_id"] for item in overview] == [0, 1]
    assert overview[0]["count"] == 2
    assert overview[0]["keywords"][:3] == ["granular", "porous", "waves"]
    assert [paper["paper_id"] for paper in overview[0]["representative_papers"]] == ["p3", "p1"]


def test_get_topic_papers_and_outliers_return_expected_rows():
    model = _FakeTopicModel()

    topic_zero = get_topic_papers(model, 0)
    outliers = get_outliers(model)

    assert [paper["paper_id"] for paper in topic_zero] == ["p3", "p1"]
    assert [paper["paper_id"] for paper in outliers] == ["p4"]


def _overview_messages(tmp_papers, tmp_db, tmp_path, monkeypatch, model_paper_ids):
    """Run cmd_topics overview with a fake model, return captured ui messages."""
    build_index(tmp_papers, tmp_db)

    model = _FakeTopicModel()
    model._paper_ids = model_paper_ids

    monkeypatch.setattr("scrinium.topics.load_model", lambda path: model)

    messages: list[str] = []
    monkeypatch.setattr(cli_misc, "ui", lambda msg="": messages.append(msg))

    cfg = SimpleNamespace(topics_model_dir=tmp_path / "topic_model", index_db=tmp_db)
    args = Namespace(
        build=False,
        rebuild=False,
        reduce=None,
        merge=None,
        topic=None,
        top=None,
        min_topic_size=None,
        nr_topics=None,
        viz=False,
    )
    cli.cmd_topics(args, cfg)
    return messages


class TestTopicsStalenessHint:
    """cmd_topics overview: hint compares model build size with registry count."""

    def test_stale_model_shows_rebuild_hint(self, tmp_papers, tmp_db, tmp_path, monkeypatch):
        messages = _overview_messages(tmp_papers, tmp_db, tmp_path, monkeypatch, ["p1"])

        assert any("模型基于 1 篇论文构建，当前主库 2 篇" in m for m in messages)
        assert any("模型已陈旧" in m and "topics --rebuild" in m for m in messages)

    def test_fresh_model_shows_count_without_stale_hint(self, tmp_papers, tmp_db, tmp_path, monkeypatch):
        messages = _overview_messages(tmp_papers, tmp_db, tmp_path, monkeypatch, ["p1", "p2"])

        assert any("模型基于 2 篇论文构建，当前主库 2 篇" in m for m in messages)
        assert not any("模型已陈旧" in m for m in messages)
