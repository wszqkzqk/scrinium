# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Ingest preserves the source PDF**: after a successful conversion the source PDF is kept as `paper.pdf` in the paper directory (previously it was deleted, keeping only `paper.md`). Applies to the batch MinerU/fallback/cloud conversion paths and to `attach-pdf`

### Fixed

- **`explore fetch --keyword` relevance**: OpenAlex requests were hard-coded to `sort=publication_year:asc`, so keyword fetches returned the *oldest* matching records (mostly irrelevant public-domain books) instead of relevant ones. Keyword fetches now default to `relevance_score:desc`; filter-only fetches (ISSN/concept/author/institution surveys) keep chronological ascending order. New `--sort` option (`year_asc` / `year_desc` / `relevance` / `citations`) overrides the default, and the resolved sort is recorded in the explore DB `meta.json`
- **OpenAlex 429 resilience**: retry budget raised from 3 attempts with 1–4 s waits to 5 attempts with 4–60 s waits — OpenAlex rate limiting can persist for minutes under shared-IP load

### Added

- **OpenAlex polite pool**: `explore fetch` sends `mailto` from `ingest.contact_email` (or the `OPENALEX_MAILTO` environment variable) for better rate limits

## [3.0.0] — 2026-08-04

Scrinium 3.0 removes **all in-framework LLM and embedding calls** — no exceptions. The framework keeps only deterministic, model-free primitives (regex metadata extraction, rule-based `enrich toc`/`enrich abstract`, FTS5 indexing, tags, citation graph, pending queue, MinerU parsing). Every capability that requires understanding is taken over by the agent (usually subagents that actually read the papers), so no user-facing function is lost.

### Removed

- **All in-framework LLM calls**: removed `scrinium/prompts.py`, `scrinium/translate.py`, and the LLM backend stack in `metrics.py` (`call_llm()`, `LLMResult`, `MetricsStore.summary()`); removed `LLMExtractor` / `FallbackExtractor` / `RobustExtractor` (metadata extraction is regex-only); removed LLM branches from abstract backfill/verification, inbox-doc metadata generation, TOC extraction, and thesis/book type detection (title-keyword heuristics retained). Removed commands: `scrinium translate` (plus the `translate` pipeline step and `translate.auto_translate`), `scrinium enrich conclusion` (alias `enrich-l3`), and `scrinium metrics --summary` (default category is now `step`)
- **All embedding / vector retrieval**: removed `scrinium/vectors.py` and the semantic/hybrid stack. Removed commands: `scrinium embed`, `scrinium vsearch`, `scrinium usearch`; the `--mode` option on `search` / `workspace search` / `explore search` is gone — search is FTS5 keyword only. `scrinium explore embed|topics|viz` removed; explore keeps OpenAlex fetch + keyword search over an isolated FTS5 index
- **BERTopic topic modeling**: removed `scrinium/topics.py`; `data/topic_model/` is no longer produced
- **Removed config sections**: `llm`, `translate`, `embed`, `topics`, `ingest.extractor` (non-regex values), and `ingest.abstract_llm_mode` — leftover sections log a one-time deprecation warning and are ignored; startup never fails
- **Removed extras**: `scrinium[embed]` and `scrinium[topics]`; `scrinium[full]` is now import + pdf + office + draw (no `modelscope`, no embedding model download)

### Added

- **Agent takeover paths**: semantic recall → agent query expansion (multiple keyword searches) + `--tag` filters + citation-graph `snowball`; translation → agent writes `paper_{lang}.md` + `meta.json["translations"]` (`show --layer 4 --lang` unchanged); L3 conclusions → agent writes `meta.json["l3_conclusion"]`; metadata correction and pending-queue review → agent edits `meta.json` / runs `repair` after actually reading the PDF
- **Handoff hints**: when a deterministic path fails or is low-confidence, CLI output (text and `--json` alike) carries a `hint: ` line naming the recommended agent takeover workflow; `pending.json` gains a `hint` field. Emission points: ingest results, `scrinium pending`, `enrich abstract` / `enrich toc` misses, `scrinium audit`, and `show --layer 3`
- **Tag-based topics ("tags are topics")**: new `scrinium topics [--json]` shows the tag distribution overview (counts, shares, untagged count) and `scrinium topics <tag>` drills into one topic; `workspace add --tag` batch-adds papers by tag (replacing `--topic`). Vocabulary merging stays in `tags.yaml` aliases; distribution charts come from the `draw` skill
- **Agent-written meta.json convention**: `toc` / `l3_conclusion` / `abstract` / `translations` fields may be written by the agent directly and become searchable after `scrinium index`
- **`repair` accepts pending items** (with a dedup guard against papers already in the library)

### Changed

- **Index schema v2**: `data/index.db` migrates automatically on the first index operation — legacy `paper_vectors` / `vector_metadata` tables are dropped and the `faiss.index` / `faiss_ids.json` sidecar files next to `index.db` are deleted
- **Pipeline presets**: `full` = `ingest` = `mineru, extract, dedup, ingest, index`; `enrich` = `abstract, toc`; `reindex` = `index`
- **`enrich toc`** is pure rules; **`enrich abstract`** is regex + optional DOI-page fetch
- **`scrinium insights`** drops the semantic-neighbor section; unread-paper discovery is an agent workflow over reading history + tag overlap + citation snowballing
- **Superseded unreleased changes**: the two intermediate CLI naming rounds after 2.0.0 (`--mode keyword|unified|semantic`, `usearch` / `vsearch` / `enrich-l3` legacy aliases) never shipped in a release and are superseded by this release's removals; surviving aliases (`enrich-toc`, `backfill-abstract`, `fsearch`, `ws`, `refs`, `citing`, `shared-refs`, `import-endnote`, `import-zotero`, `refetch`, `style`) are unchanged

### Migration

- Run `scrinium index` once to apply schema v2 (automatic; safe on libraries of any size)
- Delete manually to reclaim disk space (the framework never removes these on its own): `data/topic_model/`, `data/explore/<name>/topic_model/`, `data/explore/<name>/faiss.index`, `data/explore/<name>/faiss_ids.json`, `~/.cache/scrinium/gpu_profile.json`, and the Qwen3-Embedding model cache (~1.2 GB under `~/.cache/modelscope/` or your HuggingFace cache, depending on the old `embed.source`)
- Old config sections (`llm` / `translate` / `embed` / `topics`) can be deleted at your convenience; the deprecation warnings point them out

## [2.0.0] — 2026-08-02

### Changed

- **Hard fork: ScholarAIO renamed to Scrinium**: This project is a hard fork of [ScholarAIO](https://github.com/ZimoLiao/scholaraio) 1.3.0 (MIT). The Python package, CLI command, and distribution name are now `scrinium`; there is no `scholaraio` import alias. All `SCHOLARAIO_*` environment variables are renamed to `SCRINIUM_*` (`SCRINIUM_CONFIG`, `SCRINIUM_LLM_API_KEY`, `SCRINIUM_EMBED_PROVIDER` / `SCRINIUM_EMBED_SOURCE` / `SCRINIUM_EMBED_MODEL` / `SCRINIUM_EMBED_CACHE_DIR` / `SCRINIUM_EMBED_API_BASE` / `SCRINIUM_EMBED_API_KEY`, `SCRINIUM_HF_ENDPOINT`); each new name falls back to its deprecated old name with a warning. The global config directory is now `~/.scrinium/` (falls back to an existing `~/.scholaraio/config.yaml` with a migration warning), and the GPU profile cache moves to `~/.cache/scrinium/` (reads fall back to `~/.cache/scholaraio/`)

### Added

- **OpenAI-compatible embedding backend support**: Added `embed.provider` config with `local` / `openai-compat` / `none` options; cloud API supports configurable `api_base`, `api_key`, `api_timeout`, `batch_size`, and `max_retries`; `provider=none` disables embeddings gracefully and falls back to keyword-only search
- **Central LLM prompt registry**: All 12 embedded LLM prompts now live in `scrinium/prompts.py` as named, versioned templates with a unified `parse_llm_json()` response parser (fence stripping + bare-JSON extraction + LaTeX backslash repair); DOI hallucination guards now apply to all extractor modes; golden tests lock the parsing contract
- **`scrinium pending` command**: Lists items blocked in `data/pending/` and `data/duplicates/` grouped by issue (`no_doi` / `no_pub_num` / `duplicate`) with titles, `duplicate_of` targets, and actionable resolution hints; ingest summary points to it
- **Structured output and CLI robustness**: `--json` on `search` / `usearch` / `show` / `ws show` / `top-cited`; `--version` flag; one-line errors instead of tracebacks for invalid arguments; clean exit when output is piped to `head`; `show` header prints the canonical directory name; `export` accepts dir name / UUID / DOI like `show` does; pre-notice before the first ~1.2GB embedding model download; `topics` reports model staleness against the current library size
- **Shared search stack**: New `scrinium/search_common.py` holds the single FTS5 query sanitizer, RRF fusion (k=60), and FTS table DDL used by both the main library and explore databases

### Changed

- **Workspace typo safety**: `ws add` / `ws show` on a nonexistent workspace now fail with rc!=0 and list existing workspaces instead of silently auto-creating; `ws add` reports every unresolvable reference
- **Ingest pipeline hardening**: untyped `opts` dict replaced by a frozen `PipelineOptions` dataclass across the pipeline; library-level `sys.exit` in the pipeline now raises `PipelineError` handled at the CLI boundary; dedup meta.json read failures are counted and surfaced instead of silently skipped
- **Insights diagnosis accuracy**: semantic-neighbor recommendations now distinguish "vector index not built" from "embedding model unavailable" instead of misattributing the cause
- **Explore query behavior aligned**: explore keyword search uses the same FTS5 query sanitization as the main library (hand-written FTS5 syntax is no longer interpreted, consistent with the main library)
- **CLI package split**: `scrinium/cli.py` (3900 lines) split into the `scrinium/cli/` package by domain (`common` / `search` / `ingest` / `explore` / `ws` / `transfer` / `misc`); coverage `omit` removed so the CLI layer is measured
- **Skill governance**: unified frontmatter and routing across all 34 skills, intent-to-skill routing table in AGENTS.md/CLAUDE.md, discipline checklists for citation-check and audit, document skill slimmed with API references moved to `reference.md`, skill bodies unified to Chinese
- **Instruction files slimmed**: AGENTS.md / CLAUDE.md / AGENTS_CN.md reduced from ~540 to ~180 lines, keeping only always-needed behavioral instructions and conventions; architecture, data layouts, module overview, configuration details, and plugin packaging moved to `docs/` (progressive disclosure, loaded on demand)
- **CLAUDE.md became an import stub**: Claude Code reads `CLAUDE.md`, not `AGENTS.md`, so `CLAUDE.md` is now a 4-line stub importing `AGENTS.md` via Claude Code's `@`-import mechanism; `AGENTS.md` is the single source of truth and content drift between the two is impossible by construction
- **Agent-curated tag system ("tags as topics")**: new `scrinium/tags.py` with a controlled vocabulary in `data/tags.yaml` (aliases, descriptions) and per-paper tags in `meta.json`; `scrinium tag` / `tags` commands; tags are indexed in FTS (schema v1 migration) and filterable via `--tag` on search/usearch/ws search; `audit` reports untagged papers; new `curate` skill drives batch curation via subagents. Designed for embedding-free deployments (`embed.provider: none`) where curated labels replace semantic discovery

### Removed

- **toolref legacy snapshot**: Deleted `toolref/_legacy_snapshot.py` (2430 lines) and the `_ToolrefModule` attribute-hijack shim; the toolref test suite is now behavior-contract based, and the package exports an explicit 7-name public API

### Fixed

- **Comprehensive agent-facing audit**: ~30 staleness/executability fixes across skills, docs, configs, and wrappers. Notably: explore semantic/unified search no longer crashes when vectors are missing or `embed.provider: none`; `setup.py` config template re-synced with `config.yaml` (with a drift-prevention test); `config.local.example.yaml` no longer silently overrides `config.yaml` embed settings; setup wizard keeps editable installs editable; `clawhub.yaml` lists all 35 skills; `QWEN.md` wrapper completes Qwen Code support; runtime-env instructions are environment-manager agnostic
- **Windows compatibility**: stdout/stderr are reconfigured to UTF-8 at logging setup so redirected/piped output (CJK JSON, unicode symbols) no longer crashes or vanishes under ANSI code pages; `toolref use` now creates its `current` marker with `target_is_directory=True` and falls back to a plain text file (readable by `show`/`search`/`list`) when symlink creation is not permitted; CI test matrix adds `windows-latest`; agent-setup docs cover `core.symlinks` and MAX_PATH caveats
- **License changed to GPL-3.0-or-later**: the fork is now GPL-3.0-or-later (see LICENSE); the upstream ScholarAIO MIT license text is preserved in NOTICE as required
- **CI test fixes**: tests depending on optional extras (pandas/faiss/modelscope) now skip gracefully when the extra is absent, matching the CI install set (`.[dev,office]`)

## [1.3.0] — 2026-04-06

### Added

- **AI-for-Science foundation**: ScholarAIO v1.3.0 pushes the project beyond a paper-centric research terminal toward an AI-for-Science runtime. Added five lightweight scientific-computing domains for agents: Quantum ESPRESSO, LAMMPS, GROMACS, OpenFOAM, and bioinformatics
- **Versioned scientific tool docs via `toolref`**: Added `scholaraio toolref fetch/list/show/search/use` plus the top-level `scholaraio.toolref` facade so agents can query exact official interfaces at runtime instead of guessing parameters from memory. Current indexed coverage includes Quantum ESPRESSO, LAMMPS, GROMACS, OpenFOAM, and curated bioinformatics tools
- **Extensible onboarding for new scientific software**: Added a dedicated scientific-tool onboarding workflow so ScholarAIO can keep incorporating user-requested tools through official-doc ingestion, `toolref` integration, lightweight skill design, and end-to-end CLI verification, rather than being limited to the five tools already onboarded
- **Toolref-first scientific runtime design**: Aligned tool-specific scientific skills around a clear separation of concerns: papers and notes hold scientific context, skills hold workflow and judgment, and `toolref` holds exact interface details. This keeps skills lightweight while letting agents stay grounded in both literature and tool docs
- **Semantic Scholar API key support**: Configure `ingest.s2_api_key` (or env var `S2_API_KEY`) to authenticate Semantic Scholar requests, increasing rate limits from 100 req/5min (public) to 1 req/s (authenticated); polite delay automatically reduced from 3s to 1s when key is present
- **PDF parser benchmark harness**: Added `scholaraio/ingest/parser_matrix_benchmark.py` plus tests for comparing Docling / MinerU / PyMuPDF parser runs and configuration matrices
- **Parser-aware setup guidance**: `scholaraio setup` and the setup skill now explain MinerU vs Docling selection, provide official deployment links, note that MinerU tokens for `mineru-open-api` are free to apply for, and warn agent users about sandbox/network mis-detection
- **Insights analytics module coverage**: `scholaraio.insights` now owns reusable behavior-analysis helpers, with dedicated tests plus CLI smoke coverage for `scholaraio insights`

### Fixed

- **PDF parser fallback flow**: Batch conversion and `attach-pdf` now follow the same MinerU → fallback behavior as the main ingest path; fallback assets are preserved; unsupported parser options from the previous broader design were removed so the active chain matches the current MinerU / Docling / PyMuPDF strategy
- **MinerU cloud backend + chunking limits**: All MinerU cloud ingest entrypoints now use the `mineru-open-api` / ModelScope-backed path instead of the old raw API flow, and cloud chunk planning now respects both the 600-page and 200MB single-file limits with size-aware chunk estimation
- **Proceedings ingest routing**: Regular `data/inbox/` items no longer auto-route into `data/proceedings/`; proceedings now enter that workflow only through the dedicated `data/inbox-proceedings/` inbox, and misclassified real-library proceedings shells were cleaned back into normal paper ingest
- **Setup robustness for agents**: `setup` / `setup check` no longer fail hard when `metrics.db` is locked, parser recommendations honor an already-configured MinerU token before network probing, and interactive prompts treat EOF as empty input so agent-driven stdin does not crash the wizard
- **Docs consistency**: README, README_CN, AGENTS, and CLAUDE now describe the current parser stack and setup behavior consistently
- **arXiv ingest edge cases**: `scholaraio.sources.arxiv` no longer makes `bs4` a transitive hard dependency for normal metadata flows, and old-style arXiv IDs like `hep-th/9901001` now create parent directories correctly during PDF download
- **Scientific runtime docs compatibility**: toolref runtime behavior, scientific skills, and published setup/docs metadata now match the refactored `toolref` facade and current public CLI/package surface
- **Optional dependency guidance**: missing-dependency messages and `setup check` now consistently point users to `scholaraio[import]`, `scholaraio[pdf]`, `scholaraio[office]`, and `scholaraio[draw]` instead of raw leaf packages
- **Translate / enrich CLI feedback and recovery**: `translate` now reports chunk-level progress, persists per-chunk state in `.translate_{lang}/`, resumes unfinished work safely, and avoids writing fake success output when every chunk fails; `enrich-toc` now reports start/success/failure with extracted TOC counts for single-paper runs
- **Workspace removal and refetch status accuracy**: `ws remove` now falls back to exact workspace `dir_name` matching when registry lookup misses, and `refetch` no longer reports spurious updates when API enrichment returns no authoritative data

### Removed

- **MCP server**: Removed `scholaraio/mcp_server.py` (1585 lines, 32 tools) and the `scholaraio-mcp` entry point. All agent interactions now go through CLI + skills, which are agent-agnostic and supported across Claude Code, Codex, Cursor, Windsurf, Cline, and GitHub Copilot. The `[mcp]` optional dependency group has also been removed.

## [1.2.0] — 2026-03-26

### Added

- **Agent analysis notes (T2)**: Per-paper `notes.md` for persistent cross-session analysis notes; `show` now auto-displays existing notes, `show --append-notes` appends new notes, and `loader.load_notes()` / `loader.append_notes()` expose the workflow in Python
- **Context management guidance**: Workspace skill and 4 academic writing skills updated with `notes.md` read/write workflow and large-content delegation guidance for subagent-heavy analysis

### Fixed

- **Zotero LaTeX filename too long** ([#32](https://github.com/ZimoLiao/scholaraio/issues/32)): Titles containing LaTeX math (e.g. `$\mathrm{La}{\mathrm{BH}}_8$`) or HTML/MathML entities now get properly cleaned before directory naming; added 255-byte filename length limit as safety net

## [1.1.0] — 2026-03-24

### Added

- **Patent literature management**: New `data/inbox-patent/` inbox for patent documents; automatic publication number extraction (CN/US/EP/WO/JP/KR/DE/FR/GB/TW/IN/AU + more formats); deduplication by publication number; `paper_type: patent` auto-tagging; `publication_number` field in `PaperMetadata` and `papers_registry`
- **Paper translation** (`translate` CLI + skill): LLM-based markdown translation preserving LaTeX formulas, code blocks, and images; language detection heuristic; configurable defaults (`config.yaml` `translate` section) with per-call `--lang`/`--force` override; single paper and batch modes; `show --lang` to view translated versions; `pipeline --steps translate` for batch processing
- **Federated search** (`fsearch` CLI + `federated_search` MCP tool): search across main library, explore silos (`explore:NAME` / `explore:*`), and arXiv in a single command; arXiv results annotated with "已入库" when DOI matches the main library
- **arXiv source module** (`sources/arxiv.py`): shared Atom API client using `defusedxml` for safe XML parsing
- **Insights analytics** (`scholaraio insights`): behavior dashboard showing top search keywords, most-read papers, weekly reading trend, semantic neighbor recommendations, and active workspaces with paper counts
- **Metrics recording for search/read**: `search`, `usearch`, `vsearch`, and `show` commands now record events to `metrics.db` for behavior analysis
- **`MetricsStore.query_distinct_names()`**: efficient distinct-name query with supporting `(category, name)` index, used by insights recommendations
- **Skill YAML front matter**: all 26 skills now carry standardized `version`/`author`/`license`/`tags` metadata; new `insights` and `document` skills added
- **clawhub.yaml**: marketplace manifest listing all available skills for discovery
- **`explore fetch --limit`**: cap the number of papers fetched from OpenAlex (useful for quick sampling)
- **`attach-pdf --dry-run`**: preview what `attach-pdf` will do without actually running MinerU conversion
- **`document inspect`** (`scholaraio document inspect <file>`): inspect Office documents (DOCX/PPTX/XLSX) showing structure, layout, content preview, and overflow warnings; new `document.py` module with `inspect_pptx`/`inspect_docx`/`inspect_xlsx` functions
- **Office format ingest**: `inbox-doc/` now accepts `.docx`, `.xlsx`, `.pptx` files; new `step_office_convert` pipeline step converts them to Markdown via MarkItDown before ingestion
- **RIS export**: `export ris` outputs RIS format compatible with Zotero, Endnote, and Mendeley (zero dependencies)
- **Markdown reference list export**: `export markdown` generates formatted reference lists with configurable citation styles (APA, Vancouver, Chicago, MLA); supports ordered/unordered lists
- **DOCX export**: `export docx` converts any Markdown content to a Word `.docx` file, supporting headings, paragraphs, tables, lists, code blocks, and bold/italic text
- **Citation styles module** (`citation_styles.py`): manages built-in (APA/Vancouver/Chicago/MLA) and custom citation formats; custom styles loaded from `data/citation_styles/*.py` with path-traversal protection
- **draw skill** (`.claude/skills/draw/`): generate diagrams (Mermaid flowcharts, sequence diagrams, ER diagrams, Gantt charts, mind maps) and vector graphics (cli-anything-inkscape); outputs to `workspace/figures/`
- **`[office]` optional dependency group**: `markitdown[docx,pptx,xlsx]` + `python-docx`

### Fixed

- **Chicago citation format**: empty authors list no longer causes `IndexError`; condition reordered to check `not authors` first (consistent with APA/Vancouver)
- **Federated search DOI annotation**: `WHERE doi IN (...)` replaced with `WHERE LOWER(doi) IN (...)` in `cli.py`, preventing false negatives when stored DOIs have different casing
- **`insights --days` validation**: replaced `args.days or 30` with explicit `days <= 0` check; `--days 0` or negative values now produce a clear error instead of silently defaulting to 30

- CLI error messages and output text unified to Chinese
- `citation_styles`: `show_style()`, `list_styles()`, `get_formatter()` error messages Chinese-ified; Google-style docstrings added
- **Translation same-language skip**: language detection now recognizes common German/French/Spanish inputs, avoiding unnecessary same-language translation calls for supported targets

## [1.0.0] — 2026-03-14

### Added

- **Workspace batch add**: `ws add` now supports `--search "<query>"`, `--topic <id>`, and `--all` flags for bulk paper addition, with `--top`/`--year`/`--journal`/`--type` filter support
- **PDF optional dependency**: `pymupdf` declared in `pyproject.toml` as `[pdf]` extra (included in `[full]`), fixing undeclared dependency for long PDF splitting
- **Subagent information tiers**: T1/T2/T3 architecture documented in CLAUDE.md and AGENTS.md for structured context management

### Fixed

- **MCP `build_topics`**: `nr_topics=0` now correctly maps to `"auto"` (automatic topic merging/reduction) instead of `None` (no reduction); added `-1` as explicit "no reduction" value

## [0.1.0] — 2026-03-13

### Knowledge Base

- PDF ingestion via MinerU (local API / `mineru-open-api` cloud CLI), with auto-splitting for long PDFs (>100 pages)
- Three inboxes: regular papers (`inbox/`), theses (`inbox-thesis/`), general documents (`inbox-doc/`)
- DOI-based deduplication; unresolved papers held in `pending/` for manual review
- Metadata extraction with 4 modes: regex, auto (regex + LLM fallback), robust (regex + LLM cross-check), llm
- API-based metadata enrichment (Crossref, Semantic Scholar, OpenAlex)
- L1–L4 layered content loading (metadata → abstract → conclusion → full text)
- FTS5 full-text search index
- FAISS semantic search with Qwen3-Embedding-0.6B, GPU-adaptive batch profiling
- Unified search with Reciprocal Rank Fusion (RRF) combining keyword + semantic results
- Author search and top-cited paper ranking
- BibTeX export with year/journal filtering
- Data quality audit with structured issue reports and LLM-assisted repair
- BERTopic topic modeling with 6 HTML visualizations (hierarchy, 2D map, barchart, heatmap, term rank, topics over time)
- Citation graph queries (references, citing papers, shared references)
- Citation count fetching from Semantic Scholar / OpenAlex APIs
- Workspace management for organizing paper subsets (search, export within workspace)

### Content Enrichment

- Table of contents (TOC) extraction via LLM
- Conclusion (L3) extraction via LLM, with skip logic for non-article types (thesis, book, document, etc.)
- Abstract backfill via LLM for papers missing abstracts
- Concurrent LLM calls for batch enrichment (configurable worker count)

### Literature Exploration

- Multi-dimensional OpenAlex exploration (ISSN, concept, topic, author, institution, source type, year range, min citations)
- Isolated explore datasets (`data/explore/<name>/`) with independent FTS5 + FAISS + BERTopic
- Explore-specific unified/semantic/keyword search

### Import & Export

- Endnote import (XML and RIS formats)
- Zotero import (Web API and local SQLite)
- PDF attachment to existing papers
- BibTeX export with filtering by year, journal, or paper IDs

### LLM & Embedding

- Multi-LLM backend support: OpenAI-compatible (DeepSeek/OpenAI/vLLM/Ollama), Anthropic (Claude), Google (Gemini)
- API key resolution: config → environment variable → vendor-specific env vars
- LLM token usage and API call timing via MetricsStore
- GPU-adaptive batch embedding with automatic profiling and OOM fallback

### AI Agent Integration

- 22 Claude Code skills following AgentSkills.io open standard
- MCP server with 31 tools
- CLI with 29 subcommands (`scholaraio --help`)
- Multi-agent compatibility: AGENTS.md, .cursorrules, .windsurfrules, .clinerules, .github/copilot-instructions.md
- Claude Code plugin packaging (`.claude-plugin/plugin.json`, `marketplace.json`)
- SessionStart hook for auto-installing dependencies in plugin mode
- Global config fallback (`~/.scholaraio/`) for plugin usage outside the project repo

### Project Infrastructure

- Bilingual setup wizard (EN/ZH) with environment diagnostics
- Code quality toolchain: ruff linter/formatter, mypy type checking, pre-commit hooks
- CI workflow: lint, typecheck, test matrix (Python 3.10–3.12)
- Contract-level test suite (36 tests across 6 modules)
- Community governance: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md
- GitHub issue/PR templates (bug report, feature request)
- CITATION.cff for academic citation
- MkDocs documentation site with API reference (mkdocstrings)
- Release workflow for PyPI publishing (trusted OIDC)
