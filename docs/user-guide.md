# Holmes User Guide

## Overview

Holmes is an AI-powered troubleshooting agent backed by a shared knowledge base.
It helps you diagnose and resolve technical problems, and automatically captures
solutions for future use.

## Usage

### Starting Holmes

Holmes exposes the KB as an MCP server for use with any MCP-compatible AI agent:

```bash
holmes start              # Start MCP server on port 8765
holmes start --port 9000  # Custom port
```

MCP client config: `{ "url": "http://localhost:8765" }`

### Importing Knowledge

```bash
holmes import ./incident-report.md    # Import a document
holmes import --dir ./postmortems/    # Batch import
holmes import ./doc.md --dry-run      # Preview without writing
```

### Session Navigation

| Key | Action |
|-----|--------|
| Ctrl+H | Open session history list |
| Ctrl+K | Open knowledge base browser |
| Ctrl+R | Mark session resolved and extract knowledge |

### Tool Confirmations

When Holmes wants to execute a write operation or shell command, a confirmation
dialog appears:

- **[y]** — Allow the tool to execute
- **[n] or Esc** — Deny (session continues, Holmes adapts)

### Confirming KB Knowledge

After a KB entry helps resolve your issue:

- Ask Holmes: "That fixed it — please confirm the KB entry helped."
- Holmes calls `kb_confirm` to record evidence. No action needed from you.

### Saving New Knowledge

After successfully troubleshooting a problem with no matching KB entry:

1. Ask Holmes: "Please save this solution to the KB."
2. Holmes calls `kb_draft` to save a draft.
3. Run `holmes import _drafts/<file>` to structure it, then `holmes approve <id>` to publish.

## CLI Reference

### Config

```bash
holmes setup --kb-path ~/holmes-kb --model gpt-4o   # Initial setup
holmes config show              # View current config
holmes config set model claude-sonnet-4-6
```

### MCP Server

`holmes start` exposes the KB as an MCP server over streamable-http. Any MCP-compatible
AI agent (e.g. Claude, GPT-4o via MCP client) can then call `kb_browse`,
`kb_read`, `kb_confirm`, and `kb_draft` directly.

```bash
holmes start                    # Default: port 8765, KB from config
holmes start --port 9000        # Custom port
holmes start --kb-path ~/my-kb  # Override KB path
```

MCP client config:
```json
{ "url": "http://localhost:8765" }
```

### LLM Provider Configuration

`holmes setup` selects which LLM backend `holmes import` uses. Two provider types are supported.

#### Anthropic (default)

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider anthropic \
  --model claude-3-5-sonnet-20241022 \
  --api-key <anthropic-api-key>
```

#### OpenAI-compatible

Covers OpenAI, Azure OpenAI, Ollama, and any endpoint that implements the OpenAI chat completions API.

```bash
# Standard OpenAI
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --model gpt-4o \
  --api-key <openai-api-key>

# Azure OpenAI (requires custom base URL + Azure API key)
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --model gpt-4o \
  --api-key <azure-api-key> \
  --api-base-url https://<resource>.openai.azure.com/

# Local Ollama (use any non-empty string as api-key; Ollama ignores it)
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --model llama3.1:8b-instruct-q4_K_M \
  --api-key ollama \
  --api-base-url http://localhost:11434/v1
```

#### Provider reference

| `--provider` | Compatible services | Notes |
|---|---|---|
| `anthropic` (default) | Anthropic API | Requires an `sk-ant-…` key |
| `openai` | OpenAI, Azure OpenAI, Ollama, any OpenAI-compatible endpoint | Set `--api-base-url` to override the default OpenAI endpoint |

The provider and credentials are stored in `~/.holmes/config.json`. Re-run `holmes setup` at any time to switch providers or update credentials — all subsequent `holmes import` calls use the latest configuration.

#### Switching providers

```bash
# Currently using Anthropic; switch to OpenAI
holmes setup --kb-path ~/holmes-kb --provider openai \
  --model gpt-4o --api-key <openai-key>
```

#### Error messages

If the API key is missing or invalid, the error message names the configured provider so you can diagnose key-type mismatches quickly:

```
Error: LLM not configured. Run 'holmes setup --provider anthropic --api-key <API_KEY>'
       (requires anthropic key for import agent)
```

### Observability (Langfuse)

Holmes supports optional [Langfuse](https://langfuse.com) integration for tracing
the import pipeline. Disabled by default — no impact on normal usage.

**Setup:**

```bash
# 1. Install the observability dependency
pip install -e ".[observability]"

# 2. Start a Langfuse instance (self-hosted or use Langfuse Cloud)
docker compose -f langfuse/docker-compose.yml up -d
# Then visit http://localhost:3000 to create a project and get keys

# 3. Configure connection
holmes config set langfuse_host http://localhost:3000
holmes config set langfuse_public_key pk-lf-...
holmes config set langfuse_secret_key sk-lf-...

# 4. Enable
holmes config set langfuse_enabled true
```

Once enabled, every `holmes import` produces a trace visible in the Langfuse UI:
each pipeline phase (Classifier, Summarizer, Generator) and every LLM call with
full prompt, response, token count, and latency.

**Disable** (keeps credentials for later):

```bash
holmes config set langfuse_enabled false
```

### Knowledge Import

`holmes import` runs an **autonomous agent pipeline** powered by your configured LLM provider.
The agent classifies the document, checks for semantic duplicates, self-verifies the
draft entry, writes it to pending, and evaluates whether a skill should be generated —
all in a single tool-use loop with a full audit trail in the `ImportReport`.

```bash
# Single file
holmes import <file>                        # Auto-classify and import
holmes import <file> --type pitfall         # Override entry type
holmes import <file> --category network     # Override category
holmes import <file> --dry-run              # Preview without writing files
holmes import <file> --no-interactive       # Suppress all confirmation gates
holmes import <file> --verbose              # Show per-decision reasoning trace

# Batch (all .md/.txt/.rst in a directory)
holmes import --dir ./incidents/

# Stdin
cat incident.txt | holmes import -
```

**Output format**

```
✓ 1 created, 0 updated, 0 skipped | skill: 1 generated, 0 linked
```

Or with `--verbose`:
```
  [Redis Connection Timeout] confidence: 0.94
    title  ← "Redis connection timeouts observed during peak hours"
    root_cause  ← "Connection pool exhaustion under load"
    skill  ← RECOMMENDED: 4 steps detected
```

**Dry-run without LLM**

If no API key is configured and no `--type` is provided, the command shows a hint
and exits without calling the LLM:
```
LLM not configured. To preview the import plan without an LLM, provide --type
(e.g., --type pitfall). To configure LLM: holmes setup --provider anthropic --api-key <API_KEY>
```

If an API key is missing but `--type` was supplied (or in non-dry-run mode), the error names
the configured provider:
```
Error: LLM not configured. Run 'holmes setup --provider openai --api-key <API_KEY>'
       (requires openai key for import agent)
```

**Idempotency**: A SHA-256 `source_hash` is embedded in every imported entry.
Re-importing the same file is a no-op — the agent detects the duplicate and skips.

### Knowledge Base Management

```bash
# --- Read ---
holmes overview                 # KB overview + index summary
holmes list                     # List all entries
holmes list --type pitfall      # Filter by type
holmes show <id>                # Show full entry
holmes search <query>           # Full-text search
holmes history <id>             # List version snapshots for an entry
holmes history <id> --json      # JSON output

# --- Write (via pending / approval) ---
holmes pending                  # List pending entries
holmes approve <id>             # Approve a pending entry
holmes delete <id>              # Soft-delete (moves to _trash/)

# --- Governance ---
holmes decay                    # Demote stale entries + save snapshots
holmes decay --dry-run          # Preview changes only
holmes decay --type pitfall     # Scope to one entry type
holmes archive-orphans          # Move evidence-empty drafts to archive

# --- Maintenance ---
holmes doctor                   # Self-diagnostic
holmes doctor --fix             # Auto-fix safe issues
holmes lint                     # Health check
holmes rebuild-index            # Rebuild index.json + _index.md files
```

### Skill Management

Skills are agent instruction packages stored in `{kb_root}/skills/<name>/SKILL.md`. The import
pipeline auto-creates them when a Resolution section has ≥ 3 distinct command steps. The skill
name is derived from the entry title as a kebab-case slug.

```bash
# List skills
holmes list --type skill

# Read a skill
holmes show <skill-name>
```

To create a skill manually, create `{kb_root}/skills/<name>/SKILL.md`:

```markdown
---
name: check-redis-pool
description: Diagnose and recover Redis connection pool exhaustion
---

Check current pool status and restore connections...
```

**Skill quality curation** (run automatically after each import, advisory only):

| Finding type | Condition | Action suggested |
|---|---|---|
| `merge_candidate` | Description Jaccard similarity > 0.6 | Merge the two skills |
| `oversized` | SKILL.md body > 3 000 chars | Split or trim content |
| `update_candidate` | `patch_count=0` and linked entry updated after skill created | Review and update skill |

### Session Management

```bash
holmes session list             # All sessions
holmes session list --status resolved
holmes session show <id>        # View session messages
```

## Persistent Memory

Holmes loads two memory files at the start of each session:

1. **`{kb_root}/HOLMES.md`** — Project-specific context (shared, in KB repo)
2. **`~/.holmes/MEMORY.md`** — Your personal preferences (local)

To edit project context, edit `{kb_root}/HOLMES.md` directly.

## Knowledge Base Structure

```
{kb_root}/
├── README.md              # Overview (human-maintained, ~50 lines)
├── CHANGELOG.md           # Auto-appended change log
├── index.json             # Machine-readable index (auto-generated)
├── .history/              # VersionSnapshots — created on correction or decay
│   └── PT-DB-001-20260601-143022.md
├── pitfall/               # Fault patterns & troubleshooting steps
│   ├── _index.md
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── model/                 # Entity definitions
├── guideline/             # Best practices
├── process/               # Operational workflows
├── decision/              # Architecture decisions
├── _pending/              # Entries awaiting approval (holmes approve <id>)
│   └── pitfall/database/
├── _drafts/               # Raw notes saved by kb_draft (holmes import _drafts/<file>)
├── _trash/                # Soft-deleted entries (recoverable via git checkout)
├── skills/                # Reusable agent instruction packages
│   └── my-skill/
│       └── SKILL.md               # Frontmatter + agent instructions
└── contributions/
    ├── archive/           # Orphaned drafts (moved by archive-orphans)
    └── log.md             # All contribution events
```

### Knowledge Entry Format

```markdown
---
id: PT-DB-001
type: pitfall
title: PostgreSQL connection pool exhaustion
maturity: verified
category: database
tags: [postgresql, connection-pool, performance]
evidence: []                   # legacy field — new records go to contributions/evidence/
contributors: [alice]
created_at: 2026-05-26T10:00:00Z
updated_at: 2026-05-26T10:00:00Z
source_hash: a3f8c1d2e4b79062   # set by import agent (idempotency key)
brief: Connection pool exhaustion under heavy load  # one-line summary for kb_browse
---

## Symptoms
- Application logs show "connection pool exhausted"
- Database connections at max_connections limit

## Root Cause
Long-running transactions holding connections

## Resolution
1. Check active connections: `SELECT count(*) FROM pg_stat_activity`
2. Kill long-running transactions
3. Adjust pool size in application config
```

### Maturity Levels

Maturity is **derived automatically** from the evidence records — it is not set manually.

| Level | Rule | Meaning |
|-------|------|---------|
| `draft` | 0 evidence records | Newly added, unconfirmed |
| `verified` | ≥ 1 record | Seen and confirmed by at least one person |
| `proven` | ≥ 2 distinct sessions **and** ≥ 2 distinct contributors | Independently validated by multiple people |

**Auto-decay thresholds** (configurable in `kb-config.yml`):

| Demotion | Condition |
|----------|-----------|
| `proven` → `verified` | Last evidence > 12 months ago |
| `verified` → `draft` | Last evidence > 6 months ago |

Run `holmes decay` (or schedule it as a cron job) to apply demotions. A VersionSnapshot is saved to `.history/` before each demotion.

### Correcting a Verified Entry

Do **not** edit the file directly and push. Use the correction workflow:

```bash
# 1. Submit a correction proposal
holmes write-pending \
  --corrects PT-DB-001 \
  --content "$(cat corrected-entry.md)"

# 2. Review, then approve
holmes approve <pending_id>
# → saves .history/PT-DB-001-<timestamp>.md, replaces original, preserves evidence
```

## Git Workflow for Shared KB

```bash
cd ~/holmes-kb
git pull --rebase origin main   # Get latest
# ... add/confirm entries ...
git add .
git commit -m "Add: PT-NET-001 DNS resolution failure pattern"
git push origin main            # Share with team
```

**Evidence records are conflict-free.** Each `kb_confirm` MCP tool call appends an
evidence record to the entry's frontmatter under `evidence:` —
file additions never conflict in git, so concurrent confirmations from different
contributors merge automatically.

Entry `.md` files may still have trivial conflicts (e.g., `maturity` field) if two branches
independently promote the same entry. These are one-line conflicts and easy to resolve.
