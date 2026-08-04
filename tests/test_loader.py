"""Contract tests for the L1-L2 layer loading system.

Verifies: each layer returns the documented fields from well-formed data.
Does NOT test: internal JSON parsing details or L3 enrichment (agent-written).
"""

from __future__ import annotations

import json
import logging

import pytest

from scrinium.loader import append_notes, load_l1, load_l2, load_l4, load_notes, validate_lang


class TestLoadL1:
    """L1 contract: returns metadata dict with documented keys."""

    def test_returns_expected_keys(self, tmp_papers):
        json_path = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        result = load_l1(json_path)

        assert result["paper_id"] == "aaaa-1111"
        assert result["title"] == "Turbulence modeling in boundary layers"
        assert isinstance(result["authors"], list)
        assert result["year"] == 2023
        assert result["journal"] == "Journal of Fluid Mechanics"
        assert result["doi"] == "10.1234/jfm.2023.001"

    def test_missing_fields_have_safe_defaults(self, tmp_path):
        """Minimal JSON should not crash — missing fields get defaults."""
        d = tmp_path / "Bare-2000-Minimal"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": "min-id"}))

        result = load_l1(d / "meta.json")
        assert result["paper_id"] == "min-id"
        assert result["title"] == ""
        assert result["authors"] == []
        assert result["year"] is None


class TestLoadL2:
    """L2 contract: returns abstract string."""

    def test_returns_abstract(self, tmp_papers):
        json_path = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        assert "novel turbulence model" in load_l2(json_path)

    def test_missing_abstract_returns_placeholder(self, tmp_path):
        d = tmp_path / "NoAbstract"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": "x"}))

        result = load_l2(d / "meta.json")
        assert "No abstract" in result


class TestValidateLang:
    """validate_lang guards show --lang against path traversal and malformed codes."""

    def test_accepts_iso_codes(self):
        assert validate_lang("zh") == "zh"
        assert validate_lang("eng") == "eng"

    def test_normalizes_case_and_whitespace(self):
        assert validate_lang(" ZH ") == "zh"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="invalid language code"):
            validate_lang("../bad")

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match="invalid language code type"):
            validate_lang(None)  # type: ignore[arg-type]

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="invalid language code"):
            validate_lang("toolongcode")


class TestLoadL4:
    """L4 contract: returns full markdown text, with optional translated version."""

    def test_returns_original_text(self, tmp_papers):
        md_path = tmp_papers / "Smith-2023-Turbulence" / "paper.md"
        result = load_l4(md_path)
        assert "Turbulence modeling" in result

    def test_prefers_translated_when_lang_specified(self, tmp_papers):
        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        (paper_dir / "paper_zh.md").write_text("# 边界层湍流建模\n\n中文全文。", encoding="utf-8")
        result = load_l4(paper_dir / "paper.md", lang="zh")
        assert "边界层湍流建模" in result

    def test_falls_back_to_original_when_translation_missing(self, tmp_papers):
        md_path = tmp_papers / "Smith-2023-Turbulence" / "paper.md"
        result = load_l4(md_path, lang="fr")
        assert "Turbulence modeling" in result

    def test_no_lang_returns_original(self, tmp_papers):
        paper_dir = tmp_papers / "Smith-2023-Turbulence"
        (paper_dir / "paper_zh.md").write_text("中文", encoding="utf-8")
        result = load_l4(paper_dir / "paper.md", lang=None)
        assert "Turbulence modeling" in result

    def test_invalid_lang_logs_warning_without_traceback(self, tmp_papers, caplog):
        md_path = tmp_papers / "Smith-2023-Turbulence" / "paper.md"
        with caplog.at_level(logging.WARNING, logger="scrinium.loader"):
            result = load_l4(md_path, lang="../bad")
        assert "Turbulence modeling" in result
        records = [r for r in caplog.records if "invalid lang code" in r.getMessage()]
        assert records
        assert all(r.exc_info is None for r in records)


class TestNotes:
    """notes.md read/write contract: persist and retrieve analysis notes."""

    def test_no_notes_returns_none(self, tmp_path):
        d = tmp_path / "SomePaper"
        d.mkdir()
        assert load_notes(d) is None

    def test_append_then_load_roundtrip(self, tmp_path):
        d = tmp_path / "SomePaper"
        d.mkdir()
        append_notes(d, "## 2026-03-14 | ws | skill\n\nFirst note.")
        notes = load_notes(d)
        assert notes is not None
        assert "First note." in notes

    def test_multiple_appends_preserve_all_sections(self, tmp_path):
        d = tmp_path / "SomePaper"
        d.mkdir()
        append_notes(d, "## Section 1\n\nFirst.")
        append_notes(d, "## Section 2\n\nSecond.")
        notes = load_notes(d)
        assert "## Section 1" in notes
        assert "## Section 2" in notes


class TestEnrichToc:
    """enrich_toc is rule-based only: headings -> toc, no model calls."""

    def _paper(self, tmp_path, md_text):
        d = tmp_path / "Author-2023-Paper"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": "p1", "title": "Paper"}), encoding="utf-8")
        (d / "paper.md").write_text(md_text, encoding="utf-8")
        return d

    def test_rules_extract_numbered_sections(self, tmp_path):
        d = self._paper(
            tmp_path,
            "# Paper Title\n\n# 1 Introduction\n\nBody.\n\n# 2 Methods\n\nBody.\n\n## 2.1 Setup\n\nBody.\n",
        )

        from scrinium.loader import enrich_toc

        assert enrich_toc(d / "meta.json", d / "paper.md") is True
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        titles = [e["title"] for e in data["toc"]]
        assert any("Introduction" in t for t in titles)
        assert any("Methods" in t for t in titles)
        assert "toc_extracted_at" in data

    def test_existing_toc_not_overwritten_without_force(self, tmp_path):
        d = self._paper(tmp_path, "# 1 Introduction\n\nBody.\n")
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta["toc"] = [{"line": 1, "level": 1, "title": "Keep Me"}]
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        from scrinium.loader import enrich_toc

        assert enrich_toc(d / "meta.json", d / "paper.md", force=False) is True
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert data["toc"] == [{"line": 1, "level": 1, "title": "Keep Me"}]

    def test_force_overwrites_existing_toc(self, tmp_path):
        d = self._paper(tmp_path, "# 1 Introduction\n\nBody.\n")
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        meta["toc"] = [{"line": 1, "level": 1, "title": "Stale"}]
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        from scrinium.loader import enrich_toc

        assert enrich_toc(d / "meta.json", d / "paper.md", force=True) is True
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert [e["title"] for e in data["toc"]] != ["Stale"]

    def test_no_headings_returns_false(self, tmp_path):
        d = self._paper(tmp_path, "Plain body text without any headings.\n")

        from scrinium.loader import enrich_toc

        assert enrich_toc(d / "meta.json", d / "paper.md") is False
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert "toc" not in data
