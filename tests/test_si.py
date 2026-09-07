"""Tests for scrinium/si.py — SI 检测、解析链、验证、挂接与获取流程。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrinium.si import (
    SiCandidate,
    _resolve_elsevier,
    _resolve_europepmc,
    _resolve_nature,
    _resolve_plos,
    _resolve_rsc,
    _resolve_science,
    attach_si,
    extract_dois_from_text,
    fetch_si_for_paper,
    looks_like_si_filename,
    looks_like_si_text,
    paper_si_state,
    si_mentioned_in_text,
    verify_si_text,
)

# ============================================================================
#  Detection
# ============================================================================


class TestSiFilenameDetection:
    @pytest.mark.parametrize(
        "name",
        [
            "ja9b12345_si_001.pdf",
            "paper_si.pdf",
            "paper_SI.pdf",
            "supporting-information.pdf",
            "Supporting_Information.pdf",
            "mmc1.pdf",
            "mmc12.pdf",
            "ESI.pdf",
            "c9sc01234a_suppl.pdf",
            "supplementary-data.pdf",
            "sm.pdf",
            "article-supplementary-material.pdf",
        ],
    )
    def test_positives(self, name: str) -> None:
        assert looks_like_si_filename(name), name

    @pytest.mark.parametrize(
        "name",
        [
            "paper.pdf",
            "design.pdf",
            "singer.pdf",
            "Smith-2023-Turbulence.pdf",
            "main-text.pdf",
            "essay.pdf",  # contains "esa" not "esi" boundary
            "systems.pdf",  # "sm" not on boundary
        ],
    )
    def test_negatives(self, name: str) -> None:
        assert not looks_like_si_filename(name), name


class TestSiTextDetection:
    def test_supporting_information(self) -> None:
        assert looks_like_si_text("# Supporting Information\n\nfor: Some Title")

    def test_electronic_supplementary(self) -> None:
        assert looks_like_si_text("Electronic supplementary information (ESI) available")

    def test_beyond_head_window(self) -> None:
        text = "x" * 5000 + "supporting information"
        assert not looks_like_si_text(text)

    def test_negative(self) -> None:
        assert not looks_like_si_text("# Regular research paper\n\nWe study turbulence.")


class TestSiMention:
    @pytest.mark.parametrize(
        "text",
        [
            "see Figure S1 for details",
            "Data are in the Supporting Information.",
            "Electronic supplementary information (ESI) available.",
            "Table S3 summarizes the results",
        ],
    )
    def test_positives(self, text: str) -> None:
        assert si_mentioned_in_text(text)

    def test_negative(self) -> None:
        assert not si_mentioned_in_text("We propose a model. Results are in Table 2.")


class TestExtractDois:
    def test_basic(self) -> None:
        text = "https://doi.org/10.1021/acs.jacs.9b12345 and 10.1039/C9SC01234A."
        assert extract_dois_from_text(text) == ["10.1021/acs.jacs.9b12345", "10.1039/c9sc01234a"]

    def test_dedup_and_trailing_punct(self) -> None:
        assert extract_dois_from_text("10.1234/abc.001, 10.1234/abc.001)") == ["10.1234/abc.001"]


# ============================================================================
#  Resolvers (URL construction; network mocked)
# ============================================================================


class TestResolvers:
    def test_rsc(self) -> None:
        cands = _resolve_rsc("10.1039/C9SC01234A")
        urls = [c.url for c in cands]
        assert "https://www.rsc.org/suppdata/c9/sc/c9sc01234a/c9sc01234a1.pdf" in urls
        assert all(c.source == "rsc" for c in cands)

    def test_science(self) -> None:
        cands = _resolve_science("10.1126/science.abf1234")
        assert (
            cands[0].url
            == "https://www.science.org/doi/suppl/10.1126/science.abf1234/suppl_file/science.abf1234_sm.pdf"
        )

    def test_plos(self) -> None:
        cands = _resolve_plos("10.1371/journal.pone.0234567")
        assert len(cands) == 3
        assert cands[0].url.startswith("https://journals.plos.org/plosone/article/file")
        assert cands[0].url.endswith("10.1371/journal.pone.0234567.s001")

    def test_plos_unknown_journal(self) -> None:
        assert _resolve_plos("10.1371/unknown.x.123") == []


class _FakeResp:
    def __init__(self, status_code: int = 200, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class _FakeSession:
    """Minimal requests-like mock: routes by URL substring."""

    def __init__(self, routes: dict[str, _FakeResp]):
        self.routes = routes

    def get(self, url, **kw):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return _FakeResp(404)

    def post(self, url, **kw):
        return self.get(url, **kw)


class TestNetworkResolvers:
    def test_elsevier_pii_from_crossref(self) -> None:
        session = _FakeSession(
            {
                "api.crossref.org": _FakeResp(
                    200,
                    {"message": {"link": [{"URL": "https://api.elsevier.com/content/article/pii/S0092867420301234"}]}},
                )
            }
        )
        cands = _resolve_elsevier("10.1016/j.cell.2020.01.001", session)
        assert cands[0].url == "https://ars.els-cdn.com/content/image/1-s2.0-S0092867420301234-mmc1.pdf"
        assert len(cands) == 3

    def test_elsevier_no_pii(self) -> None:
        session = _FakeSession({"api.crossref.org": _FakeResp(200, {"message": {"link": []}})})
        assert _resolve_elsevier("10.1016/j.x.1", session) == []

    def test_nature_esm_links(self) -> None:
        html = (
            '<a href="https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-020-1/MediaObjects/41586_1_MOESM1_ESM.pdf">S</a>'
            '<a href="https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-020-1/MediaObjects/41586_1_MOESM2_ESM.pdf">S</a>'
            '<a href="https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-020-1/MediaObjects/41586_1_MOESM1_ESM.pdf">dup</a>'
        )
        session = _FakeSession({"nature.com/articles": _FakeResp(200, text=html)})
        cands = _resolve_nature("10.1038/s41586-020-1", session)
        assert len(cands) == 2  # deduped
        assert all(c.source == "nature" for c in cands)

    def test_europepmc_requires_pmcid(self) -> None:
        session = _FakeSession(
            {
                "europepmc": _FakeResp(
                    200,
                    {
                        "resultList": {
                            "result": [{"source": "MED", "id": "123", "pmcid": "PMC999", "isOpenAccess": "Y"}]
                        }
                    },
                )
            }
        )
        cands = _resolve_europepmc("10.1234/x.1", session)
        assert cands[0].is_zip
        assert "PMC999/supplementaryFiles" in cands[0].url

    def test_europepmc_no_pmcid(self) -> None:
        session = _FakeSession(
            {"europepmc": _FakeResp(200, {"resultList": {"result": [{"source": "MED", "id": "123"}]}})}
        )
        assert _resolve_europepmc("10.1234/x.1", session) == []

    def test_europepmc_not_open_access(self) -> None:
        session = _FakeSession(
            {
                "europepmc": _FakeResp(
                    200,
                    {
                        "resultList": {
                            "result": [{"source": "MED", "id": "123", "pmcid": "PMC999", "isOpenAccess": "N"}]
                        }
                    },
                )
            }
        )
        assert _resolve_europepmc("10.1234/x.1", session) == []


# ============================================================================
#  Verification
# ============================================================================


_META = {
    "title": "Turbulence modeling in boundary layers",
    "authors": ["John Smith", "Jane Doe"],
    "first_author_lastname": "Smith",
}


class TestVerify:
    def test_pass_keyword_and_title(self) -> None:
        md = "Supporting Information\nfor: Turbulence modeling in boundary layers\nSmith et al."
        ok, _ = verify_si_text(md, _META)
        assert ok

    def test_pass_keyword_and_author(self) -> None:
        md = "Supplementary material provided by Smith and colleagues."
        ok, _ = verify_si_text(md, _META)
        assert ok

    def test_mismatch_parent(self) -> None:
        md = "Supporting Information\nfor: Completely unrelated quantum chemistry study\nMiller et al."
        ok, reason = verify_si_text(md, _META)
        assert not ok
        assert "parent_mismatch" in reason

    def test_no_keyword(self) -> None:
        ok, reason = verify_si_text("Turbulence modeling in boundary layers, full text.", _META)
        assert not ok
        assert reason == "no_si_keyword"


# ============================================================================
#  attach_si
# ============================================================================


def _make_paper(tmp_path: Path, meta: dict | None = None) -> Path:
    pdir = tmp_path / "Smith-2023-Turbulence"
    pdir.mkdir()
    (pdir / "meta.json").write_text(json.dumps(meta or {**_META, "id": "aaaa-1111"}), encoding="utf-8")
    return pdir


_SI_MD = "Supporting Information\nfor: Turbulence modeling in boundary layers\nSmith et al.\nFigure S1."


class TestAttachSi:
    def test_attach_with_md(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path)
        src = tmp_path / "paper_si.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        md = tmp_path / "paper_si.md"
        md.write_text(_SI_MD, encoding="utf-8")

        res = attach_si(pdir, src, md_path=md, attached_by="pipeline")
        assert res["ok"], res["message"]
        assert (pdir / "si" / "paper_si.pdf").exists()
        assert (pdir / "si" / "paper_si.md").read_text(encoding="utf-8") == _SI_MD

        meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
        assert meta["si"]["fetch_status"] == "ok"
        assert len(meta["si"]["files"]) == 1
        assert meta["si"]["files"][0]["attached_by"] == "pipeline"

    def test_attach_mismatch_leaves_nothing(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path)
        src = tmp_path / "paper_si.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        md = tmp_path / "paper_si.md"
        md.write_text("Supporting Information\nfor: Unrelated quantum study\nMiller et al.", encoding="utf-8")

        res = attach_si(pdir, src, md_path=md)
        assert not res["ok"]
        assert res["status"] == "mismatch"
        assert not (pdir / "si").exists() or not list((pdir / "si").iterdir())

    def test_attach_raw_data_file(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path)
        src = tmp_path / "coords.xyz"
        src.write_text("C 0 0 0", encoding="utf-8")
        res = attach_si(pdir, src, verify=False)
        assert res["ok"]
        assert (pdir / "si" / "coords.xyz").exists()
        meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
        assert meta["si"]["files"][0]["md"] == ""

    def test_attach_duplicate_name_suffix(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path)
        src = tmp_path / "si.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        md = tmp_path / "si.md"
        md.write_text(_SI_MD, encoding="utf-8")
        attach_si(pdir, src, md_path=md)
        res2 = attach_si(pdir, src, md_path=md)
        assert res2["ok"]
        assert (pdir / "si" / "si-2.pdf").exists()

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path)
        src = tmp_path / "si.pdf"
        src.write_bytes(b"%PDF-1.4 fake")
        res = attach_si(pdir, src, dry_run=True)
        assert res["ok"] and res["status"] == "dry_run"
        assert not (pdir / "si").exists()


# ============================================================================
#  fetch_si_for_paper
# ============================================================================


class TestFetchSi:
    def test_no_doi(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "title": "No DOI paper", "doi": ""})
        assert fetch_si_for_paper(pdir, None) == "not_found"
        meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
        assert meta["si"]["fetch_status"] == "not_found"

    def test_skip_when_files_exist(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "doi": "10.1234/x.1", "si": {"files": [{"name": "a.pdf"}]}})
        assert fetch_si_for_paper(pdir, None) == "skip"

    def test_ok_flow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "doi": "10.1234/x.1", **_META})

        monkeypatch.setattr(
            "scrinium.si.resolve_si_candidates",
            lambda doi, **kw: [SiCandidate(url="http://example/si.pdf", source="test", filename="si.pdf")],
        )

        def fake_download(url, dest, session):
            dest.write_bytes(b"%PDF-1.4 fake pdf bytes")
            return "ok"

        monkeypatch.setattr("scrinium.si._download", fake_download)
        status = fetch_si_for_paper(pdir, None, convert=False)
        assert status == "ok"
        assert (pdir / "si" / "si.pdf").exists()

    def test_download_blocked(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "doi": "10.1234/x.1"})
        monkeypatch.setattr(
            "scrinium.si.resolve_si_candidates",
            lambda doi, **kw: [SiCandidate(url="http://example/si.pdf", source="test", filename="si.pdf")],
        )
        monkeypatch.setattr("scrinium.si._download", lambda url, dest, session: "blocked")
        assert fetch_si_for_paper(pdir, None) == "blocked"
        meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
        assert meta["si"]["fetch_status"] == "blocked"

    def test_html_not_pdf_is_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "doi": "10.1234/x.1"})
        monkeypatch.setattr(
            "scrinium.si.resolve_si_candidates",
            lambda doi, **kw: [SiCandidate(url="http://example/si.pdf", source="test", filename="si.pdf")],
        )
        monkeypatch.setattr(
            "scrinium.si._download", lambda url, dest, session: (dest.write_text("<html>404</html>"), "ok")[1]
        )
        assert fetch_si_for_paper(pdir, None) == "not_found"


# ============================================================================
#  paper_si_state / audit / index integration
# ============================================================================


class TestPaperSiState:
    def test_live_mention_scan(self, tmp_papers: Path) -> None:
        pa = tmp_papers / "Smith-2023-Turbulence"
        (pa / "paper.md").write_text("# Turbulence\n\nsee Figure S1 for details.", encoding="utf-8")
        state = paper_si_state(pa)
        assert state["mentioned"] and not state["present"]

    def test_present_from_meta(self, tmp_path: Path) -> None:
        pdir = _make_paper(tmp_path, {"id": "x", "si": {"files": [{"name": "a.pdf"}, {"name": "b.xlsx"}]}})
        state = paper_si_state(pdir)
        assert state["present"] and state["n_files"] == 2 and state["fetch_status"] == "ok"


class TestAuditIntegration:
    def test_missing_si_and_suspected_si(self, tmp_papers: Path) -> None:
        from scrinium.audit import audit_papers

        pa = tmp_papers / "Smith-2023-Turbulence"
        (pa / "paper.md").write_text("# Turbulence\n\nDetails in the Supporting Information.", encoding="utf-8")
        junk = tmp_papers / "Unknown-2020-SI"
        junk.mkdir()
        (junk / "meta.json").write_text(
            json.dumps({"id": "junk-1", "title": "Supporting Information for something", "doi": "10.9999/si.1"}),
            encoding="utf-8",
        )
        (junk / "paper.md").write_text("# Supporting Information", encoding="utf-8")

        issues = audit_papers(tmp_papers)
        by_rule = {}
        for i in issues:
            by_rule.setdefault(i.rule, []).append(i.paper_id)
        assert "Smith-2023-Turbulence" in by_rule.get("missing_si", [])
        assert "Unknown-2020-SI" in by_rule.get("suspected_si", [])


class TestIndexSiContent:
    def test_si_text_searchable(self, tmp_papers: Path, tmp_db: Path) -> None:
        from scrinium.index import build_index, search

        pa = tmp_papers / "Smith-2023-Turbulence"
        si_dir = pa / "si"
        si_dir.mkdir()
        (si_dir / "paper_si.md").write_text(
            "Supporting Information\nZebrafish oligodynamic extrapolation protocol.", encoding="utf-8"
        )
        build_index(tmp_papers, tmp_db, rebuild=True)
        results = search("oligodynamic", tmp_db, top_k=5)
        assert any(r["paper_id"] == "aaaa-1111" for r in results)


# ============================================================================
#  Pipeline helpers: _route_si_entry / _reconcile_si_orphans
# ============================================================================


class TestPipelineSiRouting:
    def _cfg(self):
        return SimpleNamespace()

    def test_route_attaches_to_parent(self, tmp_papers: Path, tmp_path: Path) -> None:
        from scrinium.ingest.pipeline import _route_si_entry

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        md = inbox / "paper_si.md"
        md.write_text(_SI_MD + "\nhttps://doi.org/10.1234/jfm.2023.001\n", encoding="utf-8")
        pdf = inbox / "paper_si.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        parent_json = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        outcome = _route_si_entry(
            "paper_si",
            {"pdf": pdf, "md": md, "office": None},
            inbox_dir=inbox,
            papers_dir=tmp_papers,
            pending_dir=tmp_path / "pending",
            existing_dois={"10.1234/jfm.2023.001": parent_json},
            cfg=self._cfg(),
            opts={},
            dry_run=False,
            inbox_steps=["extract", "dedup", "ingest"],
        )
        assert outcome == "attached"
        assert (tmp_papers / "Smith-2023-Turbulence" / "si" / "paper_si.md").exists()
        assert not pdf.exists() and not md.exists()  # inbox cleaned

    def test_route_orphan_when_no_parent(self, tmp_papers: Path, tmp_path: Path) -> None:
        from scrinium.ingest.pipeline import _route_si_entry

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        md = inbox / "paper_si.md"
        md.write_text(_SI_MD + "\ndoi:10.9999/nowhere.1\n", encoding="utf-8")

        outcome = _route_si_entry(
            "paper_si",
            {"pdf": None, "md": md, "office": None},
            inbox_dir=inbox,
            papers_dir=tmp_papers,
            pending_dir=tmp_path / "pending",
            existing_dois={},
            cfg=self._cfg(),
            opts={},
            dry_run=False,
            inbox_steps=["extract", "dedup", "ingest"],
        )
        assert outcome == "orphan"
        pending = tmp_path / "pending" / "paper_si"
        info = json.loads((pending / "pending.json").read_text(encoding="utf-8"))
        assert info["issue"] == "si_orphan"

    def test_route_normal_on_content_mismatch(self, tmp_papers: Path, tmp_path: Path) -> None:
        from scrinium.ingest.pipeline import _route_si_entry

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        md = inbox / "esi.md"
        md.write_text("# Regular paper about electrospray ionization", encoding="utf-8")

        outcome = _route_si_entry(
            "esi",
            {"pdf": None, "md": md, "office": None},
            inbox_dir=inbox,
            papers_dir=tmp_papers,
            pending_dir=tmp_path / "pending",
            existing_dois={},
            cfg=self._cfg(),
            opts={},
            dry_run=False,
            inbox_steps=["extract", "dedup", "ingest"],
        )
        assert outcome == "normal"

    def test_reconcile_orphans(self, tmp_papers: Path, tmp_path: Path) -> None:
        from scrinium.ingest.pipeline import _reconcile_si_orphans

        pending = tmp_path / "pending"
        orphan = pending / "paper_si"
        orphan.mkdir(parents=True)
        (orphan / "paper.md").write_text(_SI_MD + "\ndoi:10.1234/jfm.2023.001\n", encoding="utf-8")
        (orphan / "pending.json").write_text(json.dumps({"issue": "si_orphan"}), encoding="utf-8")

        new_paper = tmp_papers / "Smith-2023-Turbulence"
        _reconcile_si_orphans(pending, "10.1234/jfm.2023.001", new_paper, self._cfg(), dry_run=False)
        assert (new_paper / "si" / "paper.md").exists() or list((new_paper / "si").glob("*.md"))
        assert not orphan.exists()
