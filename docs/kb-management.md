# KB Management Guide

Holmes stores knowledge as plain Markdown files in a git repository. This guide covers
day-to-day KB operations from an operator/maintainer perspective.

For initial setup, see [quickstart.md](quickstart.md).
For full CLI flag reference, see [reference.md](reference.md).

---

## Understanding the Knowledge Base

Knowledge is stored as structured Markdown entries, each with a YAML frontmatter header.
The KB lives in a normal git repo — no database, no proprietary format.

### Entry Types

| Type | Purpose |
|------|---------|
| `pitfall` | Fault patterns with symptoms, root cause, and resolution steps |
| `process` | Step-by-step operational procedures |
| `guideline` | Best practices and conventions |
| `model` | Concept definitions and mental models |
| `decision` | Architecture decisions and their rationale |

### Maturity Levels

Maturity is **derived from evidence records automatically** — never set manually.

| Level | Condition |
|-------|-----------|
| `draft` | 0 evidence records |
| `verified` | 1+ confirmed resolutions |
| `proven` | 2+ distinct sessions AND 2+ distinct contributors |

Evidence decays over time: `proven` entries drop to `verified` after 12 months without
use; `verified` entries drop to `draft` after 6 months. Run `holmes kb decay` to apply.

### Directory Layout

```
{kb_root}/
├── pitfall/            # fault patterns (published)
│   └── <category>/
├── process/            # step-by-step diagnostics (published, part of pitfall trees)
│   └── <category>/
├── model/
├── guideline/
├── decision/
├── skills/             # reusable agent instruction packages
│   └── <name>/
│       └── SKILL.md
├── _pending/           # entries awaiting human review (DAG import output)
│   ├── pitfall/<category>/
│   └── process/<category>/
├── _import-state/      # Agent 1 DAG progress files (*.dag.json)
└── contributions/
    ├── evidence/       # per-session sidecar files (conflict-free git)
    ├── archive/        # orphaned drafts (no evidence)
    └── log.md          # contribution event log
```

---

## Importing Documents

`holmes import` runs an autonomous LLM pipeline that classifies any document —
runbook, postmortem, incident report, Slack export — into a structured KB entry.

```bash
# Import a single file
holmes import ./incident-report.md

# Dry run — preview without writing files
holmes import ./incident-report.md --dry-run

# Force entry type (skip LLM classification)
holmes import ./dns-runbook.md --type pitfall --category network

# Batch import a directory
holmes import --dir ./postmortems/

# Suppress interactive prompts (CI/pipelines)
holmes import ./incident.md --no-interactive

# Show per-field classification trace
holmes import ./incident.md --verbose
```

The pipeline automatically:
- Checks for semantic duplicates before creating a new entry
- Verifies the draft meets quality standards
- Evaluates whether a reusable skill should be generated (threshold: 3+ command steps)

Importing the same file twice is safe — the agent detects the existing `source_hash` and skips.

### Pitfall Document Import (DAG Pipeline)

Fault-diagnosis documents (incident reports, troubleshooting runbooks) use a two-agent pipeline that produces a navigable **diagnostic tree** instead of a single flat entry.

```
holmes import ./incident-report.md        # auto-detected as pitfall
holmes import ./runbook.md --type pitfall # force pitfall path
```

**What gets generated:**

```
_pending/
├── pitfall/<category>/
│   └── <name>-root-001.md     # pitfall root — symptoms, root cause, routing links
└── process/<category>/
    ├── <name>-N1-001.md       # process entry — step-by-step for branch 1
    └── <name>-N2-001.md       # process entry — step-by-step for branch 2
```

The pitfall root entry contains `child_entry_ids` pointing to process entries, enabling
agents to navigate the tree depth-first. Each process entry has a `parent_id` back-link.

**Pipeline stages:**

1. **Agent 1** — extracts a DAG (`.dag.json`) from the document: nodes, edges, section headings
2. **Step 2.5** — validates the DAG, cross-checks `section_heading` against the source file
3. **User confirmation** — review the DAG outline before committing to full generation
4. **Agent 2** — generates entries in topological order (leaf nodes first), then the pitfall root

If a run is interrupted, restart with `--force` — Agent 2 skips already-written entries
(checkpoint recovery via `_import-state/<hash>.dag.json`).

```bash
# Retry a single failed entry without regenerating the whole tree
holmes import ./incident.md --retry-entry N3
```

---

## Reviewing Pending Entries

DAG-imported entries land in `_pending/<type>/<category>/` for human review.
Nothing reaches the official KB without explicit confirmation.

```bash
# List all pending entries
holmes kb pending

# View a specific pending entry
holmes kb show <pending_id>

# Confirm — runs 3-gate validation, then publishes the entry
holmes kb confirm <pending_id>
holmes kb confirm <pending_id> --contributor alice

# Reject and discard
holmes kb reject <pending_id>
holmes kb reject <pending_id> --reason "duplicate of PT-DB-001"
```

`holmes kb confirm` runs three gates before publishing:
1. **Schema validation** — required fields, valid type and category
2. **Duplicate check** — no existing entry with same title or high semantic similarity
3. **Human preview** — shows the full entry, prompts for final approval

---

## Reading and Searching

```bash
# KB health overview
holmes kb overview

# List entries (with optional filters)
holmes kb list
holmes kb list --type pitfall
holmes kb list --category database

# Full-text search
holmes kb search "redis connection pool"

# Read a specific entry
holmes kb show PT-DB-001
```

---

## Governance

### Decay (Stale Knowledge)

Entries that haven't been confirmed in a while lose maturity. Run decay periodically
(e.g., monthly) or as a cron job.

```bash
# Preview what would be demoted
holmes kb decay --dry-run

# Apply demotions (saves .history/ snapshots before each change)
holmes kb decay

# Scope to a specific type
holmes kb decay --type pitfall
```

### Orphaned Drafts

Entries that were created but never confirmed by anyone can be archived.

```bash
holmes kb archive-orphans
```

### Conflict Detection

The import pipeline sets `contradiction: true` on entries that conflict with existing ones.

```bash
holmes kb check-conflicts
```

### Entry History

Every correction and decay event saves a versioned snapshot in `.history/`.

```bash
holmes kb history PT-DB-001
holmes kb history PT-DB-001 --json
```

---

## Correcting a Verified Entry

Do not edit and push directly. Use the pending workflow to preserve history:

```bash
# 1. Submit a corrected version
holmes kb write-pending \
  --corrects PT-DB-001 \
  --content "$(cat corrected-entry.md)"

# 2. Confirm as usual
holmes kb confirm <pending_id>
# Saves .history/PT-DB-001-<timestamp>.md, replaces original, preserves evidence
```

---

## Skill Management

Skills are agent instruction packages in `skills/<name>/SKILL.md`. The import pipeline
auto-creates them when a Resolution section has 3+ distinct command steps. The skill
name is derived from the entry title (kebab-case slug), not a timestamp.

Skills are read-only from the CLI — creation and updates are handled by the import pipeline:

```bash
# List skills
holmes kb list --type skill

# Read a skill
holmes kb show <skill-name>
```

To manually create or edit a skill, write a `SKILL.md` directly in `skills/<name>/`:

```markdown
---
name: check-redis-pool
description: Diagnose and recover Redis connection pool exhaustion
---

Check current pool status: `redis-cli INFO clients`
...
```

---

## Git Workflow for Team Collaboration

The KB is a standard git repo. Evidence sidecars are individual files per session —
file additions never conflict, so concurrent confirmations from multiple engineers
merge automatically without intervention.

```bash
# Sync before working
git pull --rebase origin main

# After confirming entries
git add .
git commit -m "Add PT-NET-001: DNS resolution failure under split-horizon config"
git push origin main

# If structural conflicts occur (rare — typically just a maturity field)
holmes kb merge
```

---

## KB Health Check

```bash
# Validate all entries (missing fields, broken references, etc.)
holmes kb lint

# Rebuild index.json and _index.md category files
holmes kb rebuild-index
```
