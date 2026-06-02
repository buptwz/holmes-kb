# Holmes Quick Start

Complete this guide in under 10 minutes to go from zero to your first KB-backed troubleshooting session.

## Prerequisites

| Dependency | Version | Check |
|------------|---------|-------|
| git | ≥ 2.30 | `git --version` |
| Python | ≥ 3.11 | `python3 --version` |
| Bun | ≥ 1.3 | `bun --version` |
| OpenAI-compatible API key | — | (set in step 3) |

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

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --model gpt-4o \
  --api-key <your-api-key> \
  --api-base-url https://api.openai.com/v1
```

This writes:
- `~/.holmes/config.json` — API credentials and model
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

## Step 5: Save Knowledge After Resolution

After solving a problem, Holmes automatically saves it to pending. You then confirm:

```bash
# Review pending entries
holmes kb pending

# Confirm — records first EvidenceRecord, promotes maturity to 'verified'
holmes kb confirm <pending_id> --contributor <your-name>

# Reject if not useful
holmes kb reject <pending_id> --reason "duplicate of PT-DB-001"
```

At the **end of each session**, Holmes also runs `update-refs` automatically to record
which entries were referenced. This drives automatic maturity promotion:

```bash
# (Holmes runs this automatically; you can also run it manually)
holmes kb update-refs \
  --ids PT-DB-001,GL-002 \
  --session-id "session-$(date +%s)" \
  --contributor <your-name>
```

When an entry accumulates ≥ 2 distinct sessions from ≥ 2 distinct contributors,
it is automatically promoted from `verified` to `proven`.

## Step 6: Import Existing Documents

```bash
# Import a runbook, incident report, or any document:
holmes import ./my-runbook.md

# Dry run (preview only):
holmes import ./incident-report.txt --dry-run

# With explicit type:
holmes import ./dns-issue.md --type pitfall --category network
```

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
holmes setup                  # Configure KB path and model
holmes import <file>          # Import external document

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

# Governance
holmes kb update-refs --ids <id,...> --session-id <s> --contributor <c>
holmes kb decay               # Demote stale entries
holmes kb archive-orphans     # Remove orphaned drafts
holmes kb check-conflicts     # List contradiction: true entries

# Maintenance
holmes kb lint                # KB health check
holmes kb rebuild-index       # Rebuild index files
holmes kb merge               # Resolve git conflict markers
```
