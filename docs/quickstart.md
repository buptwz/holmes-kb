# Holmes Quick Start

Complete this guide in under 10 minutes to go from zero to your first KB-backed troubleshooting session.

## Prerequisites

| Dependency | Version | Check |
|------------|---------|-------|
| git | ≥ 2.30 | `git --version` |
| Python | ≥ 3.11 | `python3 --version` |
| Bun | ≥ 1.3 | `bun --version` |
| LLM API key (Anthropic or OpenAI-compatible) | — | (set in step 3) |

Install Bun if missing:
```bash
curl -fsSL https://bun.sh/install | bash
```

## Step 1: Clone and Install

```bash
git clone <holmes-repo-url> ~/holmes-src
cd ~/holmes-src

# Install Python KB CLI
pip install -e kb/

# Build and install TypeScript TUI
cd agent   # the claude-code fork directory
bun install
bun run build
ln -sf "$(pwd)/dist/cli-bun.js" ~/.bun/bin/holmes-agent

# Verify both tools are available
holmes --help
holmes-agent --version
```

## Step 2: Clone (or Create) a Knowledge Base

```bash
# Option A: Use the shared team KB
git clone <kb-repo-url> ~/holmes-kb

# Option B: Start a fresh personal KB from the template
cp -r ~/holmes-src/kb-template ~/holmes-kb
cd ~/holmes-kb && git init && git add . && git commit -m "init KB"
```

## Step 3: Run Setup (one command)

Choose your LLM provider:

**Anthropic** (claude models):
```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider anthropic \
  --model claude-3-5-sonnet-20241022 \
  --api-key <your-anthropic-api-key>
```

**OpenAI** (GPT models, Azure, Ollama, or any OpenAI-compatible endpoint):
```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --model gpt-4o \
  --api-key <your-api-key> \
  --api-base-url https://api.openai.com/v1   # omit for default OpenAI endpoint
```

> To switch providers later, simply re-run `holmes setup` with `--provider <new-provider>`.

This writes:
- `~/.holmes/config.json` — provider, API credentials, and model
- `~/.holmes/settings.json` — KB path and tool permissions
- `~/holmes-kb/CLAUDE.md` — agent system prompt
- `~/.holmes/CLAUDE.md` — fallback system prompt

## Step 4: Start Troubleshooting

```bash
cd ~/holmes-kb
holmes-agent
```

Type your problem and press **Enter**. Holmes will:
1. Call `KbReadOverview` to inspect the KB
2. Call `KbSearch` with your symptoms
3. Read matching entries and synthesize an answer

## Step 5: Save and Confirm Knowledge

**Confirming that an existing KB entry helped** — when Holmes reads a KB entry and it
resolves your issue, ask Holmes to confirm it:

> "That fixed it — please confirm the KB entry helped."

Holmes calls `kb_confirm_entry` to write an evidence record. When an entry accumulates
≥ 2 distinct sessions from ≥ 2 distinct contributors, it is automatically promoted
from `verified` to `proven`.

**Submitting a new entry** — when the issue has no matching KB entry, Holmes will ask
to save the solution. After saving, confirm it as an official entry:

```bash
# Review pending entries
holmes kb pending

# Confirm — records first evidence record, promotes maturity to 'verified'
holmes kb confirm <pending_id>

# Reject if not useful
holmes kb reject <pending_id> --reason "duplicate of PT-DB-001"
```

## Step 6: Import Existing Documents

`holmes import` uses an autonomous agent loop to classify, verify, and write each entry.
It checks for duplicates automatically and evaluates whether a reusable skill should be created.

```bash
# Import a runbook, incident report, or any document:
holmes import ./my-runbook.md

# Dry run (preview planned actions, no files written):
holmes import ./incident-report.txt --dry-run

# With explicit type override:
holmes import ./dns-issue.md --type pitfall --category network

# Batch import — all .md/.txt/.rst files in a directory:
holmes import --dir ./incidents/

# Non-interactive mode (CI / pipelines, no prompts):
holmes import ./incident.md --no-interactive

# Verbose mode (show per-field classification trace):
holmes import ./incident.md --verbose
```

The output shows a one-line summary:
```
✓ 1 created, 0 updated, 0 skipped | skill: 1 generated, 0 linked
```

Importing the same file twice is safe — the agent detects the existing `source_hash` and skips it.

## Step 7: Share with Your Team

```bash
cd ~/holmes-kb
git add .
git commit -m "Add PT-DB-001: Redis connection pool exhaustion"
git push origin main

# Sync after others push:
git pull --rebase origin main
# Evidence sidecar files (contributions/evidence/) auto-merge.
# For any structural conflicts: holmes kb merge
```

## Step 8: Maintain the KB (optional, periodic)

```bash
# Demote entries with stale evidence (proven > 12mo, verified > 6mo)
holmes kb decay --dry-run    # preview
holmes kb decay              # apply demotions + save snapshots

# Move draft entries that have never been evidenced
holmes kb archive-orphans

# See an entry's history (corrections, decay events)
holmes kb history PT-DB-001
```

## Key CLI Commands

```bash
# Setup & import
holmes setup                          # Configure KB path and model
holmes import <file>                  # Import via autonomous agent pipeline
holmes import <file> --dry-run        # Preview without writing
holmes import <file> --no-interactive # Suppress prompts (CI-friendly)
holmes import --dir <dir>             # Batch import a directory

# MCP server (for AI agents / MCP clients)
holmes start                          # Start KB MCP server on port 8765
holmes start --port 9000              # Custom port
holmes start --kb-path ~/holmes-kb    # Override KB path

# Read
holmes kb overview            # KB overview and index
holmes kb search <query>      # Full-text search
holmes kb show <id>           # Read a specific entry
holmes kb list                # List all entries
holmes kb history <id>        # List version snapshots for an entry

# Write (via pending)
holmes kb pending             # List pending entries
holmes kb confirm <id>        # 3-gate confirmation (adds first evidence)
holmes kb reject <id>         # Reject a pending entry

# Skills
holmes kb skill detect-commands --content "..."   # Detect runbook steps
holmes kb skill manage create <name> --description "..."
holmes kb skill manage edit <name>
holmes kb skill manage patch <name> --field description --value "..."
holmes kb skill manage delete <name>

# Governance
holmes kb decay               # Demote stale entries
holmes kb archive-orphans     # Remove orphaned drafts
holmes kb check-conflicts     # List contradiction: true entries

# Maintenance
holmes kb lint                # KB health check
holmes kb rebuild-index       # Rebuild index files
holmes kb merge               # Resolve git conflict markers
```
