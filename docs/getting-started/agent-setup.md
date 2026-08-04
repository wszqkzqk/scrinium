# Agent Setup

Scrinium can be used in two different ways:

1. Open this repository directly with your coding agent.
2. Register Scrinium skills or tools so they are available from another project.

The right setup depends on which agent you use and whether it supports native skills or plugins.

## Start Here

| If you want to... | Recommended path |
|-------------------|------------------|
| Try Scrinium, inspect the codebase, or contribute | Open this repository directly |
| Use Scrinium from any project in Claude Code | Install the Claude Code plugin |
| Reuse Scrinium skills in Codex / OpenClaw | Clone the repo once, then symlink the skills into `~/.agents/skills/` |

## Open This Repository Directly

This is the simplest and most complete experience. You get the bundled instructions and local skills exactly as maintained in this repo.

```bash
git clone https://github.com/wszqkzqk/scrinium.git
cd scrinium
pip install -e ".[full]"
scrinium setup
```

`scrinium setup check` is the companion diagnostic command. It reports both the core setup state and optional advanced items such as Semantic Scholar / Zotero API keys. Current setup guidance prefers MinerU first whenever a MinerU path is available.

Then start your agent in the repository root:

| Agent | What happens in this repo |
|-------|----------------------------|
| Codex / OpenClaw / Cursor / Windsurf / Copilot / Cline / opencode / Kimi Code | Reads `AGENTS.md` natively; skills discovered via `.agents/skills/` or `.claude/skills/` |
| Claude Code | Reads `CLAUDE.md` (stub importing `AGENTS.md`) and loads `.claude/skills/` |
| Qwen Code | Reads `QWEN.md` (pointer to `AGENTS.md`) |

This mode is best when you want the full project context, not just the Scrinium skills.

## Claude Code Plugin

For Claude Code, Scrinium ships as a plugin with a marketplace entry — a managed install path (one of several ways to use the skills; direct repo open and symlinks work for any AGENTS.md-compatible agent).

Run these commands inside Claude Code as slash-commands, not in your system shell:

```text
/plugin marketplace add wszqkzqk/scrinium
/plugin install scrinium@scrinium-marketplace
```

After installation, start a new Claude Code session in your target project. Scrinium skills will be available with the `/scrinium:*` namespace, for example:

```text
/scrinium:search
/scrinium:show
/scrinium:workspace
```

### What the plugin sets up

When a new session starts for the first time, the SessionStart hook automatically:

1. Detects and installs the `scrinium` Python package
2. Creates the global config `~/.scrinium/config.yaml`
3. Creates the data directories under `~/.scrinium/data/`

In plugin mode, all data lives under `~/.scrinium/`:

```text
~/.scrinium/
├── config.yaml           # Global config (copied from the plugin bundle)
├── config.local.yaml     # API keys (created manually by the user or via the setup wizard)
├── data/
│   ├── papers/           # Ingested papers
│   ├── proceedings/      # Ingested proceedings volumes
│   ├── inbox/            # PDFs waiting for ingest
│   ├── inbox-thesis/     # Theses
│   ├── inbox-patent/     # Patents
│   ├── inbox-doc/        # Non-paper documents
│   ├── inbox-proceedings/ # Proceedings volumes waiting for dedicated ingest
│   ├── pending/          # Items awaiting confirmation
│   ├── explore/          # Literature exploration data (created on demand)
│   ├── index.db          # SQLite index
│   └── metrics.db        # Runtime metrics
└── workspace/            # Workspaces
```

The exact invocation form of skills depends on the host agent or plugin system; this repository only guarantees that skill definitions live in `.agents/skills/` and are exposed through the `.claude/skills` and `skills/` symlinks for different discovery mechanisms.

This is the recommended way to make Scrinium available outside this repository.

### Plugin packaging

The project is packaged as a Claude Code plugin plus marketplace entry:

```text
.claude-plugin/
├── plugin.json          # Plugin identity (name/version/description/keywords)
└── marketplace.json     # Marketplace catalog (used by /plugin marketplace add)
skills/ -> .claude/skills/  # Skill discovery entry point for the plugin system
hooks/hooks.json            # SessionStart hook (auto-installs dependencies + creates global config)
scripts/check-deps.sh       # Dependency detection / installation script invoked by the hook
```

Users can install it through `/plugin marketplace add wszqkzqk/scrinium`. Skill markets such as SkillsMP automatically index it by crawling GitHub for `filename:SKILL.md`.

Platform note: the SessionStart hook is a bash script, so it runs automatically on macOS and Linux. On native Windows the hook cannot execute; run `pip install -e ".[full]"` (or `pip install scrinium`) manually instead — the session itself is not blocked.

## Codex / OpenClaw Skill Registration

Codex-style agents can use Scrinium outside this repository through native skill discovery.

### One-time setup

Clone Scrinium somewhere stable:

```bash
git clone https://github.com/wszqkzqk/scrinium.git ~/.codex/scrinium
cd ~/.codex/scrinium
pip install -e ".[full]"
scrinium setup
```

Create a global skills symlink:

```bash
mkdir -p ~/.agents/skills
ln -s ~/.codex/scrinium/.claude/skills ~/.agents/skills/scrinium
```

Make config discovery explicit for cross-project use:

```bash
# Option A: keep Scrinium data rooted in the cloned repo
export SCRINIUM_CONFIG="$HOME/.codex/scrinium/config.yaml"

# Option B: move/copy the config into the global fallback location
mkdir -p ~/.scrinium
cp ~/.codex/scrinium/config.yaml ~/.scrinium/config.yaml
```

Without one of those two options, running `scrinium` from another project may fall back to defaults rooted in that current project and create `data/` plus `workspace/` there.

Restart Codex or OpenClaw after creating the symlink.

### Windows

Clone the repo somewhere stable first, for example:

```powershell
git clone https://github.com/wszqkzqk/scrinium.git "$env:USERPROFILE\.codex\scrinium"
cd "$env:USERPROFILE\.codex\scrinium"
pip install -e ".[full]"
scrinium setup
```

Two Windows-specific caveats:

- **Git symlinks**: `.claude/skills` and `skills` in the repository are git symlinks to `.agents/skills`. Windows checks out with `core.symlinks=false` by default, which turns them into plain text files and silently breaks those two skill discovery paths (the canonical `.agents/skills` is a real directory and always works). To fix: enable Developer Mode, run `git config core.symlinks true`, and re-checkout — or simply copy `.agents/skills` over those two locations manually.
- **Path length (MAX_PATH 260)**: paper directories use `Author-Year-Title` names that can get long. Clone to a shallow path (e.g. `C:\scrinium`) to stay clear of the Windows path length limit.

Then use a junction instead of a symlink:

```powershell
$repoRoot = "$env:USERPROFILE\.codex\scrinium"

New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.agents\skills"
cmd /c mklink /J "$env:USERPROFILE\.agents\skills\scrinium" "$repoRoot\.claude\skills"
```

For cross-project use on Windows, either set `SCRINIUM_CONFIG` to `"$repoRoot\config.yaml"` or copy that config to `$env:USERPROFILE\.scrinium\config.yaml`.

### What this gives you

- Global access to the Scrinium skill library
- Native discovery through `~/.agents/skills/`
- A setup path similar to other Codex skill packs

### Important limitation

This registers the skills, not the full repository instructions. If you want the agent to also read Scrinium's bundled project guidance, open this repository directly instead of only linking the skills.

## Which Path Should I Choose?

| Situation | Best choice |
|-----------|-------------|
| You are evaluating Scrinium itself | Open this repository directly |
| You want Scrinium in Claude Code across projects | Claude Code plugin |
| You want Scrinium skills in Codex / OpenClaw across projects | Global skill symlink |

## Verify the Setup

Use one of these checks after installation:

- In this repository: ask your agent to search or show a paper and confirm it can see Scrinium instructions or skills.
- In Claude Code plugin mode: verify `/scrinium:search` appears.
- In Codex / OpenClaw: restart the agent and ask it to use the `search` or `show` skill.

## Related Guides

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Docs Home](../index.md)
