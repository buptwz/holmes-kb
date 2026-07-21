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
| `pitfall` | Fault patterns with symptoms, root cause, and resolution steps (may have multiple resolution branches) |
| `process` | Step-by-step operational procedures |
| `guideline` | Best practices and conventions |
| `model` | Concept definitions and mental models |
| `decision` | Architecture decisions and their rationale |

### Maturity Levels

Maturity is **derived from evidence records at read time** — never set manually. The
frontmatter field is a cache, recalibrated by `holmes rebuild-index`.

| Level | Condition |
|-------|-----------|
| `draft` | 0 solved evidence records |
| `verified` | 1+ confirmed resolutions (`kb_confirm(solved)`) |
| `proven` | 2+ distinct sessions AND 2+ distinct contributors |

**Automatic lifecycle:**

| Event | Action |
|-------|--------|
| `proven` entry unreferenced for 12 months | Decays to `verified` |
| `verified` entry unreferenced for 6 months | Decays to `draft` |
| `draft` entry age > 30 days + unreferenced > 3 months | Archived |
| `kb_read(full)` called | Records lightweight reference (resets decay timer) |
| `kb_confirm(solved)` called | Records evidence (triggers maturity promotion) |

`holmes decay` is event-sourced: each demotion writes a system `decayed` evidence record
(anchoring the derived level) plus a `.history/` snapshot. Run `holmes doctor` to detect
lifecycle issues.

### Directory Layout

```
{kb_root}/
├── pitfall/            # fault patterns (published)
│   └── <category>/
├── process/            # step-by-step procedures (published)
│   └── <category>/
├── model/
├── guideline/
├── decision/
├── skills/             # reusable agent instruction packages
│   └── <name>/
│       └── SKILL.md
├── _drafts/            # agent-saved drafts (kb_draft)
├── _trash/             # soft-deleted entries (recoverable via git)
└── contributions/
    ├── pending/        # entries awaiting human review (import pipeline output)
    ├── evidence/       # per-session sidecar files (conflict-free git)
    ├── archive/        # retired stale drafts
    └── log.md          # contribution event log (union-merged on pull)
```

`index.json` and `*/_index.md` are derived files: git-ignored, rebuilt locally by
`holmes rebuild-index` (also automatically on server start and after approve).

---

## Importing Documents

`holmes import` runs a three-phase LLM pipeline (Classifier → Summarizer → Generator)
that converts any document — runbook, postmortem, incident report — into a single
structured KB entry. One document = one KB entry. Import requires a contributor
identity (`holmes config set username <name>`).

```bash
# Import a single file
holmes import ./incident-report.md

# Dry run — preview classification without writing files
holmes import ./incident-report.md --dry-run

# Force entry type (skip LLM classification)
holmes import ./dns-runbook.md --type pitfall

# Batch import a directory
holmes import --dir ./postmortems/

# Suppress interactive prompts (CI/pipelines)
holmes import ./incident.md --no-interactive

# Skip duplicate check
holmes import ./incident.md --force
```

The pipeline automatically:
- Classifies the document type and language
- Extracts structured summary (key facts, commands, symptoms, resolution branches)
- Generates KB Markdown with YAML frontmatter
- Normalizes headers and validates fidelity
- Detects re-imports of the same source via `source_hash` (idempotency)

Semantic duplicate detection happens later, at the `holmes approve` gate.

### Pipeline Stages

```
Source doc → Classifier (type + language detection)
                │
                ▼
          Summarizer (structured extraction: key_facts, commands, symptoms, branches)
                │
                ▼
          Type Inference (deterministic: override Classifier based on extracted content)
                │
                ▼
          Generator (format summary into KB Markdown with YAML frontmatter)
                │
                ▼
          Normalizer + Fidelity Check (validate → feedback → retry, max 2 retries)
                │
                ▼
          contributions/pending/  (awaiting human review)
```

### LLM Reliability

- **temperature=0** for all LLM calls — deterministic output
- **Validate → feedback → retry** on every LLM output (max 2 retries)
- **Deterministic fallback**: if Summarizer LLM fails, regex-based extraction ensures the pipeline never crashes
- **Direct mode**: documents under 8K chars skip the tool-use loop, reducing Summarizer from 3-7 LLM calls to 1
- **Verbatim fidelity**: shell commands, API endpoints, URLs, error codes are copied character-for-character — never paraphrased

---

## Reviewing Pending Entries

Imported entries land in `contributions/pending/` for human review.
Nothing reaches the official KB without explicit approval.

```bash
# List all pending entries
holmes pending
holmes pending --show <pending-id>            # read full content of one

# Approve — publish to confirmed space
holmes approve <pending-id>
holmes approve <pending-id> --no-interactive  # CI/pipeline safe
holmes approve <pending-id> --skip-dedup      # skip the semantic dedup gate

# Reject a pending entry
holmes reject <pending-id> --reason "outdated"

# Soft-delete any entry (moves to _trash/, recoverable via git)
holmes delete <entry-id>
```

What `holmes approve` does:

1. Detects older pending/confirmed entries from the same source document and offers to
   cancel/deprecate them
2. Runs a **semantic dedup gate**: suspected duplicates in the same category are shown
   and require explicit confirmation (a human decides; `--skip-dedup` bypasses)
3. **Mints the permanent ID** — `{TYPE}-{CAT}-{6 hex}`, e.g. `PT-DB-a3f8c2`. The old
   temporary ID (`pending-20260720-153000-ab1f`) is recorded in the entry's `former_id`
   field and logged to `contributions/log.md`
4. Rebuilds the derived index files

For hand-written pending entries and correction proposals (`--corrects`), use
`holmes confirm <pending-id>` instead — it runs 3-gate validation (schema → duplicate
check → preview) and, for corrections, snapshots the original to `.history/` before
replacing it.

---

## Reading and Searching

```bash
# KB health overview
holmes overview
holmes overview --json

# Full-text search
holmes search "redis connection pool"

# Read a specific entry
holmes show PT-DB-a3f8c2
```

---

## Applicability Metadata (`applies_to`)

Entries can carry an optional `applies_to` frontmatter block describing where the
knowledge applies:

```yaml
applies_to:
  product_line: [serdes-gen2]
  test_stage: [dvt]
  firmware: "<=2.3"
```

- Keys are fixed (`product_line`, `test_stage`, `firmware`); values are open-world and
  accumulate into a vocabulary (see `kb-config.yml` → `vocabulary:`)
- The import pipeline extracts `applies_to` automatically, preferring existing
  vocabulary values; humans verify at approve time
- `kb_browse(product_line=..., test_stage=...)` ranks matching entries first
  (`strict=true` hard-filters); entries without `applies_to` are universal
- `holmes doctor` flags values outside the vocabulary (possible typos) and entries
  whose `firmware` constraint conflicts with `kb-config.yml` → `current_context:`

---

## Governance

### Decay (Stale Knowledge)

Entries that haven't been referenced or confirmed in a while lose maturity. Run decay
periodically (e.g., monthly) or as a cron job.

```bash
# Preview what would be demoted/archived
holmes decay --dry-run

# Apply demotions (saves .history/ snapshots + decayed evidence records)
holmes decay

# Scope to a specific type
holmes decay --type pitfall
```

Decay rules:
- `proven` → `verified` after 12 months without reference
- `verified` → `draft` after 6 months without reference
- `draft` → archived after 30 days age + 3 months without reference

### KB Health Check (Doctor)

```bash
# Detect lifecycle issues: stale drafts, decay candidates, orphan entries
holmes doctor

# Verbose output
holmes doctor --verbose
```

### Entry History

Every correction and decay event saves a versioned snapshot in `.history/`.

```bash
holmes history PT-DB-a3f8c2
holmes history PT-DB-a3f8c2 --json
```

---

## Skill Management

Skills are agent instruction packages in `skills/<name>/SKILL.md`. The import pipeline
auto-creates them when a Resolution section has 3+ distinct command steps. The skill
name is derived from the entry title (kebab-case slug).

Skills are read-only from the CLI — creation and updates are handled by the import pipeline.
There is no dedicated skill listing command; browse the `skills/` directory directly.

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

Derived files never enter git: `index.json` and `*/_index.md` are git-ignored and
rebuilt locally. `contributions/log.md` uses a union merge driver (`.gitattributes`):
pulls keep lines from both sides. If entry files themselves conflict, run `holmes merge`
(auto-resolves what it can, isolates real contradictions to `contributions/conflicts/`,
then resolve with `holmes resolve <conflict-id> --keep A|B`).

```bash
# Sync before working
git pull --rebase origin main

# After confirming entries
git add .
git commit -m "Add PT-NET-9c2d51: DNS resolution failure under split-horizon config"
git push origin main
```
