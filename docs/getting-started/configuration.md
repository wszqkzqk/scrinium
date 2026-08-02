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

> **Legacy fallback**: all `SCRINIUM_*` environment variables still honor their deprecated pre-fork `SCHOLARAIO_*` names (with a warning) when the new name is unset, and a legacy `~/.scholaraio/config.yaml` is used when `~/.scrinium/config.yaml` does not exist.

All relative paths (such as `data/papers` and `data/index.db`) are resolved relative to the directory containing `config.yaml`.
When used inside the project directory, paths point into the project's `data/`; when used as a plugin, the global config makes paths point into `~/.scrinium/data/`.

## API Keys

LLM API key lookup order:

1. `config.local.yaml` → `llm.api_key`
2. Environment variable `SCRINIUM_LLM_API_KEY` (universal for any backend)
3. Backend-specific environment variables, based on `llm.backend`:
   - `openai-compat`: `DEEPSEEK_API_KEY` → `OPENAI_API_KEY`
   - `anthropic`: `ANTHROPIC_API_KEY`
   - `google`: `GOOGLE_API_KEY` → `GEMINI_API_KEY`

Which keys matter:

- **LLM key** (DeepSeek / OpenAI / Anthropic / Google): required for metadata extraction and content enrichment. Without it, the system degrades to pure regex mode and enrich features are unavailable. This is usually billed separately by the chosen provider; do not assume an agent subscription automatically covers Scrinium API calls
- **MinerU token**: used by `mineru-open-api extract` for MinerU cloud PDF-to-Markdown conversion. `MINERU_TOKEN` is preferred; `MINERU_API_KEY` remains a compatibility alias. Without it, Scrinium can still fall back to Docling / PyMuPDF, or ingest manually placed `.md` files. MinerU token application is currently free
- **Semantic Scholar API key**: optional; useful when the user needs higher throughput for citation refresh / refetch workflows
- **Zotero API key**: optional; only needed for the Zotero Web API import path (local `zotero.sqlite` import does not require it)

### Example `config.local.yaml`

```yaml
llm:
  api_key: "sk-your-key-here"

ingest:
  mineru_api_key: "your-mineru-token"  # compatibility alias; MINERU_TOKEN is preferred
  s2_api_key: "your-semantic-scholar-key"  # optional

zotero:
  api_key: "your-zotero-key"  # optional
  library_id: "1234567"  # optional
```

You can also keep the token out of YAML entirely and set `MINERU_TOKEN` in the environment. `MINERU_API_KEY` is still accepted as a compatibility alias.

## Key Settings

### LLM Backend

Default: DeepSeek (`deepseek-chat`) via OpenAI-compatible protocol.
Three backend protocols are supported: `openai-compat` (DeepSeek / OpenAI / vLLM / Ollama), `anthropic`, and `google` (Gemini).

```yaml
llm:
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

### Metadata Extraction

```yaml
ingest:
  extractor: robust  # regex + LLM (default)
  # Other options: auto, regex, llm
```

`ingest.extractor: robust` (default) means regex + LLM dual pass, where the LLM corrects OCR errors and detects multiple DOIs in the full text. Other modes: `auto` (LLM only as fallback), `regex` (pure regex), and `llm` (pure LLM).

### Embedding

```yaml
embed:
  provider: local  # local | openai-compat | none
  source: modelscope  # default (China)
  # source: huggingface  # for international users
```

`embed.provider` selects the embedding backend:

- `local` (default): runs the embedding model locally. The model (Qwen3-Embedding-0.6B, ~1.2GB) downloads automatically on the first `embed` / `vsearch`
- `openai-compat`: calls an OpenAI-compatible embeddings API instead of running a local model; requires `embed.api_base`, `embed.api_key`, and `embed.model` (the key can also come from `config.local.yaml` or the `SCRINIUM_EMBED_API_KEY` environment variable)
- `none`: disables embeddings entirely

With `embed.provider: none`, all semantic features are disabled: `vsearch` / `usearch` are unavailable, topic models cannot be rebuilt, and retrieval degrades to pure keyword search. In this mode, the curated tag vocabulary in `data/tags.yaml` plus the citation graph replace semantic discovery ("tags as topics"; see the `data/tags.yaml` section in `docs/guide/architecture.md`).

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
