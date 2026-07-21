# Data Model: KB Access Control & Governance

**Feature**: 003-kb-governance
**Date**: 2026-06-01

---

## Entities

### 1. KbEntry (existing, extended)

Markdown file with YAML frontmatter at `$KB_ROOT/{type}/{category?}/{ID}.md`.

**Existing fields** (unchanged):
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Permanent ID, e.g. `PT-DB-001` |
| `type` | string | pitfall / model / guideline / process / decision |
| `title` | string | Entry title (max 100 chars) |
| `maturity` | string | **draft** / **verified** / **proven** / deprecated |
| `category` | string | e.g. database, network (type-specific) |
| `tags` | list[str] | Search tags |
| `created_at` | ISO8601 | Creation timestamp |
| `updated_at` | ISO8601 | Last modification timestamp |
| `skill_refs` | list[str] | Optional linked skill names |
| `last_referenced` | ISO8601 | Legacy field; kept for backward compatibility; not written by new code |

**New fields** (added by this feature):
| Field | Type | Description |
|-------|------|-------------|
| `evidence` | list[EvidenceRecord] | Append-only array of reference/validation records; drives maturity |
| `contributors` | list[str] | Deduplicated list of contributor identifiers who have validated this entry |
| `contradiction` | bool? | Optional. Set to `true` when a merge conflict detected; cleared by maintainer after review |

**Maturity state machine** (evidence-driven):
```
draft ──(confirm adds evidence[0])──> verified ──(≥2 sessions + ≥2 contributors)──> proven
  ^                                       |                                              |
  └──(decay: evidence stale >6mo)─────────┘         (decay: evidence stale >12mo) ──────┘
  │
  └──(Lint orphan + no evidence)──> contributions/archive/
```

**Maturity derivation rules** (FR-011):
- `len(evidence) == 0` → `draft`
- `len(evidence) >= 1` → `verified`
- `len({e.session_id}) >= 2` AND `len({e.contributor}) >= 2` → `proven`

**Write access rules** (soft constraint, CLI layer):
- All Agent writes go through `write-pending → confirm` regardless of maturity
- Maintainers may edit files directly via filesystem (bypass)

---

### 2. EvidenceRecord (new)

Inline object within `KbEntry.evidence` array in YAML frontmatter.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | YES | Unique session identifier; used for deduplication |
| `contributor` | string | YES | User/agent identifier (e.g. username, agent-id) |
| `date` | ISO8601 | YES | When this reference occurred |
| `project` | string | NO | Project context where entry was referenced |
| `context` | string | NO | Brief description of how the entry was used |

**Deduplication rule**: One record per `session_id` per entry. Same-session multiple reads are deduplicated by `append_evidence()`.

**Example**:
```yaml
evidence:
  - session_id: "session-20260601-abc123"
    contributor: "wangzhi"
    date: "2026-06-01T15:30:00+00:00"
    project: "holmes"
    context: "US1 debugging"
  - session_id: "session-20260615-def456"
    contributor: "alice"
    date: "2026-06-15T09:00:00+00:00"
    project: "service-mesh"
```

---

### 3. PendingEntry (existing, extended)

Markdown file with YAML frontmatter at `$KB_ROOT/contributions/pending/{pending-id}.md`.

**Existing fields** (unchanged):
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Temporary ID, e.g. `pending-20260601-153045-ab12` |
| `pending` | bool | Always `true` |
| `pending_since` | ISO8601 | When added to pending |
| `source` | string | "auto" / "agent" / "human" |
| `source_session` | string | Session identifier |
| `maturity` | string | Always `draft` when created |
| `suggested_type` | string | Hint for confirm |
| `suggested_category` | string | Hint for confirm |

**New fields** (added by this feature):
| Field | Type | Description |
|-------|------|-------------|
| `corrects` | string? | Optional. Target entry ID this proposal replaces (e.g. `PT-DB-001`) |

**Title duplicate check** (enforced in `write_pending()`):
- If `title` matches an existing `verified` or `proven` entry AND `corrects` is not set → return error (hard reject)
- Agent must use `--corrects` flag instead

---

### 4. VersionSnapshot (new)

Markdown file at `$KB_ROOT/.history/{original-id}-{replaced_at_compact}.md`.

Filename format: `{id}-{YYYYMMDD-HHmmss}.md`
Example: `PT-DB-001-20260601-153045.md`

**Fields** (full original frontmatter + added fields):
| Field | Type | Description |
|-------|------|-------------|
| All original KbEntry fields | — | Preserved verbatim (including evidence array and contributors) |
| `replaced_at` | ISO8601 | When the snapshot was taken |
| `replaced_by` | string | Pending ID (correction) or `"decay"` (demotion) |
| `snapshot_reason` | string | `"correction"` or `"decay"` |

**Lifecycle**:
1. Created when `kb confirm` is called on a `corrects:`-annotated pending entry (reason: `correction`)
2. Created when `kb decay` demotes an entry (reason: `decay`)
3. Snapshot is read-only; accessible via `holmes kb history <id>`

---

### 5. ArchivedEntry (new concept)

Orphaned `draft` entry moved to `$KB_ROOT/contributions/archive/{ID}.md`.

**Conditions for archival**:
- `maturity: draft`
- Empty `evidence` array (no validation records)
- Flagged as orphan by `holmes kb lint`

**Lifecycle**: Moved from public type directory → `contributions/archive/`. Removed from active index. Cannot be promoted without being moved back and going through `confirm`.

---

## Relationships

```
KbEntry (verified/proven)
    └── evidence: [] → EvidenceRecord[]  (append-only; drives maturity)
    └── contributors: []                 (deduped from evidence[*].contributor)
    └── has many VersionSnapshot (via .history/)
    └── referenced by PendingEntry.corrects

PendingEntry
    └── corrects → KbEntry (optional)
    └── on confirm → creates first EvidenceRecord in target KbEntry
    └── on confirm (with corrects) → creates VersionSnapshot first, then overwrites original

EvidenceRecord
    └── deduped by session_id within each KbEntry
    └── contributor → added to KbEntry.contributors on append
```

---

## Directory Layout (additions)

```
$KB_ROOT/
├── .history/                          ← NEW: version snapshots
│   ├── PT-DB-001-20260601-153045.md   #   correction snapshot
│   └── PT-DB-001-20260610-091200.md   #   decay snapshot
├── contributions/
│   ├── pending/                       ← existing
│   ├── archive/                       ← NEW: orphaned draft entries
│   │   └── PT-DRAFT-OLD-001.md
│   └── log.md                         ← existing (decay/conflict events also logged)
├── pitfall/
│   └── database/
│       └── PT-DB-001.md               ← has evidence[] and contributors[] fields (new)
...
```

---

## Decay Thresholds (configurable)

Stored in `$KB_ROOT/kb-config.yml` (optional). Defaults:

```yaml
decay:
  proven_months: 12    # proven → verified if evidence stale > 12 months
  verified_months: 6   # verified → draft if evidence stale > 6 months
```

Reference date for decay = `max(evidence[*].date)` if evidence non-empty, else `updated_at`.

If `kb-config.yml` absent, defaults apply.
