<div align="center">

<img src="docs/assets/logo.png" width="180" alt="Scrinium Logo">

# Scrinium

**A research infrastructure for AI agents.**

[English](README.md) | [中文](README_CN.md)

[![GitHub stars](https://img.shields.io/github/stars/wszqkzqk/scrinium?style=social)](https://github.com/wszqkzqk/scrinium/stargazers)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
["![Python 3.10+"](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-35-purple.svg)](.agents/skills/)

</div>

> **Fork**: Scrinium is a hard fork of [ScholarAIO](https://github.com/ZimoLiao/scholaraio) (MIT). Original work © Zi-Mo Liao — see [LICENSE](LICENSE).

---

Your coding agent already reads code, writes code, and runs experiments. Scrinium adds a structured research workspace on top, so the same agent can search literature, cross-check results against papers, use scientific software more accurately, and carry the whole research workflow from one terminal.

- Your paper library becomes a reusable knowledge base for the same agent.
- When scientific software questions come up, the agent can consult official documentation at runtime instead of guessing from prompts.
- The system is built to keep expanding as new tools and workflows become worth supporting.

<div align="center">
  <img src="docs/assets/scrinium-demo.gif" width="900" alt="Scrinium natural-language research workflow">
</div>

Scrinium offers more than search. It gives an AI coding agent a research workspace that supports natural-language interaction, papers and notes, more reliable use of scientific software, writing and running code, checking results against the literature, and structured academic writing.

```mermaid
flowchart TB
    U["User / AI agent"] --> S["Skills .agents/skills — 35 workflows"]
    U --> C[scrinium CLI]
    S --> C
    C --> ING[Ingest pipeline]
    C --> RET[Retrieval]
    C --> CUR[Curation]
    ING --> PARSERS["MinerU / Docling / PyMuPDF"]
    ING --> APIS["Crossref / S2 / OpenAlex"]
    RET --> FTS[FTS5 keyword, BM25 field weights]
    RET --> TAGS["Curated tags + citation graph / snowball"]
    RET -.-> VEC(["Optional embeddings"])
    DB(["data/papers — meta.json + paper.md + notes.md"])
    ING --> DB
    RET --> DB
    CUR --> DB
```

## Quick Start

The default and recommended way to use Scrinium is simple: install it, configure it once, and open this repository directly with your coding agent.

```bash
git clone https://github.com/wszqkzqk/scrinium.git
cd scrinium
pip install -e ".[full]"
scrinium setup
```

Then open the repository in Codex, Claude Code, or another supported agent. In this setup, the agent gets the fullest experience: bundled instructions, local skills, the CLI, and the complete codebase context are all available directly. For Claude Code plugins, Codex/OpenClaw skill registration, and other setup paths, see ["`docs/getting-started/agent-setup.md`"](docs/getting-started/agent-setup.md).

## What It Does

|  | Feature | Details |
|--|---------|---------|
| **PDF Parsing** | Deep structure extraction | Convert PDFs into structured Markdown while preserving formulas, figures, and layout as much as possible |
| **Not Just Papers** | More than papers | Journal articles, theses, patents, technical reports, standards, and lecture notes — five inbox categories with tailored metadata handling |
| **Hybrid Search** | Keyword + semantic fusion | Combine full-text and vector retrieval for stronger search results |
| **Curated Tags** | Agent-maintained topics | A controlled tag vocabulary curated by the agent (`data/tags.yaml`), indexed into search and filterable via `--tag` — replaces semantic discovery in embedding-free deployments |
| **Topic Discovery** | See what your library is about | Automatically group papers into research themes and use interactive views to grasp the overall structure quickly |
| **Literature Exploration** | Multi-dimensional discovery | Explore a research direction through journal, topic, author, institution, keyword, year, citation impact, and more |
| **Citation Graph** | References & impact | Forward citations, backward citations, and shared-reference analysis |
| **Layered Reading** | Read on demand | Start with metadata or the abstract, then move into conclusions or full text only when you need to |
| **Multi-Source Import** | Connect your existing library | Import directly from reference managers, PDFs, and Markdown without rebuilding your library from scratch |
| **Workspaces** | Organize by project | Manage paper subsets with scoped search and BibTeX export |
| **Multi-Format Export** | BibTeX, RIS, Markdown, DOCX | Export your full library or a workspace for Zotero, Endnote, submission, or sharing |
| **Persistent Notes** | Cross-session memory | Keep analysis notes for each paper so future sessions can reuse them instead of starting over |
| **Research Insights** | Reading behavior analytics | Search hot keywords, most-read papers, reading trends, and semantic neighbor recommendations for papers you haven't read yet |
| **Federated Discovery** | Cross-library search | Search your main library, exploration libraries, and arXiv from one entry point instead of hopping across tools |
| **AI-for-Science Runtime** | Use scientific software more accurately | Use scientific software against official documentation at runtime instead of guessing commands and parameters |
| **Extensible Tool Onboarding** | Keep adding the tools that matter | As new scientific tools and workflows become important, the system can keep expanding |
| **Academic Writing** | AI-assisted writing | Literature review, paper sections, citation check, rebuttal, and gap analysis — with every citation traceable to your own library |

## Works With Your Agent

Scrinium follows the [AGENTS.md](https://agents.md) open standard — open this repository in any compatible agent and it just works: [Codex](https://openai.com/codex), OpenClaw, [Cursor](https://cursor.sh), [Windsurf](https://codeium.com/windsurf), [GitHub Copilot](https://github.com/features/copilot), [Cline](https://github.com/cline/cline), opencode, Kimi Code, and others. Two agents use their own entry filename: [Claude Code](https://docs.anthropic.com/en/docs/claude-code) reads `CLAUDE.md` (a stub importing `AGENTS.md`), and [Qwen Code](https://github.com/QwenLM/qwen-code) reads `QWEN.md` (a pointer to `AGENTS.md`).

Skills follow the open [AgentSkills.io](https://agentskills.io) standard and live in `.agents/skills/` (with `.claude/skills/` and `skills/` as discovery symlinks). To reuse the skills from another project, symlink the skills directory into `~/.agents/skills/`, or install the Claude Code plugin from the marketplace.

**Migrating from existing tools?** Import directly from Endnote (XML/RIS) and Zotero (Web API or local SQLite), with PDFs, metadata, and references brought over together. More import sources are on the roadmap.

## Configuration

> Start by opening `scrinium` with your agent and let it walk you through the setup. The notes below are only a basic overview.

Scrinium works with a minimal setup and can be expanded as needed.

- `scrinium setup` walks you through the basics.
- An LLM API key is optional but recommended for more robust metadata extraction and content completion.
- A MinerU token is optional but recommended, and free. You can also deploy MinerU or Docling locally for PDF parsing.
- `scrinium setup check` shows what is installed, what is optional, and what is missing.

Full setup and configuration details → ["`docs/getting-started/agent-setup.md`"](docs/getting-started/agent-setup.md), [`config.yaml`](config.yaml)

## Agent First, CLI Available

Scrinium works best through an AI coding agent, but it also provides a CLI for scripting, debugging, and quick queries. For a current command reference aligned with the code, see ["`docs/guide/cli-reference.md`"](docs/guide/cli-reference.md).

## Project Structure

```
scrinium/             # Python package — CLI and all core modules
  ingest/               #   PDF parsing + metadata extraction pipeline
  sources/              #   External source adapters (arXiv / Endnote / Zotero)

.agents/skills/         # Agent skills (AgentSkills.io format)
.agents/skills/         # ↑ symlink for cross-agent discovery
data/papers/            # Your paper library (gitignored)
data/proceedings/       # Proceedings library (gitignored)
data/inbox/             # Drop PDFs here for ingestion
data/inbox-thesis/      # Drop theses here (auto-tagged, skips DOI dedup)
data/inbox-patent/      # Drop patents here (deduplicated by publication number)
data/inbox-doc/         # Drop non-paper documents here (reports, standards, lecture notes)
data/inbox-proceedings/ # Drop proceedings volumes here for dedicated ingest
```

Full module reference → ["`docs/contributing.md`"](docs/contributing.md)

## Citation

If you use Scrinium in your research, please cite:

```bibtex
@software{scrinium,
  author = {Zhou, Qiankang and Liao, Zi-Mo},
  title = {Scrinium: A Research Infrastructure for AI Agents},
  year = {2026},
  url = {https://github.com/wszqkzqk/scrinium},
  license = {GPL-3.0-or-later}
}
```

## License

[GPL-3.0-or-later](LICENSE) © 2026 Zhou Qiankang. Scrinium is a hard fork of [ScholarAIO](https://github.com/ZimoLiao/scholaraio); the original work © 2026 Zi-Mo Liao remains under the [MIT License](NOTICE).
