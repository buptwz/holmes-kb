# Tasks: KB Soft Delete (M7 — holmes kb delete)

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M7-delete/`

**Prerequisites**: spec.md, plan.md, research.md, data-model.md

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths included in all descriptions

---

## Phase 1: Setup

**Purpose**: No new infrastructure needed — this feature extends existing `store.py` and `cli.py`.

- [x] T001 Verify branch is dev-M7 and working directory is `/home/wangzhi/project/projectTmp/holmes/holmes/kb/`

---

## Phase 2: Foundational (Blocking — move_to_trash() core)

**Purpose**: The `move_to_trash()` function is the shared foundation for all user stories. Must be complete before CLI command can be implemented.

**⚠️ CRITICAL**: All user story CLI tasks depend on this phase.

- [x] T002 Implement `move_to_trash(kb_root, entry_id, cascade=True) -> list[str]` in `kb/holmes/kb/store.py` — single-entry path: `find_entry()` lookup, read frontmatter for `type`/`category`, compute `_trash/<type>/<category>/<filename>` target, `mkdir(parents=True, exist_ok=True)`, `shutil.move()`, return moved paths
- [x] T003 Add cascade branch to `move_to_trash()` in `kb/holmes/kb/store.py` — condition: `type=="pitfall" AND parent_id is None AND pitfall_structure=="tree" AND child_entry_ids non-empty AND cascade==True`; call `collect_tree(kb_root, entry_id)` to get all IDs; loop and move each; skip missing files with warning
- [x] T004 Add filename collision handling to `move_to_trash()` in `kb/holmes/kb/store.py` — if `dst.exists()`, set `dst = dst_dir / f"{src.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{src.suffix}"`

**Checkpoint**: `move_to_trash()` is importable and handles single-entry, cascade, and collision cases.

---

## Phase 3: User Story 1 — Delete a Single Non-Root Entry (Priority: P1) MVP

**Goal**: `holmes kb delete <process-sub-entry-id>` moves exactly one file to `_trash/<type>/<category>/` without affecting siblings.

**Independent Test**: Create a confirmed process sub-entry + an unrelated pitfall entry, run `holmes kb delete <sub-entry-id>`, verify only the sub-entry moved to `_trash/`, pitfall entry untouched.

### Implementation for User Story 1

- [x] T005 [US1] Add `holmes kb delete` command to `kb/holmes/cli.py` under the `kb` group: `@kb.command("delete")`, `@click.argument("entry_id")`, `@click.option("--no-cascade", is_flag=True)`, `@click.option("--force", is_flag=True)` — two-phase flow: call `move_to_trash()` with `cascade=not no_cascade` to collect paths (preview), display list, prompt confirmation, then execute (use `shutil.move` directly in the actual move phase or call `move_to_trash()` again)
- [x] T006 [US1] Implement preview-then-confirm flow in `holmes kb delete` in `kb/holmes/cli.py`: call `find_entry()` + `collect_tree()` (dry-run: collect IDs without moving), display "Will move N file(s) to _trash/:", list each path, prompt `click.confirm("Proceed?", default=True)` (skip if `--force`), then call `move_to_trash()` for actual execution
- [x] T007 [P] [US1] Write unit test `test_move_to_trash_single_entry` in `kb/tests/test_delete.py`: create confirmed process sub-entry in `tmp_path/process/hardware/`, call `move_to_trash(tmp_path, entry_id)`, assert file exists at `tmp_path/_trash/process/hardware/<filename>` and not at original path
- [x] T008 [P] [US1] Write unit test `test_move_to_trash_pending_entry` in `kb/tests/test_delete.py`: create pending entry in `tmp_path/_pending/process/hardware/`, call `move_to_trash(tmp_path, entry_id)`, assert file moved to `tmp_path/_trash/process/hardware/<filename>`

**Checkpoint**: `holmes kb delete <sub-entry-id>` works end-to-end; T007 and T008 pass.

---

## Phase 4: User Story 2 — Cascade Delete a Pitfall Root Tree (Priority: P1)

**Goal**: `holmes kb delete <pitfall-root-id>` moves root + all descendant process entries to `_trash/`. `--no-cascade` moves only the root.

**Independent Test**: Create a pitfall root with `pitfall_structure: tree` + 2 process sub-entries linked via `child_entry_ids`. Run `holmes kb delete <root-id>` → 3 files moved. Run again with `--no-cascade` on a fresh tree → 1 file moved.

### Implementation for User Story 2

- [x] T009 [US2] Verify cascade logic in `move_to_trash()` (from T003) is correctly invoked from CLI: ensure `--no-cascade` flag maps to `cascade=False` in the `holmes kb delete` command in `kb/holmes/cli.py`
- [x] T010 [P] [US2] Write unit test `test_move_to_trash_cascade_pitfall_root` in `kb/tests/test_delete.py`: create pitfall root with `pitfall_structure: tree`, `child_entry_ids: [child-001]`, and process sub-entry `child-001`; call `move_to_trash(tmp_path, root_id, cascade=True)`; assert both root and child moved to `_trash/`
- [x] T011 [P] [US2] Write unit test `test_move_to_trash_no_cascade` in `kb/tests/test_delete.py`: same setup as T010; call `move_to_trash(tmp_path, root_id, cascade=False)`; assert only root moved; child entry still at original location
- [x] T012 [P] [US2] Write unit test `test_move_to_trash_legacy_flat_pitfall` in `kb/tests/test_delete.py`: create pitfall entry without `pitfall_structure` field and without `child_entry_ids`; call `move_to_trash(tmp_path, root_id, cascade=True)`; assert only root moved, no errors raised

**Checkpoint**: Cascade and no-cascade paths both work; T010, T011, T012 pass.

---

## Phase 5: User Story 3 — --force Flag (Priority: P2)

**Goal**: `holmes kb delete <id> --force` deletes without interactive confirmation.

**Independent Test**: Run `holmes kb delete <id> --force` in a non-TTY context; assert files are moved without any prompt.

### Implementation for User Story 3

- [x] T013 [US3] Verify `--force` flag skips `click.confirm()` in `holmes kb delete` in `kb/holmes/cli.py` — the flag was added in T005; confirm the conditional branch `if not force: click.confirm(...)` is present and correct

---

## Phase 6: User Story 4 — Filename Collision in _trash/ (Priority: P2)

**Goal**: Re-deleting a previously restored entry that already exists in `_trash/` produces a timestamped variant, not an overwrite.

**Independent Test**: Manually place a file in `_trash/pitfall/hardware/test-entry.md`, then call `move_to_trash()` for an entry whose target name is the same; assert both files exist in `_trash/` with different names.

### Implementation for User Story 4

- [x] T014 [P] [US4] Write unit test `test_move_to_trash_filename_collision` in `kb/tests/test_delete.py`: pre-create `tmp_path/_trash/pitfall/hardware/entry.md`; call `move_to_trash()` for a pitfall entry that would also land at `entry.md`; assert `_trash/` contains two files (original + timestamped variant)

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Observability and output messaging.

- [x] T015 Add `HolmesLogger` import and `kb.delete` span write to `holmes kb delete` in `kb/holmes/cli.py`: after successful deletion, call `logger.write_span(trace_id, "kb.delete", "INFO", "deleted", entry_id=entry_id, user=cfg.username or "unknown", cascade=not no_cascade, duration_ms=int((time.time()-t0)*1000))`; use `derive_trace_id(entry_id)` for `trace_id`; import `time` at top of file
- [x] T016 [P] Print completion message in `holmes kb delete` in `kb/holmes/cli.py`: "Moved N file(s) to _trash/. Recoverable via: git checkout HEAD -- <path>" for each moved file

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS Phases 3–7
- **Phase 3 (US1)**: Depends on Phase 2 — no other story dependencies
- **Phase 4 (US2)**: Depends on Phase 2 — no other story dependencies (can run in parallel with Phase 3)
- **Phase 5 (US3)**: Depends on Phase 3 (--force is part of the same CLI command)
- **Phase 6 (US4)**: Depends on Phase 2 (only tests `move_to_trash()` collision)
- **Phase 7 (Polish)**: Depends on Phases 3–6

### Task-Level Dependencies

- T003 depends on T002 (cascade extends single-entry logic)
- T004 depends on T002 (collision handling extends move logic)
- T005, T006 depend on T002, T003, T004 (CLI wraps move_to_trash)
- T009 depends on T005, T006 (verifies cascade wiring in CLI)
- T013 depends on T005 (verifies --force wiring)
- T015, T016 depend on T005, T006 (polish on top of working CLI)

### Parallel Opportunities

- T007 and T008 can run in parallel (different test cases, same file is fine for test writing)
- T010, T011, T012, T014 can be written in parallel
- T015 and T016 can run in parallel (different sections of cli.py command)

---

## Implementation Strategy

### MVP (User Stories 1 + 2 only)

1. Complete Phase 2: Implement `move_to_trash()` with single-entry + cascade + collision
2. Complete Phase 3: Add `holmes kb delete` CLI command with preview+confirm
3. Complete Phase 4: Verify cascade and --no-cascade wiring
4. **STOP and VALIDATE**: Run T007, T008, T010, T011, T012 — all should pass
5. Proceed to Phase 5–7 for --force, collision test, and logging

### Full Delivery

1. Phases 2–4 → Core deletion working
2. Phase 5 → --force added
3. Phase 6 → Collision test added
4. Phase 7 → Logging + output polish

---

## Notes

- All test tasks write to `kb/tests/test_delete.py` (new file)
- `move_to_trash()` must be exported from `holmes.kb.store` (add to existing module)
- `shutil` is already imported in `cli.py` — add `import time` for duration logging
- `HolmesLogger` is already imported in `cli.py`
- Constitution compliance: no abstraction layers added, single responsibility maintained
