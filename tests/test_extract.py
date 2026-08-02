"""Tests for scrinium.ingest.metadata._extract — regex metadata extraction."""

from __future__ import annotations

from scrinium.ingest.metadata._extract import (
    _clean_author_name,
    _clean_author_text,
    _extract_doi,
    _extract_from_filename,
    _extract_journal,
    _extract_lastname,
    _extract_text_from_latex,
    _extract_title,
    _extract_year_from_text,
    _split_authors,
    extract_metadata_from_markdown,
)


class TestExtractTitle:
    def test_simple_h1(self):
        lines = ["# Turbulence Modeling in Boundary Layers"]
        title, idx = _extract_title(lines)
        assert title == "Turbulence Modeling in Boundary Layers"
        assert idx == 0

    def test_skip_abstract_h1(self):
        lines = ["# Abstract", "# Real Title Here"]
        title, idx = _extract_title(lines)
        assert title == "Real Title Here"
        assert idx == 1

    def test_skip_section_number(self):
        lines = ["# 1 Introduction", "# A Novel Approach"]
        title, idx = _extract_title(lines)
        assert title == "A Novel Approach"
        assert idx == 1

    def test_no_h1_returns_empty(self):
        lines = ["No heading here", "Just text"]
        title, idx = _extract_title(lines)
        assert title == ""
        assert idx == -1

    def test_skip_author_like_short_h1(self):
        """Short H1 with superscript that looks like an author name."""
        lines = [
            "# John Smith<sup>1</sup>",
            "# A Long Title About Turbulence Modeling Methods",
        ]
        title, _idx = _extract_title(lines)
        assert "Turbulence" in title

    def test_fallback_longest_h1(self):
        """When all H1s are skipped, pick the longest."""
        lines = ["# 1 Intro", "# Keywords"]
        title, _idx = _extract_title(lines)
        # Both are "skippable", so fallback picks longest
        assert title != ""


class TestExtractDoi:
    def test_doi_url_format(self):
        text = "https://doi.org/10.1234/test.2023.001"
        assert _extract_doi(text) == "10.1234/test.2023.001"

    def test_doi_label_format(self):
        text = "DOI: 10.1234/test.2023.001"
        assert _extract_doi(text) == "10.1234/test.2023.001"

    def test_doi_bracket_format(self):
        text = "[DOI: 10.1234/test.2023.001]"
        assert _extract_doi(text) == "10.1234/test.2023.001"

    def test_reject_data_repo_doi(self):
        text = "DOI: 10.17632/abc123"  # Mendeley Data
        assert _extract_doi(text) == ""

    def test_reject_zenodo_doi(self):
        text = "DOI: 10.5281/zenodo.12345"
        assert _extract_doi(text) == ""

    def test_no_doi(self):
        assert _extract_doi("No DOI in this text.") == ""

    def test_doi_trailing_punctuation_stripped(self):
        text = "DOI: 10.1234/test.2023.001."
        assert _extract_doi(text) == "10.1234/test.2023.001"

    def test_chinese_doi_format(self):
        text = "文献DOI: 10.1234/test.2023"
        assert _extract_doi(text) == "10.1234/test.2023"


class TestExtractYear:
    def test_copyright_year(self):
        assert _extract_year_from_text("Copyright © 2023") == 2023

    def test_received_year(self):
        assert _extract_year_from_text("Received 15 March 2022") == 2022

    def test_cite_as_year(self):
        assert _extract_year_from_text("Cite as: Smith et al. (2024)") == 2024

    def test_volume_year(self):
        assert _extract_year_from_text("Vol. 950, 2023") == 2023

    def test_out_of_range_ignored(self):
        assert _extract_year_from_text("Copyright 1899") is None
        assert _extract_year_from_text("Copyright 2099") is None

    def test_no_year(self):
        assert _extract_year_from_text("No year here.") is None


class TestExtractJournal:
    def test_jfm(self):
        assert "Fluid Mech" in _extract_journal("Journal of Fluid Mechanics, 2023")

    def test_nature_communications(self):
        assert "Nature Communications" in _extract_journal("Published in Nature Communications")

    def test_physics_of_fluids(self):
        result = _extract_journal("Phys. Fluids 35, 2023")
        assert "Phys" in result and "Fluid" in result

    def test_no_match(self):
        assert _extract_journal("Some random text") == ""


class TestCleanAuthorText:
    def test_remove_superscripts(self):
        assert "Smith" in _clean_author_text("Smith<sup>1</sup>")

    def test_remove_orcid(self):
        result = _clean_author_text("Smith https://orcid.org/0000-0001-2345-6789")
        assert "orcid" not in result

    def test_remove_email(self):
        result = _clean_author_text("Smith user@example.com")
        assert "@" not in result

    def test_collapse_spaced_out_letters(self):
        result = _clean_author_text("B I J L A R D")
        assert "BIJLARD" in result

    def test_spaced_and_preserved(self):
        """'A N D' delimiter should become 'and', not get collapsed."""
        result = _clean_author_text("SMITH A N D JONES")
        assert "and" in result.lower()

    def test_extract_text_from_latex(self):
        assert _extract_text_from_latex(r"\mathbf{D}^{1}") == "D"
        assert _extract_text_from_latex(r"\alpha") == ""


class TestCleanAuthorName:
    def test_remove_symbols(self):
        assert _clean_author_name("Smith*†") == "Smith"

    def test_remove_by_prefix(self):
        assert _clean_author_name("By John Smith") == "John Smith"

    def test_remove_affiliations(self):
        assert _clean_author_name("Smith (MIT)") == "Smith"


class TestSplitAuthors:
    def test_comma_and(self):
        result = _split_authors("Smith, John and Doe, Jane")
        assert len(result) >= 2

    def test_semicolon_separated(self):
        result = _split_authors("Smith; Doe; Wang")
        assert len(result) == 3

    def test_chinese_delimiter(self):
        result = _split_authors("张三，李四，王五")
        assert len(result) == 3


class TestExtractLastname:
    def test_western_name(self):
        assert _extract_lastname("John Smith") == "Smith"

    def test_initials(self):
        assert _extract_lastname("S. Balachandar") == "Balachandar"

    def test_multiple_initials(self):
        assert _extract_lastname("J. K. Eaton") == "Eaton"

    def test_particle(self):
        assert _extract_lastname("Marco de Vanna") == "De Vanna"

    def test_van_dyke(self):
        assert _extract_lastname("Milton van Dyke") == "Van Dyke"

    def test_chinese_name(self):
        assert _extract_lastname("张三") == "张"

    def test_empty(self):
        assert _extract_lastname("") == ""


class TestExtractFromFilename:
    def test_mineru_standard_format(self, tmp_path):
        md = tmp_path / "MinerU_markdown_Smith-2023-Turbulence_1234567890.md"
        md.write_text("content")
        meta = _extract_from_filename(md)
        assert meta.year == 2023
        assert meta.first_author_lastname == "Smith"

    def test_mineru_slug_format(self, tmp_path):
        md = tmp_path / "MinerU_markdown_some-slug-2024-cool-paper_9876543210.md"
        md.write_text("content")
        meta = _extract_from_filename(md)
        assert meta.year == 2024

    def test_no_pattern_match(self, tmp_path):
        md = tmp_path / "random_name.md"
        md.write_text("content")
        meta = _extract_from_filename(md)
        assert meta.title == ""
        assert meta.year is None


class TestFullExtraction:
    def test_complete_markdown(self, tmp_path):
        md = tmp_path / "paper.md"
        md.write_text(
            "# A Novel Turbulence Model\n\n"
            "John Smith, Jane Doe\n\n"
            "DOI: 10.1234/test.2023\n\n"
            "Copyright © 2023\n\n"
            "Journal of Fluid Mechanics\n\n"
            "## Abstract\n\nSome abstract.\n",
            encoding="utf-8",
        )
        meta = extract_metadata_from_markdown(md)
        assert meta.title == "A Novel Turbulence Model"
        assert meta.doi == "10.1234/test.2023"
        assert meta.year == 2023
        assert len(meta.authors) > 0

    def test_empty_markdown(self, tmp_path):
        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        meta = extract_metadata_from_markdown(md)
        assert meta.title == ""
        assert meta.doi == ""
        assert meta.year is None
        assert meta.authors == []
