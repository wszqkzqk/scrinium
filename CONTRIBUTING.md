# Contributing to Scrinium

Thanks for your interest in contributing! This document explains how to get involved.

## Development Setup

```bash
# Clone and install
git clone https://github.com/wszqkzqk/scrinium.git
cd scrinium
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest
```

## Two Ways to Contribute

### 1. Orchestration Skills (no Python needed)

Skills in `.claude/skills/` are pure-prompt definitions that combine existing CLI commands. To add one:

1. Create `.claude/skills/<name>/SKILL.md` with YAML frontmatter + instructions
2. Follow the [AgentSkills.io](https://agentskills.io) format
3. Test with Claude Code: `/<name>`

See existing skills (e.g., `literature-review`, `writing-polish`) for examples.

### 2. Core Features (Python + CLI)

For new functionality that requires code:

1. Implement in `scrinium/` (library module)
2. Expose it as a subcommand in the matching domain module under `scrinium/cli/`
3. Add contract-level tests in `tests/`
4. Optionally create a skill in `.claude/skills/`

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Ensure all checks pass:
   ```bash
   ruff check scrinium/       # lint
   ruff format --check scrinium/  # format
   mypy scrinium/              # type check
   pytest                        # tests
   ```
4. Submit a PR with a clear description

### Commit Messages

Short English imperative subject lines (e.g. `Add snowball command for citation-graph discovery`, `Fix network-dependent test`, `Drop legacy harness wrappers`), optionally followed by a wrapped body explaining the why. Conventional Commit prefixes are not used. Large refactors land on a feature branch and merge into `main` with a descriptive merge commit.

### Test Guidelines

- Test **behavior contracts**, not implementation details
- A refactor should not break tests — if it does, the test was too coupled
- Use `tmp_path` / `tmp_papers` fixtures for isolation
- Mark slow tests (network, GPU) with `@pytest.mark.slow`

## Code Style

- **Linter/formatter**: ruff (configured in `pyproject.toml`)
- **Type hints**: encouraged, checked by mypy with `ignore_missing_imports`
- **Docstrings**: Google-style for public API functions in library modules
- **CLI handlers** (`cmd_*` in `scrinium/cli/`): no docstrings needed
- **UI text** (CLI output, help, errors): Chinese
- **Code comments**: English, only when logic isn't self-evident

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `scrinium/` | Python package (library + CLI) |
| `.claude/skills/` | Agent skill definitions (SKILL.md) |
| `tests/` | Contract-level test suite |
| `data/` | User paper library (not tracked) |
| `workspace/` | User workspace outputs (not tracked) |
| `docs/` | Documentation |

## Reporting Issues

- **Bugs**: use the [bug report template](https://github.com/wszqkzqk/scrinium/issues/new?template=bug_report.yml)
- **Features**: use the [feature request template](https://github.com/wszqkzqk/scrinium/issues/new?template=feature_request.yml)
- **Security**: see [SECURITY.md](SECURITY.md) — do **not** open a public issue

## Questions?

Open a [discussion](https://github.com/wszqkzqk/scrinium/discussions) or file an issue.
