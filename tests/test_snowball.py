"""Tests for ``scrinium snowball`` — citation-graph snowball discovery.

Fixture graph (arrows = "references")::

    S -> W, X      A -> X, Y, S      B -> X, Z, S
    C -> X         D -> W, X         ISO -> (nothing)

From seed S: A/B cite S, W/X are referenced by S, and C/D share references
with S (X, resp. W+X). Y and Z sit in the library but are unreachable from S.
"""

from __future__ import annotations

import json
import logging
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrinium import cli
from scrinium.index import build_index
from scrinium.snowball import snowball_candidates
from scrinium.workspace import add, create

_PAPERS = [
    # (dir_name, uuid, doi, title, year, reference DOIs)
    ("S-2020-Seed", "uuid-s", "10.0/s", "Seed paper", 2020, ["10.0/w", "10.0/x"]),
    ("A-2021-Paper", "uuid-a", "10.0/a", "Paper A", 2021, ["10.0/x", "10.0/y", "10.0/s"]),
    ("B-2022-Paper", "uuid-b", "10.0/b", "Paper B", 2022, ["10.0/x", "10.0/z", "10.0/s"]),
    ("C-2023-Paper", "uuid-c", "10.0/c", "Paper C", 2023, ["10.0/x"]),
    ("D-2024-Paper", "uuid-d", "10.0/d", "Paper D", 2024, ["10.0/w", "10.0/x"]),
    ("W-2019-Paper", "uuid-w", "10.0/w", "Paper W", 2019, []),
    ("X-2018-Paper", "uuid-x", "10.0/x", "Paper X", 2018, []),
    ("Y-2017-Paper", "uuid-y", "10.0/y", "Paper Y", 2017, []),
    ("Z-2016-Paper", "uuid-z", "10.0/z", "Paper Z", 2016, []),
    ("ISO-2025-Alone", "uuid-iso", "10.0/iso", "Isolated paper", 2025, []),
]


def _build_library(tmp_path: Path) -> tuple[Path, Path]:
    """Create the fixture library on disk and index it."""
    papers_dir = tmp_path / "papers"
    for dir_name, uuid, doi, title, year, refs in _PAPERS:
        pdir = papers_dir / dir_name
        pdir.mkdir(parents=True)
        (pdir / "meta.json").write_text(
            json.dumps(
                {
                    "id": uuid,
                    "title": title,
                    "authors": ["Some Author"],
                    "first_author_lastname": dir_name.split("-")[0],
                    "year": year,
                    "journal": "Journal of Snowball",
                    "doi": doi,
                    "abstract": f"Abstract of {title}.",
                    "paper_type": "journal-article",
                    "citation_count": {"s2": year - 2000},
                    "references": [{"doi": r} for r in refs],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (pdir / "paper.md").write_text(f"# {title}\n", encoding="utf-8")
    db_path = tmp_path / "index.db"
    build_index(papers_dir, db_path)
    return papers_dir, db_path


def _cfg(papers_dir: Path, db_path: Path, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(papers_dir=papers_dir, index_db=db_path, _root=tmp_path)


def _args(**overrides) -> Namespace:
    base = {"paper_ids": ["S-2020-Seed"], "depth": 1, "top": None, "ws": None, "json": False}
    base.update(overrides)
    return Namespace(**base)


def _by_name(ranked: list[dict]) -> dict[str, dict]:
    return {c["dir_name"]: c for c in ranked}


class TestSnowballCandidates:
    def test_expansion_ranking_and_seed_exclusion(self, tmp_path):
        _, db_path = _build_library(tmp_path)

        ranked = snowball_candidates(["uuid-s"], db_path)

        names = [c["dir_name"] for c in ranked]
        assert names == [
            "D-2024-Paper",
            "A-2021-Paper",
            "B-2022-Paper",
            "C-2023-Paper",
            "W-2019-Paper",
            "X-2018-Paper",
        ]
        # The seed itself is never a candidate.
        assert "S-2020-Seed" not in names
        # Y/Z are in the library but unreachable from the seed.
        assert "Y-2017-Paper" not in names
        assert "Z-2016-Paper" not in names

    def test_shared_references_outrank_direct_citation(self, tmp_path):
        _, db_path = _build_library(tmp_path)

        ranked = snowball_candidates(["uuid-s"], db_path)

        by_name = _by_name(ranked)
        # D shares 2 references with the seed (W, X) -> 2*2 = 4, outranking
        # A/B which cite the seed directly but share only 1 reference.
        assert ranked[0]["dir_name"] == "D-2024-Paper"
        assert by_name["D-2024-Paper"]["score"] == 4
        assert by_name["D-2024-Paper"]["shared"] == 2
        assert by_name["A-2021-Paper"]["score"] == 3  # 2*1 shared + 1 cites-seed
        assert by_name["A-2021-Paper"]["cites_seeds"] == 1
        assert by_name["C-2023-Paper"]["score"] == 2
        assert by_name["W-2019-Paper"]["score"] == 1
        assert by_name["W-2019-Paper"]["cited_by_seeds"] == 1

    def test_relation_annotations(self, tmp_path):
        _, db_path = _build_library(tmp_path)

        by_name = _by_name(snowball_candidates(["uuid-s"], db_path))

        assert by_name["A-2021-Paper"]["relations"] == ["citing", "shared"]
        assert by_name["B-2022-Paper"]["relations"] == ["citing", "shared"]
        assert by_name["C-2023-Paper"]["relations"] == ["shared"]
        assert by_name["W-2019-Paper"]["relations"] == ["refs"]
        assert by_name["X-2018-Paper"]["relations"] == ["refs"]

    def test_multi_seed_counts_cited_by_seeds(self, tmp_path):
        _, db_path = _build_library(tmp_path)

        ranked = snowball_candidates(["uuid-s", "uuid-c"], db_path)

        by_name = _by_name(ranked)
        # C is now a seed and must not appear as a candidate.
        assert "C-2023-Paper" not in by_name
        # X is referenced by both seeds -> cited_by_seeds 2, outranking W (1).
        assert by_name["X-2018-Paper"]["cited_by_seeds"] == 2
        assert by_name["X-2018-Paper"]["score"] == 2
        assert by_name["W-2019-Paper"]["cited_by_seeds"] == 1
        assert by_name["D-2024-Paper"]["score"] == 4

    def test_ws_ids_restrict_candidates(self, tmp_path):
        _, db_path = _build_library(tmp_path)

        ranked = snowball_candidates(["uuid-s"], db_path, ws_ids={"uuid-a", "uuid-c", "uuid-w"})

        assert [c["dir_name"] for c in ranked] == ["A-2021-Paper", "C-2023-Paper", "W-2019-Paper"]


class TestSnowballCli:
    def test_json_output_parseable(self, tmp_path, capsys):
        papers_dir, db_path = _build_library(tmp_path)

        cli.cmd_snowball(_args(json=True), _cfg(papers_dir, db_path, tmp_path))

        payload = json.loads(capsys.readouterr().out)
        assert payload["seeds"] == [{"id": "uuid-s", "dir_name": "S-2020-Seed"}]
        assert payload["depth"] == 1
        assert payload["total"] == 6
        assert payload["count"] == 6
        first = payload["results"][0]
        assert first["dir_name"] == "D-2024-Paper"
        assert first["score"] == 4
        assert first["shared"] == 2
        assert first["relations"] == ["shared"]
        assert first["citation_count"] == 24  # s2 count from meta.json

    def test_seeds_resolve_by_uuid_and_doi(self, tmp_path, capsys):
        papers_dir, db_path = _build_library(tmp_path)

        cli.cmd_snowball(_args(paper_ids=["uuid-s", "10.0/c"], json=True), _cfg(papers_dir, db_path, tmp_path))

        payload = json.loads(capsys.readouterr().out)
        assert [s["id"] for s in payload["seeds"]] == ["uuid-s", "uuid-c"]
        names = {r["dir_name"] for r in payload["results"]}
        assert "C-2023-Paper" not in names

    def test_top_limits_results(self, tmp_path, capsys):
        papers_dir, db_path = _build_library(tmp_path)

        cli.cmd_snowball(_args(top=2, json=True), _cfg(papers_dir, db_path, tmp_path))

        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == 6
        assert payload["count"] == 2
        assert [r["dir_name"] for r in payload["results"]] == ["D-2024-Paper", "A-2021-Paper"]

    def test_ws_filter(self, tmp_path, capsys):
        papers_dir, db_path = _build_library(tmp_path)
        ws_dir = tmp_path / "workspace" / "ws1"
        create(ws_dir)
        add(ws_dir, ["uuid-a", "uuid-c", "uuid-w"], db_path)

        cli.cmd_snowball(_args(ws="ws1", json=True), _cfg(papers_dir, db_path, tmp_path))

        payload = json.loads(capsys.readouterr().out)
        assert [r["dir_name"] for r in payload["results"]] == ["A-2021-Paper", "C-2023-Paper", "W-2019-Paper"]

    def test_text_output_mentions_score_and_relations(self, tmp_path, caplog):
        papers_dir, db_path = _build_library(tmp_path)

        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_snowball(_args(), _cfg(papers_dir, db_path, tmp_path))

        assert "滚雪球候选共 6 篇" in caplog.text
        assert "[score 4] D-2024-Paper" in caplog.text
        assert "关系 citing+shared" in caplog.text

    def test_empty_candidates_hint(self, tmp_path, caplog):
        papers_dir, db_path = _build_library(tmp_path)

        with caplog.at_level(logging.INFO, logger="scrinium.ui"):
            cli.cmd_snowball(_args(paper_ids=["ISO-2025-Alone"]), _cfg(papers_dir, db_path, tmp_path))

        assert "引用图数据不足" in caplog.text
        assert "refetch" in caplog.text

    def test_unresolvable_seed_raises(self, tmp_path):
        papers_dir, db_path = _build_library(tmp_path)

        with pytest.raises(ValueError, match="无法解析种子论文"):
            cli.cmd_snowball(_args(paper_ids=["No-Such-Paper"]), _cfg(papers_dir, db_path, tmp_path))

    def test_depth_beyond_one_rejected(self, tmp_path):
        papers_dir, db_path = _build_library(tmp_path)

        with pytest.raises(ValueError, match="depth 1"):
            cli.cmd_snowball(_args(depth=2), _cfg(papers_dir, db_path, tmp_path))
