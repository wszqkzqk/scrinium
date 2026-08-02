"""Tests for scrinium.citation_styles — APA, Vancouver, Chicago, MLA formatting."""

from __future__ import annotations

import pytest

from scrinium.citation_styles import (
    BUILTIN_STYLES,
    _fmt_apa,
    _fmt_chicago_author_date,
    _fmt_mla,
    _fmt_vancouver,
    get_formatter,
    list_styles,
    show_style,
    styles_dir,
)
from scrinium.config import _build_config


@pytest.fixture()
def cfg(tmp_path):
    return _build_config({"paths": {"papers_dir": str(tmp_path / "papers")}}, tmp_path)


# Sample metadata for testing
FULL_META = {
    "title": "Turbulence modeling in boundary layers",
    "authors": ["Smith, John", "Doe, Jane", "Wang, Wei"],
    "year": 2023,
    "journal": "Journal of Fluid Mechanics",
    "volume": "950",
    "issue": "2",
    "pages": "100-120",
    "doi": "10.1234/jfm.2023.001",
}

MINIMAL_META = {"title": "Untitled", "authors": [], "year": None}


class TestAPA:
    def test_single_author(self):
        meta = {**FULL_META, "authors": ["Smith, John"]}
        ref = _fmt_apa(meta, idx=1)
        assert ref.startswith("1. Smith, John (2023)")

    def test_two_authors(self):
        meta = {**FULL_META, "authors": ["Smith, John", "Doe, Jane"]}
        ref = _fmt_apa(meta)
        assert "Smith, John, & Doe, Jane" in ref

    def test_three_authors(self):
        ref = _fmt_apa(FULL_META)
        assert "Smith, John, Doe, Jane, & Wang, Wei" in ref

    def test_four_plus_authors_et_al(self):
        meta = {**FULL_META, "authors": ["A", "B", "C", "D"]}
        ref = _fmt_apa(meta)
        assert "A et al." in ref

    def test_no_authors(self):
        ref = _fmt_apa(MINIMAL_META)
        assert "Unknown" in ref

    def test_no_year(self):
        ref = _fmt_apa(MINIMAL_META)
        assert "n.d." in ref

    def test_doi_included(self):
        ref = _fmt_apa(FULL_META)
        assert "https://doi.org/10.1234/jfm.2023.001" in ref

    def test_no_doi(self):
        meta = {**FULL_META, "doi": ""}
        ref = _fmt_apa(meta)
        assert "doi.org" not in ref

    def test_journal_formatting(self):
        ref = _fmt_apa(FULL_META)
        assert "*Journal of Fluid Mechanics*" in ref
        assert "*950*" in ref
        assert "(2)" in ref

    def test_bullet_prefix(self):
        ref = _fmt_apa(FULL_META)
        assert ref.startswith("- ")

    def test_numbered_prefix(self):
        ref = _fmt_apa(FULL_META, idx=5)
        assert ref.startswith("5. ")


class TestVancouver:
    def test_basic_format(self):
        meta = {**FULL_META, "authors": ["Smith, John"]}
        ref = _fmt_vancouver(meta, idx=1)
        assert "Smith J" in ref
        assert "2023" in ref

    def test_six_authors(self):
        meta = {**FULL_META, "authors": [f"Author{i}, X" for i in range(6)]}
        ref = _fmt_vancouver(meta)
        assert "et al" not in ref

    def test_seven_authors_et_al(self):
        meta = {**FULL_META, "authors": [f"Author{i}, X" for i in range(7)]}
        ref = _fmt_vancouver(meta)
        assert "et al" in ref

    def test_doi_prefix(self):
        ref = _fmt_vancouver(FULL_META)
        assert "doi:10.1234" in ref

    def test_no_authors(self):
        ref = _fmt_vancouver(MINIMAL_META)
        assert "Unknown" in ref


class TestChicago:
    def test_single_author_reversed(self):
        meta = {**FULL_META, "authors": ["Smith, John"]}
        ref = _fmt_chicago_author_date(meta)
        assert "Smith, John" in ref

    def test_two_authors_second_normal(self):
        meta = {**FULL_META, "authors": ["Smith, John", "Doe, Jane"]}
        ref = _fmt_chicago_author_date(meta)
        assert "and Jane Doe" in ref

    def test_four_authors_et_al(self):
        meta = {**FULL_META, "authors": ["Smith, John", "A", "B", "C"]}
        ref = _fmt_chicago_author_date(meta)
        assert "et al." in ref

    def test_title_in_quotes(self):
        ref = _fmt_chicago_author_date(FULL_META)
        assert '"Turbulence modeling' in ref

    def test_doi_url(self):
        ref = _fmt_chicago_author_date(FULL_META)
        assert "https://doi.org/" in ref

    def test_no_authors(self):
        ref = _fmt_chicago_author_date(MINIMAL_META)
        assert "Unknown" in ref


class TestMLA:
    def test_single_author_reversed(self):
        meta = {**FULL_META, "authors": ["Smith, John"]}
        ref = _fmt_mla(meta)
        assert "Smith, John" in ref

    def test_two_authors(self):
        meta = {**FULL_META, "authors": ["Smith, John", "Doe, Jane"]}
        ref = _fmt_mla(meta)
        assert "and Jane Doe" in ref

    def test_three_plus_et_al(self):
        ref = _fmt_mla(FULL_META)
        assert "et al." in ref

    def test_volume_issue_formatting(self):
        ref = _fmt_mla(FULL_META)
        assert "vol. 950" in ref
        assert "no. 2" in ref
        assert "pp. 100-120" in ref

    def test_title_in_quotes(self):
        ref = _fmt_mla(FULL_META)
        assert '"Turbulence modeling' in ref


class TestListStyles:
    def test_builtins_listed(self, cfg):
        styles = list_styles(cfg)
        names = [s["name"] for s in styles]
        assert "apa" in names
        assert "vancouver" in names
        assert "chicago-author-date" in names
        assert "mla" in names

    def test_builtin_source_tag(self, cfg):
        styles = list_styles(cfg)
        for s in styles:
            if s["name"] in BUILTIN_STYLES:
                assert s["source"] == "built-in"

    def test_custom_style_discovered(self, cfg, tmp_path):
        sd = styles_dir(cfg)
        sd.mkdir(parents=True)
        (sd / "ieee.py").write_text("def format_ref(meta, idx=None): return ''")
        styles = list_styles(cfg)
        names = [s["name"] for s in styles]
        assert "ieee" in names

    def test_custom_with_json_metadata(self, cfg, tmp_path):
        sd = styles_dir(cfg)
        sd.mkdir(parents=True)
        (sd / "ieee.py").write_text("def format_ref(meta, idx=None): return ''")
        (sd / "ieee.json").write_text('{"description": "IEEE style"}')
        styles = list_styles(cfg)
        ieee = next(s for s in styles if s["name"] == "ieee")
        assert ieee["description"] == "IEEE style"


class TestGetFormatter:
    def test_builtin(self, cfg):
        f = get_formatter("apa", cfg)
        assert callable(f)
        assert f is _fmt_apa

    def test_custom_style(self, cfg):
        sd = styles_dir(cfg)
        sd.mkdir(parents=True)
        (sd / "test_style.py").write_text("def format_ref(meta, idx=None): return f'{idx}. custom'")
        f = get_formatter("test_style", cfg)
        assert f({}, 1) == "1. custom"

    def test_invalid_name_chars(self, cfg):
        with pytest.raises(ValueError, match="无效"):
            get_formatter("../hack", cfg)

    def test_nonexistent_style(self, cfg):
        with pytest.raises(FileNotFoundError):
            get_formatter("nonexistent_style_xyz", cfg)

    def test_style_missing_format_ref(self, cfg):
        sd = styles_dir(cfg)
        sd.mkdir(parents=True)
        (sd / "bad.py").write_text("x = 1")
        with pytest.raises(AttributeError, match="format_ref"):
            get_formatter("bad", cfg)


class TestShowStyle:
    def test_builtin_returns_comment(self, cfg):
        result = show_style("apa", cfg)
        assert "内置格式" in result
        assert "apa" in result

    def test_custom_returns_source(self, cfg):
        sd = styles_dir(cfg)
        sd.mkdir(parents=True)
        (sd / "ieee.py").write_text("# IEEE\ndef format_ref(meta, idx=None): pass")
        result = show_style("ieee", cfg)
        assert "# IEEE" in result

    def test_invalid_name(self, cfg):
        with pytest.raises(ValueError):
            show_style("../etc/passwd", cfg)

    def test_nonexistent(self, cfg):
        with pytest.raises(FileNotFoundError):
            show_style("nope", cfg)
