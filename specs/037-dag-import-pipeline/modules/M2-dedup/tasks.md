# Tasks: M2-dedup — Step 0 去重与更新检测

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M2-dedup/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: 创建测试文件骨架，无依赖

- [X] T001 Create test file skeleton `kb/tests/test_m2_dedup.py` with fixtures (tmp kb_root, pending dir, sample frontmatter helper)

---

## Phase 2: Foundational — store.py 扩展（所有 US 的前置）

**Purpose**: EntryMeta 新字段 + 两个查询函数，所有用户故事依赖这些

**⚠️ CRITICAL**: 所有 User Story 实现必须等 Phase 2 完成后才能开始

- [X] T002 Add `source_hash: str = ""` and `source_file: str = ""` fields to `EntryMeta` dataclass in `kb/holmes/kb/store.py`
- [X] T003 Update `list_entries()` in `kb/holmes/kb/store.py` to populate `source_hash` and `source_file` from `meta.get("source_hash", "")` and `meta.get("source_file", "")` in both confirmed and pending scanning branches
- [X] T004 [P] Implement `find_entries_by_source_hash(kb_root: Path, source_hash: str) -> list[EntryMeta]` in `kb/holmes/kb/store.py` — scans confirmed type dirs + `contributions/pending/*.md`; returns `[]` immediately if `source_hash` is empty string
- [X] T005 [P] Implement `find_entries_by_source_file(kb_root: Path, source_file: str) -> list[EntryMeta]` in `kb/holmes/kb/store.py` — scans same two spaces; normalises paths with `Path(x).as_posix()` for comparison; returns `[]` if `source_file` is empty

**Checkpoint**: `find_entries_by_source_hash` and `find_entries_by_source_file` available in store.py — User Story phases can now begin

---

## Phase 3: User Story 1 — 完全重复跳过 (Priority: P1) 🎯 MVP

**Goal**: import 完全相同文档时不启动 LLM pipeline

**Independent Test**: `pytest kb/tests/test_m2_dedup.py -k hash` 全绿

### Implementation

- [X] T006 [US1] Add `_compute_source_file(kb_root, file_path) -> str` private helper in `kb/holmes/kb/agent/pipeline.py` (returns `file_path.relative_to(kb_root).as_posix()` or `""` on ValueError)
- [X] T007 [US1] Refactor `pipeline.py` `run()`: replace the existing `if not self.dry_run:` hash-dedup block (lines ~114-150) with new Step 0 structure — wrap in `if not self.force:` guard; move `--force`-clears-pending logic into the `self.force` branch (before the Step 0 check)
- [X] T008 [US1] Implement Step 0a in `pipeline.py` `run()`: call `find_entries_by_source_hash(kb_root, source_hash)`; if matches found → append ids to `report.skipped`, append warning "已存在完全相同的文档，跳过导入", return report

### Tests

- [X] T009 [P] [US1] Test: hash match in confirmed space → report.skipped contains entry id, pipeline does NOT proceed in `kb/tests/test_m2_dedup.py`
- [X] T010 [P] [US1] Test: hash match in pending space → skip in `kb/tests/test_m2_dedup.py`
- [X] T011 [P] [US1] Test: empty source_hash in existing entry is NOT matched (legacy entry safety) in `kb/tests/test_m2_dedup.py`

**Checkpoint**: 重复文档导入被正确跳过，MVP 可交付

---

## Phase 4: User Story 2 — 文档更新检测 + Pending 清理 (Priority: P1)

**Goal**: 同路径不同内容的文档触发更新流程并处理旧 pending

**Independent Test**: `pytest kb/tests/test_m2_dedup.py -k update` 全绿

### Implementation

- [X] T012 [US2] Implement Step 0b in `pipeline.py` `run()`: after Step 0a, compute `source_file` via `_compute_source_file`; if `source_file` non-empty, call `find_entries_by_source_file(kb_root, source_file)`; if matches found → print update notice with oldest `created_at` from matches
- [X] T013 [US2] Add `_is_pending_entry(entry: EntryMeta) -> bool` in `pipeline.py` — returns `True` if `"contributions/pending"` in `entry.file_path`
- [X] T014 [US2] Add `_prompt_cancel_old_pending(old_pending, no_interactive, kb_root, dry_run)` in `pipeline.py` — in interactive mode: `click.confirm(...)` defaulting True; Y path: call `delete_pending(kb_root, e.id)` for each; `no_interactive` or `dry_run`: auto-n (no deletion)
- [X] T015 [US2] Wire `_prompt_cancel_old_pending` into Step 0b: after printing update notice, filter `old_pending = [m for m in matches if _is_pending_entry(m)]`; if non-empty call `_prompt_cancel_old_pending`

### Tests

- [X] T016 [P] [US2] Test: source_file match + different hash → update notice printed, pipeline continues in `kb/tests/test_m2_dedup.py`
- [X] T017 [P] [US2] Test: old pending found + user answers Y → pending files deleted in `kb/tests/test_m2_dedup.py`
- [X] T018 [P] [US2] Test: old pending found + user answers n → pending files NOT deleted in `kb/tests/test_m2_dedup.py`
- [X] T019 [P] [US2] Test: `no_interactive=True` with old pending → auto-n, no deletion in `kb/tests/test_m2_dedup.py`
- [X] T020 [P] [US2] Test: `dry_run=True` + old pending → no deletion (dry_run semantics) in `kb/tests/test_m2_dedup.py`

**Checkpoint**: 文档更新场景完整工作

---

## Phase 5: User Story 3 — 全新文档正常导入 (Priority: P2)

**Goal**: 全新文档不触发任何 Step 0 分支，pipeline 零干扰正常运行

**Independent Test**: `pytest kb/tests/test_m2_dedup.py -k new_doc` 全绿

### Tests (no new implementation needed — covered by existing pipeline flow)

- [X] T021 [P] [US3] Test: no hash match + no source_file match → no warnings, report.skipped empty, pipeline proceeds in `kb/tests/test_m2_dedup.py`
- [X] T022 [P] [US3] Test: source_file outside kb_root (file_path=None or external path) → source_file="" → Step 0b skipped in `kb/tests/test_m2_dedup.py`

**Checkpoint**: 全新文档导入完全无干扰

---

## Phase 6: User Story 4 — --force 跳过去重 (Priority: P2)

**Goal**: `--force` 完全绕过 Step 0 所有检测

**Independent Test**: `pytest kb/tests/test_m2_dedup.py -k force` 全绿

### Tests (no new implementation needed — T007 already adds `if not self.force:` guard)

- [X] T023 [P] [US4] Test: `force=True` + confirmed hash match → no skip, no warning in `kb/tests/test_m2_dedup.py`
- [X] T024 [P] [US4] Test: `force=True` + source_file match + old pending → no prompt, old pending preserved in `kb/tests/test_m2_dedup.py`

**Checkpoint**: --force 完整工作

---

## Phase 7: Polish & Cross-Cutting

- [X] T025 [P] Run full test suite `pytest kb/tests/` to verify no regressions from EntryMeta / list_entries changes
- [X] T026 [P] Add `find_entries_by_source_hash` and `find_entries_by_source_file` to `kb/holmes/kb/store.py` module `__all__` (if defined)
- [X] T027 Verify `kb/tests/test_store.py` still passes after EntryMeta field additions (backwards-compat check)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** (Setup): No dependencies
- **Phase 2** (Foundation): Depends on Phase 1 — BLOCKS all user stories
- **Phase 3** (US1): Depends on Phase 2
- **Phase 4** (US2): Depends on Phase 2 + Phase 3 (Step 0a must exist before Step 0b)
- **Phase 5** (US3): Depends on Phase 2 (no new code, just tests)
- **Phase 6** (US4): Depends on Phase 3 (--force guard in T007)
- **Phase 7** (Polish): Depends on all prior phases

### Parallel Opportunities

- T004 and T005 can run in parallel (both are new functions in store.py, different function bodies)
- T009, T010, T011 can all be written in parallel (different test functions in same file)
- T016–T020 can all be written in parallel
- T021–T024 can all be written in parallel
- T025 and T026 can run in parallel

---

## Implementation Strategy

### MVP First (Phase 1–3: US1 only)

1. T001: create test file
2. T002–T005: store.py foundation
3. T006–T008: Step 0a (hash dedup)
4. T009–T011: US1 tests
5. **Validate**: `pytest kb/tests/test_m2_dedup.py -k hash` all green

### Full Delivery

6. T012–T015: Step 0b (update detection)
7. T016–T020: US2 tests
8. T021–T022: US3 tests
9. T023–T024: US4 tests
10. T025–T027: polish + regression check

---

## Notes

- [P] tasks = different functions/files, can be parallelised
- [Story] label traces each task to its user story
- T007 is the most invasive: it refactors an existing code block in pipeline.py — read lines 109-151 carefully before editing
- `find_entries_by_source_hash` and `find_entries_by_source_file` share the same scan pattern; consider extracting a `_scan_all_entries(kb_root) -> list[EntryMeta]` private helper to avoid duplication
- All test mocks should use `tmp_path` fixture; no real KB files should be modified
