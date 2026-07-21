# CLI Reference

Complete flag reference for all `holmes` commands.

All management commands are top-level (`holmes approve`, `holmes pending`, ...).
The legacy `holmes kb <cmd>` form still works as a hidden alias for one version cycle.

Global option: `--kb-path <path>` (or env `HOLMES_KB_PATH`) — placed **before** the
subcommand, e.g. `holmes --kb-path ~/my-kb list`.

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

Start the KB MCP server (streamable-http transport).

```bash
holmes start
  --port <n>              # HTTP port (default: 8765)
  --mode local|central    # local (default): loopback, no auth, git-config identity fallback
                          # central: shared server, bearer token auth, contributor enforced
  --host <addr>           # Bind interface (default: 127.0.0.1 local, 0.0.0.0 central)
```

Central mode requires a token first:

```bash
holmes config set mcp_token <token>
holmes start --mode central
```

MCP client config: `{ "url": "http://localhost:<port>" }`
(central mode: add an `Authorization: Bearer <token>` header).

---

## `holmes import`

Import a document via three-phase LLM pipeline (Classifier → Summarizer → Generator).
One document = one KB entry, written to `contributions/pending/`.
Requires `holmes config set username <name>` first.

```bash
holmes import <file>
  --type pitfall|model|guideline|process|decision   # Override LLM classification
  --category <category>   # Override category
  --title <title>         # Override LLM-generated title
  --tags <a,b,c>          # Comma-separated tags (overrides LLM output)
  --dry-run               # Preview without writing files
  --no-interactive        # Suppress all prompts (CI-safe)
  --verbose               # Show per-decision reasoning trace
  --force                 # Skip duplicate pending check

holmes import --dir <directory>   # Batch import all .md/.txt/.rst files
holmes import -                   # Read from stdin
```

---

## `holmes config`

```bash
holmes config show                    # View current config (JSON)
holmes config set <key> <value>       # Update a single field
  # e.g.: holmes config set model claude-opus-4-6
```

Settable keys: `kb_path`, `model`, `api_key`, `api_base_url`, `username`, `mcp_token`,
`langfuse_enabled`, `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host`.

---

## Read commands

### `holmes overview`

KB overview — README + total entry count.

```bash
holmes overview [--json]
```

### `holmes search`

Full-text search across all entries (BM25; ties broken by evidence freshness).

```bash
holmes search <query>
  --limit <n>        # Max results (default: 5)
  --type <type>      # Filter by entry type
  --all              # Include deprecated entries and process sub-entries
  --json             # JSON output
```

### `holmes list`

List entries from the index.

```bash
holmes list
  --type <type>           # Filter by entry type
  --category <category>   # Filter by category
  --query <keyword>       # Keyword filter (title and tags)
  --maturity <level>      # draft | verified | proven
  --limit <n>             # Max entries (0 = unlimited)
  --offset <n>            # Skip first N entries
  --format table|json|id-only
  --all                   # Include deprecated entries
  --all-types             # Include process sub-entries
```

### `holmes show`

Read a specific entry's full content.

```bash
holmes show <id>
  --json
  --with-evidence    # Evidence summary (sessions, contributors, last date)
```

### `holmes read-category`

Print the `_index.md` for an entry type.

```bash
holmes read-category pitfall [--json]
```

### `holmes history`

List `.history/` snapshots for an entry.

```bash
holmes history <id>
  --json
  --show <snapshot-file>   # Print full content of one snapshot
```

---

## Pending workflow

### `holmes pending`

List pending entries awaiting review (grouped by category).

```bash
holmes pending
  --json
  --show <pending-id>   # Print full content of one pending entry
```

### `holmes approve`

Publish a pending entry from `contributions/pending/` to the confirmed KB space.

Flow: detect same-source old entries → semantic dedup gate (LLM, human-confirmed) →
mint permanent ID (`PT-DB-a3f8c2` style; old temporary ID recorded in `former_id`) →
rebuild index.

```bash
holmes approve <pending-id>
  --no-interactive   # Skip all confirmation prompts (CI-safe)
  --skip-dedup       # Skip the semantic dedup gate
```

### `holmes confirm`

3-gate confirm for hand-written pending entries and correction proposals:
schema validation → duplicate check → forced preview → promote to KB.
For correction proposals (`corrects: <id>`), replaces the original entry and saves a
VersionSnapshot to `.history/`.

```bash
holmes confirm <pending-id>
  --force                 # Skip duplicate check
  --type <type>           # Override entry type
  --category <category>   # Override category
  --contributor <name>    # Contributor recorded in the first evidence record
```

### `holmes reject`

Reject and delete a pending entry.

```bash
holmes reject <pending-id> [--reason <text>] [--force]
holmes reject --stale-days <n> [--dry-run] [--force]   # Batch reject stale pending
```

### `holmes write-pending`

Write content directly to the pending area.

```bash
holmes write-pending --content <markdown> | --file <path>
  --corrects <entry-id>   # Submit as a correction proposal for an existing entry
```

### `holmes amend-pending`

Replace a pending entry's content, preserving system metadata.

```bash
holmes amend-pending <pending-id> --content <markdown> | --file <path>
```

### `holmes drafts`

List draft documents in `_drafts/` waiting to be imported.

---

## Entry lifecycle

### `holmes delete`

Soft-delete an entry (moves it to `_trash/`; recoverable via `git checkout`).

```bash
holmes delete <id> [--force]
```

### `holmes update-refs`

Batch-append `solved` evidence records at session end (drives maturity promotion).

```bash
holmes update-refs --ids <id1,id2> --session-id <uuid> --contributor <name>
  [--project <p>] [--context <text>]
```

---

## Governance

### `holmes decay`

Demote stale entries; archive old stale drafts. Saves `.history/` snapshots and writes
a system `decayed` evidence record per demotion.

```bash
holmes decay
  --dry-run            # Preview without writing
  --type <type>        # Scope to one entry type
  --json
```

Decay rules (thresholds configurable in `kb-config.yml`):
- `proven` → `verified` after 12 months without reference
- `verified` → `draft` after 6 months without reference
- `draft` → archived after 30 days age + 3 months without reference

### `holmes archive-orphans`

Move evidence-empty draft entries to `contributions/archive/`.

```bash
holmes archive-orphans [--dry-run] [--json]
```

### `holmes doctor`

Comprehensive self-diagnostic: configuration, directory structure, entry integrity,
index consistency, search health, evidence/maturity correctness, applicability
(`applies_to` vs `kb-config.yml` vocabulary and `current_context`), **entry
hygiene**, **not_solved feedback**, git state.

Entry hygiene catches mechanical flaws left by older pipeline versions — behavior
tags that understate a command's risk (e.g. an `i2cset` step tagged `[api:read]`,
judged by deterministic verb rules) and placeholder noise in `applies_to`
(`firmware: "unknown"`). `--fix` rewrites only these mechanically decidable cases,
never the content. The not_solved check surfaces entries whose content may be
wrong (agents reported failure); correct those via
`holmes write-pending --corrects <id>`.

```bash
holmes doctor
  --fix          # Apply safe auto-fixes (create dirs, rebuild index, recalibrate maturity cache, clean entries)
  --verbose      # Per-entry detail
  --check-api    # Test LLM API connectivity
  --json
```

### `holmes lint`

Lightweight health check: index consistency, stale pending, duplicate titles,
contradiction flags.

```bash
holmes lint [--fix] [--report]   # --report outputs JSON
```

### `holmes rebuild-index`

Rebuild `index.json` and all `_index.md` files from disk (derived files, git-ignored).

---

## Git conflict handling

### `holmes merge`

Detect and resolve git conflict markers across the KB:

- `contributions/log.md` — union-merged line-wise (both sides kept)
- `_index.md` / `index.json` — resolved by rebuilding from entries
- auto-resolvable entry files — resolved automatically
- genuine content contradictions — isolated to `contributions/conflicts/`

### `holmes resolve`

Resolve an isolated content-contradiction conflict.

```bash
holmes resolve <conflict-id> --keep A|B   # Keep local (A) or remote (B)
holmes resolve <conflict-id> --manual     # Accept manually edited file (no markers left)
```

### `holmes check-conflicts`

List entries flagged `contradiction: true` pending maintainer review (`--json` available).

---

## `holmes log`

View CLI operation logs (traces and spans).

```bash
holmes log list
holmes log show <trace-id>
```

---

## Entry Format

```markdown
---
id: PT-DB-a3f8c2               # permanent ID: TYPE-CAT-6hex, minted at approve
type: pitfall
title: "Redis Connection Pool Exhausted"
maturity: verified             # cache — true value derived from evidence at read time
category: database
tags: [redis, connection-pool, timeout]
brief: "Redis maxclients too low causes connection timeout under load"
created_at: "2026-03-15T08:00:00Z"
updated_at: "2026-03-15T08:00:00Z"
contributors: [alice]
source_hash: a3f8c1d2e4b79062  # set by import pipeline (idempotency key)
former_id: pending-20260315-080000-ab1f   # temporary ID before approve (if any)
applies_to:                    # optional applicability metadata
  product_line: [serdes-gen2]
  test_stage: [dvt]
  firmware: "<=2.3"
---

## Symptoms
...

## Root Cause
...

## Resolution
...
```

**Required frontmatter fields:** `id`, `type`, `title`, `maturity`, `category`, `tags`, `created_at`, `updated_at`

**ID formats:**
- Permanent: `{TYPE_PREFIX}-{CAT_ABBR}-{6 lowercase hex}`, e.g. `PT-DB-a3f8c2` — minted at
  approve/confirm time with random suffix (collision-retried)
- Pending (temporary): `pending-{YYYYMMDD}-{HHMMSS}-{4 random}`, e.g. `pending-20260720-153000-ab1f`

---

## Maturity Rules

Maturity is derived from evidence sidecar records at read time; the frontmatter field is
a cache recalibrated by `holmes rebuild-index`.

| Level | Condition | Auto-decay trigger |
|-------|-----------|-------------------|
| `draft` | 0 solved evidence records | Archived after 30 days age + 3 months stale |
| `verified` | 1+ confirmed resolutions | Drop to `draft` after 6 months without reference |
| `proven` | 2+ sessions AND 2+ contributors | Drop to `verified` after 12 months without reference |

Run `holmes decay` (or schedule as a cron job) to apply demotions.
A `.history/` snapshot and a system `decayed` evidence record are written per demotion.

---

## Configuration File Reference

**`~/.holmes/config.json`**

```json
{
  "kb_path": "/home/alice/holmes-kb",
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "api_key": "sk-ant-...",
  "api_base_url": "",
  "username": "alice",
  "mcp_token": ""
}
```

**`~/.holmes/settings.json`**

```json
{
  "env": {
    "HOLMES_KB_PATH": "/home/alice/holmes-kb"
  }
}
```

**`<kb_root>/kb-config.yml`** (optional, in the KB repo)

```yaml
decay:
  draft_min_age_days: 30
  draft_stale_months: 3
vocabulary:                  # known values for applies_to (doctor lints others)
  product_line: [serdes-gen2]
  test_stage: [dvt, pvt]
current_context:             # current deployment context for doctor staleness checks
  serdes-gen2_firmware: "3.0"
```
