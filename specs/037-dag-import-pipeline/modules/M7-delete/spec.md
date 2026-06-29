# Feature Specification: KB Soft Delete (holmes kb delete)

**Feature Branch**: `dev-M7`

**Created**: 2026-06-24

**Status**: Draft

**Input**: M7 — holmes kb delete（垃圾箱）: 为所有 KB entry 提供软删除能力

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Delete a Single Non-Root Entry (Priority: P1)

A KB maintainer wants to remove an incorrect or outdated process sub-entry without affecting sibling nodes or the parent pitfall tree structure.

**Why this priority**: Most common deletion case; establishing correct single-entry soft delete is the foundation for cascade logic.

**Independent Test**: Run `holmes kb delete <process-sub-entry-id>` and verify only that file is moved to `_trash/`, sibling nodes remain intact.

**Acceptance Scenarios**:

1. **Given** a confirmed process sub-entry exists at `process/hardware/gpu-check-001.md`, **When** `holmes kb delete gpu-check-001` is run and user confirms, **Then** the file is moved to `_trash/process/hardware/gpu-check-001.md` and no other files are affected.
2. **Given** a pending process sub-entry exists at `_pending/process/hardware/gpu-check-001.md`, **When** `holmes kb delete gpu-check-001` is run, **Then** the file is moved to `_trash/process/hardware/gpu-check-001.md`.
3. **Given** deletion is confirmed, **When** `git status` is checked, **Then** the moved file is visible as a tracked git change (not gitignored).

---

### User Story 2 - Cascade Delete a Pitfall Root Tree (Priority: P1)

A KB maintainer wants to remove an entire pitfall tree (root + all associated process entries) because the troubleshooting scenario is no longer relevant.

**Why this priority**: Cascade delete is the primary safety-critical behavior; incorrect cascade could delete unrelated entries.

**Independent Test**: Run `holmes kb delete <pitfall-root-id>` on a tree with 3 process sub-entries; verify all 4 files moved to `_trash/`.

**Acceptance Scenarios**:

1. **Given** a pitfall root entry with `pitfall_structure: tree` and two process sub-entries, **When** `holmes kb delete <root-id>` is run with confirmation, **Then** root + both sub-entries are moved to `_trash/<type>/<category>/`.
2. **Given** same pitfall root, **When** `holmes kb delete <root-id> --no-cascade` is run, **Then** only the root file is moved to `_trash/`, sub-entries remain in place.
3. **Given** a pitfall root with `pitfall_structure: flat` (legacy, no `child_entry_ids`), **When** `holmes kb delete <root-id>` is run, **Then** only the root is moved (no cascade), no errors raised.

---

### User Story 3 - Skip Confirmation with --force (Priority: P2)

A KB maintainer running automated cleanup wants to skip the interactive confirmation prompt.

**Why this priority**: Needed for scripted/batch workflows; does not change the deletion semantics.

**Independent Test**: Run `holmes kb delete <id> --force` and verify files are moved without any prompts.

**Acceptance Scenarios**:

1. **Given** a valid entry ID, **When** `holmes kb delete <id> --force` is run, **Then** deletion proceeds immediately without asking "Confirm? [Y/n]".
2. **Given** `--force` is used, **When** deletion completes, **Then** a summary "Moved N file(s) to _trash/. Recoverable via git checkout." is printed.

---

### User Story 4 - Conflict Resolution: Filename Already in _trash/ (Priority: P2)

A KB maintainer deletes a previously-restored entry that was already once moved to `_trash/`.

**Why this priority**: Prevents silent data loss from overwriting an existing trashed file.

**Acceptance Scenarios**:

1. **Given** `_trash/pitfall/hardware/old-gpu-issue.md` already exists, **When** a new deletion of `old-gpu-issue` is triggered, **Then** the new file is saved as `_trash/pitfall/hardware/old-gpu-issue-<timestamp>.md` and the original is not overwritten.

---

### Edge Cases

- What happens when the entry ID does not exist? → Error "Entry not found: <id>", exit code 1.
- What happens when a child entry in a cascade tree is missing on disk? → Skip that child, print a warning, continue with remaining entries.
- What happens when `_trash/<type>/<category>/` does not exist? → Directory is created automatically before moving.
- What happens when the user answers "n" at the confirmation prompt? → Deletion aborted, no files moved, exit code 0.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST move entry files to `_trash/<type>/<category>/` rather than deleting them from disk (soft delete).
- **FR-002**: `move_to_trash()` MUST accept `kb_root`, `entry_id`, and `cascade` (default `True`) parameters and return a list of moved file paths.
- **FR-003**: When `cascade=True` and the entry is a pitfall root with `pitfall_structure: tree` and non-empty `child_entry_ids`, the system MUST use `collect_tree()` to collect all descendant entry IDs and move them all to `_trash/`.
- **FR-004**: When `cascade=False` OR the entry is not a pitfall tree root, the system MUST move only the single entry file.
- **FR-005**: Legacy pitfall entries with `pitfall_structure: flat` or missing `pitfall_structure`/`child_entry_ids` MUST be treated as non-cascade (only self deleted).
- **FR-006**: Both pending entries (`_pending/<type>/<category>/`) and confirmed entries (`<type>/<category>/`) MUST be deletable; both are moved to `_trash/<type>/<category>/` (pending prefix is dropped).
- **FR-007**: If a file with the same name already exists in `_trash/`, the system MUST append `-<ISO-timestamp>` to the filename stem to avoid overwriting.
- **FR-008**: If a child entry file is not found on disk during cascade, the system MUST log a warning and skip that entry without aborting.
- **FR-009**: The `_trash/<type>/<category>/` directory MUST be created automatically if it does not exist.
- **FR-010**: The CLI command `holmes kb delete <id>` MUST show a preview of files to be moved and prompt for confirmation before executing.
- **FR-011**: The `--no-cascade` flag MUST override cascade behavior for pitfall root nodes.
- **FR-012**: The `--force` flag MUST skip the confirmation prompt.
- **FR-013**: After successful deletion, the CLI MUST write a `kb.delete` span via `HolmesLogger` with fields: `entry_id`, `user`, `cascade`, `duration_ms`.
- **FR-014**: The `find_entry()` function's existing scan of both confirmed and pending spaces ensures entry lookup works for both states.

### Key Entities

- **EntryFile**: A Markdown file with YAML frontmatter; has `id`, `type`, `category`, `parent_id`, `child_entry_ids`, `pitfall_structure` fields.
- **TrashDirectory**: `_trash/<type>/<category>/` — the destination for soft-deleted entries; git-tracked.
- **CollectTree**: The existing `collect_tree()` function in `store.py` — DFS traversal of `child_entry_ids`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `holmes kb delete <process-sub-entry-id>` moves exactly 1 file to `_trash/` and leaves all other KB files untouched.
- **SC-002**: `holmes kb delete <pitfall-root-id>` (default cascade) moves root + all descendant process entries in a single operation.
- **SC-003**: `holmes kb delete <pitfall-root-id> --no-cascade` moves exactly 1 file regardless of tree size.
- **SC-004**: Deleted files remain visible in `git status` and are recoverable via `git checkout`.
- **SC-005**: All 5 required unit test scenarios pass (single non-root, cascade root, no-cascade, pending entry, legacy flat pitfall).
- **SC-006**: Filename collision in `_trash/` produces a timestamped variant with no data loss.

## Assumptions

- `find_entry()` already scans both `_pending/` and confirmed type directories — no changes needed to lookup logic.
- `collect_tree()` already exists in `store.py` (added in M6b) and correctly traverses arbitrary-depth trees.
- `HolmesLogger` is available from `holmes.kb.logger` (added in M8/M9); the `kb.delete` span is fire-and-forget.
- `config.username` is available via `load_config()` for logging the `user` field.
- Files in `_trash/` are not gitignored — they follow the KB git-tracked convention.
- The `shutil.move()` approach is sufficient; no atomic write wrapper is needed since `_trash/` moves are non-critical (original file is already moved away).
- The CLI runs interactively by default; `--force` is available for non-interactive use.
