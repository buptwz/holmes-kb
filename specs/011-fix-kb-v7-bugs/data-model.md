# Data Model: 修复 Holmes KB v7 报告问题

## Affected Entities

### CommandCandidate (US1)

**File**: `kb/holmes/kb/skill/manager.py`

Filtering logic in `detect_commands()` → added 4 new backtick skip conditions:

| Filter | Pattern | Skipped Examples |
|--------|---------|-----------------|
| JVM args | starts with `-X` | `-Xmx4g`, `-Xms4g`, `-XX:+UseG1GC` |
| Config keys | `^\w[\w.]*\.\w[\w]*$` (contains dot, no spaces) | `session.timeout.ms`, `heartbeat.interval.ms` |
| Method calls | first char alpha + contains `(` | `emitter.on()`, `emitter.setMaxListeners(20)` |
| Config blocks | ends with `{` | `upstream backend {`, `server {` |

### PendingEntry (US2, US3, US6)

**File**: `kb/holmes/kb/pending.py`

Metadata fields preserved by `amend-pending`:
- `id` — pending entry ID (immutable)
- `pending_since` — original creation timestamp (immutable)
- `source` — origin marker (immutable)
- `source_session` — session ID (immutable)
- `pending` — always True (immutable)
- `suggested_type` — re-derived from new content's `type` field
- `suggested_category` — re-derived from new content's `category` field

Fields replaced from new content:
- `title`, `type`, `category`, `maturity`, `resolution`, `symptoms`, and all user-provided fields

### PendingTableRow (US6)

Table display in `kb_pending()`:

| Column | Before | After |
|--------|--------|-------|
| CREATED | `e['created_at'][:10]` (empty for old entries) | `e['pending_since'][:10]` (always non-empty) |
