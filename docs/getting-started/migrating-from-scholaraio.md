# Migrating from ScholarAIO (fork upgrade)

Scrinium 2.0.0 is a hard fork of ScholarAIO 1.3.0. All user data formats are unchanged, so **your library, notes, tags, metrics, and workspaces carry over with zero conversion** — the upgrade is about repointing the git remote, the CLI name, and (optionally) the directory name and agent session records.

> **Also read the 3.0 section below** if you are upgrading from Scrinium 2.x or from ScholarAIO directly to 3.0 — it lists breaking changes and the one-time data cleanup.

## Upgrading to Scrinium 3.0 (breaking)

Scrinium 3.0 removes **all in-framework LLM and embedding calls**. Every removed capability has a stronger agent-side takeover path (the agent, usually via subagents, reads the real text and writes results back), so no user-facing function is lost — but the CLI surface and config changed.

### Breaking changes

- **Removed commands**: `scrinium translate`, `scrinium embed`, `scrinium vsearch`, `scrinium usearch`, `scrinium enrich conclusion` (alias `enrich-l3`), `scrinium explore embed|topics|viz`, and `scrinium metrics --summary`
- **Removed options**: `--mode` on `search` / `workspace search` / `explore search` — search is keyword (FTS5) only. Meaning-based recall is an agent workflow: query expansion into multiple keyword searches, `--tag` filters, and citation-graph `snowball`
- **Removed config sections**: `llm`, `translate`, `embed`, `topics`, plus `ingest.extractor` (extraction is regex-only) and `ingest.abstract_llm_mode`. Leftover sections trigger a one-time deprecation warning and are ignored — startup never fails
- **Removed extras**: `scrinium[embed]` and `scrinium[topics]`; `scrinium[full]` no longer includes them (now: import + pdf + office + draw)
- **Changed behavior**: `scrinium topics` is now tag-based topic browsing (distribution overview + per-tag drill-down); tags are the only topic system. Translation keeps its storage conventions (`paper_{lang}.md`, `meta.json["translations"]`, `show --layer 4 --lang`) but is performed by the agent. L3 conclusions are written by the agent into `meta.json["l3_conclusion"]` and become searchable after `scrinium index`
- **Handoff hints**: when a deterministic path fails or is low-confidence, CLI output (text and `--json`) carries a `hint: ` line telling the agent which skill workflow should take over

### Data migration

- **`data/index.db`**: automatic. The first index operation upgrades to schema v2 — the legacy `paper_vectors` / `vector_metadata` tables are dropped and the `faiss.index` / `faiss_ids.json` sidecar files next to `index.db` are deleted. Run `scrinium index` once to trigger it
- **Delete manually to reclaim disk space** (the framework never removes these on its own):
  - `data/topic_model/` — old BERTopic artifacts
  - `data/explore/<name>/topic_model/`, `data/explore/<name>/faiss.index`, `data/explore/<name>/faiss_ids.json` — old explore-library artifacts
  - `~/.cache/scrinium/gpu_profile.json` — old GPU batching profile
  - the Qwen3-Embedding model cache (about 1.2 GB under `~/.cache/modelscope/` or your HuggingFace cache, depending on the old `embed.source`)
- **Kept as-is**: `data/papers/`, `data/tags.yaml`, workspaces, `metrics.db` (historical `llm` events simply stop growing), and `meta.json` fields such as `toc` / `l3_conclusion` / `translations` — they remain valid data

## 1. Repoint the repository

```bash
cd /path/to/scholaraio          # your existing deployment
git status --short              # make sure you know your local changes first
git remote set-url origin git@github.com:wszqkzqk/scrinium.git
git remote remove upstream      # drop the ZimoLiao upstream if present
git fetch origin
git switch main && git reset --hard origin/main   # or merge/rebase if you have local commits
```

`config.local.yaml` (API keys) is gitignored and survives untouched.

## 2. Reinstall the package (CLI renamed `scholaraio` → `scrinium`)

```bash
pip uninstall -y scholaraio
pip install -e ".[full]"        # or recreate your venv/conda env first
scrinium --version              # expect: scrinium 2.0.0 (3.0.0 on latest main — see the 3.0 section above)
```

## 3. Data history: nothing to migrate

Everything under `data/` and `workspace/` works as-is. On first use:

```bash
scrinium index                  # one-time FTS schema upgrade (adds the tags column)
scrinium search "<any query>"   # smoke test
scrinium tags                   # curated tag vocabulary intact
```

Runtime fallbacks (read-only, with a one-line warning) keep old locations working until you move them:

- `~/.scholaraio/config.yaml` is used when `~/.scrinium/config.yaml` does not exist
- `SCHOLARAIO_CONFIG` still works (`SCRINIUM_CONFIG` takes precedence)

## 4. Optional: rename the directory and keep agent history

Agent session stores key on the directory path. Rename safely with a symlink backstop:

```bash
mv ~/projects/scholaraio ~/projects/scrinium
ln -s scrinium ~/projects/scholaraio   # old path keeps resolving (also keeps .venv shebangs alive)
```

Then migrate each agent's records:

- **Kimi Code**: the session directory hash is `sha256(abs_path)[:16]`. Compute and rename:
  ```bash
  python3 -c "import hashlib; print(hashlib.sha256(b'/ABS/NEW/PATH/scrinium').hexdigest()[:16])"
  mv ~/.kimi-code/sessions/wd_scholaraio_<old_hash> ~/.kimi-code/sessions/wd_scrinium_<new_hash>
  ```
- **Claude Code**: rename the project dir slug, e.g. `mv ~/.claude/projects/-home-arch-projects-scholaraio ~/.claude/projects/-home-arch-projects-scrinium`
- **Codex / opencode**: records are date-keyed or DB-internal; nothing to do — old sessions remain in history.

If you recreate the virtualenv later, drop the symlink afterwards: shebangs inside `.venv/bin/` reference the old absolute path and resolve through it.

## 5. Verify

```bash
scrinium pending        # pending items visible
scrinium workspace list  # workspaces intact
scrinium tags           # tag vocabulary intact
```

Notes: the old GitHub repo (`wszqkzqk/scholaraio`) can be archived in its settings once every deployment has moved. If any deployment used plugin mode (`~/.scholaraio/`), the fallback above covers it; copy to `~/.scrinium/` when convenient.
