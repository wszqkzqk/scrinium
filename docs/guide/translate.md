# Translation Guide

Scrinium no longer calls any translation API itself. Translation is an agent-side workflow; the framework keeps only the storage and reading conventions, so translated papers stay browsable and resumable.

## Storage Conventions

- Translations live next to the original as `data/papers/<Author-Year-Title>/paper_{lang}.md` (for example `paper_zh.md`)
- The agent records translation state in `meta.json["translations"]`
- Reading prefers the translation when `--lang` is given and falls back to the original otherwise:

```bash
scrinium show "<paper-id>" --layer 4 --lang zh
```

Language codes are validated (lowercase letters only) before any file lookup, so `--lang` cannot escape the paper directory.

## Agent Translation Workflow

The `translate` skill orchestrates the work with subagents:

1. Read the original with `scrinium show "<paper-id>" --layer 4`
2. Split the Markdown into chunks along section boundaries, keeping LaTeX formulas, code blocks, and image links intact
3. Dispatch parallel subagents to translate the chunks (a shared glossary from workspace notes keeps terminology consistent across chunks and papers)
4. Append the translated chunks to `paper_{lang}.md` in original order — the partially written file is the resume point, so an interrupted run simply continues from the current file length
5. Update `meta.json["translations"]`
6. Spot-check the result with `scrinium show "<paper-id>" --layer 4 --lang zh`

Batch translation is the same workflow fanned out: one subagent per paper.

## Portable Copies

Because translations are plain files inside the paper directory, a portable bundle is just a copy: duplicate `paper_{lang}.md` together with the paper's `images/` directory wherever you need it (for example under `workspace/`). Image links are relative, so the copy keeps rendering as long as `images/` travels with it.
