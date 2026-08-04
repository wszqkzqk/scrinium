# Paper Ingestion

## Quick Ingest

Place PDFs in `data/inbox/` and run the pipeline:

```bash
scrinium pipeline ingest
```

This will:

1. Convert PDFs to Markdown (MinerU first, then Docling / PyMuPDF fallback when needed)
2. Extract metadata (regex only — the framework makes no LLM calls)
3. Query APIs for completeness (Crossref, Semantic Scholar, OpenAlex)
4. Deduplicate by DOI
5. Move to `data/papers/` and update indexes

When extraction comes back low-confidence (missing title/authors), the output includes a `hint:` line suggesting agent takeover — see "Agent Handoff Hints" in the [Architecture](architecture.md) guide.

## Five Inboxes

| Inbox | Path | Behavior |
|-------|------|----------|
| Papers | `data/inbox/` | Standard pipeline with DOI dedup |
| Proceedings | `data/inbox-proceedings/` | Two-stage proceedings pipeline; first ingest creates `data/proceedings/<Volume>/` with `proceeding.md` + `split_candidates.json` and marks `split_status=pending_review` |
| Theses | `data/inbox-thesis/` | Skips DOI check, marks as thesis |
| Patents | `data/inbox-patent/` | Extracts publication number and deduplicates as patent |
| Documents | `data/inbox-doc/` | Skips DOI check, minimal rule-based metadata (first heading/filename -> title, first 500 words -> abstract) |

Proceedings are only routed from the dedicated `data/inbox-proceedings/` path. Regular `data/inbox/` items always stay on the normal paper/document flow unless you move them into the proceedings inbox explicitly. Child papers are written under `data/proceedings/<Volume>/papers/` only after you review the split and run `scrinium proceedings apply-split`.

## Proceedings Search

Proceedings child papers are not included in default main-library search. Use federated search when you want them:

```bash
scrinium search granular damping --scope proceedings
```

Scrinium prefers MinerU when available, but the live ingest path does not depend on MinerU alone. If MinerU is unavailable or fails, the fallback parser chain is `Docling -> PyMuPDF`.

## Skip PDF Parsing

Already have Markdown? Place `.md` files directly in the inbox — PDF parsing is skipped entirely.

## Pending Papers

Papers without DOI go to `data/pending/` unless a title-keyword heuristic recognizes them as theses. `pending.json` records the reason plus a `hint` for the recommended takeover action, and `scrinium pending` lists everything grouped by issue.

The intended resolution flow is agent-driven: a subagent reads the PDF, judges the real type (thesis / patent / genuinely missing DOI), then either runs `scrinium repair <pending-stem>` with the corrected metadata — `repair` accepts pending items directly, guards against duplicates already in the library (DOI / arXiv ID), ingests the item, and removes the pending directory — or moves the file into the matching inbox for re-ingest.

## Pipeline Presets

| Preset | Steps |
|---|---|
| `full` | `mineru, extract, dedup, ingest, index` (same as `ingest`) |
| `ingest` | `mineru, extract, dedup, ingest, index` |
| `enrich` | `abstract, toc` |
| `reindex` | `index` |

## External Import

```bash
# From Endnote
scrinium import endnote library.xml

# From Zotero
scrinium import zotero --api-key KEY --library-id ID
```

## Metadata Maintenance

After papers are already in `data/papers/`, the metadata subpackage also powers two maintenance flows:

```bash
# Backfill missing abstracts from paper.md, with optional DOI-page fetch
scrinium enrich abstract
scrinium enrich abstract --doi-fetch

# Refresh citation counts and bibliographic details from APIs
scrinium refresh --all
scrinium refresh "<paper-id>"
```

- `enrich abstract` fills missing abstracts from local Markdown, and can prefer official publisher abstracts when `--doi-fetch` is enabled.
- `refresh` re-runs Crossref / Semantic Scholar / OpenAlex enrichment for already ingested papers.
