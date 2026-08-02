"""Contract tests for papers.py — path helpers and iteration.

Verifies: directory iteration yields only valid paper dirs, path helpers
compose correctly.
Does NOT test: UUID generation randomness, internal sorting.
"""

from __future__ import annotations

from scrinium.papers import iter_paper_dirs, md_path, meta_path, paper_dir


class TestPathHelpers:
    """Path composition contract."""

    def test_paper_dir_joins_correctly(self, tmp_papers):
        result = paper_dir(tmp_papers, "Smith-2023-Turbulence")
        assert result == tmp_papers / "Smith-2023-Turbulence"

    def test_meta_path(self, tmp_papers):
        result = meta_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "meta.json"
        assert result.exists()

    def test_md_path(self, tmp_papers):
        result = md_path(tmp_papers, "Smith-2023-Turbulence")
        assert result.name == "paper.md"
        assert result.exists()


class TestIterPaperDirs:
    """Iteration contract: yields dirs with meta.json, skips others."""

    def test_yields_valid_paper_dirs(self, tmp_papers):
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "Smith-2023-Turbulence" in names
        assert "Wang-2024-DeepLearning" in names

    def test_skips_dirs_without_meta(self, tmp_papers):
        # Create a directory without meta.json
        (tmp_papers / "orphan-dir").mkdir()
        dirs = list(iter_paper_dirs(tmp_papers))
        names = [d.name for d in dirs]
        assert "orphan-dir" not in names

    def test_nonexistent_dir_yields_nothing(self, tmp_path):
        dirs = list(iter_paper_dirs(tmp_path / "nonexistent"))
        assert dirs == []
