"""Contract tests for ``--json`` output of core read commands.

Verifies: stdout carries a single parseable JSON payload with stable
snake_case fields, and decorative output (headers, next-step hints) is
suppressed so the output can be piped directly.
"""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from scrinium import cli
from scrinium.index import build_index
from scrinium.workspace import add, create


class TestSearchJson:
    def test_search_json_outputs_parseable_results(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))
        args = Namespace(query=["turbulence"], top=None, year=None, journal=None, paper_type=None, json=True)

        cli.cmd_search(args, cfg)

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["query"] == "turbulence"
        assert payload["count"] == 1
        result = payload["results"][0]
        assert result["id"] == "aaaa-1111"
        assert result["dir_name"] == "Smith-2023-Turbulence"
        assert result["doi"] == "10.1234/jfm.2023.001"
        assert "下一步" not in out


class TestShowJson:
    def test_show_json_layer2_includes_metadata_and_abstract(self, tmp_papers, capsys):
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="Smith-2023-Turbulence", layer=2, json=True)

        cli.cmd_show(args, cfg)

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["id"] == "aaaa-1111"
        assert payload["dir_name"] == "Smith-2023-Turbulence"
        assert payload["title"] == "Turbulence modeling in boundary layers"
        assert payload["authors"] == ["John Smith", "Jane Doe"]
        assert payload["doi"] == "10.1234/jfm.2023.001"
        assert payload["abstract"].startswith("We propose a novel turbulence model")
        assert "conclusion" not in payload
        assert "content" not in payload
        assert "---" not in out

    def test_show_json_includes_notes_field_when_present(self, tmp_papers, capsys):
        (tmp_papers / "Smith-2023-Turbulence" / "notes.md").write_text(
            "## 2026-08-01 | test | analysis\n- Key finding\n",
            encoding="utf-8",
        )
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_papers / "index.db")
        args = Namespace(paper_id="aaaa-1111", layer=1, json=True)

        cli.cmd_show(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert "Key finding" in payload["notes"]


class TestTopCitedJson:
    def test_top_cited_json_outputs_parseable_results(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)
        cfg = SimpleNamespace(index_db=tmp_db, search=SimpleNamespace(top_k=10))
        args = Namespace(top=None, year=None, journal=None, paper_type=None, json=True)

        cli.cmd_top_cited(args, cfg)

        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["count"] == 2
        result = payload["results"][0]
        assert result["id"] == "aaaa-1111"
        assert result["dir_name"] == "Smith-2023-Turbulence"
        assert result["citation_count"] == "12"
        assert "下一步" not in out


class TestWsShowJson:
    def test_ws_show_json_outputs_papers_array(self, tmp_papers, tmp_db, tmp_path, capsys):
        build_index(tmp_papers, tmp_db)
        ws_dir = tmp_path / "workspace" / "ws"
        create(ws_dir)
        add(ws_dir, ["aaaa-1111"], tmp_db)
        cfg = SimpleNamespace(_root=tmp_path, index_db=tmp_db)
        args = Namespace(ws_action="show", name="ws", json=True)

        cli.cmd_ws(args, cfg)

        payload = json.loads(capsys.readouterr().out)
        assert payload["workspace"] == "ws"
        assert payload["count"] == 1
        assert payload["papers"][0]["id"] == "aaaa-1111"
        assert payload["papers"][0]["dir_name"] == "Smith-2023-Turbulence"
