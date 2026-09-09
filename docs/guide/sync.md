# Cross-Device Sync (`scrinium sync`)

Synchronize the knowledge base (`data/`) and workspaces (`workspace/`) between Scrinium instances on different devices. Everything is included: full text (`paper.md`, `paper.pdf`, `images/`, `notes.md`), metadata (`meta.json`), the tag vocabulary (`tags.yaml`), the index (`index.db`), and workspace definitions (`papers.json`).

> `scrinium export` / `scrinium import` handle citation formats (BibTeX/RIS/Markdown/DOCX) and external imports (Endnote/Zotero) — they cannot sync the knowledge base itself.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `scrinium sync push <target>` | Push `data/` + `workspace/` to the target |
| `scrinium sync pull <target>` | Pull from the target into the local instance |
| `scrinium sync status <target>` | Show what would change (dry-run, no changes made) |
| `scrinium sync export <file.tar.gz>` | Pack into an archive (offline / cloud-drive / USB transfer) |
| `scrinium sync import <file.tar.gz>` | Import from an archive |

## Target Formats

- SSH: `user@host:remote/path/to/scrinium` (e.g. `wm2:~/scrinium`)
- Local path: `/path/to/other/scrinium` (a second instance on the same machine or a shared drive)

## Sync Semantics

- **Default `--update` (safe)**: copies only files that are newer on the source or missing on the target, and **never deletes anything**. No data loss.
- **`--mirror`**: deletes target files that do not exist on the source. Runs a dry-run preview of the deletions first and requires `--yes` to confirm.
- **`status`**: dry-run; lists the files that would change without executing.

## Exclusions (never synced by default)

- `data/inbox*` (staging areas)
- `*.log`, `scholaraio.log*`, `metrics.db`, `.coverage`
- `__pycache__/`, `.DS_Store`, `trash/`, `topic_model/`

`index.db` is optional to transfer (the target can rebuild it with `scrinium index`), but transferring it saves the rebuild.

## Examples

```bash
# Push from laptop to cluster
scrinium sync push wm2:~/scrinium

# Pull from cluster
scrinium sync pull wm2:~/scrinium

# Preview changes first
scrinium sync status wm2:~/scrinium

# Offline transfer
scrinium sync export sync_backup.tar.gz
# after copying sync_backup.tar.gz to the other device:
scrinium sync import sync_backup.tar.gz
```

## Notes

- This is **file-level sync**: `meta.json` conflicts are resolved by file mtime (newer wins); there is no field-level merge.
- When the same file is edited on both sides, the later write wins. If you need two-way editing, put `data/` and `workspace/` under git instead.
