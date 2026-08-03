# Migrating from ScholarAIO (fork upgrade)

Scrinium 2.0.0 is a hard fork of ScholarAIO 1.3.0. All user data formats are unchanged, so **your library, notes, tags, metrics, and workspaces carry over with zero conversion** — the upgrade is about repointing the git remote, the CLI name, and (optionally) the directory name and agent session records.

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
scrinium --version              # expect: scrinium 2.0.0
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
- `SCHOLARAIO_*` environment variables still work (`SCRINIUM_*` takes precedence)
- `~/.cache/scholaraio` GPU profile is read as a fallback

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
