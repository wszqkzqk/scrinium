# Architecture

This page is the architecture reference for Scrinium. Core behavioral instructions for agents live in `AGENTS.md` at the repository root.

## Main Ingest Flow

- PDFs first try `MinerU` (local API / `mineru-open-api` cloud CLI)
- If `MinerU` is unavailable or fails, processing falls back through `pdf_fallback.py` (`Docling -> PyMuPDF`)
- Direct `.md` ingestion is also supported, skipping PDF parsing entirely
- Generated Markdown enters `extractor.py`
  - Stage 1: extract fields from the Markdown header (`regex` only — the framework makes no LLM calls)
- Then it enters `metadata/`
  - Stage 2: API completion, abstract backfill, document metadata generation, JSON output, and rule-based renaming
- Then it enters `pipeline.py`
  - With DOI: write to `data/papers/<Author-Year-Title>/meta.json + paper.md`
  - With patent publication number: write to `data/papers/<Author-Year-Title>/`, deduplicated by publication number
  - Without DOI: move to `data/pending/` for manual confirmation
- After ingestion:
  - `index.py` writes to `data/index.db` (SQLite FTS5, schema v2)
- Finally, the `cli/` package exposes everything to skills and coding agents

## Explore Flow

`explore.py` as an independent data flow:

- Uses the OpenAlex API for multi-dimensional filtering (ISSN / concept / author / institution / keyword / source-type, and more)
- Writes results to `data/explore/<name>/papers.jsonl`
- Maintains `explore.db` (FTS5 full-text index)
- Supported search mode: keyword

## Workspace Layer

`workspace.py` as a thin layer:

- `workspace/<name>/papers.json` records paper UUIDs pointing into `data/papers/`
- Search and export reuse existing capabilities by injecting the `paper_ids` parameter (for example `search()` and `export_bibtex()`)

## External Import Flow

`import endnote` / `import zotero` as the external import flow:

- `sources/endnote.py` / `sources/zotero.py` parse metadata and match PDFs
- Then hand off to `pipeline.import_external()`
- Then `pipeline.batch_convert_pdfs()` completes batch PDF->MD conversion and indexing; abstract/TOC backfill runs through the `enrich` preset or agent post-processing

## Layered Loading Design (L1-L4)

| Layer | Content | Source |
|----|------|------|
| L1 | title, authors, year, journal, doi, volume, issue, pages, publisher, issn | JSON file |
| L2 | abstract | JSON field |
| L3 | conclusion section | JSON field (written by the agent after reading L4 — see "Agent-Written meta.json Fields" below) |
| L4 | full Markdown | Read `.md` directly |

## `data/papers/` Directory Structure

```text
data/papers/
└── <Author-Year-Title>/
    ├── meta.json    # L1+L2+L3 metadata (includes "id": "<uuid>")
    ├── paper.md     # L4 source (MinerU output)
    ├── notes.md     # Agent analysis notes (T2 layer, optional, created/appended on demand)
    ├── paper_{lang}.md # Translated version written by the agent (such as paper_zh.md, optional)
    ├── images/      # Images extracted by MinerU (referenced from md)
    ├── layout.json  # MinerU layout analysis result (optional)
    └── *_content_list.json  # MinerU structured content (optional)
```

Each paper lives in its own directory. The UUID is the internal unique identifier (written to `meta.json["id"]` and never changed).
The directory name is the human-readable `Author-Year-Title`; rename operations only change the directory name.
The `papers_registry` table inside `data/index.db` provides UUID <-> DOI <-> dir_name lookup in both directions.

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

Note: papers without DOI in the regular inbox are checked against title-keyword heuristics (for example "thesis" / "dissertation"). A heuristic hit tags and ingests the item as a thesis; anything else goes to `data/pending/`, where an agent (usually a subagent) can review the PDF and decide.
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
- Minimal rule-based metadata keeps the document searchable: first Markdown heading or filename -> title, first 500 words -> abstract; an agent can refine title/abstract later by editing `meta.json` directly
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

`pending.json` also carries a `hint` field with the recommended agent takeover action (see "Agent Handoff Hints" below).

Note: theses are ingested automatically (either from the thesis inbox or via title-keyword heuristics) and do not pass through pending.
Patents are ingested automatically (from the patent inbox), deduplicated by publication number, and do not pass through pending.

**Important**: the `missing_md` issue reported by `audit` means an already ingested paper in `data/papers/` is missing `paper.md`; it is a quality problem, not a `data/pending/` status. Pending only contains papers blocked during the ingestion flow (missing DOI or duplicates); `missing_md` means the item has already been ingested but not yet parsed into full text, so full-text search is unavailable.

## `data/duplicates/` Directory

Duplicate entries left over from ingest dedup judgments (for example, items confirmed as duplicates of papers already in the library). `scrinium pending` scans this directory together with `data/pending/` and lists its entries with the `duplicate` issue.

## `data/explore/` Directory

```text
data/explore/<name>/
├── papers.jsonl        # Full paper list fetched from OpenAlex (title/abstract/authors/year/doi/cited_by_count)
├── meta.json           # Exploration-library metadata (query parameters/count/fetched_at)
└── explore.db          # SQLite (papers_fts FTS5 full-text index)
```

Leftover artifacts from pre-3.0 installs (`faiss.index`, `faiss_ids.json`, `topic_model/`) are no longer read or produced and can be deleted manually.

## `data/tags.yaml` — Curated Tag Vocabulary (Tags as Topics)

```yaml
tags:
  force-field:
    aliases: [forcefield, FF, 力场]
    description: 分子力场相关
```

Agent-curated tag taxonomy (see `scrinium/tags.py`). Canonical tags with aliases and descriptions; per-paper tags live in `meta.json["tags"]`, are indexed into FTS, and can filter searches via `--tag`.

Tags are the topic system: `scrinium topics` renders the topic distribution from this vocabulary (per-tag counts, shares, untagged count) and `scrinium topics <tag>` drills into a single topic. There is no second clustering layer — vocabulary merging is done through tag aliases, and distribution charts are produced by the agent's `draw` skill on demand.

## Agent Handoff Hints (`hint: `)

The framework makes no model calls. When a deterministic path fails or returns low confidence, the CLI emits a line prefixed with `hint: ` (in text and `--json` output alike) instead of trying to be clever. That line is the framework-to-agent handoff signal: the agent is expected to take over via the matching skill workflow. Emission points:

- **Ingest results** — low-confidence extraction (missing title/authors), `no_doi`, and `duplicate` each come with a hint; `pending.json` stores the same hint in its `hint` field
- **`scrinium pending`** — each blocked item suggests the resolution workflow (subagent review, `repair`, or re-ingest)
- **`enrich abstract` / `enrich toc`** — when the regex misses, the hint asks the agent to read the paper and write the field directly
- **`scrinium audit`** — each finding suggests the agent-side repair workflow (edit `meta.json`, `repair`, `rename`)
- **`show --layer 3`** — when no conclusion exists yet, the hint asks the agent to read L4 and write `l3_conclusion`

## Agent-Written meta.json Fields

Several `meta.json` fields are designed to be written by the agent (usually a subagent that actually read the paper) rather than by framework code:

| Field | Written by | Takes effect |
|---|---|---|
| `toc` | `enrich toc` (pure rules), or the agent | immediately (navigation aid; not part of the FTS index) |
| `l3_conclusion` (+ `l3_extraction_method: agent`) | the agent, after reading L4 | `show --layer 3`; searchable after `scrinium index` |
| `abstract` | `enrich abstract` (regex / DOI fetch), or the agent | `show --layer 2`; searchable after `scrinium index` |
| `translations` | the agent, alongside `paper_{lang}.md` | `show --layer 4 --lang <code>` |

The FTS index covers title, authors, abstract, conclusion, and tags — after editing `abstract` or `l3_conclusion`, run `scrinium index` so search picks them up.

## Index Schema v2

`data/index.db` carries `PRAGMA user_version = 2`. On the first index operation against a pre-3.0 database, the migration runs automatically: the legacy embedding tables (`paper_vectors`, `vector_metadata`) are dropped and the FAISS sidecar files (`faiss.index`, `faiss_ids.json`) next to `index.db` are deleted. No user action is required; other pre-3.0 artifacts (`data/topic_model/`, model caches) are never touched by the framework and can be deleted manually.

## `sources/` Abstraction Layer

`papers.py` is the path-helper layer for the local library under `data/papers/`, and modules use it directly to iterate paper directories and read `meta.json`.
`sources/` holds external-source adapters such as arXiv, Endnote, and Zotero.
