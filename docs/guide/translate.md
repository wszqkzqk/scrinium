# Translation Guide

Scrinium can translate `paper.md` into `paper_{lang}.md` while preserving Markdown structure, LaTeX formulas, code blocks, and image links.

## Basic Usage

Translate one paper:

```bash
scrinium translate "<paper-id>" --lang zh
```

Translate all papers:

```bash
scrinium translate --all --lang zh
```

Read the translated version:

```bash
scrinium show "<paper-id>" --layer 4 --lang zh
```

## Concurrency and Resume

- Single-paper translation uses `config.translate.concurrency` to send multiple chunk requests concurrently
- Chunking prefers natural paragraph boundaries; only oversized paragraphs are split further
- Translation state is persisted in a temporary per-paper workdir such as `.translate_zh/`
- Each chunk is written separately to `parts/*.md`, with state tracked in `state.json` and `chunks.json`
- Chunk failures use timeout retry with exponential backoff (up to 5 attempts by default)
- The final `paper_{lang}.md` still advances in original order, so partially completed continuous prefixes remain readable
- Successful trailing chunks are still preserved in the temporary workdir; reruns skip those chunks and only fill the missing gaps
- If translation is interrupted, rerun the same command to resume from unfinished or failed chunks
- Use `--force` to discard the temporary workdir and start over

## Portable Export

If you want a translated copy that can be moved out of the paper directory without breaking image links:

```bash
scrinium translate "<paper-id>" --lang zh --portable
```

This keeps the normal in-place translation:

```text
data/papers/<Author-Year-Title>/paper_zh.md
```

And also creates a portable bundle:

```text
workspace/translation-ws/<Author-Year-Title>/
├── paper_zh.md
└── images/
```

The bundle is created by copying, not moving, so the original `paper.md`, `paper_{lang}.md`, and `images/` remain untouched.
