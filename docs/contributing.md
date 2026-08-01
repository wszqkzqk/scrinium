# Contributing

See [CONTRIBUTING.md](https://github.com/zimoliao/scholaraio/blob/main/CONTRIBUTING.md) for the full guide.

## Module Overview

| Module | Function |
|------|------|
| `config.py` | Configuration loading (multi-layer YAML override + path resolution + API key lookup) |
| `papers.py` | Paper path helpers (iterate/build paper directories + `meta.json` read/write + paper UUID generation) |
| `log.py` | Runtime logging + user-facing terminal output (`ui()`) + session tracking |
| `ingest/mineru.py` | PDF -> MinerU Markdown (local API / `mineru-open-api` cloud CLI) |
| `ingest/pdf_fallback.py` | PDF fallback parsing (Docling / PyMuPDF) |
| `ingest/extractor.py` | Metadata extraction (four modes: regex / auto / robust / llm) |
| `ingest/metadata/` | API completion (Crossref / S2 / OpenAlex) + abstract backfill + document metadata generation + JSON output + file renaming |
| `ingest/pipeline.py` | Composable multi-inbox ingest pipeline (dedup + pending + papers/global postprocess + external-import batch conversion) |
| `index.py` | Keyword full-text search + papers_registry + citation graph |
| `search_common.py` | Shared FTS5 query sanitization + RRF fusion + FTS table DDL (used by both `index.py` and `explore.py`) |
| `prompts.py` | Central LLM prompt registry + unified `parse_llm_json()` response parser |
| `vectors.py` | Semantic vectors + incremental indexing + GPU-adaptive batching |
| `topics.py` | BERTopic topic modeling + 6 HTML visualizations |
| `loader.py` | L1-L4 layered loading + enrich_toc + enrich_l3 |
| `proceedings.py` | Proceedings storage helpers + child-paper iteration + proceedings DB path helpers |
| `ingest/proceedings.py` | Proceedings volume preparation + split-plan application + clean-plan application |
| `explore.py` | Multi-dimensional literature exploration (OpenAlex multi-filter + keyword + semantic + hybrid search + topics, isolated under `data/explore/`) |
| `workspace.py` | Workspace paper subset management (reuses search/export) |
| `document.py` | Office document inspection (DOCX / PPTX / XLSX structure, layout, overflow checks) |
| `export.py` | BibTeX / RIS / Markdown bibliography / DOCX export |
| `citation_styles.py` | Citation style management (built-in APA/Vancouver/Chicago/MLA + dynamically loaded custom styles stored in `data/citation_styles/`) |
| `citation_check.py` | Citation verification (extract author-year citations from text + cross-check against the local library) |
| `audit.py` | Data-quality auditing + repair |
| `sources/` | External source adapters (endnote / zotero / arxiv) |
| `cli/` | Main CLI entry point (package split by domain: `common` / `search` / `ingest` / `explore` / `ws` / `transfer` / `misc`) |
| `setup.py` | Environment detection + setup wizard |
| `metrics.py` | LLM token usage + API timing |
| `insights.py` | Research behavior analytics (hot keywords, read trends, semantic neighbor recommendations, workspace activity) |
| `translate.py` | Paper translation (language detection + concurrent chunked LLM translation + batch translation + optional portable bundle export) |

CLI command reference: `scholaraio --help`

Besides skills, the current CLI also provides several important capabilities worth using directly:

- Retrieval-related: `search-author`, `embed`, `vsearch`, `usearch`, `fsearch`, `top-cited`
- Graph-related: `refs`, `citing`, `shared-refs`
- Enrichment and repair: `enrich-toc`, `enrich-l3`, `backfill-abstract`, `refetch`, `repair`
- Data maintenance: `attach-pdf`
- Workspace: `ws` (subcommands such as `init`, `add`, `remove`, `show`, `search`, `export`, and more)
- Proceedings: `proceedings` (`apply-split`, `build-clean-candidates`, `apply-clean`) and `fsearch --scope proceedings`
- External and scientific runtime: `arxiv`, `toolref`, `insights`, `style`, `document`

## Adding a New Skill

The workflow for adding a new skill (tool-oriented skills wrapping CLI commands vs prompt-only orchestration skills) is documented in the "Agent Skills" section of [`AGENTS.md`](https://github.com/zimoliao/scholaraio/blob/main/AGENTS.md).
