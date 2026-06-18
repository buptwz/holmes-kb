# CLI Contracts: Holmes KB Autonomous Import Agent

**Feature**: `013-kb-skill-evolution` | **Date**: 2026-06-07

---

## Contract 1: `holmes import <source>` — Single File

**Command**:
```
holmes [--kb-path <path>] import <file>
       [--dry-run]
       [--no-interactive]
       [--verbose]
       [--force]
       [--type <type>]
       [--category <category>]
```

**Arguments**:

| Argument/Option | Required | Default | Description |
|----------------|----------|---------|-------------|
| `<file>` | Yes | — | Path to source document to import |
| `--dry-run` | No | False | Preview plan, no writes, no git commit |
| `--no-interactive` | No | False | Suppress all confirmation gates; use conservative defaults |
| `--verbose` | No | False | Show per-decision reasoning trace |
| `--force` | No | False | Bypass duplicate pending check |
| `--type` | No | None | Override LLM type classification |
| `--category` | No | None | Override LLM category classification |

**Exit codes**:

| Code | Condition |
|------|-----------|
| 0 | Success (including partial: some items failed, reported in summary) |
| 1 | Fatal error: file not found, KB path not configured, content too short (<50 chars) |
| 2 | Configuration error: KB path missing or KB directory does not exist |

**Stdout (normal mode)**:
```
Analyzing source...
✓ Knowledge point 1: pitfall/database — "PostgreSQL connection exhaustion"
  Dedup check: no existing match
  Skill assessment: Recommended (3 steps, has {parameter})
  Writing to pending... done (pending-20260607-103001-ab12)
  Skill created: pg-connection-recovery (agent_created: true)
  Curator: 1 suggestion — check-pg-health may merge with pg-connection-recovery

Summary: 1 created, 0 updated, 0 skipped | skill: 1 generated, 0 merged | 1 suggestion
```

**Stdout (dry-run mode)**:
```
[DRY RUN] Analyzing source...
  Would create: pitfall/database — "PostgreSQL connection exhaustion"
  Would generate skill: pg-connection-recovery
  Would suggest: curator merge candidate

[DRY RUN] No files written.
```

**Stdout (--verbose mode)**: Includes confidence scores, source text fragments for each field, and full reasoning.

**Stderr**: Error messages only (file not found, API errors, etc.)

---

## Contract 2: `holmes import --dir <directory>`

**Command**:
```
holmes [--kb-path <path>] import --dir <directory>
       [--dry-run] [--no-interactive] [--verbose] [--force]
```

**Behavior**:
- Processes all `.md`, `.txt`, `.rst` files in `<directory>` (non-recursive by default)
- Each file processed independently; failure of one does not stop others
- Final summary aggregates results across all files

**Stdout**:
```
Processing 3 files from ./docs/...
[1/3] incident-2026-05.md — ✓ created (pending-20260607-103001-ab12)
[2/3] deployment-guide.md — ✓ created (pending-20260607-103002-cd34)
[3/3] notes.md — ⚠ skipped (already imported, source_hash match)

Batch summary: 2 created, 0 updated, 1 skipped | skill: 1 generated | 0 errors
```

---

## Contract 3: `holmes import` — Stdin pipe

**Command**:
```
echo "..." | holmes import -
cat doc.md | holmes [--kb-path <path>] import -
```

**Behavior**: `-` as file argument reads from stdin. `source_hash` computed on stdin content. No `file_path` stored in frontmatter.

---

## Contract 4: Interactive Confirmation Gates

**Gate trigger conditions** (skipped in `--no-interactive` mode):

| Gate | Trigger | Prompt format |
|------|---------|---------------|
| Classification confidence | confidence < 0.7 | `I think this is pitfall/database. Correct? [Y/n/other-type]` |
| Dedup: similar entry found | semantic similarity detected | `Similar entry found: PT-DB-001 "Postgres OOM". Update it or create new? [u=update/n=new]` |
| Multi-knowledge-point | ≥2 independent topics detected | `Detected 2 independent topics. Create separate entries or merge? [s=separate/m=merge]` |
| Skill generation recommended | ≥3 steps + parameters | `Recommend creating skill: pg-connection-recovery. Confirm? [Y/n]` |

**`--no-interactive` default decisions**:

| Gate | Auto-decision |
|------|--------------|
| Low-confidence classification | Use LLM best guess; maturity=draft; log warning |
| Dedup ambiguity | Create new entry; add `related_entries` link |
| Multi-knowledge-point | Create separate entries |
| Skill recommendation | Skip skill generation; log suggestion |

---

## Contract 5: ImportReport Summary Format

**Normal mode** (FR-020):
```
✓ {created} created, {updated} updated, {skipped} skipped | skill: {gen} generated, {merged} merged | {n} suggestion(s)
```

**Error present**:
```
✓ {created} created, {updated} updated, {skipped} skipped | skill: {gen} generated | ⚠ {errors} error(s): {first_error}
```

**Verbose mode** (FR-021) — additional per-item block:
```
  [PT-DB-001] confidence: 0.92
    title  ← "PostgreSQL connection exhaustion" (source: line 3)
    root_cause  ← "PgBouncer pool_size too low" (source: line 7)
    resolution  ← verified (3/3 steps have source support)
    skill  ← pg-connection-recovery (created; 3 steps, {pool_size} parameter)
```

---

## Contract 6: Atomic Write Guarantee

Every file write is atomic (R-003: temp + os.replace). Invariants:
- A file is either old-complete or new-complete; never half-written
- `.tmp` orphans from crashed runs are safe to delete (do not contain committed data)
- `git commit` runs after all file writes succeed; no partial commit

---

## Contract 7: Skill Usage Sidecar

**File**: `skills/<name>/.skill_usage.json`

**Written when**:
- Skill created by agent → `agent_created: true`, all counts 0
- Skill deleted with `--absorbed-into B` → `absorbed_into: "B"` set, file kept as tombstone

**Not written** when skill is created manually by user (file absent = all defaults apply).
