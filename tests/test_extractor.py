"""Tests for scrinium.ingest.extractor — RegexExtractor and factory."""

from __future__ import annotations

from scrinium.ingest.extractor import RegexExtractor, get_extractor


class TestRegexExtractor:
    def test_extract_returns_metadata(self, tmp_path):
        md = tmp_path / "paper.md"
        md.write_text(
            "# Test Paper Title\n\nJohn Smith\n\nDOI: 10.1234/test.2023\n\nCopyright © 2023\n",
            encoding="utf-8",
        )
        ext = RegexExtractor()
        meta = ext.extract(md)
        assert meta.title == "Test Paper Title"
        assert meta.doi == "10.1234/test.2023"

    def test_extract_preserves_arxiv_id_from_filename(self, tmp_path):
        md = tmp_path / "2603.25457v1.md"
        md.write_text(
            "# Universal transport laws in buoyancy-driven porous mixing\n\nMarco De Paoli\n",
            encoding="utf-8",
        )
        meta = RegexExtractor().extract(md)
        assert meta.arxiv_id == "2603.25457"


class TestGetExtractor:
    def test_always_returns_regex(self):
        ext = get_extractor()
        assert isinstance(ext, RegexExtractor)

    def test_no_api_key_needed(self):
        ext = get_extractor()
        assert isinstance(ext, RegexExtractor)
