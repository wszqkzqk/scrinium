# Contributing

See [CONTRIBUTING.md](https://github.com/wszqkzqk/scrinium/blob/main/CONTRIBUTING.md) for the full guide.

## Module Overview

| Module | Function |
|------|------|
| `config.py` | Configuration loading (multi-layer YAML override + path resolution + API key lookup + deprecation warnings for removed model-related sections) |
| `papers.py` | Paper path helpers (iterate/build paper directories + `meta.json` read/write + paper UUID generation) |
| `log.py` | Runtime logging + user-facing terminal output (`ui()`) + session tracking |
| `ingest/mineru.py` | PDF -> MinerU Markdown (local API / `mineru-open-api` cloud CLI) |
| `ingest/pdf_fallback.py` | PDF fallback parsing (Docling / PyMuPDF) |
| `ingest/extractor.py` | Metadata extraction (regex only) |
| `ingest/metadata/` | API completion (Crossref / S2 / OpenAlex) + abstract backfill (regex + DOI fetch) + document metadata generation + JSON output + file renaming |
| `ingest/pipeline.py` | Composable multi-inbox ingest pipeline (dedup + pending + papers/global postprocess + external-import batch conversion) |
| `index.py` | Keyword full-text search (FTS5, schema v2) + papers_registry + citation graph |
| `search_common.py` | Shared FTS5 query sanitization + FTS table DDL (used by both `index.py` and `explore.py`) |
| `loader.py` | L1-L4 layered loading + enrich_toc + `validate_lang` |
| `proceedings.py` | Proceedings storage helpers + child-paper iteration + proceedings DB path helpers |
| `ingest/proceedings.py` | Proceedings volume preparation + split-plan application + clean-plan application |
| `explore.py` | Multi-dimensional literature exploration (OpenAlex multi-filter fetch + keyword search, isolated under `data/explore/`) |
| `workspace.py` | Workspace paper subset management (reuses search/export) |
| `document.py` | Office document inspection (DOCX / PPTX / XLSX structure, layout, overflow checks) |
| `export.py` | BibTeX / RIS / Markdown bibliography / DOCX export |
| `citation_styles.py` | Citation style management (built-in APA/Vancouver/Chicago/MLA + dynamically loaded custom styles stored in `data/citation_styles/`) |
| `citation_check.py` | Citation verification (extract author-year citations from text + cross-check against the local library) |
| `audit.py` | Data-quality auditing + repair |
| `tags.py` | Agent-curated tag system (taxonomy in `data/tags.yaml` with aliases + `meta.json["tags"]` read/write + usage counts + topic overview/drill-down backing `scrinium topics`) |
| `sources/` | External source adapters (endnote / zotero / arxiv) |
| `toolref/` | Scientific tool documentation pipeline (fetch + manifest + storage + search + parsers) |
| `cli/` | Main CLI entry point (package split by domain: `common` / `search` / `ingest` / `explore` / `ws` / `transfer` / `misc`) |
| `setup.py` | Environment detection + setup wizard |
| `metrics.py` | Runtime metrics (pipeline step / API timing + search/read events) |
| `insights.py` | Research behavior analytics (hot keywords, read trends, workspace activity) |

CLI command reference: `scrinium --help`

Besides skills, the current CLI also provides several important capabilities worth using directly:

- Retrieval-related: `search` (`--scope`, `--tag`), `search-author`, `top-cited`
- Graph-related: `references`, `cited-by`, `shared-references`, `snowball`
- Topic browsing: `topics` (tag distribution overview + per-tag drill-down)
- Enrichment and repair: `enrich toc`, `enrich abstract`, `refresh`, `repair`
- Data maintenance: `attach-pdf`
- Workspace: `workspace` (subcommands such as `init`, `add`, `remove`, `show`, `search`, `export`, and more)
- Proceedings: `proceedings` (`apply-split`, `build-clean-candidates`, `apply-clean`) and `search --scope proceedings`
- External and scientific runtime: `arxiv`, `toolref`, `insights`, `citation-styles`, `document`

## Adding a New Skill

The workflow for adding a new skill (tool-oriented skills wrapping CLI commands vs prompt-only orchestration skills) is documented in the "Agent Skills" section of [`AGENTS.md`](https://github.com/wszqkzqk/scrinium/blob/main/AGENTS.md).
