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

Import a document via three-phase LLM pipeline (Classifier → Summarizer → Generator).
One document = one KB entry.

```bash
holmes import <file>
  --type pitfall|model|guideline|process|decision   # Override LLM classification
  --category <category>   # Override category
  --dry-run               # Preview classification without writing files
  --no-interactive        # Suppress all prompts (CI-safe)
  --verbose               # Show per-field reasoning trace
  --force                 # Skip duplicate check

holmes import --dir <directory>   # Batch import all .md/.txt/.rst files
holmes import -                   # Read from stdin
```

**Output:**
```
✓ 1 created, 0 skipped
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

## `holmes overview`

KB structure overview — types, categories, entry counts, maturity distribution.

```bash
holmes overview
  --json               # JSON output
```

---

## `holmes search`

Full-text search across all entries.

```bash
holmes search <query>
```

---

## `holmes pending`

List pending entries awaiting review.

```bash
holmes pending
  --json               # JSON output
```

---

## `holmes approve`

Move a pending entry from `_pending/` to the confirmed KB space.

```bash
holmes approve <id>
  --no-interactive     # Skip confirmation prompt (CI-safe)
```

---

## `holmes delete`

Remove an entry.

```bash
holmes delete <id>
  --force              # Skip confirmation prompt
```

---

## `holmes show`

Read a specific entry's full content.

```bash
holmes show <id>
```

---

## `holmes decay`

Demote stale entries and archive old drafts. Saves `.history/` snapshots before each change.

```bash
holmes decay
  --dry-run            # Preview without writing
  --type <type>        # Scope to one entry type
```

Decay rules:
- `proven` → `verified` after 12 months without reference
- `verified` → `draft` after 6 months without reference
- `draft` → archived after 30 days age + 3 months without reference

---

## `holmes doctor`

KB health check — detect stale drafts, decay candidates, orphan entries, lifecycle issues.

```bash
holmes doctor
  --verbose            # Show detailed findings
```

---

## `holmes history`

List `.history/` snapshots for an entry.

```bash
holmes history <id>
  --json               # JSON output
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
brief: "Redis maxclients too low causes connection timeout under load"
created_at: "2026-03-15T08:00:00Z"
updated_at: "2026-03-15T08:00:00Z"
contributors: [alice]
source_hash: a3f8c1d2e4b79062    # set by import pipeline (idempotency key)
---

## Symptoms
...

## Root Cause
...

## Resolution
...
```

**Required frontmatter fields:** `id`, `type`, `title`, `maturity`, `category`, `tags`, `created_at`, `updated_at`

---

## Maturity Rules

| Level | Condition | Auto-decay trigger |
|-------|-----------|-------------------|
| `draft` | 0 solved evidence records | Archived after 30 days age + 3 months stale |
| `verified` | 1+ confirmed resolutions | Drop to `draft` after 6 months without reference |
| `proven` | 2+ sessions AND 2+ contributors | Drop to `verified` after 12 months without reference |

Run `holmes decay` (or schedule as a cron job) to apply demotions.
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
