"""Alignment checks for the multi-agent instruction files.

AGENTS.md and CLAUDE.md differ only in their header lines (title and
audience-specific role description); the body from the first ``## `` section
onward must stay byte-identical. AGENTS_CN.md is a real translation and
cannot be byte-compared, so only its top-level section structure is checked.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def _body(text: str) -> str:
    """Content from the first ``## `` section onward (headers may differ)."""
    idx = text.index("\n## ")
    return text[idx:]


class TestAgentsClaudeAlignment:
    def test_body_byte_identical(self):
        agents = _read("AGENTS.md")
        claude = _read("CLAUDE.md")
        assert _body(agents) == _body(claude), (
            "AGENTS.md and CLAUDE.md bodies diverged; "
            "mirror the change in both files (only the title/role header lines may differ)"
        )

    def test_only_header_lines_differ(self):
        agents_head = _read("AGENTS.md").split("\n## ")[0]
        claude_head = _read("CLAUDE.md").split("\n## ")[0]
        # Headers should stay short; a long divergence means content leaked into the header
        assert len(agents_head.splitlines()) <= 5
        assert len(claude_head.splitlines()) <= 5


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
