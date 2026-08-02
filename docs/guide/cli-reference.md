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
scrinium vsearch
scrinium usearch
scrinium fsearch
scrinium top-cited
scrinium tag
scrinium tags
scrinium pending
```

- `search` performs keyword search.
- `vsearch` performs semantic vector search (requires an embedding backend).
- `usearch` performs fused keyword + semantic retrieval.
- `fsearch` searches across the main library, proceedings, explore databases, and arXiv.
- `show` supports layered reading from metadata to full text.
- `tag` / `tags` manage agent-curated paper tags and the controlled vocabulary (`data/tags.yaml`); `search` / `usearch` / `ws search` accept `--tag` filters.
- `pending` lists items blocked in `data/pending/` and `data/duplicates/` with resolution hints.
- Read-oriented commands (`search` / `usearch` / `show` / `ws show` / `top-cited`) accept `--json` for structured output.

## Ingest And Enrich

```text
scrinium pipeline [preset]
scrinium enrich-toc
scrinium enrich-l3
scrinium backfill-abstract
scrinium refetch
scrinium translate
scrinium attach-pdf
```

- `pipeline` is the main composable ingest entrypoint.
- Current preset values are `full`, `ingest`, `enrich`, and `reindex`.
- Run `scrinium pipeline --help` for pipeline options such as `--steps`, `--dry-run`, `--no-api`, and `--rebuild`.

## Graph, Topics, And Explore

```text
scrinium refs
scrinium citing
scrinium shared-refs
scrinium topics
scrinium explore
```

- Use `refs`, `citing`, and `shared-refs` for citation-graph analysis.
- Use `topics` for BERTopic-based topic modeling and exploration.
- Use `explore` for OpenAlex-backed literature exploration outside the main library.

## Import, Export, And Workspaces

```text
scrinium import-endnote
scrinium import-zotero
scrinium export
scrinium ws
```

- `import-endnote` and `import-zotero` bring existing libraries into Scrinium.
- `export` handles BibTeX, RIS, Markdown, and DOCX export.
- `ws` manages paper subsets for focused projects and writing workflows.

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

## Recommended Pattern

Use the agent for the full workflow, and fall back to CLI commands when you want:

- fast scripted access
- a precise diagnostic check
- direct inspection of intermediate results
- reproducible command-line automation
