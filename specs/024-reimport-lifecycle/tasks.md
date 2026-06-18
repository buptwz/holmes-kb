# Tasks: Import Pipeline 永远新建策略

**Input**: Design documents from `/specs/024-reimport-lifecycle/`

**Prerequisites**: plan.md, spec.md, research.md

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2)

---

## Phase 1: Setup

**Purpose**: Verify baseline before making changes.

- [X] T001 Run existing test suite and record baseline pass count (`cd kb && python -m pytest tests/test_pipeline.py -q`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared helper functions required by both user stories.

- [X] T002 Add `_text_similarity(a, b)` (difflib.SequenceMatcher) and `_draft_dedup_key(body, metadata)` (Root Cause or title fallback) helpers to `kb/holmes/kb/agent/pipeline.py`

**Checkpoint**: Helpers available — both US1 and US2 can proceed.

---

## Phase 3: User Story 1 — 移除跨文档 dedup，pipeline 只新建 (Priority: P1)

**Goal**: `_run_dedup_pass` no longer reads or modifies existing KB entries; re-importing a document always creates new entries, leaving old ones untouched.

**Independent Test**: Run two sequential imports of the same topic with different content. Verify KB contains two independent entry batches and no existing entry was modified.

### Implementation for User Story 1

- [X] T003 [US1] Rewrite `_run_dedup_pass()` in `kb/holmes/kb/agent/pipeline.py`: remove all KB read/query calls (`read_kb_entries_by_category`, `compare_root_cause`, `atomic_write` update path); method should return an empty set for now (cross-KB dedup fully removed)
- [X] T004 [US1] Remove `_IMPORT_SYSTEM_PROMPT` step 3 (`read_kb_entries_by_category + compare_root_cause` cross-KB semantic dedup instruction) in `kb/holmes/kb/agent/runner.py`
- [X] T005 [US1] Update `_IMPORT_SYSTEM_PROMPT` step 5 in `kb/holmes/kb/agent/runner.py`: change "write_kb_entry (new) or update_kb_entry (merge)" to "write_kb_entry (new) only"
- [X] T006 [US1] Remove `_pending_dedup_match` field and the `write_kb_entry` intercept block inside `_dispatch_tool()` in `kb/holmes/kb/agent/runner.py`
- [X] T007 [P] [US1] Update `kb/tests/test_pipeline.py`: delete tests that assert cross-KB dedup updates existing entries; add test verifying that a second import of different-content document creates new entries without modifying old entries

**Checkpoint**: US1 complete — import never updates existing entries. Old cross-KB dedup tests deleted.

---

## Phase 4: User Story 2 — 单次 Import 内部草稿去重 (Priority: P2)

**Goal**: Within a single import run, KP drafts with root-cause similarity >= 0.8 are deduplicated; only the first draft is created; duplicates are annotated in ImportReport.

**Independent Test**: Import a document containing two paragraphs describing the same problem. Verify only one KB entry is created and the ImportReport.skipped list contains the duplicate draft ID with annotation.

### Implementation for User Story 2

- [X] T008 [US2] Rename `_run_dedup_pass()` to `_run_intra_import_dedup()` in `kb/holmes/kb/agent/pipeline.py` and implement draft-vs-draft similarity: maintain `seen: list[tuple[str, str]]`; for each draft extract key via `_draft_dedup_key()`; compare against all seen keys using `_text_similarity()`; if similarity >= 0.8 mark as duplicate; else append to seen; return `set[duplicate_kp_ids]`
- [X] T009 [US2] Update all call sites of `_run_dedup_pass` → `_run_intra_import_dedup` in `kb/holmes/kb/agent/pipeline.py` and add ImportReport annotation: `report.skipped.append(f"{kp_id} (intra-import duplicate of {seen_id})")` for each skipped draft
- [X] T010 [P] [US2] Add test to `kb/tests/test_pipeline.py`: same-document two identical KP drafts (pitfall type) → only 1 entry created, 1 skipped with annotation
- [X] T011 [P] [US2] Add test to `kb/tests/test_pipeline.py`: same-document two different KP drafts (different root causes) → 2 entries created, 0 skipped
- [X] T012 [P] [US2] Add test to `kb/tests/test_pipeline.py`: non-pitfall type (guideline) → title similarity used as dedup key

**Checkpoint**: US2 complete — intra-import dedup live, cross-KB dedup gone.

---

## Phase 5: Polish & Validation

**Purpose**: Confirm existing hash precheck and regression-free test suite.

- [X] T013 Verify document-level hash precheck (FR-003) still works: run existing test for identical-document re-import skip in `kb/tests/test_pipeline.py` (test should still pass unchanged)
- [X] T014 Run full test suite (`cd kb && python -m pytest -q`) and confirm no regressions; cross-KB dedup test removals should result in lower count but no failures

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1
- **US1 (Phase 3)**: Depends on Phase 2 (uses helpers added in T002)
- **US2 (Phase 4)**: Depends on Phase 2; also depends on US1 (T003 renames/stubs the method that US2 reimplements in T008)
- **Polish (Phase 5)**: Depends on US1 + US2 completion

### Within Each User Story

- T003 (stub method) before T008 (full implementation) — both touch same method
- T004, T005, T006 can run in parallel (different parts of runner.py)
- T010, T011, T012 can run in parallel (different test functions, same file)

### Parallel Opportunities

- T004, T005, T006 within US1 after T003 completes
- T010, T011, T012 within US2 after T008 + T009 complete

---

## Parallel Example: User Story 2

```text
# After T008 + T009 complete:
Task T010: test same-KP dedup (pitfall type)
Task T011: test different-KP no-dedup
Task T012: test non-pitfall title-based dedup
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational helpers
3. Complete Phase 3: US1 (cross-KB dedup removal)
4. **STOP and VALIDATE**: Run tests, confirm re-import creates new entries
5. Proceed to US2 for intra-import dedup

### Incremental Delivery

1. Setup + Foundational → helpers ready
2. US1 → cross-KB dedup gone, pipeline always creates
3. US2 → intra-import quality guard live
4. Polish → full regression check

---

## Notes

- No new external dependencies (difflib is stdlib)
- `update_kb_entry` tool is retained but not called from import pipeline (manual/external use only)
- `compare_root_cause` tool is retained (runner side may still use it)
- Existing document-level hash precheck (`_find_all_entries_by_hash`) must NOT be removed (FR-003)
- Test count: 45 baseline → 43 final (removed 8 old cross-KB dedup tests, added 6 new intra-import dedup tests)
- Full suite: 731 tests passing
