# Configuration

Scrinium uses two config files:

| File | Tracked | Purpose |
|------|---------|---------|
| `config.yaml` | Yes | Default settings |
| `config.local.yaml` | No (git-ignored) | API keys and local overrides |

## Config Discovery

Config lookup order for `config.yaml`:

1. Explicitly passed `config_path`
2. Environment variable `SCRINIUM_CONFIG`
3. Walk upward from the current working directory (up to 6 levels)
4. `~/.scrinium/config.yaml` (global config used in plugin mode)

> **Legacy fallback**: `SCRINIUM_CONFIG` still honors the deprecated pre-fork `SCHOLARAIO_CONFIG` name (with a warning) when the new name is unset, and a legacy `~/.scholaraio/config.yaml` is used when `~/.scrinium/config.yaml` does not exist.

All relative paths (such as `data/papers` and `data/index.db`) are resolved relative to the directory containing `config.yaml`.
When used inside the project directory, paths point into the project's `data/`; when used as a plugin, the global config makes paths point into `~/.scrinium/data/`.

## API Keys

Scrinium makes no LLM or embedding calls, so no LLM key is needed anywhere. The remaining keys:

- **MinerU token**: used by `mineru-open-api extract` for MinerU cloud PDF-to-Markdown conversion. `MINERU_TOKEN` is preferred; `MINERU_API_KEY` remains a compatibility alias. Without it, Scrinium can still fall back to Docling / PyMuPDF, or ingest manually placed `.md` files. MinerU token application is currently free
- **Semantic Scholar API key**: optional; useful when the user needs higher throughput for citation refresh / refetch workflows
- **Zotero API key**: optional; only needed for the Zotero Web API import path (local `zotero.sqlite` import does not require it)

### Example `config.local.yaml`

```yaml
ingest:
  mineru_api_key: "your-mineru-token"  # compatibility alias; MINERU_TOKEN is preferred
  s2_api_key: "your-semantic-scholar-key"  # optional

zotero:
  api_key: "your-zotero-key"  # optional
  library_id: "1234567"  # optional
```

You can also keep the token out of YAML entirely and set `MINERU_TOKEN` in the environment. `MINERU_API_KEY` is still accepted as a compatibility alias.

### Deprecated Config Sections

The `llm`, `translate`, `embed`, and `topics` sections (plus `ingest.extractor` values other than `regex` and `ingest.abstract_llm_mode`) were removed in 3.0 together with all in-framework model calls. If an old config still contains them, Scrinium logs a one-time deprecation warning per section and ignores the values — startup never fails, and you can delete the sections at your convenience.

## Key Settings

### Metadata Extraction

Metadata extraction is regex-only (`RegexExtractor`); there is no `ingest.extractor` setting anymore. When extraction comes back low-confidence, the CLI emits a `hint:` and the agent takes over (see "Agent Handoff Hints" in `docs/guide/architecture.md`).

### MinerU Constraints

MinerU configuration constraints (aligned with current code):

- Keep the user-facing experience minimal first; do not proactively expose advanced MinerU parameters
- `mineru_model_version_cloud` should only be recommended as `pipeline` or `vlm`; `MinerU-HTML` should not be the default for PDF ingest
- For the cloud precise parsing API, `mineru_parse_method` only maps `ocr` to the official `file.is_ocr=true`; `auto` and `txt` both follow the default non-forced OCR path
- `mineru_enable_formula`, `mineru_enable_table`, and `mineru_lang` only take effect for cloud `pipeline` / `vlm`; keep defaults unless there is a clear need
- `mineru_backend_local` is only relevant when the user explicitly self-hosts local MinerU; pure cloud usage usually does not need it
- The official upper limit for `mineru_batch_size` is `200`; keep the default conservative
- Current recommended defaults:
  - Chinese or mixed Chinese-English PDFs: `mineru_lang: ch`
  - English-only PDFs: change to `mineru_lang: en`
