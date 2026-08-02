from __future__ import annotations

_MANIFEST_REQUEST_TIMEOUT = (10, 20)
_OPENFOAM_DISCOVERY_TIMEOUT = (5, 10)
_OPENFOAM_MAX_DISCOVERY_PAGES = 800
_OPENFOAM_DISCOVERY_SEEDS = ("fundamentals/", "tools/")
_BIO_DISCOVERY_TIMEOUT = (5, 15)
_BIO_DISCOVERED_PAGE_ALIASES = {
    "iqtree/ultrafast-bootstrap": {
        "source_page": "iqtree/ultrafast-bootstrap-parameters",
        "anchor": "ultrafast-bootstrap-parameters",
    },
}

TOOL_REGISTRY: dict[str, dict] = {
    "qe": {
        "display_name": "Quantum ESPRESSO",
        "source_type": "git",
        "repo": "https://github.com/QEF/q-e.git",
        "tag_prefix": "qe-",
        "doc_path": None,
        "doc_glob": "**/INPUT_*.def",
        "format": "def",
    },
    "lammps": {
        "display_name": "LAMMPS",
        "source_type": "git",
        "repo": "https://github.com/lammps/lammps.git",
        "tag_prefix": "stable_",
        "doc_path": "doc/src",
        "doc_glob": "*.rst",
        "format": "rst",
    },
    "gromacs": {
        "display_name": "GROMACS",
        "source_type": "git",
        "repo": "https://github.com/gromacs/gromacs.git",
        "tag_prefix": "release-",
        "doc_path": "docs",
        "doc_glob": "**/*.rst",
        "format": "rst",
    },
    "openfoam": {
        "display_name": "OpenFOAM",
        "source_type": "manifest",
        "manifest_name": "openfoam",
        "format": "html",
        "default_version": "2312",
    },
    "bioinformatics": {
        "display_name": "Bioinformatics Toolchain",
        "source_type": "manifest",
        "manifest_name": "bioinformatics",
        "format": "html",
        "default_version": "2026-03-curated",
    },
}
