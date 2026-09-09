# Supporting Information (SI)

Scrinium treats a paper's Supporting Information as an **attachment of the paper**, never as a standalone library entry. SI lives in the paper's `si/` subdirectory, and its converted Markdown is indexed into the parent paper's FTS row, so SI keywords find the parent paper in `scrinium search`.

```text
data/papers/<Author-Year-Title>/
├── meta.json        # the "si" field: mentioned / files / fetch_status
├── paper.md
└── si/
    ├── <name>.pdf     # original files (PDF/Office/data files, kept as-is)
    ├── <name>.md      # converted Markdown (indexed)
    └── images/        # SI figures (Figure S1 etc., readable by the agent)
```

## Trust Model: Automatic First, Agent As Fallback

The resolver chain (`scrinium/si.py`) produces candidate SI URLs from the paper's DOI (publisher rules for ACS-Figshare, RSC, Science, Elsevier, PLOS, Nature/Springer, plus Europe PMC for open-access papers). Every download is checked before attaching:

- **DOI-bound provenance** (URL derived from the DOI, or the file matched via DOI) skips content verification — provenance already guarantees parentage, and figure-only SIs have no verifiable text. A `verify_note` is recorded for spot-checks.
- **Unknown provenance** (`scrinium attach-si` with an arbitrary file) must pass strict verification: SI keyword + parent title/author hit on the first page.

Failures are recorded per paper in `meta.json["si"]["fetch_status"]` with a handoff hint; the agent takes over per the `/si` skill and attaches through `scrinium attach-si`, which funnels through the same verify → convert → attach → index path.

## Commands

```bash
scrinium si scan                    # scan the library, mark papers whose text references SI
scrinium si status                  # queue overview: counts by status + takeover list
scrinium si fetch <paper-id>        # auto-fetch SI for one paper
scrinium si fetch --missing         # batch: all mentioned-but-not-attached papers
scrinium attach-si <paper-id> <file> [--source-url URL] [--no-convert] [--no-verify]
scrinium show <paper-id> --si       # read SI text
```

## `fetch_status` Values

| Status | Meaning | Recommended agent action |
|---|---|---|
| `not_found` | No candidate URL resolved (or all 404) | Web-search for the SI manually |
| `blocked` | Publisher returned 403/429 | Alternate channel: PMC, author homepage, preprint mirror |
| `mismatch` | Downloaded file failed verification | Inspect what was actually downloaded |
| `paywalled` | SI behind a paywall (rare) | Check for an OA mirror, else mark `exhausted` |
| `error` | Network/conversion error | Just retry |
| `exhausted` | Agent confirmed no SI exists | Terminal — never retried |

Terminal statuses (`ok`, `exhausted`, `paywalled`) are never retried automatically; `--force` overrides.

## Ingest-Time Routing

- Inbox entries whose filenames look like SI (`*_si_001.pdf`, `mmc1.pdf`, `supporting-*.pdf`) are deferred until main papers are ingested, then attached by matching the DOI printed in the SI text.
- A file whose DOI duplicates an existing paper **and** looks like SI is attached to that paper instead of going to pending as a duplicate.
- An SI with no parent match goes to `data/pending/` as `si_orphan`; it is reconciled automatically (by DOI) when the parent paper is later ingested.
- Every newly ingested paper triggers one automatic SI fetch (disable with `ingest.si_fetch_on_ingest: false`).

## Audit Integration

`scrinium audit` reports two SI-related findings:

- `missing_si` (info): the text references SI but nothing is attached — run `scrinium si fetch <paper-id>` or take over per the `/si` skill.
- `suspected_si` (warning): a title that looks like Supporting Information was ingested as a standalone paper — migrate it into the parent's `si/` and remove the polluted entry.

## Notes And Limits

- Batch fetch spends MinerU conversion quota (SI PDFs are often 100+ pages); `--no-convert` keeps only the raw files (not indexed).
- A full-library backfill takes roughly 30–60 min per 100 papers (mostly MinerU conversion); run it in the background.
- The resolver chain currently covers ACS (Figshare), RSC, Science, Elsevier, PLOS, Nature/Springer, and Europe PMC (OA subset). Wiley/AIP/bioRxiv are not covered and fall through to the agent takeover queue.
- Downloads are capped at 200 MB per file; larger packages (e.g. huge source-data zips) are skipped with `error` and left for manual handling.
