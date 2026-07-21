# Tasks: KB Store Internal Cleanup

**Input**: Design documents from `/specs/026-kb-store-cleanup/`

**Prerequisites**: plan.md, spec.md

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Verify baseline before making changes.

- [ ] T001 Run existing test suite and record baseline: `cd kb && python -m pytest -q`
- [ ] T002 Confirm zero callers: `grep -r "update_references" kb/ agent/ tui/ --include="*.py"` must return zero results outside store.py itself

---

## Phase 2: User Story 1 — Remove Dead Code update_references() (Priority: P1)

**Goal**: 删除 `kb/holmes/kb/store.py` 中的 `update_references()` 函数及其相关 import，消除与 `append_evidence()` 并行的 maturity 逻辑。

**Independent Test**: 删除后 `grep -r "update_references" .` 返回零结果；`cd kb && python -m pytest -q` 无回归。

### Implementation for User Story 1

- [ ] T003 [US1] In `kb/holmes/kb/store.py`: delete the entire `update_references()` function (function signature, docstring, and body — approximately lines 348–394); do not leave any remnant stub or comment placeholder
- [ ] T004 [US1] In `kb/holmes/kb/store.py`: check if `datetime.timezone` is used anywhere other than the deleted `update_references()` function; if `timezone` is only used there, remove `timezone` from the `from datetime import datetime, timezone` import line (keep `datetime` if still needed, or simplify to `from datetime import datetime`)
- [ ] T005 [US1] Verify removal: run `grep -rn "update_references" kb/` and confirm zero matches; run `cd kb && python -m pytest -q` and confirm no regressions

**Checkpoint**: US1 complete — single authoritative maturity path via `append_evidence()`.

---

## Phase 3: User Story 2 — Remove Orphaned EntryMeta Fields (Priority: P2)

**Goal**: 从 `EntryMeta` dataclass 删除 `last_referenced` 和 `reference_count` 字段及其在 `list_entries()` 中的 frontmatter 读取行。

**Independent Test**: 删除后 `grep -rn "last_referenced\|reference_count" kb/holmes/` 返回零结果（生产代码中）；`cd kb && python -m pytest -q` 无回归；decay 测试仍通过。

### Implementation for User Story 2

- [ ] T006 [US2] In `kb/holmes/kb/store.py` `EntryMeta` dataclass: remove the field `last_referenced: str = ""` and the field `reference_count: int = 0`; these two lines are the only changes to the dataclass definition
- [ ] T007 [US2] In `kb/holmes/kb/store.py` `list_entries()` function: remove the two lines `last_referenced=str(meta.get("last_referenced", "")),` and `reference_count=int(meta.get("reference_count", 0)),` from the `EntryMeta(...)` constructor call
- [ ] T008 [US2] Check `kb/tests/test_store.py` for any assertions on `EntryMeta.last_referenced` or `EntryMeta.reference_count`; if found, remove those specific assertion lines (do not remove the surrounding test functions unless they test only these fields)
- [ ] T009 [US2] Run `cd kb && python -m pytest -q` and confirm no regressions; additionally run `cd kb && python -m pytest tests/test_store.py -q -k "decay or evidence or maturity"` to confirm decay-related tests pass

**Checkpoint**: US2 complete — `EntryMeta` no longer carries dead fields; `list_entries()` no longer reads unused frontmatter.

---

## Phase 4: User Story 3 — Fix Search Evidence Loading O(n×m) → O(m) (Priority: P3)

**Goal**: 在 `kb/holmes/kb/search.py` 的 `LinearScanBackend.search()` 中，将 per-entry `load_evidence()` + `get_last_evidence_date()` 调用替换为一次性 `_build_evidence_date_index()` 扫描。

**Independent Test**: 现有 `test_search_ranks_evidence_entry_higher` 和 `test_search_no_evidence_falls_back_to_score` 无修改通过；代码检查确认 `load_evidence` 不再出现在 `search()` 方法体内。

### Implementation for User Story 3

- [ ] T010 [US3] Add private module-level function `_build_evidence_date_index(kb_root: Path) -> dict` to `kb/holmes/kb/search.py`: the function scans `kb_root / "contributions/evidence/"` (return empty dict if directory does not exist); for each subdirectory (subdirectory name = entry_id), read all `*.json` files, parse each as JSON dict, extract the `"date"` field string; return `{entry_id: max_date_string}` where max_date is the lexicographic maximum across all session files for that entry_id; handle all exceptions silently (try/except pass per file)
- [ ] T011 [US3] In `kb/holmes/kb/search.py` `LinearScanBackend.search()` method: add a single call `date_index = _build_evidence_date_index(self._kb_root)` immediately before the `for type_dir in search_roots:` loop
- [ ] T012 [US3] In `kb/holmes/kb/search.py` `LinearScanBackend.search()` method: replace the two lines `evidence = load_evidence(self._kb_root, entry_id_str)` and `led = get_last_evidence_date(evidence)` with a single line `led = date_index.get(entry_id_str)`
- [ ] T013 [US3] In `kb/holmes/kb/search.py`: remove the import line `from holmes.kb.store import get_last_evidence_date, load_evidence` since `load_evidence` and `get_last_evidence_date` are no longer called directly in this file
- [ ] T014 [US3] Run `cd kb && python -m pytest tests/test_search.py -q` and confirm both `test_search_ranks_evidence_entry_higher` and `test_search_no_evidence_falls_back_to_score` pass without modification

**Checkpoint**: US3 complete — search evidence loading is O(m) instead of O(n×m).

---

## Phase 5: Polish & Validation

**Purpose**: Full regression check confirming all three user stories have no mutual interference.

- [ ] T015 Run full KB test suite: `cd kb && python -m pytest -q` — confirm no regressions; record final test count
- [ ] T016 Verify dead code fully gone: `grep -rn "update_references\|last_referenced\|reference_count" kb/holmes/` — confirm zero results in production code
- [ ] T017 Verify search no longer calls load_evidence in loop: `grep -n "load_evidence" kb/holmes/kb/search.py` — confirm zero results (all calls replaced by index lookup)
- [ ] T018 Confirm store.py net line reduction: `wc -l kb/holmes/kb/store.py` — should be at least 50 lines fewer than baseline

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **US1 (Phase 2)**: Depends on Phase 1
- **US2 (Phase 3)**: Depends on US1 (fields are owned by the function being removed in US1)
- **US3 (Phase 4)**: Depends on Phase 1; **fully independent of US1 and US2** (different file)
- **Polish (Phase 5)**: Depends on US1 + US2 + US3 completion

### Within Each User Story

- T003 → T004 → T005: sequential (same file, each builds on previous deletion)
- T006 → T007 → T008 → T009: sequential (same file, each builds on previous deletion)
- T010 → T011 → T012 → T013 → T014: sequential (same file, each line depends on previous)

### Parallel Opportunities

- **US3 (Phase 4) and US1+US2 (Phases 2+3)** can be worked in parallel — zero file overlap

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: US1 (delete update_references)
3. **STOP and VALIDATE**: pytest passes, grep confirms zero callers
4. Proceed to US2 (EntryMeta fields), then US3 (search I/O)

### Incremental Delivery

1. Setup → baseline confirmed
2. US1 → dead function removed (most critical, highest confusion risk)
3. US2 → orphaned fields cleaned up (follows naturally from US1)
4. US3 → search I/O optimized (independent, different file)
5. Polish → full regression check

---

## Notes

- Do NOT modify `decay.py` — its `_get_reference_date()` method reads from the entry's frontmatter dict directly, not from `EntryMeta.last_referenced`
- Do NOT modify `agent/holmes/kb/store.py` — it is a separate lightweight module with its own `append_evidence()` implementation
- `update_references()` uses `reference_count` field in frontmatter writes — after deletion, that frontmatter key may remain in existing KB files but is harmless (ignored by all active code)
- Baseline test count from feature 025: approximately 737 tests; final count should remain the same (no new tests needed unless US3 verification test is added)
