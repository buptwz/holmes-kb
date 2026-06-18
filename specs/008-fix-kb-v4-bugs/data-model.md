# Data Model: 修复 Holmes KB v4 报告问题

## Entities

### PendingEntry
Represents a pending KB entry awaiting confirmation.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| id | string | frontmatter `id` or path stem | `post.metadata.get("id") or path.stem` |
| type | string | frontmatter `type` | |
| title | string | frontmatter `title` | |
| created_at | string | frontmatter `created_at` | may be empty for old entries |
| pending_since | string | frontmatter `pending_since` | **NEW**: written by `write_pending()`, now exposed in `list_pending()` |
| path | string | filesystem path | |

**Internal fields** (written to frontmatter, must be stripped before Gate 3 preview and KB write):
- `pending` (bool)
- `pending_since` (datetime string)
- `source` (string: "auto" | "manual")
- `source_session` (string)
- `suggested_type` (string)
- `suggested_category` (string)

### EvidenceSidecar
Evidence records stored in `contributions/evidence/<entry_id>/`.

| Field | Type | Notes |
|-------|------|-------|
| session_id | string | |
| contributor | string | |
| date | string (ISO 8601) | |

### VersionSnapshot
Markdown snapshots stored in `.history/<entry_id>/`.

| Field | Notes |
|-------|-------|
| filename | snapshot name (no path separators allowed) |
| content | full Markdown + frontmatter |

## State Transitions

### CMD_PATTERN Detection Pipeline (US4)

```
Input text
  → Strip YAML frontmatter block (if text starts with ---)
  → Apply CMD_PATTERN.finditer()
  → Filter candidates: apply _SQL_KEYWORDS check
  → Return clean command list
```

### Gate 3 Preview (US2)

```
pending raw content
  → fm.loads(raw) → post
  → pop internal fields: pending, pending_since, source, source_session, suggested_type, suggested_category
  → fm.dumps(post) → display_text
  → show display_text to user
```

## Validation Rules

- `history --show <name>`: `Path(name).name == name` (no path separators, no traversal)
- `pending_since`: graceful empty string if missing from old data
- Evidence sidecar: `Evidence: none` if no sidecar file exists
- Gate 3 stripped content: show `(empty content)` if result is empty after stripping
