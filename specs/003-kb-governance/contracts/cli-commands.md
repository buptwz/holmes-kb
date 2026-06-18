# CLI Contracts: KB Access Control & Governance

**Feature**: 003-kb-governance
**Date**: 2026-06-01

---

## New Commands

### `holmes kb decay [OPTIONS]`

Run maturity decay check across all public KB entries.

```
USAGE:
  holmes --kb-path <path> kb decay [--dry-run] [--type <type>] [--json]

OPTIONS:
  --dry-run         Show what would change without writing
  --type TEXT       Limit to one entry type (pitfall/model/guideline/process/decision)
  --json            Output JSON instead of human-readable table

EXIT CODES:
  0   Completed (even if 0 entries decayed)
  1   Partial failure (some entries could not be processed — logged)

STDOUT (success, human):
  Scanned: 42 entries
  Decayed: 3 entries
    [PT-DB-001] proven → verified  (last evidence: 2025-04-01, 14 months ago)
    [GL-001]    verified → draft   (last evidence: 2025-11-01, 7 months ago)
    [MOD-002]   proven → verified  (last evidence: 2025-03-15, 15 months ago)

STDOUT (success, json):
  {
    "scanned": 42,
    "decayed": 3,
    "changes": [
      {
        "id": "PT-DB-001",
        "old_maturity": "proven",
        "new_maturity": "verified",
        "last_evidence_date": "2025-04-01T00:00:00+00:00",
        "months_unreferenced": 14
      }
    ],
    "errors": []
  }

STDOUT (dry-run prefix):
  [DRY RUN] Would decay 3 entries (no changes written)
  ...same table...

NOTES:
  - Reference date = max(evidence[*].date); falls back to updated_at if evidence empty
  - Saves VersionSnapshot (.history/) for each demoted entry
  - Logs each decay event to contributions/log.md with reason "decay: unreferenced N months"
  - Thresholds read from kb-config.yml; defaults: proven=12mo, verified=6mo
```

---

## Modified Commands

### `holmes kb update-refs` (extended)

Batch append EvidenceRecord to multiple entries at session end.

```
USAGE:
  holmes --kb-path <path> kb update-refs \
    --ids <id1,id2,...> \
    --session-id <session_id> \
    --contributor <contributor> \
    [--project <project>] \
    [--context <context>]

OPTIONS:
  --ids TEXT           Comma-separated entry IDs to update (required)
  --session-id TEXT    Unique session identifier for deduplication (required)
  --contributor TEXT   Contributor identifier, e.g. username (required)
  --project TEXT       Optional project context
  --context TEXT       Optional usage context description

EXIT CODES:
  0   Success (even if some IDs not found — those are reported in output)
  1   All IDs failed or required parameters missing

STDOUT (success):
  {
    "updated": ["PT-DB-001", "GL-002"],
    "skipped_duplicate": ["MOD-003"],
    "not_found": [],
    "maturity_promoted": [
      {"id": "PT-DB-001", "old": "verified", "new": "proven"}
    ]
  }

BEHAVIOR CHANGES from previous version:
  - Now appends EvidenceRecord to evidence array (previously updated last_referenced field)
  - Deduplicates by session_id — same session calling update-refs twice = no double-count
  - After appending, recomputes maturity via derive_maturity(evidence)
  - Appends contributor to entry's contributors list (dedup)
  - Reports any maturity promotions that occurred
```

---

### `holmes kb write-pending` (extended)

```
USAGE (unchanged):
  holmes --kb-path <path> kb write-pending --content <markdown> [--corrects <entry_id>]

NEW OPTION:
  --corrects TEXT   Target entry ID that this proposal intends to replace

BEHAVIOR CHANGES:
  1. Title duplicate check: if title matches any verified/proven entry AND --corrects not set
     → return error (exit 1): {"error": "Duplicate title: 'Redis connection timeout' matches PT-DB-001 (verified). Use --corrects PT-DB-001 to submit a correction."}

  2. If --corrects <id> provided:
     → entry ID must exist in public KB (error if not found)
     → writes corrects: <id> into pending frontmatter
     → title duplicate check is skipped (correction is intentional)

EXIT CODES:
  0   Success
  1   Duplicate title (without --corrects) OR corrects target not found
```

---

### `holmes kb confirm <pending_id>` (extended)

```
BEHAVIOR CHANGES:
  After Gate 2 (duplicate detection), before Gate 3 (preview):

  If pending entry has corrects: <original_id>:
    1. Look up <original_id> in public KB
       → error if not found
    2. Save VersionSnapshot: write original entry to .history/<original_id>-<timestamp>.md
       with replaced_at, replaced_by, snapshot_reason="correction" fields added
    3. Overwrite original entry file with proposal content
       (set maturity: verified, updated_at: now, remove corrects field)
       (PRESERVE original evidence array and contributors list)
    4. Delete pending entry (same as normal confirm)
    5. Rebuild index

    STDOUT: "✓ Correction applied: PT-DB-001 (snapshot: .history/PT-DB-001-20260601-153045.md)"

  If no corrects field (normal confirm):
    - Assigns new permanent ID to entry
    - Writes to type/category/ directory
    - Appends first EvidenceRecord to evidence array (contributor = current user, session = confirm session)
    - Maturity auto-derived from evidence count (1 record → "verified")
    - Updates contributors list with confirming user
```

---

## Existing Commands (unchanged contracts)

| Command | Status |
|---------|--------|
| `holmes kb pending` | Unchanged |
| `holmes kb reject <id>` | Unchanged |
| `holmes kb show <id>` | Unchanged |
| `holmes kb search <query>` | Unchanged |
| `holmes kb lint` | Unchanged (orphan detection used by archive workflow) |
| `holmes kb list` | Unchanged |
| `holmes import <file>` | Unchanged |
| `holmes kb history <id>` | New — list .history/ snapshots for an entry |

---

## Removed Commands

| Command | Reason |
|---------|--------|
| `holmes kb touch <id>` | Removed. Replaced by session-end `update-refs` with evidence array. Per-read single-field updates cause git conflicts in multi-user environments. |
| `holmes kb write-entry <id>` | Removed. All Agent writes go through `write-pending → confirm`. No direct write path to public KB entries. |
