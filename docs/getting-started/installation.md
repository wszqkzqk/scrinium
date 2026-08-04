# Installation

## Requirements

- Python 3.10+
- Git

## Install from PyPI

```bash
# Core installation
pip install scrinium

# Full installation (import + pdf + office + draw)
pip install "scrinium[full]"
```

Then run:

```bash
scrinium setup
```

## Install from Source

```bash
git clone https://github.com/wszqkzqk/scrinium.git
cd scrinium

# Core only (search, export, audit)
pip install -e .

# Full installation (import + pdf + office + draw)
pip install -e ".[full]"
```

Use the source install path when you want to inspect the codebase, edit the package locally, or contribute changes upstream.

## Upgrading from ScholarAIO (pre-fork)

Scrinium is a hard fork of ScholarAIO; the git history is continuous, so an existing checkout upgrades in place. Data (`data/`, `workspace/`, `config.local.yaml`) is untouched.

```bash
cd /path/to/scholaraio                       # your existing checkout
git remote set-url origin git@github.com:wszqkzqk/scrinium.git
git fetch origin && git switch main && git pull --ff-only

pip uninstall -y scholaraio                  # drop the old editable install
rm -rf scholaraio.egg-info
pip install -e ".[full]"                     # install scrinium (new CLI name)

scrinium --version                           # 3.0.0
scrinium index                               # one-time index migration (schema v2: drops legacy vector tables)
```

Compatibility fallbacks (with a deprecation warning):

- `SCHOLARAIO_CONFIG` is honored when `SCRINIUM_CONFIG` is unset
- `~/.scholaraio/config.yaml` is used when `~/.scrinium/config.yaml` does not exist

See [Migrating from ScholarAIO](migrating-from-scholaraio.md) for the 3.0 breaking changes and cleanup steps (removed LLM/embedding features, manual deletion of old model artifacts).

Optional tidy-up: rename the checkout directory to `scrinium` (recreate the venv afterwards, or keep a `scholaraio -> scrinium` symlink so old venv shebangs keep resolving); update any `~/.agents/skills` symlinks that point at the old path; mirror the new code to other remotes you pull from (e.g. `git push <mirror> main`).

## Optional Dependencies

| Extra | What it adds |
|-------|-------------|
| `pdf` | PyMuPDF-based PDF fallback and long-PDF utilities |
| `import` | Endnote / Zotero import |
| `office` | DOCX / PPTX / XLSX ingest and inspection |
| `draw` | Mermaid and Inkscape-powered diagram generation |
| `full` | Core research workflow extras: import + pdf + office + draw |
| `dev` | Development tools (pytest, ruff, mypy) |

The `embed` and `topics` extras were removed in 3.0 together with all in-framework embedding/LLM features; no model download is ever required.

## Setup Wizard

Run the interactive setup wizard to configure API keys and directories:

```bash
scrinium setup
```

Or check what's already configured:

```bash
scrinium setup check
```

`setup check` is the most complete initial diagnostic surface. It covers:

- core setup items: dependency groups, `config.yaml`, MinerU / Docling availability, parser recommendation, `contact_email`, and directory state
- optional advanced items: Semantic Scholar API key and Zotero API key

Current setup guidance prefers **MinerU first** whenever a MinerU path is available (local service or `mineru-open-api` + token). `Docling` and then PyMuPDF remain the fallback chain when MinerU is not usable or when the user explicitly prefers a lighter parser path.

Cost transparency:

- `MINERU_TOKEN`: free to apply
- `contact_email`: free
- `Semantic Scholar API key`: optional; most endpoints work anonymously, but some require a key
- `Zotero API key`: optional; Scrinium's current Web API import path expects it, while local `zotero.sqlite` import does not

## Agent Setup

If you want to know which path to use for Claude Code, Codex, OpenClaw, Cursor, or other agents, see:

- [Agent Setup](agent-setup.md)

That guide separates:

- opening this repository directly
- registering Scrinium for use from another project
- choosing between native skills and plugins
