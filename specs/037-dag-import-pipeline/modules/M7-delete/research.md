# Research: KB Soft Delete (M7)

**Phase 0 output** | 2026-06-24

## Decision Log

### D-001: File Move Mechanism

**Decision**: Use `shutil.move(src, dst)` directly.

**Rationale**: `atomic_write()` is designed for write-new-content operations. Soft delete is a move-file operation; `shutil.move()` is the standard Python idiom. Atomicity is not critical here because the source file is the authoritative copy — if the process dies mid-move, the file remains at the source and can be retried.

**Alternatives considered**: `atomic_write` + unlink — unnecessarily complex; `os.rename()` — fails across filesystem boundaries (e.g., temp to home).

---

### D-002: Cascade Condition

**Decision**: Cascade only when ALL THREE conditions hold:
1. `type == "pitfall"`
2. `parent_id` is absent/None (root node)
3. `pitfall_structure == "tree"` AND `child_entry_ids` is non-empty

**Rationale**: Old-format pitfall entries (`pitfall_structure: flat` or field absent) have no `child_entry_ids` and must not cascade. This matches the brief's explicit rule: "旧 pitfall entries（`pitfall_structure: flat` 或缺省）不级联".

**Alternatives considered**: Only checking `child_entry_ids` — could accidentally cascade a manually-malformed old entry; checking only `type == "pitfall"` — too broad.

---

### D-003: Trash Directory Structure

**Decision**: `_trash/<type>/<category>/` — mirrors confirmed space, not pending space.

**Rationale**: Both pending (`_pending/pitfall/hardware/`) and confirmed (`pitfall/hardware/`) entries map to the same `_trash/pitfall/hardware/` destination. This simplifies restore: the user always looks in `_trash/<type>/<category>/` regardless of origin.

**Alternatives considered**: `_trash/_pending/<type>/<category>/` for pending entries — adds complexity, no benefit since `_trash/` is already separate.

---

### D-004: Filename Collision Handling

**Decision**: Append `-<YYYYMMDD-HHMMSS>` to the stem when the target path already exists.

**Rationale**: Git history tracks deletion time; the timestamp suffix ensures no data loss on re-deletion of a previously restored entry. ISO-style timestamp avoids colons (not allowed in filenames on some systems).

**Alternatives considered**: Append a counter (`-1`, `-2`) — ambiguous ordering; overwrite — data loss risk.

---

### D-005: HolmesLogger Integration

**Decision**: Write `kb.delete` span in the CLI command (not in `move_to_trash()`).

**Rationale**: `move_to_trash()` is a pure store-layer function that should not depend on logging. The CLI command owns the logger instance and knows the user, duration, and cascade flag.

**Alternatives considered**: Logging inside `move_to_trash()` — violates single responsibility; requires logger parameter threading.

---

### D-006: find_entry() Scope

**Decision**: Use existing `find_entry()` which already scans `_pending/` and confirmed directories via `rglob`.

**Rationale**: `find_entry()` was updated in M1 to scan both spaces. No changes needed.

**Note**: `find_entry()` skips files starting with `_` — this is fine since entry files never start with `_`.

---

### D-007: collect_tree() for Cascade

**Decision**: Reuse `collect_tree(kb_root, root_id)` from M6b.

**Rationale**: `collect_tree()` already does DFS traversal of `child_entry_ids`, handles cycles, and searches both `_pending/` and confirmed spaces. No need to reimplement.
