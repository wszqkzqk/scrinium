"""Contract tests for the CLI naming ergonomics refactor.

Covers the unified ``search`` entry point (``--mode`` / ``--scope`` dispatch),
the grouped ``enrich`` command, full-word aliases (``workspace`` / ``ingest`` /
``references`` / ``cited-by`` / ``shared-references``), the hidden legacy
aliases, and the top-level ``--help`` listing.
"""

from __future__ import annotations

import json
import re
from argparse import Namespace
from types import SimpleNamespace

import pytest

from scrinium import cli, metrics
from scrinium.cli import ingest as cli_ingest
from scrinium.cli import misc as cli_misc
from scrinium.cli import search as cli_search
from scrinium.cli import ws as cli_ws
from scrinium.index import build_index
from scrinium.workspace import add, create


def _search_ns(**overrides) -> Namespace:
    base = {
        "query": ["turbulence"],
        "mode": "keyword",
        "scope": None,
        "top": None,
        "year": None,
        "journal": None,
        "paper_type": None,
        "json": False,
        "tags": None,
    }
    base.update(overrides)
    return Namespace(**base)


class TestSearchModeDispatch:
    """cmd_search delegates --mode / --scope to the existing implementations."""

    def test_mode_unified_delegates_to_usearch(self, monkeypatch):
        seen = []
        monkeypatch.setattr(cli_search, "cmd_usearch", lambda args, cfg: seen.append(args))
        args = _search_ns(mode="unified")

        cli.cmd_search(args, SimpleNamespace())

        assert seen == [args]

    def test_mode_semantic_delegates_to_vsearch(self, monkeypatch):
        seen = []
        monkeypatch.setattr(cli_search, "cmd_vsearch", lambda args, cfg: seen.append(args))
        args = _search_ns(mode="semantic")

        cli.cmd_search(args, SimpleNamespace())

        assert seen == [args]

    def test_scope_delegates_to_fsearch_regardless_of_mode(self, monkeypatch):
        seen = []
        monkeypatch.setattr(cli_search, "cmd_fsearch", lambda args, cfg: seen.append(args))
        monkeypatch.setattr(
            cli_search,
            "cmd_usearch",
            lambda *_: pytest.fail("--scope must win over --mode"),
        )
        args = _search_ns(mode="unified", scope="main,arxiv")

        cli.cmd_search(args, SimpleNamespace())

        assert seen == [args]

    def test_keyword_mode_keeps_original_behavior(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))

        cli.cmd_search(_search_ns(json=True), cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload["count"] == 1
        assert payload["results"][0]["dir_name"] == "Smith-2023-Turbulence"

    def test_namespace_without_mode_or_scope_still_works(self, tmp_papers, tmp_db, capsys):
        # Back-compat for programmatic callers building Namespace by hand.
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))
        args = Namespace(query=["turbulence"], top=None, year=None, journal=None, paper_type=None, json=True)

        cli.cmd_search(args, cfg)

        assert json.loads(capsys.readouterr().out)["count"] == 1


class TestSearchMetricsCompat:
    """Delegating to the legacy implementations preserves metrics event names."""

    def test_mode_unified_records_usearch_event(self, tmp_papers, tmp_db, tmp_path):
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))
        store = metrics.init(tmp_path / "metrics.db", "test-session")
        try:
            cli.cmd_search(_search_ns(mode="unified", json=True), cfg)
            rows = store.query(category="search")
        finally:
            metrics.reset()

        assert [r["name"] for r in rows] == ["usearch"]


class TestSearchParserShape:
    @pytest.fixture()
    def parser(self):
        return cli._build_parser()

    def test_mode_choices_and_default(self, parser):
        args = parser.parse_args(["search", "q"])
        assert args.mode == "keyword"
        assert args.scope is None
        assert parser.parse_args(["search", "q", "--mode", "unified"]).mode == "unified"
        assert parser.parse_args(["search", "q", "--mode", "semantic"]).mode == "semantic"

    def test_scope_passthrough(self, parser):
        args = parser.parse_args(["search", "q", "--scope", "main,arxiv"])
        assert args.func is cli.cmd_search
        assert args.scope == "main,arxiv"

    def test_invalid_mode_rejected(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["search", "q", "--mode", "bogus"])


class TestLegacyAliasSmoke:
    """Every hidden legacy alias still parses to the same handler and runs."""

    @pytest.fixture()
    def parser(self):
        return cli._build_parser()

    def test_usearch_alias_runs(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))
        args = cli._build_parser().parse_args(["usearch", "turbulence", "--json"])
        assert args.func is cli.cmd_usearch

        args.func(args, cfg)

        assert json.loads(capsys.readouterr().out)["count"] == 1

    def test_vsearch_alias_runs(self, monkeypatch):
        monkeypatch.setattr("scrinium.vectors.vsearch", lambda *a, **k: [])
        messages = []
        monkeypatch.setattr(cli_search, "ui", lambda msg="": messages.append(msg))
        cfg = SimpleNamespace(index_db="unused.db", embed=SimpleNamespace(top_k=10))
        args = cli._build_parser().parse_args(["vsearch", "turbulence"])
        assert args.func is cli.cmd_vsearch

        args.func(args, cfg)

        assert any("未找到" in m for m in messages)

    def test_fsearch_alias_runs(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)
        messages = []
        monkeypatch.setattr(cli_search, "ui", lambda msg="": messages.append(msg))
        cfg = SimpleNamespace(index_db=tmp_db, papers_dir=tmp_papers, search=SimpleNamespace(top_k=10))
        args = cli._build_parser().parse_args(["fsearch", "turbulence", "--scope", "main"])
        assert args.func is cli.cmd_fsearch

        args.func(args, cfg)

        assert any("主库" in m for m in messages)
        assert any("Smith-2023-Turbulence" in m for m in messages)

    def test_enrich_toc_alias_runs(self, tmp_papers, monkeypatch):
        monkeypatch.setattr("scrinium.loader.enrich_toc", lambda *a, **k: True)
        monkeypatch.setattr(cli_ingest, "ui", lambda *_a, **_k: None)
        args = cli._build_parser().parse_args(["enrich-toc", "Smith-2023-Turbulence"])
        assert args.func is cli.cmd_enrich_toc

        args.func(args, SimpleNamespace(papers_dir=tmp_papers))

    def test_enrich_l3_alias_runs(self, tmp_papers, monkeypatch):
        monkeypatch.setattr("scrinium.loader.enrich_l3", lambda *a, **k: True)
        monkeypatch.setattr(cli_ingest, "ui", lambda *_a, **_k: None)
        args = cli._build_parser().parse_args(["enrich-l3", "Smith-2023-Turbulence"])
        assert args.func is cli.cmd_enrich_l3

        args.func(args, SimpleNamespace(papers_dir=tmp_papers))

    def test_backfill_abstract_alias_runs(self, tmp_papers, monkeypatch):
        monkeypatch.setattr(
            "scrinium.ingest.metadata.backfill_abstracts",
            lambda *a, **k: {"filled": 0, "updated": 0, "skipped": 2, "failed": 0},
        )
        monkeypatch.setattr(cli_ingest, "ui", lambda *_a, **_k: None)
        args = cli._build_parser().parse_args(["backfill-abstract"])
        assert args.func is cli.cmd_backfill_abstract

        args.func(args, SimpleNamespace(papers_dir=tmp_papers))

    def test_ws_alias_runs(self, tmp_path, monkeypatch):
        create(tmp_path / "workspace" / "w1")
        messages = []
        monkeypatch.setattr(cli_ws, "ui", lambda msg="": messages.append(msg))
        args = cli._build_parser().parse_args(["ws", "list"])
        assert args.func is cli.cmd_ws

        args.func(args, SimpleNamespace(_root=tmp_path))

        assert any("w1" in m for m in messages)

    def test_refs_alias_runs(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)
        messages = []
        monkeypatch.setattr(cli_misc, "ui", lambda msg="": messages.append(msg))
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = cli._build_parser().parse_args(["refs", "Smith-2023-Turbulence"])
        assert args.func is cli.cmd_refs

        args.func(args, cfg)

        assert any("没有参考文献数据" in m for m in messages)

    def test_citing_alias_runs(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)
        messages = []
        monkeypatch.setattr(cli_misc, "ui", lambda msg="": messages.append(msg))
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = cli._build_parser().parse_args(["citing", "Smith-2023-Turbulence"])
        assert args.func is cli.cmd_citing

        args.func(args, cfg)

        assert any("没有找到引用该论文" in m for m in messages)

    def test_shared_refs_alias_runs(self, tmp_papers, tmp_db, monkeypatch):
        build_index(tmp_papers, tmp_db)
        messages = []
        monkeypatch.setattr(cli_misc, "ui", lambda msg="": messages.append(msg))
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)
        args = cli._build_parser().parse_args(["shared-refs", "Smith-2023-Turbulence", "Wang-2024-DeepLearning"])
        assert args.func is cli.cmd_shared_refs

        args.func(args, cfg)

        assert any("共同引用" in m for m in messages)


class TestEnrichGroup:
    @pytest.fixture()
    def parser(self):
        return cli._build_parser()

    def test_toc_subcommand(self, parser):
        args = parser.parse_args(["enrich", "toc", "Smith-2023-Turbulence", "--force"])
        assert args.func is cli.cmd_enrich_toc
        assert args.paper_id == "Smith-2023-Turbulence"
        assert args.force is True

    def test_conclusion_subcommand(self, parser):
        args = parser.parse_args(["enrich", "conclusion", "--all", "--max-retries", "3"])
        assert args.func is cli.cmd_enrich_l3
        assert args.all is True
        assert args.max_retries == 3

    def test_abstract_subcommand(self, parser):
        args = parser.parse_args(["enrich", "abstract", "--doi-fetch", "--dry-run"])
        assert args.func is cli.cmd_backfill_abstract
        assert args.doi_fetch is True
        assert args.dry_run is True

    def test_enrich_requires_subcommand(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args(["enrich"])

    def test_toc_subcommand_runs(self, tmp_papers, monkeypatch):
        monkeypatch.setattr("scrinium.loader.enrich_toc", lambda *a, **k: True)
        monkeypatch.setattr(cli_ingest, "ui", lambda *_a, **_k: None)
        args = cli._build_parser().parse_args(["enrich", "toc", "Smith-2023-Turbulence"])

        args.func(args, SimpleNamespace(papers_dir=tmp_papers))


class TestIngestAlias:
    def test_bare_ingest_defaults_to_ingest_preset(self):
        args = cli._build_parser().parse_args(["ingest"])
        assert args.func is cli.cmd_pipeline
        assert args.preset == "ingest"

    def test_ingest_passthrough_options(self):
        args = cli._build_parser().parse_args(["ingest", "--dry-run", "--no-api", "--force"])
        assert args.preset == "ingest"
        assert (args.dry_run, args.no_api, args.force) == (True, True, True)

    def test_ingest_runs_ingest_preset_steps(self, monkeypatch, tmp_path):
        from scrinium.ingest.pipeline import PRESETS

        seen = {}
        monkeypatch.setattr(
            "scrinium.ingest.pipeline.run_pipeline",
            lambda step_names, cfg, opts: seen.update(steps=step_names, dry_run=opts.dry_run),
        )
        args = cli._build_parser().parse_args(["ingest", "--dry-run"])

        args.func(args, SimpleNamespace())

        assert seen["steps"] == PRESETS["ingest"]
        assert seen["dry_run"] is True

    def test_pipeline_preset_still_required(self):
        # `pipeline` without preset/--steps keeps the original error behavior.
        args = cli._build_parser().parse_args(["pipeline"])
        assert args.preset is None


class TestFullWordAliases:
    @pytest.fixture()
    def parser(self):
        return cli._build_parser()

    def test_workspace_parses_like_ws(self, parser):
        for argv in (["workspace", "list"], ["ws", "list"]):
            args = parser.parse_args(argv)
            assert args.func is cli.cmd_ws
            assert args.ws_action == "list"

    def test_workspace_show_runs(self, tmp_papers, tmp_db, tmp_path, capsys):
        build_index(tmp_papers, tmp_db)
        ws_dir = tmp_path / "workspace" / "w"
        create(ws_dir)
        add(ws_dir, ["aaaa-1111"], tmp_db)
        args = cli._build_parser().parse_args(["workspace", "show", "w", "--json"])

        args.func(args, SimpleNamespace(_root=tmp_path, index_db=tmp_db))

        assert json.loads(capsys.readouterr().out)["count"] == 1

    def test_references_parses_like_refs(self, parser):
        for argv in (["references", "x"], ["refs", "x"]):
            args = parser.parse_args(argv)
            assert args.func is cli.cmd_refs
            assert args.paper_id == "x"

    def test_cited_by_parses_like_citing(self, parser):
        for argv in (["cited-by", "x"], ["citing", "x"]):
            args = parser.parse_args(argv)
            assert args.func is cli.cmd_citing
            assert args.paper_id == "x"

    def test_shared_references_parses_like_shared_refs(self, parser):
        for argv in (["shared-references", "a", "b"], ["shared-refs", "a", "b"]):
            args = parser.parse_args(argv)
            assert args.func is cli.cmd_shared_refs
            assert args.paper_ids == ["a", "b"]


class TestHiddenAliasesHelp:
    """Legacy aliases work but stay out of the top-level --help listing."""

    _HIDDEN = ("usearch", "vsearch", "fsearch", "enrich-toc", "enrich-l3", "backfill-abstract", "shared-refs")
    _HIDDEN_WORDS = ("ws", "refs", "citing")

    def test_hidden_aliases_absent_from_top_level_help(self):
        help_text = cli._build_parser().format_help()

        for name in self._HIDDEN:
            assert name not in help_text
        for name in self._HIDDEN_WORDS:
            assert not re.search(rf"(?<![\w-]){name}(?![\w-])", help_text)
        assert "SUPPRESS" not in help_text

    def test_primary_names_present_in_top_level_help(self):
        help_text = cli._build_parser().format_help()

        for name in ["search", "enrich", "ingest", "workspace", "references", "cited-by", "shared-references"]:
            assert re.search(rf"(?<![\w-]){name}(?![\w-])", help_text)

    def test_hidden_alias_own_help_still_available(self):
        parser = cli._build_parser()
        fsearch_parser = parser._subparsers._group_actions[0].choices["fsearch"]

        assert "proceedings" in fsearch_parser.format_help()
