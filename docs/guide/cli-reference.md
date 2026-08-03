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
scrinium embed
scrinium top-cited
scrinium tag
scrinium tags
scrinium pending
```

- `search` is the single retrieval entry point. `--mode keyword` (default) performs FTS5 keyword search, `--mode unified` fuses keyword + semantic retrieval, and `--mode semantic` performs pure vector search (requires an embedding backend).
- `search --scope main,proceedings,explore:*,arxiv` runs federated search across the main library, proceedings, explore databases, and arXiv.
- `search-author` searches by author name.
- `show` supports layered reading from metadata to full text.
- `tag` / `tags` manage agent-curated paper tags and the controlled vocabulary (`data/tags.yaml`); `search` / `workspace search` accept `--tag` filters.
- `pending` lists items blocked in `data/pending/` and `data/duplicates/` with resolution hints.
- Read-oriented commands (`search` / `show` / `workspace show` / `top-cited`) accept `--json` for structured output.

## Ingest And Enrich

```text
scrinium ingest
scrinium pipeline [preset]
scrinium enrich toc|conclusion|abstract
scrinium refetch
scrinium translate
scrinium attach-pdf
```

- `ingest` runs the inbox ingest preset; it is an alias for `pipeline ingest` and accepts all pipeline options.
- `pipeline` is the main composable ingest entrypoint.
- Current preset values are `full`, `ingest`, `enrich`, and `reindex`.
- Run `scrinium pipeline --help` for pipeline options such as `--steps`, `--dry-run`, `--no-api`, and `--rebuild`.
- `enrich toc` extracts the table of contents, `enrich conclusion` extracts the conclusion section (L3), and `enrich abstract` backfills missing abstracts.

## Graph, Topics, And Explore

```text
scrinium references
scrinium cited-by
scrinium shared-references
scrinium topics
scrinium explore
```

- Use `references`, `cited-by`, and `shared-references` for citation-graph analysis.
- Use `topics` for BERTopic-based topic modeling and exploration.
- Use `explore` for OpenAlex-backed literature exploration outside the main library.

## Import, Export, And Workspaces

```text
scrinium import-endnote
scrinium import-zotero
scrinium export
scrinium workspace
```

- `import-endnote` and `import-zotero` bring existing libraries into Scrinium.
- `export` handles BibTeX, RIS, Markdown, and DOCX export.
- `workspace` manages paper subsets for focused projects and writing workflows (`init` / `add` / `remove` / `list` / `show` / `search` / `rename` / `export`).

## Scientific Runtime And Documents

```text
scrinium toolref
scrinium arxiv
scrinium document
scrinium style
```

- `toolref` provides versioned scientific tool documentation lookup.
- Current `toolref` subcommands are `fetch`, `show`, `search`, `list`, and `use`.
- `arxiv` supports arXiv search and PDF fetch.
- `document` provides Office-document utilities such as inspection.
- `style` manages citation styles.

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
- `insights` analyzes research behavior such as hot keywords and reading trends.
- `metrics` shows LLM token and runtime usage.
- `proceedings` provides dedicated proceedings helpers.
- `citation-check` verifies whether citations in text are backed by the local library.

## Legacy Aliases

Older short names still work but are hidden from the top-level `--help` listing. Prefer the primary names in new scripts and prompts:

| Legacy alias | Primary form |
|---|---|
| `usearch <q>` | `search <q> --mode unified` |
| `vsearch <q>` | `search <q> --mode semantic` |
| `fsearch <q> --scope S` | `search <q> --scope S` |
| `enrich-toc` | `enrich toc` |
| `enrich-l3` | `enrich conclusion` |
| `backfill-abstract` | `enrich abstract` |
| `refs` | `references` |
| `citing` | `cited-by` |
| `shared-refs` | `shared-references` |
| `ws` | `workspace` |

## Recommended Pattern

Use the agent for the full workflow, and fall back to CLI commands when you want:

- fast scripted access
- a precise diagnostic check
- direct inspection of intermediate results
- reproducible command-line automation
