"""Alignment checks for the multi-agent instruction files.

`AGENTS.md` is the single source of truth, natively read by most agents.
Claude Code reads `CLAUDE.md`, not `AGENTS.md`, so `CLAUDE.md` must stay a
minimal stub that imports `AGENTS.md` via Claude Code's ``@``-import
mechanism; Qwen Code reads `QWEN.md`, which must stay a minimal pointer.
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


class TestQwenPointer:
    def test_qwen_md_points_to_agents_md(self):
        qwen = _read("QWEN.md")
        assert "AGENTS.md" in qwen

    def test_stays_a_thin_pointer(self):
        lines = [ln for ln in _read("QWEN.md").splitlines() if ln.strip()]
        assert len(lines) <= 12
