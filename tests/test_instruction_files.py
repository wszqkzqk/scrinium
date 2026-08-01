"""Alignment checks for the multi-agent instruction files.

`AGENTS.md` is the single source of truth. Claude Code reads `CLAUDE.md`,
not `AGENTS.md`, so `CLAUDE.md` must stay a minimal stub that imports
`AGENTS.md` via Claude Code's ``@``-import mechanism. `AGENTS_CN.md` is a
real translation and cannot be byte-compared, so only its top-level section
structure is checked.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class TestClaudeStub:
    def test_imports_agents_md(self):
        claude = _read("CLAUDE.md")
        # The import must not be wrapped in backticks, or Claude Code keeps it literal
        assert "\n@AGENTS.md\n" in f"\n{claude}", (
            "CLAUDE.md lost its @AGENTS.md import; Claude Code reads CLAUDE.md, "
            "not AGENTS.md, so the stub must keep importing it"
        )

    def test_stays_a_thin_stub(self):
        lines = [ln for ln in _read("CLAUDE.md").splitlines() if ln.strip()]
        assert len(lines) <= 6, (
            f"CLAUDE.md has {len(lines)} non-empty lines; shared content belongs in AGENTS.md "
            "(the single source of truth), not in the Claude Code stub"
        )

    def test_agents_md_holds_shared_content(self):
        agents = _read("AGENTS.md")
        for anchor in ("## Agent Skills", "## Deep Reference", "T1", "T2"):
            assert anchor in agents


class TestAgentsCnStructure:
    def test_same_section_count(self):
        en_sections = [ln for ln in _read("AGENTS.md").splitlines() if ln.startswith("## ")]
        cn_sections = [ln for ln in _read("AGENTS_CN.md").splitlines() if ln.startswith("## ")]
        assert len(en_sections) == len(cn_sections), (
            f"AGENTS_CN.md has {len(cn_sections)} top-level sections, "
            f"AGENTS.md has {len(en_sections)}; keep the translation structurally aligned"
        )

    def test_deep_reference_pointers_present(self):
        cn = _read("AGENTS_CN.md")
        for target in (
            "docs/guide/architecture.md",
            "docs/contributing.md",
            "docs/getting-started/configuration.md",
            "docs/getting-started/agent-setup.md",
        ):
            assert target in cn
