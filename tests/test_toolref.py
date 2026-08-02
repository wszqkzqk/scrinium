"""Contract tests for the toolref package (scientific tool documentation knowledge base).

Tests assert the behavioral contract of each submodule (paths/parsers/manifest/
fetch/indexing/storage/search) plus the package-level public API surface.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from scrinium.toolref import (
    TOOL_REGISTRY,
    toolref_fetch,
    toolref_list,
    toolref_search,
    toolref_show,
    toolref_use,
    validate_tool_name,
)
from scrinium.toolref import fetch as fetch_mod
from scrinium.toolref import indexing as indexing_mod
from scrinium.toolref import manifest as manifest_mod
from scrinium.toolref import parsers as parsers_mod
from scrinium.toolref import paths as paths_mod
from scrinium.toolref import search as search_mod
from scrinium.toolref import storage as storage_mod


@pytest.fixture
def toolref_home(tmp_path, monkeypatch):
    """Redirect the toolref data root to a temp directory."""
    monkeypatch.setattr(paths_mod, "_DEFAULT_TOOLREF_DIR", tmp_path)
    return tmp_path


def _seed_tool_db(root: Path, tool: str, current: str, rows: list[tuple]) -> Path:
    """Create root/<tool>/toolref.db with a `current` symlink and insert rows.

    Each row is (version, program, section, page_name, title, synopsis, content);
    the tool name is prepended automatically.
    """
    tdir = root / tool
    vdir = tdir / current
    vdir.mkdir(parents=True, exist_ok=True)
    link = tdir / "current"
    if not link.is_symlink():
        link.symlink_to(vdir, target_is_directory=True)
    db = tdir / "toolref.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(storage_mod._PAGES_SCHEMA)
        conn.executescript(storage_mod._FTS_SCHEMA)
        conn.executescript(storage_mod._FTS_TRIGGERS)
        conn.executemany(
            """INSERT INTO toolref_pages
               (tool, version, program, section, page_name, title, synopsis, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(tool, *row) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _write_manifest_page(pages_dir: Path, stem: str, page_name: str, html: str = "<main><h1>page</h1></main>") -> None:
    (pages_dir / f"{stem}.html").write_text(html, encoding="utf-8")
    (pages_dir / f"{stem}.json").write_text(json.dumps({"page_name": page_name}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Package surface
# ---------------------------------------------------------------------------


def test_package_public_api_surface():
    import scrinium.toolref as pkg

    assert set(pkg.__all__) == {
        "TOOL_REGISTRY",
        "toolref_fetch",
        "toolref_list",
        "toolref_search",
        "toolref_show",
        "toolref_use",
        "validate_tool_name",
    }
    for name in pkg.__all__:
        getattr(pkg, name)


def test_tool_registry_contract():
    assert set(TOOL_REGISTRY) == {"qe", "lammps", "gromacs", "openfoam", "bioinformatics"}
    for info in TOOL_REGISTRY.values():
        assert info["display_name"]
        assert info["source_type"] in {"git", "manifest"}
        assert info["format"] in {"def", "rst", "html"}
        if info["source_type"] == "git":
            assert info["repo"].startswith("https://")
            assert "tag_prefix" in info
            assert info["doc_glob"]
        else:
            assert info["manifest_name"]
            assert info["default_version"]


def test_validate_tool_name():
    for name in ("qe", "lammps", "gromacs", "openfoam", "bioinformatics"):
        assert validate_tool_name(name)
    assert not validate_tool_name("vasp")


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def test_paths_layout_under_default_root(toolref_home):
    assert paths_mod._tool_dir("qe") == toolref_home / "qe"
    assert paths_mod._version_dir("qe", "7.5") == toolref_home / "qe" / "7.5"
    assert paths_mod._db_path("qe") == toolref_home / "qe" / "toolref.db"
    assert paths_mod._current_link("qe") == toolref_home / "qe" / "current"


def test_toolref_root_prefers_config_root(tmp_path):
    cfg = SimpleNamespace(_root=tmp_path)
    assert paths_mod._toolref_root(cfg) == tmp_path / "data" / "toolref"
    assert paths_mod._db_path("qe", cfg) == tmp_path / "data" / "toolref" / "qe" / "toolref.db"


def test_validate_version_rejects_unsafe_values():
    assert paths_mod._validate_version("7.5")
    assert paths_mod._validate_version("2026-03-curated")
    for bad in ("", "../escape", "a/b", "a\\b", "/abs"):
        assert not paths_mod._validate_version(bad)


# ---------------------------------------------------------------------------
# parsers: QE .def
# ---------------------------------------------------------------------------


def test_parse_qe_def_handles_compact_braces_and_option_info(tmp_path):
    def_file = tmp_path / "INPUT_PW.def"
    def_file.write_text(
        """
-program pw.x

namelist SYSTEM {
  var occupations {
    default{'smearing'}
    info{Occupation control}
    options{
      opt -val 'fixed' info{Keep occupations fixed}
      opt -val 'smearing' info{Use electronic smearing}
    }
  }
}
""",
        encoding="utf-8",
    )

    rows = parsers_mod._parse_qe_def(def_file)

    assert len(rows) == 1
    row = rows[0]
    assert row["program"] == "pw.x"
    assert row["section"] == "SYSTEM"
    assert row["page_name"] == "pw.x/SYSTEM/occupations"
    assert row["category"] == "variable"
    assert row["default_val"] == "'smearing'"
    assert "Occupation control" in row["content"]
    assert "Options: fixed, smearing" in row["content"]
    assert "Keep occupations fixed" in row["content"]
    assert "Use electronic smearing" in row["content"]


def test_parse_qe_def_parses_dimension_vargroup_and_card(tmp_path):
    def_file = tmp_path / "INPUT_PW.def"
    def_file.write_text(
        """
-program pw.x

namelist CONTROL {
  dimension ndeep -type INTEGER {
    default{1}
    info{Number of levels}
  }
  vargroup -type REAL {
    var ecutwfc
    var ecutrho
    info{Kinetic energy cutoffs}
  }
}

card ATOMIC_POSITIONS {
  Atomic positions card
  @br
  Syntax: ATOMIC_POSITIONS { alat }
}
""",
        encoding="utf-8",
    )

    records = parsers_mod._parse_qe_def(def_file)
    by_page = {r["page_name"]: r for r in records}

    ndeep = by_page["pw.x/CONTROL/ndeep"]
    assert ndeep["category"] == "dimension"
    assert ndeep["var_type"] == "INTEGER"
    assert ndeep["default_val"] == "1"

    for name in ("ecutwfc", "ecutrho"):
        rec = by_page[f"pw.x/CONTROL/{name}"]
        assert rec["category"] == "vargroup"
        assert rec["var_type"] == "REAL"
        assert "Kinetic energy cutoffs" in rec["content"]

    card = by_page["pw.x/card/ATOMIC_POSITIONS"]
    assert card["category"] == "card"
    assert card["section"] == "card"
    assert card["synopsis"] == "Input card: ATOMIC_POSITIONS"
    assert "Syntax: ATOMIC_POSITIONS" in card["content"]


def test_parse_qe_def_derives_program_from_filename(tmp_path):
    def_file = tmp_path / "INPUT_PH.def"
    def_file.write_text(
        "namelist INPUTPH {\n  var eps -type LOGICAL {\n    default{.false.}\n    info{Dielectric}\n  }\n}\n",
        encoding="utf-8",
    )

    records = parsers_mod._parse_qe_def(def_file)

    assert len(records) == 1
    assert records[0]["program"] == "ph"
    assert records[0]["page_name"] == "ph/INPUTPH/eps"


# ---------------------------------------------------------------------------
# parsers: LAMMPS / GROMACS rst
# ---------------------------------------------------------------------------


def test_parse_lammps_rst_surfaces_aliases_for_search(tmp_path):
    rst = tmp_path / "fix_nh.rst"
    rst.write_text(
        "\n".join(
            [
                "fix nvt command",
                "================",
                "",
                ".. index:: fix nvt",
                ".. index:: fix npt",
                ".. index:: fix nph",
                "",
                "Syntax",
                '""""""',
                "",
                ".. code-block:: LAMMPS",
                "",
                "   fix ID group-ID style_name keyword value ...",
                "",
                "Description",
                '"""""""""""',
                "",
                "Thermostat and barostat.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parsers_mod._parse_lammps_rst(rst)[0]

    assert "Aliases: fix nvt, fix npt, fix nph" in parsed["synopsis"]
    assert "fix npt" in parsed["content"]


def test_parse_lammps_rst_classifies_category_and_page(tmp_path):
    rst = tmp_path / "pair_lj.rst"
    rst.write_text(
        "\n".join(
            [
                "pair lj/cut command",
                "===================",
                "",
                "Syntax",
                '""""""',
                "",
                ".. code-block:: LAMMPS",
                "",
                "   pair_style lj/cut 2.5",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rec = parsers_mod._parse_lammps_rst(rst)[0]

    assert rec["program"] == "lammps"
    assert rec["category"] == "pair"
    assert rec["section"] == "pair"
    assert rec["page_name"] == "lammps/pair_lj"
    assert rec["title"] == "pair lj/cut command"
    assert "pair_style lj/cut 2.5" in rec["synopsis"]


def test_parse_gromacs_mdp_block_keeps_option_descriptions(tmp_path):
    rst = tmp_path / "mdp-options.rst"
    rst.write_text(
        """
.. mdp:: pcoupl

   .. mdp-value:: no

      No pressure coupling.

   .. mdp-value:: Parrinello-Rahman

      Extended-ensemble pressure coupling.

.. mdp:: constraints

   Controls which bonds become rigid.

   .. mdp-value:: h-bonds

      Convert the bonds with H-atoms to constraints.
""",
        encoding="utf-8",
    )

    records = parsers_mod._parse_gromacs_rst(rst)
    pcoupl = next(r for r in records if r["title"] == "pcoupl")
    constraints = next(r for r in records if r["title"] == "constraints")

    assert "Parrinello-Rahman" in pcoupl["synopsis"]
    assert "Extended-ensemble pressure coupling" in pcoupl["content"]
    assert pcoupl["page_name"] == "gromacs/mdp/pcoupl"
    assert "h-bonds" in constraints["synopsis"]
    assert "Convert the bonds with H-atoms to constraints." in constraints["content"]


def test_parse_gromacs_rst_general_page_uses_path_section(tmp_path):
    guide = tmp_path / "user-guide"
    guide.mkdir()
    rst = guide / "getting-started.rst"
    rst.write_text("Getting Started\n===============\n\nBody text.\n", encoding="utf-8")

    records = parsers_mod._parse_gromacs_rst(rst)

    assert len(records) == 1
    rec = records[0]
    assert rec["program"] == "gromacs"
    assert rec["section"] == "user-guide"
    assert rec["page_name"] == "gromacs/user-guide/getting-started"
    assert rec["title"] == "Getting Started"
    assert "Body text." in rec["content"]


# ---------------------------------------------------------------------------
# parsers: manifest html
# ---------------------------------------------------------------------------


def _write_manifest_html_pair(tmp_path: Path, meta: dict, html: str) -> Path:
    html_path = tmp_path / "page.html"
    html_path.write_text(html, encoding="utf-8")
    html_path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    return html_path


def test_parse_manifest_html_extracts_main_text(tmp_path):
    html_path = _write_manifest_html_pair(
        tmp_path,
        {
            "program": "simpleFoam",
            "section": "solver",
            "page_name": "openfoam/simpleFoam",
            "title": "simpleFoam",
        },
        """
        <html>
          <body>
            <main>
              <h1>simpleFoam</h1>
              <p>Steady-state incompressible solver.</p>
              <pre><code>simpleFoam -case motorBike</code></pre>
            </main>
          </body>
        </html>
        """,
    )

    records = parsers_mod._parse_manifest_html(html_path)

    assert len(records) == 1
    record = records[0]
    assert record["page_name"] == "openfoam/simpleFoam"
    assert record["program"] == "simpleFoam"
    assert record["section"] == "solver"
    assert "Steady-state incompressible solver." in record["content"]
    assert "simpleFoam -case motorBike" in record["content"]


def test_parse_manifest_html_uses_dictionary_synopsis(tmp_path):
    html_path = _write_manifest_html_pair(
        tmp_path,
        {
            "program": "fvSchemes",
            "section": "dictionary",
            "page_name": "openfoam/fvSchemes",
            "title": "fvSchemes",
        },
        """
        <html><body><main><h1>fvSchemes</h1><pre><code>FoamFile {}</code></pre></main></body></html>
        """,
    )

    record = parsers_mod._parse_manifest_html(html_path)[0]
    assert record["synopsis"] == "fvSchemes dictionary"


def test_clean_manifest_text_removes_common_navigation_and_footer():
    raw = """
Top
Toggle navigation
simpleFoam
- solvers
Overview
Steady-state incompressible solver.
Search results
Found a content problem with this page?
"""
    cleaned = parsers_mod._clean_manifest_text(raw, "simpleFoam", "simpleFoam")
    assert "Toggle navigation" not in cleaned
    assert "Search results" not in cleaned
    assert "Steady-state incompressible solver." in cleaned


def test_clean_manifest_text_anchors_blast_manual():
    raw = """
Bookshelf
Toggle navigation
BLAST® Command Line Applications User Manual
This manual documents the BLAST command line applications.
Search results
"""
    cleaned = parsers_mod._clean_manifest_text(raw, "BLAST+ user manual", "blastn")
    assert cleaned.startswith("BLAST")
    assert "Bookshelf" not in cleaned


def test_pick_manifest_synopsis_skips_generic_lines():
    lines = ["simpleFoam", "- solvers", "Overview", "Steady-state incompressible solver."]
    assert parsers_mod._pick_manifest_synopsis(lines, "simpleFoam") == "Steady-state incompressible solver."


# ---------------------------------------------------------------------------
# manifest: builders and discovery
# ---------------------------------------------------------------------------


def test_build_openfoam_manifest_uses_requested_version():
    manifest = manifest_mod._build_openfoam_manifest("2312")
    assert manifest
    assert all("page_name" in item for item in manifest)
    assert any("/2312/" in item["url"] for item in manifest if "doc.openfoam.com" in item["url"])


def test_build_openfoam_manifest_includes_specific_mesh_and_post_pages():
    manifest = manifest_mod._build_openfoam_manifest("2312")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["openfoam/blockMesh"]["url"].endswith(
        "/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/"
    )
    assert pages["openfoam/forceCoeffs"]["url"].endswith(
        "/2312/tools/post-processing/function-objects/forces/forceCoeffs/"
    )
    assert pages["openfoam/Q"]["url"].endswith("/2312/tools/post-processing/function-objects/field/Q/")


def test_build_openfoam_manifest_includes_validation_and_wall_pages():
    manifest = manifest_mod._build_openfoam_manifest("2312")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["openfoam/yPlus"]["url"].endswith("/2312/tools/post-processing/function-objects/field/yPlus/")
    assert pages["openfoam/wallShearStress"]["url"].endswith(
        "/2312/tools/post-processing/function-objects/field/wallShearStress/"
    )
    assert pages["openfoam/residuals"]["url"].endswith("/2312/tools/processing/numerics/solvers/residuals/")


def test_build_bioinformatics_manifest_contains_multiple_subtools():
    manifest = manifest_mod._build_bioinformatics_manifest("2026-03-curated")
    programs = {item["program"] for item in manifest}
    assert {"blastn", "minimap2", "samtools", "bcftools", "mafft", "iqtree", "esmfold"} <= programs


def test_build_bioinformatics_manifest_includes_high_value_entry_points():
    manifest = manifest_mod._build_bioinformatics_manifest("2026-03-curated")
    pages = {item["page_name"]: item for item in manifest}

    assert pages["minimap2/manual"]["url"] == "https://lh3.github.io/minimap2/minimap2.html"
    assert "fallback_urls" in pages["minimap2/manual"]
    assert "github.com/lh3/minimap2" in pages["minimap2/manual"]["fallback_urls"][0]
    assert pages["bcftools/call"]["url"].endswith("/bcftools.html#call")
    assert pages["bcftools/mpileup"]["url"].endswith("/bcftools.html#mpileup")
    assert pages["iqtree/ultrafast-bootstrap"]["url"].endswith("/Command-Reference#ultrafast-bootstrap-parameters")
    assert pages["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap-parameters"
    assert pages["samtools/index"]["url"].endswith("/samtools-index.html")


def test_build_manifest_dispatches_by_tool_and_rejects_unknown():
    openfoam = manifest_mod._build_manifest("openfoam", "2312")
    assert any(item["page_name"] == "openfoam/simpleFoam" for item in openfoam)
    bio = manifest_mod._build_manifest("bioinformatics", "2026-03-curated")
    assert any(item["page_name"] == "blast/blastn" for item in bio)
    with pytest.raises(ValueError):
        manifest_mod._build_manifest("qe", "7.5")


def test_manifest_snapshot_roundtrip(tmp_path):
    vdir = tmp_path / "openfoam" / "2312"
    vdir.mkdir(parents=True)

    assert manifest_mod._load_manifest_snapshot(vdir) is None

    manifest_mod._write_manifest_snapshot(vdir, [{"page_name": "openfoam/simpleFoam"}])
    assert manifest_mod._load_manifest_snapshot(vdir) == [{"page_name": "openfoam/simpleFoam"}]

    (vdir / "manifest.json").write_text("{corrupt", encoding="utf-8")
    assert manifest_mod._load_manifest_snapshot(vdir) is None

    (vdir / "manifest.json").write_text('{"not": "a list"}', encoding="utf-8")
    assert manifest_mod._load_manifest_snapshot(vdir) is None


def test_normalize_openfoam_doc_url_filters_version_and_assets():
    assert (
        manifest_mod._normalize_openfoam_doc_url("/2312/fundamentals/", "2312")
        == "https://doc.openfoam.com/2312/fundamentals/"
    )
    assert manifest_mod._normalize_openfoam_doc_url("/2212/fundamentals/", "2312") is None
    assert manifest_mod._normalize_openfoam_doc_url("/2312/img/logo.png", "2312") is None


def test_extract_openfoam_doc_links_keeps_main_doc_paths():
    html = """
    <a href="/2312/fundamentals/">Fundamentals</a>
    <a href="/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/">blockMesh</a>
    <a href="/2312/installation/">Install</a>
    <a href="/2312/img/openfoam_logo.jpg">Logo</a>
    """
    links = manifest_mod._extract_openfoam_doc_links(html, "2312")
    assert "https://doc.openfoam.com/2312/fundamentals/" in links
    assert "https://doc.openfoam.com/2312/tools/pre-processing/mesh/generation/blockMesh/blockmesh/" in links
    assert all("/installation/" not in link for link in links)


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_discover_openfoam_manifest_builds_curated_mainline_pages():
    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://doc.openfoam.com/2312/fundamentals/": """
                    <a href="/2312/fundamentals/case-structure/controldict/">controlDict</a>
                    <a href="/2312/fundamentals/case-structure/fvschemes/">fvSchemes</a>
                    <a href="/2312/installation/">Installation</a>
                """,
                "https://doc.openfoam.com/2312/tools/": """
                    <a href="/2312/tools/processing/solvers/rtm/incompressible/simpleFoam/">simpleFoam</a>
                    <a href="/2312/tools/post-processing/function-objects/forces/forceCoeffs/">forceCoeffs</a>
                    <a href="/2312/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/">kOmegaSST</a>
                """,
                "https://doc.openfoam.com/2312/fundamentals/case-structure/controldict/": "<main><h1>controlDict</h1></main>",
                "https://doc.openfoam.com/2312/fundamentals/case-structure/fvschemes/": "<main><h1>fvSchemes</h1></main>",
                "https://doc.openfoam.com/2312/tools/processing/solvers/rtm/incompressible/simpleFoam/": "<main><h1>simpleFoam</h1></main>",
                "https://doc.openfoam.com/2312/tools/post-processing/function-objects/forces/forceCoeffs/": "<main><h1>forceCoeffs</h1></main>",
                "https://doc.openfoam.com/2312/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSST/": "<main><h1>kOmegaSST</h1></main>",
            }

        def get(self, url, timeout=None):
            return _FakeResponse(self.pages[url])

    manifest = manifest_mod._discover_openfoam_manifest("2312", FakeSession())
    page_names = {item["page_name"] for item in manifest}
    assert "openfoam/controlDict" in page_names
    assert "openfoam/fvSchemes" in page_names
    assert "openfoam/simpleFoam" in page_names
    assert "openfoam/forceCoeffs" in page_names
    assert "openfoam/kOmegaSST" in page_names
    assert all("installation" not in item["url"] for item in manifest)


def test_discover_openfoam_manifest_preserves_curated_core_pages_when_crawl_is_partial():
    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://doc.openfoam.com/2312/fundamentals/": """
                    <a href="/2312/fundamentals/case-structure/controldict/">controlDict</a>
                """,
                "https://doc.openfoam.com/2312/tools/": """
                    <a href="/2312/tools/post-processing/function-objects/forces/forceCoeffs/">forceCoeffs</a>
                """,
                "https://doc.openfoam.com/2312/fundamentals/case-structure/controldict/": "<main><h1>controlDict</h1></main>",
                "https://doc.openfoam.com/2312/tools/post-processing/function-objects/forces/forceCoeffs/": "<main><h1>forceCoeffs</h1></main>",
            }

        def get(self, url, timeout=None):
            return _FakeResponse(self.pages[url])

    manifest = manifest_mod._discover_openfoam_manifest("2312", FakeSession())
    page_names = {item["page_name"] for item in manifest}

    assert "openfoam/simpleFoam" in page_names
    assert "openfoam/fvSchemes" in page_names
    assert "openfoam/controlDict" in page_names
    assert "openfoam/forceCoeffs" in page_names


def test_extract_html_headings_with_ids_reads_h2_and_h3():
    html = """
    <h2 id="general-options">General options</h2>
    <h3 id="call">bcftools call</h3>
    <h4 id="ignored">ignored</h4>
    """
    headings = manifest_mod._extract_html_headings_with_ids(html)
    assert headings == [
        {"level": 2, "id": "general-options", "title": "General options"},
        {"level": 3, "id": "call", "title": "bcftools call"},
    ]


def test_extract_html_anchor_fragment_cuts_section_until_next_peer_heading():
    html = """
    <main>
      <h2 id="alpha">Alpha</h2>
      <p>A</p>
      <h3 id="beta">Beta</h3>
      <p>B</p>
      <h3 id="gamma">Gamma</h3>
      <p>C</p>
    </main>
    """
    fragment = manifest_mod._extract_html_anchor_fragment(html, "beta")
    assert "Beta" in fragment
    assert "B" in fragment
    assert "Gamma" not in fragment


def test_discover_bioinformatics_manifest_expands_from_official_index_pages():
    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://www.htslib.org/doc/samtools.html": """
                    <a href="samtools-flagstat.html">flagstat</a>
                    <a href="samtools-depth.html">depth</a>
                """,
                "https://samtools.github.io/bcftools/bcftools.html": """
                    <h3 id="call">bcftools call</h3>
                    <h3 id="query">bcftools query</h3>
                    <h2 id="expressions">EXPRESSIONS</h2>
                """,
                "https://iqtree.github.io/doc/Command-Reference": """
                    <h2 id="general-options">General options</h2>
                    <h2 id="ultrafast-bootstrap">Ultrafast bootstrap</h2>
                    <h3 id="example-usages">Example usages</h3>
                """,
            }

        def get(self, url, timeout=None):
            return _FakeResponse(self.pages[url])

    manifest, prefetched = manifest_mod._discover_bioinformatics_manifest(
        "2026-03-curated",
        FakeSession(),
        manifest_mod._build_bioinformatics_manifest("2026-03-curated"),
    )
    pages = {item["page_name"] for item in manifest}
    assert "samtools/flagstat" in pages
    assert "samtools/depth" in pages
    assert "bcftools/query" in pages
    assert "bcftools/expressions" in pages
    assert "iqtree/general-options" in pages
    assert "iqtree/ultrafast-bootstrap" in pages
    items = {item["page_name"]: item for item in manifest}
    assert items["bcftools/call"]["anchor"] == "call"
    assert items["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap"
    assert "https://www.htslib.org/doc/samtools.html" in prefetched


def test_discover_bioinformatics_manifest_upgrades_curated_alias_to_real_anchor():
    class FakeSession:
        def __init__(self):
            self.pages = {
                "https://www.htslib.org/doc/samtools.html": "",
                "https://samtools.github.io/bcftools/bcftools.html": "",
                "https://iqtree.github.io/doc/Command-Reference": """
                    <h2 id="ultrafast-bootstrap-parameters">Ultrafast bootstrap parameters</h2>
                """,
            }

        def get(self, url, timeout=None):
            return _FakeResponse(self.pages[url])

    manifest, _ = manifest_mod._discover_bioinformatics_manifest(
        "2026-03-curated",
        FakeSession(),
        manifest_mod._build_bioinformatics_manifest("2026-03-curated"),
    )
    items = {item["page_name"]: item for item in manifest}
    assert items["iqtree/ultrafast-bootstrap"]["anchor"] == "ultrafast-bootstrap-parameters"
    assert items["iqtree/ultrafast-bootstrap"]["url"].endswith("/Command-Reference#ultrafast-bootstrap-parameters")


def test_discover_bioinformatics_manifest_reuses_cached_seed_pages(tmp_path):
    class FailingSession:
        def get(self, url, timeout=None):
            raise requests.RequestException("timeout")

    cache_vdir = tmp_path / "bio" / "2026-03-curated"
    pages_dir = cache_vdir / "pages"
    pages_dir.mkdir(parents=True)
    _write_manifest_page(
        pages_dir,
        "001-bcftools-manual",
        "bcftools/manual",
        html='<h3 id="query">bcftools query</h3><h3 id="view">bcftools view</h3>',
    )

    manifest, prefetched = manifest_mod._discover_bioinformatics_manifest(
        "2026-03-curated",
        FailingSession(),
        manifest_mod._build_bioinformatics_manifest("2026-03-curated"),
        cache_vdir=cache_vdir,
    )

    pages = {item["page_name"] for item in manifest}
    assert "bcftools/query" in pages
    assert "https://samtools.github.io/bcftools/bcftools.html" in prefetched


def test_has_local_docs_for_manifest_html(toolref_home):
    pages_dir = toolref_home / "openfoam" / "2312" / "pages"
    pages_dir.mkdir(parents=True)
    assert not manifest_mod._has_local_docs("openfoam", "2312")

    _write_manifest_page(pages_dir, "001-openfoam-simpleFoam", "openfoam/simpleFoam", html="<html></html>")
    assert not manifest_mod._has_local_docs("openfoam", "2312")

    manifest = manifest_mod._build_openfoam_manifest("2312")
    for idx, item in enumerate(manifest, start=1):
        (pages_dir / f"{idx:03d}-{item['page_name'].replace('/', '-')}.html").write_text(
            "<html></html>", encoding="utf-8"
        )
        (pages_dir / f"{idx:03d}-{item['page_name'].replace('/', '-')}.json").write_text("{}", encoding="utf-8")
    assert manifest_mod._has_local_docs("openfoam", "2312")


# ---------------------------------------------------------------------------
# indexing / storage
# ---------------------------------------------------------------------------


def test_index_tool_returns_final_unique_entry_count(toolref_home, monkeypatch):
    vdir = toolref_home / "qe" / "7.5" / "def"
    vdir.mkdir(parents=True)
    (vdir / "INPUT_FAKE.def").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(
        indexing_mod,
        "_parse_qe_def",
        lambda _path: [
            {
                "program": "pw.x",
                "section": "SYSTEM",
                "page_name": "pw.x/SYSTEM/ecutwfc",
                "title": "ecutwfc",
                "content": "first",
            },
            {
                "program": "pw.x",
                "section": "SYSTEM",
                "page_name": "pw.x/SYSTEM/ecutwfc",
                "title": "ecutwfc",
                "content": "updated",
            },
            {
                "program": "pw.x",
                "section": "ELECTRONS",
                "page_name": "pw.x/ELECTRONS/conv_thr",
                "title": "conv_thr",
                "content": "third",
            },
        ],
    )

    count = indexing_mod._index_tool("qe", "7.5", cfg=None)

    assert count == 2
    conn = sqlite3.connect(toolref_home / "qe" / "toolref.db")
    try:
        db_count = conn.execute(
            "SELECT COUNT(*) FROM toolref_pages WHERE tool = ? AND version = ?",
            ("qe", "7.5"),
        ).fetchone()[0]
        assert db_count == 2
    finally:
        conn.close()


def test_ensure_db_drops_legacy_fts_triggers(tmp_path):
    db = tmp_path / "toolref.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE toolref_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool TEXT NOT NULL,
                version TEXT NOT NULL,
                program TEXT,
                section TEXT,
                page_name TEXT NOT NULL,
                title TEXT,
                category TEXT,
                var_type TEXT,
                default_val TEXT,
                synopsis TEXT,
                content TEXT NOT NULL,
                UNIQUE(tool, version, page_name)
            );
            CREATE VIRTUAL TABLE toolref_fts USING fts5(
                page_name, title, synopsis, content,
                content=toolref_pages,
                content_rowid=id
            );
            CREATE TRIGGER toolref_ai AFTER INSERT ON toolref_pages BEGIN
                INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
                VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
            END;
            CREATE TRIGGER toolref_ad AFTER DELETE ON toolref_pages BEGIN
                INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
                VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
            END;
            CREATE TRIGGER toolref_au AFTER UPDATE ON toolref_pages BEGIN
                INSERT INTO toolref_fts(toolref_fts, rowid, page_name, title, synopsis, content)
                VALUES ('delete', old.id, old.page_name, old.title, old.synopsis, old.content);
                INSERT INTO toolref_fts(rowid, page_name, title, synopsis, content)
                VALUES (new.id, new.page_name, new.title, new.synopsis, new.content);
            END;
            """
        )
        conn.execute(
            """INSERT INTO toolref_pages
               (tool, version, program, section, page_name, title, synopsis, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("qe", "7.5", "pw.x", "SYSTEM", "pw.x/SYSTEM/ecutwfc", "ecutwfc", "cutoff", "content"),
        )
        conn.commit()
    finally:
        conn.close()

    conn = storage_mod._ensure_db(db)
    try:
        trigger_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name").fetchall()
        }
        assert "toolref_ai" not in trigger_names
        assert "toolref_ad" not in trigger_names
        assert "toolref_au" not in trigger_names
        assert "toolref_pages_ai" in trigger_names
        assert "toolref_pages_ad" in trigger_names
        assert "toolref_pages_au" in trigger_names

        conn.execute("DELETE FROM toolref_pages WHERE tool = ? AND version = ?", ("qe", "7.5"))
        conn.commit()
    finally:
        conn.close()


def test_toolref_use_sets_current_symlink(toolref_home):
    (toolref_home / "qe" / "7.5").mkdir(parents=True)

    toolref_use("qe", "7.5", cfg=None)

    link = toolref_home / "qe" / "current"
    assert link.is_symlink()
    assert link.resolve().name == "7.5"


def test_toolref_use_requires_existing_version_dir(toolref_home):
    with pytest.raises(FileNotFoundError):
        toolref_use("qe", "9.9", cfg=None)


def test_toolref_use_rejects_unsafe_version_path(toolref_home):
    with pytest.raises(ValueError, match="非法版本号"):
        toolref_use("qe", "../outside", cfg=None)

    assert not (toolref_home / "qe" / "current").exists()


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def test_toolref_fetch_rejects_unknown_tool_and_bad_version():
    with pytest.raises(ValueError, match="未知工具"):
        toolref_fetch("vasp", cfg=None)
    with pytest.raises(ValueError, match="无效版本号"):
        toolref_fetch("qe", version="../x", cfg=None)


def test_toolref_fetch_refreshes_manifest_meta_when_skipping_existing_docs(toolref_home, monkeypatch):
    vdir = toolref_home / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, page_name in enumerate(["openfoam/simpleFoam", "openfoam/fvSchemes"], start=1):
        _write_manifest_page(pages_dir, f"{idx:03d}-page", page_name)
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": "openfoam/simpleFoam"}, {"page_name": "openfoam/fvSchemes"}]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "display_name": "OpenFOAM",
                "version": "2312",
                "format": "html",
                "repo": "",
                "source_type": "manifest",
                "force_refreshed": False,
                "fetched_pages": 2,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 2)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = fetch_mod.toolref_fetch("openfoam", version="2312", cfg=None)

    assert count == 2
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["expected_pages"] == 2
    assert meta["failed_pages"] == 0


def test_toolref_fetch_bioinformatics_reuses_prefetched_seed_html_for_anchor_pages(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            raise requests.RequestException(f"unexpected fetch: {url}")

    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_discover_bioinformatics_manifest",
        lambda version, session, manifest, cache_vdir=None: (
            [
                {
                    "program": "bcftools",
                    "section": "variant-calling",
                    "page_name": "bcftools/query",
                    "title": "bcftools query",
                    "url": "https://samtools.github.io/bcftools/bcftools.html#query",
                    "anchor": "query",
                }
            ],
            {
                "https://samtools.github.io/bcftools/bcftools.html": '<h3 id="query">bcftools query</h3><p>query body</p>'
            },
        ),
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    page = toolref_home / "bioinformatics" / "2026-03-curated" / "pages" / "001-bcftools-query.html"
    assert page.exists()


def test_toolref_fetch_manifest_force_rebuilds_pages(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            return _FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            }
        ],
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("openfoam", version="2312", cfg=None)
    assert count == 1

    extra = toolref_home / "openfoam" / "2312" / "pages" / "stale.html"
    extra.write_text("stale", encoding="utf-8")

    count = toolref_fetch("openfoam", version="2312", force=True, cfg=None)
    assert count == 1
    assert not extra.exists()


def test_toolref_fetch_manifest_force_keeps_more_complete_cache(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            if "view" in url:
                raise requests.RequestException("boom")
            return _FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/sort",
                "title": "samtools sort",
                "url": "https://example.org/sort",
            },
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/view",
                "title": "samtools view",
                "url": "https://example.org/view",
            },
        ],
    )

    vdir = toolref_home / "bioinformatics" / "2026-03-curated"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, (name, page_name) in enumerate(
        [("samtools-sort", "samtools/sort"), ("samtools-view", "samtools/view")],
        start=1,
    ):
        _write_manifest_page(pages_dir, f"{idx:03d}-{name}", page_name, html="<html></html>")
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "bioinformatics",
                "version": "2026-03-curated",
                "source_type": "manifest",
                "fetched_pages": 2,
                "expected_pages": 2,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod, "_index_tool", lambda tool, version, cfg=None: fetch_mod.manifest_mod._manifest_page_count(vdir)
    )
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)
    assert count == 2
    assert (pages_dir / "002-samtools-view.html").exists()
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["failed_pages"] == 0
    assert meta["last_fetch_failed_page_names"] == ["samtools/view"]


def test_toolref_fetch_manifest_force_preserves_failed_pages_from_existing_cache(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=60):
            if "simpleFoam" in url:
                raise requests.RequestException("timeout")
            return _FakeResponse(f"<html><body><main><h1>{url}</h1></main></body></html>")

    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            },
            {
                "program": "yPlus",
                "section": "post-processing",
                "page_name": "openfoam/yPlus",
                "title": "yPlus",
                "url": "https://example.org/yPlus",
            },
        ],
    )

    vdir = toolref_home / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "001-openfoam-simpleFoam.html").write_text(
        "<html><body>cached simpleFoam</body></html>", encoding="utf-8"
    )
    (pages_dir / "001-openfoam-simpleFoam.json").write_text(
        json.dumps(
            {
                "program": "simpleFoam",
                "section": "solver",
                "page_name": "openfoam/simpleFoam",
                "title": "simpleFoam",
                "url": "https://example.org/simpleFoam",
            }
        ),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 1,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 2)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("openfoam", version="2312", force=True, cfg=None)
    assert count == 2
    assert (pages_dir / "001-openfoam-simpleFoam.html").exists()
    assert (pages_dir / "002-openfoam-yPlus.html").exists()
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["fetched_pages"] == 2
    assert meta["failed_pages"] == 0
    assert meta["last_fetch_failed_page_names"] == ["openfoam/simpleFoam"]


def test_toolref_fetch_manifest_force_recovers_from_corrupted_meta_json(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.trust_env = True

        def get(self, url, timeout=60):
            return _FakeResponse("<html><body><main><h1>doc</h1></main></body></html>")

    monkeypatch.setattr(requests, "Session", FakeSession)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "samtools",
                "section": "alignment",
                "page_name": "samtools/sort",
                "title": "samtools sort",
                "url": "https://example.org/sort",
            }
        ],
    )

    vdir = toolref_home / "bioinformatics" / "2026-03-curated"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    (vdir / "meta.json").write_text("{not valid json", encoding="utf-8")

    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = fetch_mod.toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    meta = json.loads((vdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["tool"] == "bioinformatics"
    assert meta["version"] == "2026-03-curated"
    assert meta["fetched_pages"] == 1
    assert meta["failed_pages"] == 0
    assert (pages_dir / "001-samtools-sort.html").exists()


def test_toolref_fetch_manifest_uses_fallback_urls(toolref_home, monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
            self.trust_env = True

        def get(self, url, timeout=60):
            self.calls.append(url)
            if "primary" in url:
                raise requests.RequestException("timeout")
            return _FakeResponse("<html><body><main><h1>minimap2 manual</h1></main></body></html>")

    session = FakeSession()
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(
        fetch_mod.manifest_mod,
        "_build_manifest",
        lambda tool, version: [
            {
                "program": "minimap2",
                "section": "alignment",
                "page_name": "minimap2/manual",
                "title": "minimap2 manual",
                "url": "https://example.org/primary",
                "fallback_urls": ["https://example.org/fallback"],
            }
        ],
    )
    monkeypatch.setattr(fetch_mod, "_index_tool", lambda tool, version, cfg=None: 1)
    monkeypatch.setattr(fetch_mod.storage_mod, "_set_current", lambda tool, version, cfg=None: None)

    count = toolref_fetch("bioinformatics", version="2026-03-curated", force=True, cfg=None)

    assert count == 1
    assert session.trust_env is False
    assert session.calls == ["https://example.org/primary", "https://example.org/fallback"]


# ---------------------------------------------------------------------------
# toolref_list
# ---------------------------------------------------------------------------


def test_toolref_list_reads_manifest_meta(toolref_home):
    vdir = toolref_home / "openfoam" / "2312"
    vdir.mkdir(parents=True)
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": f"page-{idx}"} for idx in range(11)]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 9,
                "expected_pages": 11,
                "failed_pages": 2,
            }
        ),
        encoding="utf-8",
    )
    (toolref_home / "openfoam" / "current").symlink_to(vdir, target_is_directory=True)

    entries = toolref_list("openfoam", cfg=None)
    assert len(entries) == 1
    assert entries[0]["source_type"] == "manifest"
    assert entries[0]["expected_pages"] == 11
    assert entries[0]["failed_pages"] == 2
    assert entries[0]["is_current"]


def test_toolref_list_reconciles_stale_manifest_meta_with_snapshot(toolref_home):
    vdir = toolref_home / "openfoam" / "2312"
    pages_dir = vdir / "pages"
    pages_dir.mkdir(parents=True)
    for idx, page_name in enumerate(["openfoam/simpleFoam", "openfoam/fvSchemes"], start=1):
        _write_manifest_page(pages_dir, f"{idx:03d}-page", page_name)
    (vdir / "manifest.json").write_text(
        json.dumps([{"page_name": "openfoam/simpleFoam"}, {"page_name": "openfoam/fvSchemes"}]),
        encoding="utf-8",
    )
    (vdir / "meta.json").write_text(
        json.dumps(
            {
                "tool": "openfoam",
                "version": "2312",
                "source_type": "manifest",
                "fetched_pages": 2,
                "expected_pages": 1,
                "failed_pages": 0,
            }
        ),
        encoding="utf-8",
    )
    (toolref_home / "openfoam" / "current").symlink_to(vdir, target_is_directory=True)

    entries = toolref_list("openfoam", cfg=None)
    assert len(entries) == 1
    assert entries[0]["page_count"] == 2
    assert entries[0]["expected_pages"] == 2
    assert entries[0]["failed_pages"] == 0


# ---------------------------------------------------------------------------
# search helpers
# ---------------------------------------------------------------------------


def test_normalize_program_filter_for_qe():
    assert search_mod._normalize_program_filter("qe", "pw") == "pw.x"
    assert search_mod._normalize_program_filter("qe", "ph.x") == "ph.x"


def test_normalize_program_filter_for_non_qe():
    assert search_mod._normalize_program_filter("openfoam", "simpleFoam") == "simplefoam"
    assert search_mod._normalize_program_filter("bioinformatics", "samtools") == "samtools"


def test_normalize_search_query_rewrites_punctuation_runs():
    assert search_mod._normalize_search_query("k-point/convergence") == "k point convergence"
    assert search_mod._normalize_search_query("  spike__rbd ") == "spike rbd"


def test_normalize_alias_phrase_normalizes_case_underscores_and_spacing():
    assert search_mod._normalize_alias_phrase("Fix  NPT") == "fix npt"
    assert search_mod._normalize_alias_phrase("fix_nvt") == "fix nvt"
    assert search_mod._normalize_alias_phrase("fix", "npt") == "fix npt"
    assert search_mod._normalize_alias_phrase("", "  ") == ""


def test_tokenize_rank_text_splits_normalized_tokens():
    assert search_mod._tokenize_rank_text("Fix_NPT  command") == ["fix", "npt", "command"]
    assert search_mod._tokenize_rank_text("") == []


def test_expand_search_query_passes_through_unknown_terms():
    assert search_mod._expand_search_query("qe", "ecutwfc") == "ecutwfc"


def test_expand_search_query_adds_openfoam_aliases():
    expanded = search_mod._expand_search_query("openfoam", "drag coefficient")
    assert "forces" in expanded
    assert "forcecoeffs" in expanded


def test_expand_search_query_adds_more_openfoam_aliases():
    expanded = search_mod._expand_search_query("openfoam", "y plus")
    assert "yplus" in expanded
    expanded = search_mod._expand_search_query("openfoam", "wall shear stress")
    assert "wallshearstress" in expanded
    expanded = search_mod._expand_search_query("openfoam", "solver residuals")
    assert "residuals" in expanded
    expanded = search_mod._expand_search_query("openfoam", "k omega sst turbulence")
    assert "komegasst" in expanded
    expanded = search_mod._expand_search_query("openfoam", "numerical schemes")
    assert "fvschemes" in expanded
    expanded = search_mod._expand_search_query("openfoam", "linear solver settings")
    assert "fvsolution" in expanded


def test_expand_search_query_adds_bioinformatics_aliases():
    expanded = search_mod._expand_search_query("bioinformatics", "phylogenetic tree")
    assert "iqtree" in expanded
    expanded = search_mod._expand_search_query("bioinformatics", "read mapping nanopore")
    assert "minimap2" in expanded
    expanded = search_mod._expand_search_query("bioinformatics", "protein structure folding")
    assert "esmfold" in expanded
    expanded = search_mod._expand_search_query("bioinformatics", "multiple sequence alignment fasta")
    assert "mafft" in expanded
    expanded = search_mod._expand_search_query("bioinformatics", "bam indexing")
    assert "samtools index" in expanded


def test_expand_search_query_adds_qe_aliases():
    expanded = search_mod._expand_search_query("qe", "ecut rho")
    assert "ecutrho" in expanded


def test_expand_search_query_adds_lammps_and_bio_aliases():
    lammps_expanded = search_mod._expand_search_query("lammps", "phase transition pressure")
    assert "fix_nphug" in lammps_expanded
    bio_expanded = search_mod._expand_search_query("bioinformatics", "spike mutation")
    assert "bcftools" in bio_expanded


def test_expand_search_query_adds_gromacs_aliases():
    expanded = search_mod._expand_search_query("gromacs", "Parrinello Rahman")
    assert "pcoupl" in expanded
    expanded = search_mod._expand_search_query("gromacs", "v-rescale thermostat")
    assert "tcoupl" in expanded
    expanded = search_mod._expand_search_query("gromacs", "constraints h-bonds")
    assert "constraints" in expanded
    expanded = search_mod._expand_search_query("gromacs", "temperature coupling")
    assert "tcoupl" in expanded
    expanded = search_mod._expand_search_query("gromacs", "pressure coupling")
    assert "pcoupl" in expanded


# ---------------------------------------------------------------------------
# search scoring contract
# ---------------------------------------------------------------------------


def test_score_search_result_lammps_alias_row_contract():
    # Alias hit in synopsis (+90) and content (+70) plus token hits; rank passes through.
    row = {
        "title": "fix nvt command",
        "page_name": "lammps/fix_nh",
        "synopsis": "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
        "content": "Alias keys: |fix nvt| |fix npt| |fix nph|",
        "section": "fix",
        "program": "lammps",
        "rank": -4.8,
    }

    assert search_mod._score_search_result("lammps", "fix npt", "fix npt", row) == (214, -4.8)


def test_score_search_result_openfoam_expanded_alias_contract():
    # Exact title/page match on the expanded "yplus" term outranks raw phrase hits.
    row = {
        "title": "yplus",
        "page_name": "openfoam/yPlus",
        "synopsis": "post processing field function object",
        "content": "y plus wall function boundary layer",
        "section": "post-processing",
        "program": "yPlus",
        "rank": -7.1,
    }
    expanded = search_mod._expand_search_query("openfoam", "y plus")

    assert search_mod._score_search_result("openfoam", "y plus", expanded.lower(), row) == (343, -7.1)


# ---------------------------------------------------------------------------
# toolref_show integration
# ---------------------------------------------------------------------------


def test_toolref_show_falls_back_to_program_manual_page(toolref_home):
    _seed_tool_db(
        toolref_home,
        "bioinformatics",
        "2026-03-curated",
        [
            (
                "2026-03-curated",
                "minimap2",
                "alignment",
                "minimap2/manual",
                "minimap2 manual",
                "manual page",
                "manual content",
            ),
            (
                "2026-03-curated",
                "minimap2",
                "alignment",
                "minimap2/options",
                "minimap2 options",
                "options page",
                "options content",
            ),
        ],
    )

    rows = toolref_show("bioinformatics", "minimap2", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "minimap2/manual"


def test_toolref_show_qe_prefers_exact_program_title_match(toolref_home):
    _seed_tool_db(
        toolref_home,
        "qe",
        "7.5",
        [
            ("7.5", "pw.x", "ELECTRONS", "pw.x/ELECTRONS/conv_thr", "conv_thr", "", "exact"),
            ("7.5", "pw.x", "CONTROL", "pw.x/CONTROL/forc_conv_thr", "forc_conv_thr", "", "other"),
        ],
    )

    rows = toolref_show("qe", "pw", "conv_thr", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "pw.x/ELECTRONS/conv_thr"


def test_toolref_show_lammps_resolves_alias_from_query(toolref_home):
    _seed_tool_db(
        toolref_home,
        "lammps",
        "stable",
        [
            (
                "stable",
                "lammps",
                "fix",
                "lammps/fix_nh",
                "fix nvt command",
                "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
                "Alias keys: |fix nvt| |fix npt| |fix nph|\nAliases: fix nvt, fix npt, fix nph",
            ),
            (
                "stable",
                "lammps",
                "fix",
                "lammps/fix_npt_asphere",
                "fix npt/asphere command",
                "fix ID group-ID npt/asphere keyword value ... | Aliases: fix npt/asphere",
                "Alias keys: |fix npt/asphere|",
            ),
        ],
    )

    rows = toolref_show("lammps", "fix_npt", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "lammps/fix_nh"


# ---------------------------------------------------------------------------
# toolref_search integration
# ---------------------------------------------------------------------------


def test_search_and_show_reject_unknown_tool():
    with pytest.raises(ValueError, match="未知工具"):
        toolref_search("vasp", "anything", cfg=None)
    with pytest.raises(ValueError, match="未知工具"):
        toolref_show("vasp", "anything", cfg=None)


def test_search_and_show_require_indexed_db(toolref_home):
    with pytest.raises(FileNotFoundError):
        toolref_search("qe", "ecutwfc", cfg=None)
    with pytest.raises(FileNotFoundError):
        toolref_show("qe", "pw", "ecutwfc", cfg=None)


def test_toolref_search_lammps_boosts_exact_alias_match(toolref_home):
    _seed_tool_db(
        toolref_home,
        "lammps",
        "stable",
        [
            (
                "stable",
                "lammps",
                "howto",
                "lammps/Howto_barostat",
                "Howto barostat",
                "barostat notes",
                "NPT barostat overview",
            ),
            (
                "stable",
                "lammps",
                "fix",
                "lammps/fix_nh",
                "fix nvt command",
                "fix ID group-ID style_name keyword value ... | Aliases: fix nvt, fix npt, fix nph",
                "Aliases: fix nvt, fix npt, fix nph",
            ),
        ],
    )

    rows = toolref_search("lammps", "fix npt", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "lammps/fix_nh"


def test_toolref_search_fallback_keeps_version_program_and_section_filters(toolref_home):
    _seed_tool_db(
        toolref_home,
        "qe",
        "7.5",
        [
            (
                "7.5",
                "pw.x",
                "SYSTEM",
                "pw.x/SYSTEM/ecutwfc",
                "pw.x ecutwfc",
                "pw.x system cutoff",
                "pw.x cutoff variable",
            ),
            ("7.4", "pw.x", "SYSTEM", "pw.x/SYSTEM/legacy", "pw.x legacy", "pw.x old version", "pw.x legacy variable"),
            (
                "7.5",
                "cp.x",
                "SYSTEM",
                "cp.x/SYSTEM/other",
                "cp.x mentions pw.x",
                "cp.x unrelated page",
                "pw.x appears here but should be filtered out",
            ),
            (
                "7.5",
                "pw.x",
                "ELECTRONS",
                "pw.x/ELECTRONS/conv_thr",
                "pw.x conv_thr",
                "pw.x wrong section",
                "pw.x wrong section result",
            ),
        ],
    )

    rows = toolref_search("qe", "pw.x", program="pw.x", section="SYSTEM", cfg=None)

    assert rows
    assert [row["page_name"] for row in rows] == ["pw.x/SYSTEM/ecutwfc"]
    assert {row["version"] for row in rows} == {"7.5"}
    assert {row["program"] for row in rows} == {"pw.x"}
    assert {row["section"] for row in rows} == {"SYSTEM"}


def test_toolref_search_scores_each_row_once(toolref_home, monkeypatch):
    _seed_tool_db(
        toolref_home,
        "lammps",
        "stable",
        [
            ("stable", "lammps", "fix", "lammps/fix_nh", "fix nvt command", "alias", "fix npt"),
            ("stable", "lammps", "howto", "lammps/Howto_barostat", "Howto barostat", "notes", "npt"),
        ],
    )

    seen: list[str] = []

    def fake_score(tool: str, normalized_query: str, expanded_query: str, row: sqlite3.Row) -> tuple[int, float]:
        seen.append(row["page_name"])
        return (10 if row["page_name"].endswith("fix_nh") else 5, float(row["rank"] or 0.0))

    monkeypatch.setattr(search_mod, "_score_search_result", fake_score)

    rows = search_mod.toolref_search("lammps", "fix npt", cfg=None)

    assert rows
    assert seen == ["lammps/fix_nh", "lammps/Howto_barostat"]


def test_toolref_search_breaks_score_ties_by_fts_rank(tmp_path, monkeypatch):
    db_path = tmp_path / "toolref.db"
    db_path.write_text("", encoding="utf-8")

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return list(self._rows)

    class FakeConn:
        def __init__(self, rows):
            self.rows = rows
            self.row_factory = None

        def execute(self, _sql, _params):
            return FakeCursor(self.rows)

        def close(self):
            return None

    rows = [
        {
            "id": 1,
            "tool": "gromacs",
            "version": "2024",
            "program": "gromacs",
            "section": "mdp",
            "page_name": "gromacs/mdp/tau-p",
            "title": "tau-p",
            "category": "mdp",
            "var_type": "",
            "default_val": "",
            "synopsis": "MDP parameter",
            "content": "The time constant for pressure coupling.",
            "rank": -18.0,
        },
        {
            "id": 2,
            "tool": "gromacs",
            "version": "2024",
            "program": "gromacs",
            "section": "mdp",
            "page_name": "gromacs/mdp/ref-p",
            "title": "ref-p",
            "category": "mdp",
            "var_type": "",
            "default_val": "",
            "synopsis": "MDP parameter",
            "content": "The reference setting for pressure coupling.",
            "rank": -21.0,
        },
    ]

    monkeypatch.setattr(search_mod, "_db_path", lambda tool, cfg=None: db_path)
    monkeypatch.setattr(search_mod, "_current_link", lambda tool, cfg=None: tmp_path / "current")
    monkeypatch.setattr(search_mod.sqlite3, "connect", lambda _path: FakeConn(rows))

    results = search_mod.toolref_search("gromacs", "pressure coupling", cfg=None)

    assert [row["page_name"] for row in results[:2]] == ["gromacs/mdp/ref-p", "gromacs/mdp/tau-p"]


def test_toolref_search_gromacs_boosts_parameter_hits(toolref_home):
    _seed_tool_db(
        toolref_home,
        "gromacs",
        "2024",
        [
            (
                "2024",
                "gromacs",
                "mdp",
                "gromacs/mdp/pcoupl",
                "pcoupl",
                "MDP parameter | Options: no, Parrinello-Rahman",
                "pcoupl Parrinello-Rahman pressure coupling tau-p ref-p",
            ),
            (
                "2024",
                "gromacs",
                "general",
                "gromacs/general/physical_validation",
                "Physical validation",
                "General notes",
                "Parrinello Rahman mentioned in passing",
            ),
        ],
    )

    rows = toolref_search("gromacs", "Parrinello Rahman", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/pcoupl"


def test_toolref_search_gromacs_v_rescale_maps_to_tcoupl(toolref_home):
    _seed_tool_db(
        toolref_home,
        "gromacs",
        "2024",
        [
            (
                "2024",
                "gromacs",
                "mdp",
                "gromacs/mdp/tcoupl",
                "tcoupl",
                "MDP parameter | Options: no, nose-hoover, v-rescale",
                "tcoupl v rescale thermostat temperature coupling tau t ref t",
            ),
            (
                "2024",
                "gromacs",
                "general",
                "gromacs/general/2020.4",
                "2020.4",
                "release notes",
                "v rescale mentioned in release notes",
            ),
        ],
    )

    rows = toolref_search("gromacs", "v-rescale thermostat", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/tcoupl"


def test_toolref_search_gromacs_pressure_coupling_prefers_pcoupl(toolref_home):
    _seed_tool_db(
        toolref_home,
        "gromacs",
        "2024",
        [
            (
                "2024",
                "gromacs",
                "mdp",
                "gromacs/mdp/pcoupl",
                "pcoupl",
                "pressure coupling",
                "Pressure coupling master switch",
            ),
            (
                "2024",
                "gromacs",
                "mdp",
                "gromacs/mdp/pcoupltype",
                "pcoupltype",
                "pressure coupling type",
                "Select isotropic or anisotropic pressure coupling type",
            ),
        ],
    )

    rows = toolref_search("gromacs", "pressure coupling", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "gromacs/mdp/pcoupl"


def test_toolref_search_bioinformatics_multiple_sequence_alignment_prefers_mafft(toolref_home):
    _seed_tool_db(
        toolref_home,
        "bioinformatics",
        "2026-03-curated",
        [
            (
                "2026-03-curated",
                "samtools",
                "alignment",
                "samtools/manual",
                "samtools manual",
                "manual",
                "General utilities for FASTA and SAM workflows",
            ),
            (
                "2026-03-curated",
                "mafft",
                "phylogenetics",
                "mafft/manual",
                "MAFFT manual",
                "multiple sequence alignment",
                "Multiple sequence alignment for FASTA inputs",
            ),
        ],
    )

    rows = toolref_search("bioinformatics", "multiple sequence alignment fasta", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "mafft/manual"


def test_toolref_search_bioinformatics_bam_indexing_prefers_samtools_index(toolref_home):
    _seed_tool_db(
        toolref_home,
        "bioinformatics",
        "2026-03-curated",
        [
            (
                "2026-03-curated",
                "samtools",
                "alignment",
                "samtools/sort",
                "samtools sort",
                "sort bam",
                "Sort BAM files before indexing",
            ),
            (
                "2026-03-curated",
                "samtools",
                "alignment",
                "samtools/index",
                "samtools index",
                "index bam",
                "Create BAM indexes for region access",
            ),
        ],
    )

    rows = toolref_search("bioinformatics", "bam indexing", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "samtools/index"


def test_toolref_search_openfoam_boosts_yplus_page(toolref_home):
    _seed_tool_db(
        toolref_home,
        "openfoam",
        "2312",
        [
            (
                "2312",
                "yPlus",
                "post-processing",
                "openfoam/yPlus",
                "yPlus",
                "wall distance non-dimensionalisation",
                "yPlus function object wall y plus boundary layer",
            ),
            (
                "2312",
                "functionObjects",
                "post-processing",
                "openfoam/functionObjects",
                "function objects",
                "overview",
                "post processing overview mentioning yPlus",
            ),
        ],
    )

    rows = toolref_search("openfoam", "y plus", cfg=None)
    assert rows
    assert rows[0]["page_name"] == "openfoam/yPlus"
