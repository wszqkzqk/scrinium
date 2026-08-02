"""Contract tests for RIS, Markdown reference, DOCX export, and citation styles.

Verifies: given well-formed metadata, each exporter produces correct output.
"""

from __future__ import annotations

import pytest

from scrinium.export import export_markdown_refs, export_ris, meta_to_ris

# ============================================================================
#  RIS export
# ============================================================================


class TestMetaToRis:
    """Single-entry RIS conversion."""

    def test_journal_article_has_required_tags(self):
        meta = {
            "title": "Some Title",
            "authors": ["Alice", "Bob"],
            "year": 2023,
            "journal": "Nature",
            "doi": "10.1234/test",
            "paper_type": "journal-article",
        }
        ris = meta_to_ris(meta)
        assert ris.startswith("TY  - JOUR")
        assert "TI  - Some Title" in ris
        assert "AU  - Alice" in ris
        assert "AU  - Bob" in ris
        assert "PY  - 2023" in ris
        assert "DO  - 10.1234/test" in ris
        assert ris.rstrip().endswith("ER  -")

    def test_thesis_maps_to_thes(self):
        meta = {"title": "My Thesis", "authors": ["Grad Student"], "paper_type": "thesis"}
        ris = meta_to_ris(meta)
        assert ris.startswith("TY  - THES")

    def test_unknown_type_maps_to_gen(self):
        meta = {"title": "Something", "authors": [], "paper_type": ""}
        ris = meta_to_ris(meta)
        assert ris.startswith("TY  - GEN")


class TestExportRis:
    """Batch RIS export with filtering."""

    def test_export_all(self, tmp_papers):
        result = export_ris(tmp_papers)
        assert "TY  - JOUR" in result
        assert "TY  - THES" in result

    def test_filter_by_year(self, tmp_papers):
        result = export_ris(tmp_papers, year="2024")
        assert "Deep learning" in result
        assert "Turbulence" not in result

    def test_filter_by_journal(self, tmp_papers):
        result = export_ris(tmp_papers, journal="Fluid Mechanics")
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_empty_result(self, tmp_papers):
        result = export_ris(tmp_papers, year="1900")
        assert result == ""


# ============================================================================
#  Markdown reference list export
# ============================================================================


class TestExportMarkdownRefs:
    """Markdown reference list with style support."""

    def test_default_apa_numbered(self, tmp_papers):
        result = export_markdown_refs(tmp_papers)
        assert result.startswith("1. ")
        # APA uses (year) format
        assert "(2024)" in result or "(2023)" in result

    def test_bullet_mode(self, tmp_papers):
        result = export_markdown_refs(tmp_papers, numbered=False)
        assert result.startswith("- ")

    def test_builtin_vancouver_style(self, tmp_papers):
        result = export_markdown_refs(tmp_papers, style="vancouver")
        # Vancouver uses semicolon for volume: 2023;950
        assert ";950" in result

    def test_builtin_mla_style(self, tmp_papers):
        result = export_markdown_refs(tmp_papers, style="mla")
        # MLA uses "vol." prefix
        assert "vol." in result

    def test_filter_by_year(self, tmp_papers):
        result = export_markdown_refs(tmp_papers, year="2023")
        assert "Turbulence" in result
        assert "Deep learning" not in result

    def test_empty_result(self, tmp_papers):
        result = export_markdown_refs(tmp_papers, year="1900")
        assert result == ""


# ============================================================================
#  Citation styles module
# ============================================================================


class TestCitationStyles:
    """Citation style discovery, loading, and validation."""

    def test_list_styles_includes_builtins(self, tmp_papers):
        from scrinium.citation_styles import BUILTIN_STYLES, list_styles
        from scrinium.config import Config

        cfg = Config()
        cfg._root = tmp_papers.parent
        styles = list_styles(cfg)
        builtin_names = {s["name"] for s in styles if s["source"] == "built-in"}
        assert builtin_names == set(BUILTIN_STYLES)

    def test_get_formatter_builtin(self):
        from scrinium.citation_styles import get_formatter
        from scrinium.config import Config

        cfg = Config()
        fmt = get_formatter("apa", cfg)
        result = fmt({"title": "Test", "authors": ["A"], "year": 2024}, 1)
        assert result.startswith("1. ")

    def test_get_formatter_missing_raises(self, tmp_path):
        from scrinium.citation_styles import get_formatter
        from scrinium.config import Config

        cfg = Config()
        cfg._root = tmp_path
        (tmp_path / "data" / "papers").mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="不存在"):
            get_formatter("nonexistent-style", cfg)

    def test_custom_style_loaded_from_file(self, tmp_path):
        from scrinium.citation_styles import get_formatter, list_styles
        from scrinium.config import Config

        cfg = Config()
        cfg._root = tmp_path
        papers_dir = tmp_path / "data" / "papers"
        papers_dir.mkdir(parents=True)
        styles_dir = tmp_path / "data" / "citation_styles"
        styles_dir.mkdir(parents=True)

        # Write a minimal custom style
        (styles_dir / "test-style.py").write_text(
            "def format_ref(meta, idx=None):\n"
            "    title = meta.get('title', '')\n"
            "    return f'{idx}. CUSTOM: {title}'\n",
            encoding="utf-8",
        )

        # Should appear in list
        names = [s["name"] for s in list_styles(cfg)]
        assert "test-style" in names

        # Should load and format
        fmt = get_formatter("test-style", cfg)
        result = fmt({"title": "Hello"}, 1)
        assert "CUSTOM: Hello" in result

    def test_path_traversal_rejected(self):
        from scrinium.citation_styles import get_formatter
        from scrinium.config import Config

        cfg = Config()
        with pytest.raises(ValueError, match="引用格式名称无效"):
            get_formatter("../../../etc/passwd", cfg)

    def test_path_traversal_dots_rejected(self):
        from scrinium.citation_styles import get_formatter
        from scrinium.config import Config

        cfg = Config()
        with pytest.raises(ValueError, match="引用格式名称无效"):
            get_formatter("foo/bar", cfg)


# ============================================================================
#  DOCX export
# ============================================================================


pytest.importorskip("docx", reason="python-docx not installed")


class TestExportDocx:
    """DOCX generation from Markdown content."""

    def test_basic_export(self, tmp_path):
        from scrinium.export import export_docx

        out = tmp_path / "test.docx"
        export_docx("# Hello\n\nWorld", out, title="Test Doc")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_export_without_title(self, tmp_path):
        from scrinium.export import export_docx

        out = tmp_path / "notitle.docx"
        export_docx("Just a paragraph.", out)
        assert out.exists()

    def test_export_with_table(self, tmp_path):
        from scrinium.export import export_docx

        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        out = tmp_path / "table.docx"
        export_docx(md, out)
        assert out.exists()
        assert out.stat().st_size > 0
