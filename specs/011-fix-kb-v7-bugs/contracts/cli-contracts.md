# CLI Contracts: 修复 Holmes KB v7 报告问题

## Changed Commands

### write-pending (US3)

**Before**:
```
holmes kb write-pending --content <text> [--corrects <id>]
```

**After**:
```
holmes kb write-pending (--content <text> | --file <path>) [--corrects <id>]
```

**Rules**:
- `--content` and `--file` are mutually exclusive
- One of `--content` or `--file` is required
- `--file` path must exist (validated before read)
- Output: `{"pending_id": "<id>"}` on success
- Exit 1 with `{"error": "..."}` on failure

**Error cases**:
- Both `--content` and `--file` provided → `Error: --content and --file are mutually exclusive.` + exit 1
- Neither provided → `Error: one of --content or --file is required.` + exit 1
- `--file` path not found → click.Path(exists=True) raises automatically

---

### reject (US5)

**Before**:
```
holmes kb reject [<pending_id>] [--reason <text>] [--stale-days N] [--dry-run]
# --dry-run required --stale-days, error otherwise
```

**After**:
```
holmes kb reject [<pending_id>] [--reason <text>] [--stale-days N] [--dry-run]
# --dry-run works in both single-entry and batch mode
```

**Single-entry + dry-run output**:
```
<pending_id>
✓ Rejected: <pending_id> (dry run)
```
Exit 0. File NOT deleted.

**Batch + dry-run output** (unchanged):
```
<id1>
<id2>
Rejected: 2 stale entries (dry run)
```

---

### archive-orphans (US4)

**Before**:
```
holmes kb archive-orphans [--json]
```

**After**:
```
holmes kb archive-orphans [--json] [--dry-run]
```

**--dry-run text output**:
```
<entry_id>
<entry_id>
Archived 2 orphan draft(s) (dry run)
```
Exit 0. Files NOT moved.

**--dry-run JSON output**:
```json
{"archived": ["<id1>", "<id2>"], "errors": [], "dry_run": true}
```

**No orphans + --dry-run**:
```
No orphan draft entries found. (dry run)
```

---

## New Commands

### amend-pending (US2)

```
holmes kb amend-pending <pending_id> (--content <text> | --file <path>)
```

**Behavior**:
- Reads existing pending file
- Parses new content (validates it is valid frontmatter)
- Merges: system metadata from original + user content from new
- Writes back to same pending file path
- Output: `✓ Amended: <pending_id>`
- Exit 0 on success

**Preserved fields** (from original): `id`, `pending_since`, `source`, `source_session`, `pending`, `suggested_type` (re-derived), `suggested_category` (re-derived)

**Error cases**:
- `pending_id` not found → `Pending entry not found: <id>` + exit 1
- Both/neither `--content`/`--file` → error + exit 1
- `--file` path not found → click.Path(exists=True) raises automatically

**Note**: amend-pending does NOT bypass Gate 1 — the amended entry still goes through `confirm` with full schema validation.

---

## Unchanged Commands with New Behavior

### pending (table display) (US6)

CREATED column now shows `pending_since[:10]` instead of `created_at[:10]`.
For entries without `created_at`, this was previously blank; now shows mtime-derived date.
