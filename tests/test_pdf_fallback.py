from __future__ import annotations

from pathlib import Path

from scrinium.ingest import pdf_fallback


def test_convert_pdf_with_fallback_uses_first_success(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md = tmp_path / "a.md"

    monkeypatch.setattr(pdf_fallback, "_run_docling", lambda *_: (False, "docling fail"))

    def _ok(_pdf: Path, out: Path):
        out.write_text("ok\n", encoding="utf-8")
        return True, None

    monkeypatch.setattr(pdf_fallback, "run_pymupdf", _ok)

    ok, parser, err = pdf_fallback.convert_pdf_with_fallback(pdf, md, parser_order=["docling", "pymupdf"])
    assert ok is True
    assert parser == "pymupdf"
    assert err is None
    assert md.read_text(encoding="utf-8") == "ok\n"


def test_convert_pdf_with_fallback_collects_errors(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    md = tmp_path / "a.md"

    monkeypatch.setattr(pdf_fallback, "_run_docling", lambda *_: (False, "docling bad"))
    monkeypatch.setattr(pdf_fallback, "run_pymupdf", lambda *_: (False, "pymupdf bad"))

    ok, parser, err = pdf_fallback.convert_pdf_with_fallback(pdf, md, parser_order=["docling", "pymupdf"])
    assert ok is False
    assert parser is None
    assert "docling bad" in (err or "")
    assert "pymupdf bad" in (err or "")


def test_pick_and_write_md_picks_longest(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "small.md").write_text("a", encoding="utf-8")
    (out_dir / "big.md").write_text("long markdown", encoding="utf-8")

    md = tmp_path / "final.md"
    ok, err = pdf_fallback.pick_and_write_md(out_dir, md, "docling")
    assert ok is True
    assert err is None
    assert "long markdown" in md.read_text(encoding="utf-8")


def test_pick_and_write_md_preserves_assets(tmp_path):
    out_dir = tmp_path / "out"
    doc_dir = out_dir / "doc"
    images_dir = doc_dir / "images"
    images_dir.mkdir(parents=True)
    (doc_dir / "paper.md").write_text("![fig](images/figure.png)\n", encoding="utf-8")
    (images_dir / "figure.png").write_bytes(b"pngdata")

    md_dir = tmp_path / "final"
    md_dir.mkdir()
    md = md_dir / "paper.md"

    ok, err = pdf_fallback.pick_and_write_md(out_dir, md, "docling")
    assert ok is True
    assert err is None
    assert "![fig](images/figure.png)" in md.read_text(encoding="utf-8")
    assert (md_dir / "images" / "figure.png").read_bytes() == b"pngdata"


def test_pick_and_write_md_preserves_leading_whitespace(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    original = "    code block line\n\nparagraph\n\n"
    (out_dir / "doc.md").write_text(original, encoding="utf-8")

    md = tmp_path / "final.md"
    ok, err = pdf_fallback.pick_and_write_md(out_dir, md, "docling")

    assert ok is True
    assert err is None
    assert md.read_text(encoding="utf-8") == "    code block line\n\nparagraph\n"


def test_copy_parser_assets_replaces_matching_asset_tree_only(tmp_path):
    src_dir = tmp_path / "src"
    src_images = src_dir / "images"
    src_images.mkdir(parents=True)
    selected = src_dir / "paper.md"
    selected.write_text("![fig](images/new.png)\n", encoding="utf-8")
    (src_images / "new.png").write_bytes(b"new")

    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    md = dst_dir / "paper.md"
    md.write_text("old\n", encoding="utf-8")
    stale_images = dst_dir / "images"
    stale_images.mkdir()
    (stale_images / "old.png").write_bytes(b"old")
    (dst_dir / "stale.txt").write_text("stale\n", encoding="utf-8")
    (dst_dir / "meta.json").write_text('{"title": "keep"}\n', encoding="utf-8")
    (dst_dir / "source.pdf").write_bytes(b"%PDF-1.4\n")

    pdf_fallback.copy_parser_assets(selected, md)

    assert (dst_dir / "images" / "new.png").read_bytes() == b"new"
    assert not (dst_dir / "images" / "old.png").exists()
    assert (dst_dir / "stale.txt").read_text(encoding="utf-8") == "stale\n"
    assert (dst_dir / "meta.json").read_text(encoding="utf-8") == '{"title": "keep"}\n'
    assert (dst_dir / "source.pdf").read_bytes() == b"%PDF-1.4\n"


def test_public_pdf_fallback_helpers_are_available():
    assert callable(pdf_fallback.run_pymupdf)
    assert callable(pdf_fallback.pick_and_write_md)
    assert callable(pdf_fallback.copy_parser_assets)


def test_resolve_parser_order_auto(monkeypatch):
    monkeypatch.setattr(pdf_fallback, "detect_available_parsers", lambda: ["docling", "pymupdf"])
    order = pdf_fallback.resolve_parser_order(["auto", "docling", "auto"], auto_detect=True)
    assert order == ["docling", "pymupdf"]


def test_resolve_parser_order_auto_disabled():
    order = pdf_fallback.resolve_parser_order(["auto", "docling"], auto_detect=False)
    assert order == ["pymupdf", "docling"]


def test_resolve_parser_order_ignores_null_and_non_string_entries(monkeypatch):
    monkeypatch.setattr(pdf_fallback, "detect_available_parsers", lambda: ["docling", "pymupdf"])
    order = pdf_fallback.resolve_parser_order(["auto", None, " docling ", 123], auto_detect=True)
    assert order == ["docling", "pymupdf"]
