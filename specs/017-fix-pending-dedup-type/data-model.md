# Data Model: Import Pipeline — Pending Dedup & Type Override

**Branch**: `017-fix-pending-dedup-type` | **Date**: 2026-06-09

---

## Existing Entities (unchanged schema)

### PendingEntry
Location: `contributions/pending/<pending_id>.md`

| Field | Type | Description |
|-------|------|-------------|
| `pending_id` | `str` | Unique ID (e.g. `pending-20260609-abc123`) |
| `source_hash` | `str` | 16-char SHA-derived hash of source document |
| `type` | `str` | KB entry type: `pitfall` / `model` / `guideline` / `process` / `decision` |
| `title` | `str` | Entry title (LLM-generated) |
| `import_confidence` | `float` | LLM classification confidence |

No schema changes required for D-5 or E-2. The `source_hash` field is already written to every pending entry by `write_kb_entry`.

---

## Changed Behavior (not schema changes)

### `_find_entry_by_hash(kb_root, source_hash)` — extended scan scope

**Before**: Scans only `list_entries(kb_root)` (approved KB entries).

**After**: Scans approved KB entries first; if no match, scans `contributions/pending/*.md` by reading each file's frontmatter and comparing `source_hash`. Returns on first match.

Return type unchanged: `tuple[str | None, str | None]` → `(entry_id_or_pending_id, file_path)`.

---

### `ImportAgentRunner` — new `force_type` field

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `force_type` | `Optional[str]` | `None` | When set, overrides LLM-classified `type` field |

### `ThreePhaseImportPipeline` — new `force_type` field

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `force_type` | `Optional[str]` | `None` | Propagated from runner; applied post-extraction |

---

## Valid Type Values

`pitfall` | `model` | `guideline` | `process` | `decision`

Validated at CLI entry point (`import_cmd`) before runner construction. Invalid values produce an immediate error with the valid set listed.
