"""Unit tests for scrinium/sources/arxiv.py — search/fetch helpers.

All tests stub requests.get so no network access is required.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Sample Atom XML fixtures
# ---------------------------------------------------------------------------

_ATOM_FULL = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Attention Is All You Need Again</title>
    <summary>We propose a new transformer variant.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <arxiv:doi>10.1234/attn2</arxiv:doi>
  </entry>
</feed>
"""

_ATOM_MISSING_OPTIONAL = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2402.99999v1</id>
    <title>Minimal Entry</title>
    <!-- no summary, no published, no arxiv:doi -->
  </entry>
</feed>
"""

_ATOM_EMPTY_TEXT = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v2</id>
    <title></title>
    <summary></summary>
    <published>2024-03-01T00:00:00Z</published>
  </entry>
</feed>
"""

_ATOM_MULTI = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Paper One</title>
    <summary>Abstract one.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Alice</name></author>
    <arxiv:doi>10.1111/one</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Paper Two</title>
    <summary>Abstract two.</summary>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Bob</name></author>
  </entry>
</feed>
"""

_RECENT_LIST_HTML = """\
<html><body>
<dl>
  <dt>[1] <a href="/abs/2603.25626">arXiv:2603.25626</a></dt>
  <dd>
    <div class="list-title mathjax">Title: Converting vertical heat supply into horizontal motion</div>
    <div class="list-authors">Authors:
      <a href="/search/?searchtype=author&query=Schäfer">Jan-Niklas Schäfer</a>,
      <a href="/search/?searchtype=author&query=Carl">Tillmann Carl</a>
    </div>
  </dd>
  <dt>[2] <a href="/abs/2603.25200">arXiv:2603.25200</a></dt>
  <dd>
    <div class="list-title mathjax">Title: Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers</div>
    <div class="list-authors">Authors:
      <a href="/search/?searchtype=author&query=Zhang">Jizhong Zhang</a>,
      <a href="/search/?searchtype=author&query=Yao">Jie Yao</a>
    </div>
  </dd>
</dl>
</body></html>
"""


def _mock_response(xml_text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = xml_text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchArxivParsing:
    def test_session_respects_env_proxies(self):
        from scrinium.sources import arxiv

        assert arxiv._SESSION.trust_env is True

    def test_module_import_does_not_require_bs4(self, monkeypatch):
        real_import = builtins.__import__
        sys.modules.pop("scrinium.sources.arxiv", None)

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "bs4":
                raise ModuleNotFoundError("No module named 'bs4'")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        module = importlib.import_module("scrinium.sources.arxiv")

        assert hasattr(module, "search_arxiv")

    def test_full_entry_fields(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_FULL)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("attention", top_k=1)

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Attention Is All You Need Again"
        assert r["abstract"] == "We propose a new transformer variant."
        assert r["year"] == "2024"
        assert r["authors"] == ["Alice Smith", "Bob Jones"]
        assert r["arxiv_id"] == "2401.00001v1"
        assert r["doi"] == "10.1234/attn2"

    def test_missing_optional_fields(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_MISSING_OPTIONAL)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("minimal")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Minimal Entry"
        assert r["abstract"] == ""
        assert r["year"] == ""
        assert r["authors"] == []
        assert r["doi"] == ""
        assert r["arxiv_id"] == "2402.99999v1"

    def test_empty_title_and_abstract(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_EMPTY_TEXT)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("empty")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == ""
        assert r["abstract"] == ""
        assert r["year"] == "2024"

    def test_multiple_entries(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_MULTI)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("papers", top_k=5)

        assert len(results) == 2
        assert results[0]["title"] == "Paper One"
        assert results[0]["doi"] == "10.1111/one"
        assert results[1]["title"] == "Paper Two"
        assert results[1]["doi"] == ""

    def test_network_error_returns_empty(self):
        with patch("scrinium.sources.arxiv._SESSION.get", side_effect=ConnectionError("timeout")):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_http_error_returns_empty(self):
        import requests

        resp = _mock_response("", status_code=403)
        resp.raise_for_status.side_effect = requests.HTTPError("403")
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=resp):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_malformed_xml_returns_empty(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response("<not valid xml<<")):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_arxiv_id_extracted_from_url(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_FULL)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("attention")

        assert results[0]["arxiv_id"] == "2401.00001v1"

    def test_multiline_title_normalized(self):
        xml = _ATOM_FULL.replace("Attention Is All You Need Again", "Attention\nIs All\nYou Need")
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(xml)):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("attention")

        assert "\n" not in results[0]["title"]

    def test_search_supports_category_and_recent_sort(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_FULL)) as mocked_get:
            from scrinium.sources.arxiv import search_arxiv

            search_arxiv("turbulence", top_k=5, category="physics.flu-dyn", sort="recent")

        _, kwargs = mocked_get.call_args
        assert kwargs["params"]["search_query"] == "all:turbulence AND cat:physics.flu-dyn"
        assert kwargs["params"]["sortBy"] == "submittedDate"

    def test_search_supports_category_only(self):
        with patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(_ATOM_FULL)) as mocked_get:
            from scrinium.sources.arxiv import search_arxiv

            search_arxiv("", top_k=3, category="physics.flu-dyn")

        _, kwargs = mocked_get.call_args
        assert kwargs["params"]["search_query"] == "cat:physics.flu-dyn"

    def test_search_recent_falls_back_to_recent_list_page(self):
        responses = [
            _mock_response("", status_code=429),
            _mock_response(_RECENT_LIST_HTML),
        ]
        responses[0].raise_for_status.side_effect = Exception("429")

        with patch("scrinium.sources.arxiv._SESSION.get", side_effect=responses):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("direct numerical", top_k=5, category="physics.flu-dyn", sort="recent")

        assert len(results) == 1
        assert results[0]["arxiv_id"] == "2603.25200"
        assert results[0]["year"] == "2026"

    def test_search_recent_without_bs4_returns_empty(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "bs4":
                raise ModuleNotFoundError("No module named 'bs4'")
            return real_import(name, globals, locals, fromlist, level)

        responses = [
            _mock_response("", status_code=429),
            _mock_response(_RECENT_LIST_HTML),
        ]
        responses[0].raise_for_status.side_effect = Exception("429")

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with patch("scrinium.sources.arxiv._SESSION.get", side_effect=responses):
            from scrinium.sources.arxiv import search_arxiv

            results = search_arxiv("direct numerical", top_k=5, category="physics.flu-dyn", sort="recent")

        assert results == []


class TestNormalizeArxivRef:
    def test_accepts_bare_id(self):
        from scrinium.sources.arxiv import normalize_arxiv_ref

        assert normalize_arxiv_ref("2603.25200") == "2603.25200"

    def test_strips_version_suffix(self):
        from scrinium.sources.arxiv import normalize_arxiv_ref

        assert normalize_arxiv_ref("2603.25200v2") == "2603.25200"

    def test_parses_abs_url(self):
        from scrinium.sources.arxiv import normalize_arxiv_ref

        assert normalize_arxiv_ref("https://arxiv.org/abs/2603.25200v1") == "2603.25200"

    def test_parses_pdf_url(self):
        from scrinium.sources.arxiv import normalize_arxiv_ref

        assert normalize_arxiv_ref("https://arxiv.org/pdf/2603.25200.pdf") == "2603.25200"

    def test_accepts_old_ids_with_subject_class(self):
        from scrinium.sources.arxiv import normalize_arxiv_ref

        assert normalize_arxiv_ref("math.GT/0309136v1") == "math.GT/0309136"
        assert normalize_arxiv_ref("https://arxiv.org/abs/physics.class-ph/0301001v2") == "physics.class-ph/0301001"


class TestGetArxivPaperFallback:
    def test_falls_back_to_abs_page_meta_tags(self):
        html = """
        <html><head>
        <meta name="citation_title" content="Fallback Title" />
        <meta name="citation_author" content="Alice Smith" />
        <meta name="citation_author" content="Bob Jones" />
        <meta name="citation_date" content="2026/03/26" />
        <meta name="citation_arxiv_id" content="2603.25200" />
        <meta name="citation_abstract" content="Fallback abstract." />
        </head></html>
        """

        with (
            patch("scrinium.sources.arxiv._query_arxiv_api", return_value=[]),
            patch("scrinium.sources.arxiv._SESSION.get", return_value=_mock_response(html)),
        ):
            from scrinium.sources.arxiv import get_arxiv_paper

            result = get_arxiv_paper("2603.25200")

        assert result["title"] == "Fallback Title"
        assert result["authors"] == ["Alice Smith", "Bob Jones"]
        assert result["year"] == "2026"
        assert result["abstract"] == "Fallback abstract."
        assert result["arxiv_id"] == "2603.25200"


class TestDownloadArxivPdf:
    def test_downloads_pdf_to_target_dir(self, tmp_path):
        pdf_bytes = b"%PDF-1.4 fake"
        resp = MagicMock()
        resp.iter_content.return_value = [pdf_bytes]
        resp.raise_for_status = MagicMock()

        with patch("scrinium.sources.arxiv._SESSION.get", return_value=resp) as mocked_get:
            from scrinium.sources.arxiv import download_arxiv_pdf

            out = download_arxiv_pdf("https://arxiv.org/abs/2603.25200v1", tmp_path)

        assert out.name == "2603.25200.pdf"
        assert out.read_bytes() == pdf_bytes
        args, kwargs = mocked_get.call_args
        assert args[0] == "https://arxiv.org/pdf/2603.25200.pdf"
        assert kwargs["stream"] is True

    def test_download_old_style_id_uses_flat_sanitized_filename(self, tmp_path):
        pdf_bytes = b"%PDF-1.4 old-style"
        resp = MagicMock()
        resp.iter_content.return_value = [pdf_bytes]
        resp.raise_for_status = MagicMock()

        with patch("scrinium.sources.arxiv._SESSION.get", return_value=resp):
            from scrinium.sources.arxiv import download_arxiv_pdf

            out = download_arxiv_pdf("hep-th/9901001v1", tmp_path)

        assert out == tmp_path / "hep-th_9901001.pdf"
        assert out.read_bytes() == pdf_bytes

    def test_download_cleans_up_partial_file_when_stream_fails(self, tmp_path):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()

        def broken_stream(chunk_size=0):
            yield b"%PDF-1.4 partial"
            raise RuntimeError("network interrupted")

        resp.iter_content.side_effect = broken_stream

        with patch("scrinium.sources.arxiv._SESSION.get", return_value=resp):
            from scrinium.sources.arxiv import download_arxiv_pdf

            try:
                download_arxiv_pdf("2603.25200", tmp_path)
            except RuntimeError as exc:
                assert "network interrupted" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

        assert not (tmp_path / "2603.25200.pdf").exists()
        assert not list(tmp_path.glob("2603.25200.pdf.*"))
