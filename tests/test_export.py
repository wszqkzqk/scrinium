"""Contract tests for BibTeX export.

Verifies: given well-formed metadata, export produces valid BibTeX.
Does NOT test: internal helper functions, exact string formatting.
"""

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pytest

from scrinium import cli
from scrinium.cli import common as cli_common
from scrinium.export import export_bibtex, meta_to_bibtex
from scrinium.index import build_index


class TestMetaToBibtex:
    """Single-entry BibTeX conversion contract."""

    def test_journal_article_has_required_fields(self):
        meta = {
            "title": "Some Title",
            "authors": ["Alice", "Bob"],
            "year": 2023,
            "journal": "Nature",
            "doi": "10.1234/test",
            "paper_type": "journal-article",
            "first_author_lastname": "Alice",
        }
        bib = meta_to_bibtex(meta)
        assert bib.startswith("@article{")
        assert "Some Title" in bib
        assert "author = {Alice and Bob}" in bib
        assert "year = {2023}" in bib
        assert "doi = {10.1234/test}" in bib

    def test_thesis_maps_to_phdthesis(self):
        meta = {
            "title": "My Thesis",
            "authors": ["Grad Student"],
            "year": 2024,
            "paper_type": "thesis",
            "first_author_lastname": "Student",
        }
        bib = meta_to_bibtex(meta)
        assert bib.startswith("@phdthesis{")

    def test_special_chars_escaped(self):
        meta = {
            "title": "CO2 & H2O: 50% of the #1 problem",
            "authors": [],
            "first_author_lastname": "Test",
        }
        bib = meta_to_bibtex(meta)
        assert "\\&" in bib
        assert "\\%" in bib
        assert "\\#" in bib


class TestExportBibtex:
    """Batch export contract: filters work, output is concatenated entries."""

    def test_export_all(self, tmp_papers):
        result = export_bibtex(tmp_papers)
        assert "@article{" in result
        assert "@phdthesis{" in result

    def test_filter_by_year(self, tmp_papers):
        result = export_bibtex(tmp_papers, year="2024")
        assert "Deep learning" in result
        assert "Turbulence" not in result

    def test_filter_by_journal(self, tmp_papers):
        result = export_bibtex(tmp_papers, journal="Fluid Mechanics")
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_filter_by_paper_type(self, tmp_papers):
        result = export_bibtex(tmp_papers, paper_type="THES")
        assert "Deep learning" in result
        assert "Turbulence" not in result

    def test_filter_by_paper_ids(self, tmp_papers):
        result = export_bibtex(tmp_papers, paper_ids=["Smith-2023-Turbulence"])
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_empty_result_returns_empty_string(self, tmp_papers):
        result = export_bibtex(tmp_papers, year="1900")
        assert result == ""


# ============================================================================
#  CLI-layer identifier resolution (dir_name / UUID / DOI)
# ============================================================================


class TestExportCliIdentifierResolution:
    """export bibtex/ris/markdown accept dir_name, UUID, and DOI like show does."""

    @staticmethod
    def _cfg(tmp_papers, tmp_db):
        return SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_db)

    @staticmethod
    def _args(action, paper_ids):
        return Namespace(
            export_action=action,
            paper_ids=paper_ids,
            all=False,
            year=None,
            journal=None,
            output=None,
            bullet=False,
            style="apa",
        )

    def test_bibtex_resolves_uuid_via_registry(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)

        cli.cmd_export(self._args("bibtex", ["aaaa-1111"]), self._cfg(tmp_papers, tmp_db))

        out = capsys.readouterr().out
        assert "Turbulence" in out
        assert "Deep learning" not in out

    def test_bibtex_resolves_mixed_case_doi_without_registry(self, tmp_papers, tmp_path, capsys):
        cfg = SimpleNamespace(papers_dir=tmp_papers, index_db=tmp_path / "missing-index.db")

        cli.cmd_export(self._args("bibtex", ["10.1234/JFM.2023.001"]), cfg)

        out = capsys.readouterr().out
        assert "Turbulence" in out
        assert "Deep learning" not in out

    def test_ris_resolves_doi(self, tmp_papers, tmp_db, capsys):
        build_index(tmp_papers, tmp_db)

        cli.cmd_export(self._args("ris", ["10.1234/jfm.2023.001"]), self._cfg(tmp_papers, tmp_db))

        out = capsys.readouterr().out
        assert "TY  - JOUR" in out
        assert "Turbulence" in out

    def test_partial_failure_reports_each_unresolved_id(self, tmp_papers, tmp_db, monkeypatch, capsys):
        build_index(tmp_papers, tmp_db)
        messages: list[str] = []
        monkeypatch.setattr(cli_common, "ui", lambda msg="": messages.append(msg))

        cli.cmd_export(self._args("bibtex", ["aaaa-1111", "bogus-ref"]), self._cfg(tmp_papers, tmp_db))

        out = capsys.readouterr().out
        assert "Turbulence" in out
        assert "无法解析: bogus-ref" in messages

    def test_all_unresolved_raises(self, tmp_papers, tmp_db):
        build_index(tmp_papers, tmp_db)

        with pytest.raises(ValueError, match="无法解析"):
            cli.cmd_export(self._args("bibtex", ["bogus-1", "bogus-2"]), self._cfg(tmp_papers, tmp_db))
