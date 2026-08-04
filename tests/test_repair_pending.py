"""Tests for `scrinium repair` against data/pending/ targets."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrinium.cli import ingest as cli_ingest


def _make_pending(root: Path, stem: str, *, with_images: bool = True) -> Path:
    """Create a pending item: paper.md + pending.json + original PDF (+ images/)."""
    pending_d = root / "data" / "pending" / stem
    pending_d.mkdir(parents=True)
    (pending_d / "paper.md").write_text("# Draft full text\n\nContent.", encoding="utf-8")
    (pending_d / "pending.json").write_text(
        json.dumps({"issue": "no_doi", "message": "no DOI after API query"}),
        encoding="utf-8",
    )
    (pending_d / "original.pdf").write_bytes(b"%PDF-1.4 fake")
    if with_images:
        (pending_d / "images").mkdir()
        (pending_d / "images" / "fig1.png").write_bytes(b"png")
    return pending_d


def _args(paper_id: str, **overrides) -> Namespace:
    base = {
        "paper_id": paper_id,
        "title": "A Brand New Paper",
        "doi": "10.9999/new.2021.001",
        "author": "John Doe",
        "year": 2021,
        "no_api": True,
        "dry_run": False,
    }
    base.update(overrides)
    return Namespace(**base)


def _cfg(tmp_path: Path, papers_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(_root=tmp_path, papers_dir=papers_dir)


@pytest.fixture()
def messages(monkeypatch) -> list[str]:
    """Capture ui() output (logging-based, invisible to capsys)."""
    collected: list[str] = []
    monkeypatch.setattr(cli_ingest, "ui", collected.append)
    return collected


class TestRepairPendingIngest:
    def test_pending_item_ingested_into_library(self, tmp_path: Path, tmp_papers: Path):
        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        cli_ingest.cmd_repair(_args("stuck-paper"), cfg)

        target = tmp_papers / "Doe-2021-A-Brand-New-Paper"
        assert target.is_dir()
        meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
        assert meta["title"] == "A Brand New Paper"
        assert meta["doi"] == "10.9999/new.2021.001"
        assert meta["first_author_lastname"] == "Doe"
        assert meta["year"] == 2021
        assert meta["id"]  # a fresh UUID was assigned
        assert (target / "paper.md").read_text(encoding="utf-8").startswith("# Draft full text")
        assert (target / "images" / "fig1.png").exists()
        # Pending dir fully removed (original PDF and pending.json included)
        assert not pending_d.exists()

    def test_stem_collision_gets_dash2_suffix(self, tmp_path: Path, tmp_papers: Path):
        (tmp_papers / "Doe-2021-A-Brand-New-Paper").mkdir()
        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        cli_ingest.cmd_repair(_args("stuck-paper"), cfg)

        assert (tmp_papers / "Doe-2021-A-Brand-New-Paper-2" / "meta.json").exists()
        assert not pending_d.exists()

    def test_pending_without_images(self, tmp_path: Path, tmp_papers: Path):
        _make_pending(tmp_path, "stuck-paper", with_images=False)
        cfg = _cfg(tmp_path, tmp_papers)

        cli_ingest.cmd_repair(_args("stuck-paper"), cfg)

        target = tmp_papers / "Doe-2021-A-Brand-New-Paper"
        assert (target / "paper.md").exists()
        assert not (target / "images").exists()


class TestRepairPendingDedupGuard:
    def test_same_doi_in_library_refused(self, tmp_path: Path, tmp_papers: Path, messages):
        # tmp_papers paper A already owns 10.1234/jfm.2023.001
        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        with pytest.raises(SystemExit) as exc:
            cli_ingest.cmd_repair(_args("stuck-paper", doi="10.1234/JFM.2023.001"), cfg)

        assert exc.value.code == 1
        out = "\n".join(messages)
        assert "Smith-2023-Turbulence" in out
        assert str(pending_d) in out
        # Pending dir untouched
        assert (pending_d / "paper.md").exists()
        assert (pending_d / "pending.json").exists()
        assert (pending_d / "original.pdf").exists()
        # Nothing new ingested
        assert not (tmp_papers / "Doe-2021-A-Brand-New-Paper").exists()

    def test_same_arxiv_id_in_library_refused(self, tmp_path: Path, tmp_papers: Path, messages, monkeypatch):
        # Give library paper A an arXiv id (versioned, as stored in ids)
        meta_path = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.setdefault("ids", {})["arxiv"] = "2401.12345v2"
        meta_path.write_text(json.dumps(data), encoding="utf-8")

        def fake_enrich(meta):
            meta.arxiv_id = "2401.12345"
            return meta

        monkeypatch.setattr("scrinium.ingest.metadata.enrich_metadata", fake_enrich)

        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        with pytest.raises(SystemExit) as exc:
            cli_ingest.cmd_repair(_args("stuck-paper", no_api=False, doi=""), cfg)

        assert exc.value.code == 1
        assert "Smith-2023-Turbulence" in "\n".join(messages)
        assert (pending_d / "paper.md").exists()

    def test_dry_run_no_writes(self, tmp_path: Path, tmp_papers: Path, messages):
        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        cli_ingest.cmd_repair(_args("stuck-paper", dry_run=True), cfg)

        out = "\n".join(messages)
        assert "查重" in out
        assert "dry-run" in out
        assert not (tmp_papers / "Doe-2021-A-Brand-New-Paper").exists()
        assert (pending_d / "paper.md").exists()
        assert (pending_d / "pending.json").exists()

    def test_dry_run_still_refuses_duplicates(self, tmp_path: Path, tmp_papers: Path, messages):
        pending_d = _make_pending(tmp_path, "stuck-paper")
        cfg = _cfg(tmp_path, tmp_papers)

        with pytest.raises(SystemExit) as exc:
            cli_ingest.cmd_repair(_args("stuck-paper", doi="10.1234/jfm.2023.001", dry_run=True), cfg)

        assert exc.value.code == 1
        assert "Smith-2023-Turbulence" in "\n".join(messages)
        assert (pending_d / "paper.md").exists()


class TestRepairLibraryTargetUnchanged:
    def test_in_library_repair_still_renames_in_place(self, tmp_path: Path, tmp_papers: Path):
        cfg = _cfg(tmp_path, tmp_papers)
        args = _args("Smith-2023-Turbulence", title="Turbulence modeling in boundary layers")

        cli_ingest.cmd_repair(args, cfg)

        # Dir renamed to the standardized stem, meta.json rewritten, UUID kept
        assert not (tmp_papers / "Smith-2023-Turbulence").exists()
        target = tmp_papers / "Doe-2021-Turbulence-modeling-in-boundary-layers"
        assert target.is_dir()
        meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
        assert meta["id"] == "aaaa-1111"
        assert meta["title"] == "Turbulence modeling in boundary layers"
        assert (target / "paper.md").exists()

    def test_missing_target_still_errors(self, tmp_path: Path, tmp_papers: Path):
        cfg = _cfg(tmp_path, tmp_papers)

        with pytest.raises(SystemExit) as exc:
            cli_ingest.cmd_repair(_args("no-such-paper"), cfg)

        assert exc.value.code == 1
