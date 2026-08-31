# Scrinium

**Scrinium** — a research infrastructure for AI agents (hard fork of [ScholarAIO](https://github.com/ZimoLiao/scholaraio)).

> This site is published at <https://wszqkzqk.github.io/scrinium/> via GitHub Pages.

Scrinium is a research infrastructure for AI agents. You interact with your literature knowledge base through natural language — searching, reading, analyzing, and writing — all from the command line.

## Features

- **PDF Ingestion**: Convert PDFs to structured Markdown via MinerU (cloud or local)
- **Keyword Search**: FTS5 full-text search with field-weighted ranking; the agent extends recall through query expansion, curated tags, and citation-graph snowballing
- **Tag-Based Topics**: A controlled tag vocabulary curated by the agent doubles as the topic system — distribution overview and drill-down via `scrinium topics`
- **Citation Graph**: View references, citing papers, and shared references
- **BibTeX Export**: Filtered export with standard citation formats
- **Paper Translation**: Agent-driven chunked translation stored as `paper_{lang}.md`, readable via `show --lang`
- **Literature Exploration**: Multi-dimensional OpenAlex queries with isolated data
- **Workspace Management**: Organize papers into subsets for focused work
- **Federated Discovery**: Search your library, explore silos, and arXiv in one flow
- **Research Insights**: Inspect search/read behavior trends
- **Scientific Tool Docs**: Query indexed official docs for scientific computing tools with `toolref`
- **Extensible Tool Onboarding**: Keep adding the next scientific tool users need through a documented onboarding workflow
- **Office Document Inspection**: Verify DOCX / PPTX / XLSX structure with `document inspect`
- **Agent Skills**: Reusable workflows for search, writing, scientific runtime, and more

Scrinium makes no in-framework LLM or embedding calls: anything that requires understanding (summarizing, translating, classifying, recommending) is done by the agent itself, with the framework providing storage, retrieval, and queue primitives.

## Quick Start

```bash
pip install "scrinium[full]"
scrinium setup
```

See [Installation](getting-started/installation.md) for detailed instructions.
If you are working from a local clone or contributing to Scrinium itself, use the editable install path shown there instead.
See [Agent Setup](getting-started/agent-setup.md) for repo-open vs plugin setup paths.
See [Translation Guide](guide/translate.md) for the agent-driven translation workflow and storage conventions.
See [Insights Guide](guide/insights.md) for reading/search behavior analytics.
See [API Reference](api/index.md) for Python module documentation.

## Two Usage Modes

| Mode | Interface | Best for |
|------|-----------|----------|
| **Agent** | Any AGENTS.md-compatible coding agent | Full research workflow via natural language |
| **CLI** | Terminal | Scripting and automation |
