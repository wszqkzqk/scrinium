# Architecture

This page is the architecture reference for Scrinium. Core behavioral instructions for agents live in `AGENTS.md` at the repository root.

## Main Ingest Flow

- PDFs first try `MinerU` (local API / `mineru-open-api` cloud CLI)
- If `MinerU` is unavailable or fails, processing falls back through `pdf_fallback.py` (`Docling -> PyMuPDF`)
- Direct `.md` ingestion is also supported, skipping PDF parsing entirely
- Generated Markdown enters `extractor.py`
  - Stage 1: extract fields from the Markdown header, supporting `regex`, `auto`, `robust`, and `llm`
- Then it enters `metadata/`
  - Stage 2: API completion, abstract backfill, document metadata generation, JSON output, and rule-based renaming
- Then it enters `pipeline.py`
  - With DOI: write to `data/papers/<Author-Year-Title>/meta.json + paper.md`
  - With patent publication number: write to `data/papers/<Author-Year-Title>/`, deduplicated by publication number
  - Without DOI: move to `data/pending/` for manual confirmation
- After ingestion:
  - `index.py` writes to `data/index.db` (SQLite FTS5)
  - `vectors.py` writes to `data/index.db` (`paper_vectors` table)
  - `topics.py` writes to `data/topic_model/` (BERTopic, reusing `paper_vectors`)
- Finally, the `cli/` package exposes everything to skills and coding agents

## Explore Flow

`explore.py` as an independent data flow:

- Uses the OpenAlex API for multi-dimensional filtering (ISSN / concept / author / institution / keyword / source-type, and more)
- Writes results to `data/explore/<name>/papers.jsonl`
- Maintains at the same time:
  - `explore.db` (`paper_vectors` + FTS5 full-text index)
  - `faiss.index` (FAISS semantic retrieval)
  - `topic_model/` (BERTopic in a unified format) and `viz/` (HTML visualizations)
- Supported search modes: semantic / keyword / hybrid

## Workspace Layer

`workspace.py` as a thin layer:

- `workspace/<name>/papers.json` records paper UUIDs pointing into `data/papers/`
- Search and export reuse existing capabilities by injecting the `paper_ids` parameter (for example `search()`, `vsearch()`, `unified_search()`, and `export_bibtex()`)

## External Import Flow

`import endnote` / `import zotero` as the external import flow:

- `sources/endnote.py` / `sources/zotero.py` parse metadata and match PDFs
- Then hand off to `pipeline.import_external()`
- Then `pipeline.batch_convert_pdfs(enrich=True)` completes batch PDF->MD conversion, abstract backfill, TOC/L3 extraction, embeddings, and indexing

## GPU-Adaptive Batching

The embedding pipeline in `vectors.py` automatically adjusts batch size based on available GPU memory:

1. **Initial profiling** (~10 seconds): starting from 64 tokens, it doubles step by step, measuring incremental memory usage for each length until OOM
2. **Cache reuse**: results are written to `~/.cache/scrinium/gpu_profile.json`, keyed by `model_name::GPU_name`; changing GPU or model triggers automatic re-profiling
3. **Runtime bucketing**: texts are bucketed by token length (64/128/.../16384), and each bucket interpolates an optimal batch size from the profile
4. **OOM fallback**: on OOM, batch size is halved and retried automatically; if OOM still occurs at batch size 1, it falls back to CPU

All paths that call `_embed_batch()` (main-library embedding, explore embedding, and BERTopic's `QwenEmbedder`) benefit automatically.

## Layered Loading Design (L1-L4)

| Layer | Content | Source |
|----|------|------|
| L1 | title, authors, year, journal, doi, volume, issue, pages, publisher, issn | JSON file |
| L2 | abstract | JSON field |
| L3 | conclusion section | JSON field (requires running `enrich conclusion` first) |
| L4 | full Markdown | Read `.md` directly |

## `data/papers/` Directory Structure

```text
data/papers/
└── <Author-Year-Title>/
    ├── meta.json    # L1+L2+L3 metadata (includes "id": "<uuid>")
    ├── paper.md     # L4 source (MinerU output)
    ├── notes.md     # Agent analysis notes (T2 layer, optional, created/appended on demand)
    ├── paper_{lang}.md # Translated version (such as paper_zh.md, optional)
    ├── images/      # Images extracted by MinerU (referenced from md)
    ├── layout.json  # MinerU layout analysis result (optional)
    └── *_content_list.json  # MinerU structured content (optional)
```

Each paper lives in its own directory. The UUID is the internal unique identifier (written to `meta.json["id"]` and never changed).
The directory name is the human-readable `Author-Year-Title`; rename operations only change the directory name.
The `papers_registry` table inside `data/index.db` provides UUID <-> DOI <-> dir_name lookup in both directions.

Portable translation exports are written under:

```text
workspace/translation-ws/
└── <Author-Year-Title>/
    ├── paper_{lang}.md
    └── images/
```

## `data/inbox/` Directory

```text
data/inbox/
├── paper.pdf     # PDF waiting for ingestion (deleted after pipeline processing)
└── paper.md      # Or place .md directly (skip MinerU and ingest directly)
```

## `data/inbox-thesis/` Directory

```text
data/inbox-thesis/
└── thesis.pdf    # Thesis PDF (auto-tagged with paper_type: thesis, skips DOI dedup)
```

Paper types: `article` (default), `thesis`, `patent`, `book`, and `document` (including subtypes such as `technical-report` / `lecture-notes`).

Note: papers without DOI in the regular inbox are automatically judged by the LLM to determine whether they are theses. If yes, they are tagged and ingested; otherwise they are sent to pending.
The thesis inbox skips that judgment and ingests directly as thesis.

## `data/inbox-patent/` Directory

```text
data/inbox-patent/
└── patent.pdf    # Patent PDF (automatically extracts publication number, deduplicates by publication number, tags as patent)
```

Note: supported publication number formats are CN/US/EP/WO/JP/KR/DE/FR/GB/TW/TWI/IN/AU/CA/RU/BR + 6 or more digits + type code (for example `CN112345678A`, `US10123456B2`, `TWI694356B`).

## `data/inbox-doc/` Directory

```text
data/inbox-doc/
├── report.pdf    # Non-paper document PDF (technical reports, standards, lecture notes, etc.)
├── notes.md      # Or place .md directly
├── report.docx   # Word document (converted by MarkItDown)
├── data.xlsx     # Excel spreadsheet (converted by MarkItDown)
└── slides.pptx   # PowerPoint (converted by MarkItDown)
```

Non-paper document ingest flow:

- **Office files** (`.docx` / `.xlsx` / `.pptx`): first converted to `.md` by `step_office_convert` (MarkItDown), then passed through the remaining steps
- DOI deduplication and API queries are skipped
- The LLM auto-generates title and abstract to ensure searchability
- Without an LLM, it degrades to: first Markdown heading or filename -> title, first 500 words -> abstract
- `paper_type` is tagged as `document` (or a more specific type such as `technical-report` / `lecture-notes`)
- Audit rules do not report `missing_doi` warnings for document / patent types

Very long PDFs are split automatically before MinerU conversion when needed:

- local MinerU follows `chunk_page_limit` (default: more than 100 pages)
- MinerU cloud follows the stricter of its documented limits (more than 600 pages or 200MB) and estimates a safe chunk size when only the file-size limit is exceeded

## `data/inbox-proceedings/` Directory

```text
data/inbox-proceedings/
└── volume.pdf    # Proceedings volume / collected papers (explicit manual routing only)
```

Proceedings are only ingested from this dedicated inbox. Regular `data/inbox/` items do not auto-route into `data/proceedings/`; if the user wants the proceedings workflow, they must place the file in `data/inbox-proceedings/` explicitly.

## `data/pending/` Directory

```text
data/pending/
└── <PDF-stem>/
    ├── paper.md           # Markdown for a paper without DOI
    ├── <original-filename>.pdf    # Original PDF (if present)
    ├── pending.json       # Marker file (contains reason and extracted metadata)
    ├── images/            # Images extracted by MinerU (if any)
    ├── layout.json        # MinerU layout info (if any)
    └── *_content_list.json # MinerU structured content (if any)
```

The `issue` field in `pending.json` indicates the reason:

- `no_doi` - No DOI and not thesis/patent; requires manual confirmation and DOI completion before ingestion
- `no_pub_num` - Patent inbox failed to extract a publication number; requires manual confirmation or manual entry
- `duplicate` - The DOI or patent publication number duplicates an already ingested item (including a `duplicate_of` field pointing to the existing paper directory); the user can decide whether to overwrite

Note: theses are ingested automatically (either from the thesis inbox or from LLM judgment) and do not pass through pending.
Patents are ingested automatically (from the patent inbox), deduplicated by publication number, and do not pass through pending.

**Important**: the `missing_md` issue reported by `audit` means an already ingested paper in `data/papers/` is missing `paper.md`; it is a quality problem, not a `data/pending/` status. Pending only contains papers blocked during the ingestion flow (missing DOI or duplicates); `missing_md` means the item has already been ingested but not yet parsed into full text, so full-text search is unavailable.

## `data/duplicates/` Directory

Duplicate entries left over from ingest dedup judgments (for example, items confirmed as duplicates of papers already in the library). `scrinium pending` scans this directory together with `data/pending/` and lists its entries with the `duplicate` issue.

## `data/explore/` Directory

```text
data/explore/<name>/
├── papers.jsonl        # Full paper list fetched from OpenAlex (title/abstract/authors/year/doi/cited_by_count)
├── meta.json           # Exploration-library metadata (query parameters/count/fetched_at)
├── explore.db          # SQLite (paper_vectors table + papers_fts FTS5 full-text index)
├── faiss.index         # FAISS IndexFlatIP (cosine similarity)
├── faiss_ids.json      # List of paper_ids corresponding to the FAISS index
└── topic_model/
    ├── bertopic_model.pkl   # BERTopic model (unified format, same as main library)
    ├── scrinium_meta.pkl  # Additional metadata (paper_ids/metas/topics/embeddings/docs)
    ├── info.json            # Statistics (n_topics/n_outliers/n_papers)
    └── viz/                 # 6 HTML visualizations
```

## `data/tags.yaml` — Curated Tag Vocabulary

```yaml
tags:
  force-field:
    aliases: [forcefield, FF, 力场]
    description: 分子力场相关
```

Agent-curated tag taxonomy (see `scrinium/tags.py`). Canonical tags with aliases and descriptions; per-paper tags live in `meta.json["tags"]`, are indexed into FTS (schema v1), and can filter searches via `--tag`. In embedding-free deployments (`embed.provider: none`), curated tags plus the citation graph replace semantic discovery ("tags as topics").

## `sources/` Abstraction Layer

`papers.py` is the path-helper layer for the local library under `data/papers/`, and modules use it directly to iterate paper directories and read `meta.json`.
`sources/` holds external-source adapters such as arXiv, Endnote, and Zotero.
