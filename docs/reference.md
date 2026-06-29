# CLI Reference

Complete flag reference for all `holmes` commands.

---

## `holmes setup`

Configure KB path, LLM provider, and credentials.

```bash
holmes setup \
  --kb-path <path>          # KB root directory (required)
  --provider anthropic|openai
  --model <model-id>
  --api-key <key>
  --api-base-url <url>      # OpenAI-compatible endpoint (optional)
```

Writes `~/.holmes/config.json`, `~/.holmes/settings.json`, and KB-side `CLAUDE.md`.

**Provider reference:**

| `--provider` | Compatible services |
|---|---|
| `anthropic` (default) | Anthropic API (`sk-ant-...` key) |
| `openai` | OpenAI, Azure OpenAI, Ollama, any OpenAI-compatible endpoint |

---

## `holmes start`

Start the KB MCP server.

```bash
holmes start
  --port <n>          # HTTP port (default: 8765)
  --kb-path <path>    # Override configured KB path
```

MCP client config: `{ "url": "http://localhost:<port>" }`

---

## `holmes import`

Import a document via autonomous LLM pipeline.

```bash
holmes import <file>
  --type pitfall|model|guideline|process|decision   # Override LLM classification
  --category <category>   # Override category
  --dry-run               # Preview without writing files
  --no-interactive        # Suppress all prompts (CI-safe)
  --verbose               # Show per-field reasoning trace
  --force                 # Re-import even if source_hash matches (skip dedup)
  --retry-entry <node_id> # Retry a single failed node (DAG pipeline only)

holmes import --dir <directory>   # Batch import all .md/.txt/.rst files
holmes import -                   # Read from stdin
```

**Output:**
```
✓ 1 created, 0 updated, 0 skipped | skill: 1 generated, 0 linked
```

---

## `holmes config`

```bash
holmes config init                    # Interactive setup wizard
holmes config show                    # View current config
holmes config set <key> <value>       # Update a single field
  # e.g.: holmes config set model claude-opus-4-6
```

---

## `holmes kb`

### Read

```bash
holmes kb overview                    # KB structure overview
holmes kb list                        # List all entries
  --type <type>                       # Filter by entry type
  --category <category>               # Filter by category
holmes kb show <id>                   # Full entry content
holmes kb search <query>              # Full-text search
holmes kb history <id>                # List .history/ snapshots for an entry
  --json                              # JSON output
```

### Pending / Write

```bash
holmes kb pending                     # List pending entries
  --json                              # JSON output
  <entry_id>                          # Show a specific pending entry

holmes kb approve <id>                # Move from _pending/ to confirmed space
  --no-interactive                    # Skip confirmation prompt (CI-safe)
  # Pitfall roots: cascades to entire tree atomically

holmes kb confirm <id>                # 3-gate validation + publish (legacy pending)
  --contributor <name>                # Record confirmer identity

holmes kb reject <id>                 # Discard pending entry
  --reason "<text>"                   # Optional rejection reason

holmes kb delete <id>                 # Soft delete — moves to _trash/
  --no-cascade                        # Don't cascade to child entries
  --force                             # Skip confirmation prompt

holmes kb write-pending               # Submit a correction for an existing entry
  --corrects <entry_id>
  --content "$(cat corrected.md)"
```

### Governance

```bash
holmes kb decay                       # Demote stale entries + save snapshots
  --dry-run                           # Preview without writing
  --type <type>                       # Scope to one entry type

holmes kb archive-orphans             # Move evidence-empty drafts to archive
holmes kb check-conflicts             # List entries with contradiction: true
```

### Maintenance

```bash
holmes kb lint                        # KB health check (missing fields, broken refs)
holmes kb rebuild-index               # Rebuild index.json and _index.md files
holmes kb merge                       # Resolve git conflict markers in entry files
```

---

## `holmes session`

```bash
holmes session list                   # All sessions (most recent first)
  --status active|resolved|abandoned  # Filter by status
holmes session show <id>              # View messages for a session
```

---

## Entry Format

```markdown
---
id: PT-DB-001
type: pitfall
title: "Redis Connection Pool Exhausted"
maturity: verified
category: database
tags: [redis, connection-pool, timeout]
created_at: "2026-03-15T08:00:00Z"
updated_at: "2026-03-15T08:00:00Z"
contributors: [alice]
source_hash: a3f8c1d2e4b79062    # set by import agent (idempotency key)
import_confidence: 0.94           # LLM confidence at import time
skill_refs: [check-redis-pool]    # linked skills
---

## Symptoms
...

## Root Cause
...

## Resolution
...
```

**Required frontmatter fields:** `id`, `type`, `title`, `maturity`

**Pitfall-specific required fields:** `category`

---

## Maturity Rules

| Level | Condition | Auto-decay trigger |
|-------|-----------|-------------------|
| `draft` | 0 evidence records | — |
| `verified` | 1+ evidence records | Drop to `draft` after 6 months without new evidence |
| `proven` | 2+ sessions AND 2+ contributors | Drop to `verified` after 12 months without new evidence |

Run `holmes kb decay` (or schedule as a cron job) to apply demotions.
A `.history/` snapshot is saved before each demotion.

---

## Configuration File Reference

**`~/.holmes/config.json`**

```json
{
  "kb_path": "/home/alice/holmes-kb",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "api_key": "sk-ant-...",
  "api_base_url": null
}
```

**`~/.holmes/settings.json`**

```json
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```
