# CLI Reference

Scrinium is designed to work best through an AI coding agent, but the CLI remains useful for scripting, inspection, and quick queries.

The authoritative source is always:

```bash
scrinium --help
scrinium <command> --help
```

The command groups below are aligned with the current codebase.

## Core Commands

```text
scrinium index
scrinium search
scrinium search-author
scrinium show
scrinium top-cited
scrinium tag
scrinium tags
scrinium topics
scrinium pending
```

- `search` is the single retrieval entry point, performing FTS5 keyword search (the only built-in retrieval mode; meaning-based recall is an agent-side workflow — see `docs/guide/search.md`).
- `search --scope main,proceedings,explore:*,arxiv` runs federated search across the main library, proceedings, explore databases, and arXiv.
- `search-author` searches by author name.
- `show` supports layered reading from metadata to full text.
- `tag` / `tags` manage agent-curated paper tags and the controlled vocabulary (`data/tags.yaml`); `search` / `workspace search` accept `--tag` filters.
- `topics` browses the tag-based topic distribution: `scrinium topics` shows the overview (tags sorted by paper count, with shares and the untagged count), `scrinium topics <tag>` drills into one topic. Tags are the only topic system.
- `pending` lists items blocked in `data/pending/` and `data/duplicates/` with resolution hints; a no-DOI item can be resolved in place via `scrinium repair <pending-stem>`, which ingests it with a dedup guard against papers already in the library.
- Read-oriented commands (`search` / `show` / `workspace show` / `top-cited`) accept `--json` for structured output.

## Ingest And Enrich

```text
scrinium ingest
scrinium pipeline [preset]
scrinium enrich toc|abstract
scrinium refresh
scrinium attach-pdf
```

- `ingest` runs the inbox ingest preset; it is an alias for `pipeline ingest` and accepts all pipeline options.
- `pipeline` is the main composable ingest entrypoint.
- Current preset values are `full` and `ingest` (both `mineru, extract, dedup, ingest, index`), `enrich` (`abstract, toc`), and `reindex` (`index`).
- Run `scrinium pipeline --help` for pipeline options such as `--steps`, `--dry-run`, `--no-api`, and `--rebuild`.
- `enrich toc` extracts the table of contents with pure rules, and `enrich abstract` backfills missing abstracts (regex, with optional DOI-page fetch). When a rule-based path misses, the command prints a `hint:` suggesting the agent read the paper and write the field directly.
- `refresh` re-fetches metadata, citation counts, and references from the APIs.

## Graph, Topics, And Explore

```text
scrinium references
scrinium cited-by
scrinium shared-references
scrinium snowball
scrinium topics
scrinium explore
```

- Use `references`, `cited-by`, and `shared-references` for citation-graph analysis, and `snowball` to expand from seed papers along the graph.
- Use `topics` for tag-based topic browsing (distribution overview + per-tag drill-down); there is no second topic system behind it.
- Use `explore` for OpenAlex-backed literature exploration outside the main library (`fetch` / `search` / `list` / `info`; keyword search over an isolated FTS5 index).

## Import, Export, And Workspaces

```text
scrinium import endnote|zotero
scrinium export
scrinium workspace
```

- `import endnote` and `import zotero` bring existing libraries into Scrinium.
- `export` handles BibTeX, RIS, Markdown, and DOCX export.
- `workspace` manages paper subsets for focused projects and writing workflows (`init` / `add` / `remove` / `list` / `show` / `search` / `rename` / `export`).

## Scientific Runtime And Documents

```text
scrinium toolref
scrinium arxiv
scrinium document
scrinium citation-styles
```

- `toolref` provides versioned scientific tool documentation lookup.
- Current `toolref` subcommands are `fetch`, `show`, `search`, `list`, and `use`.
- `arxiv` supports arXiv search and PDF fetch.
- `document` provides Office-document utilities such as inspection.
- `citation-styles` manages citation styles (`list` / `show`).

## Audit, Setup, And Runtime Inspection

```text
scrinium audit
scrinium repair
scrinium rename
scrinium setup
scrinium insights
scrinium metrics
scrinium proceedings
scrinium citation-check
```

- `setup` is the environment check and setup wizard entrypoint.
- `repair` fixes a library paper's metadata in place (standardized rename), or — given a `data/pending/` item name — ingests that pending item into the library with a dedup guard and removes the pending directory.
- `insights` analyzes research behavior such as hot keywords and reading trends.
- `metrics` shows runtime metrics (pipeline step / API call timing and search/read events; `--category` defaults to `step`).
- `proceedings` provides dedicated proceedings helpers.
- `citation-check` verifies whether citations in text are backed by the local library.

## Agent Handoff Hints

When a deterministic path fails or returns low confidence, CLI output (text and `--json` alike) includes a line prefixed with `hint: `. This is a framework-to-agent handoff signal: the agent is expected to take over with the corresponding skill workflow (e.g. dispatch a subagent to read the original PDF and fix `meta.json` directly). Emission points include ingest results, `pending`, `enrich abstract` / `enrich toc` misses, `audit` findings, and `show --layer 3` when no conclusion has been written yet.

## Legacy Aliases

Older short names still work but are hidden from the top-level `--help` listing. Prefer the primary names in new scripts and prompts:

| Legacy alias | Primary form |
|---|---|
| `fsearch <q> --scope S` | `search <q> --scope S` |
| `enrich-toc` | `enrich toc` |
| `backfill-abstract` | `enrich abstract` |
| `import-endnote` | `import endnote` |
| `import-zotero` | `import zotero` |
| `refetch` | `refresh` |
| `refs` | `references` |
| `citing` | `cited-by` |
| `shared-refs` | `shared-references` |
| `ws` | `workspace` |
| `style` | `citation-styles` |

Removed in 3.0 (no alias): `embed`, `vsearch`, `usearch`, `enrich-l3` / `enrich conclusion`, `translate`, `explore embed|topics|viz`, and the `--mode` option on `search` / `workspace search` / `explore search`.

## Recommended Pattern

Use the agent for the full workflow, and fall back to CLI commands when you want:

- fast scripted access
- a precise diagnostic check
- direct inspection of intermediate results
- reproducible command-line automation
