# Tasks: Import Pipeline — Pending Dedup & Type Override (D-5, E-2)

**Input**: Design documents from `specs/017-fix-pending-dedup-type/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks grouped by user story. No foundational blocking phase — both fixes are independent and can proceed in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: Mapped user story (US1–US2)

---

## Phase 1: Setup

**Purpose**: No new files or project initialization needed — all fixes are within existing files.

*(No tasks — skip to Phase 2)*

---

## Phase 2: User Story 1 — Duplicate Import Skipped at Pending Layer (P1) 🎯 MVP

**Goal**: D-5. Second import of the same document detects the existing pending entry and reports `1 skipped` instead of creating a duplicate.

**Independent Test**: Import any document twice without approving the first pending entry. Assert second run reports `0 created, 1 skipped` and pending count is unchanged.

- [X] T001 [US1] Extend `_find_entry_by_hash()` to also scan `contributions/pending/*.md` for matching `source_hash`; import `PENDING_DIR` from `holmes.kb.pending`; silently skip malformed files (D-5) in `holmes/kb/agent/tools.py`
- [X] T002 [P] [US1] Write unit tests for D-5: assert `_find_entry_by_hash` returns a match when a pending file with the same `source_hash` exists; assert it returns `(None, None)` when no match; assert corrupt pending file is skipped without error in `tests/test_tools.py`

**Checkpoint**: `python -m pytest tests/test_tools.py -q` passes. Manually verify: two imports of the same doc → second reports `1 skipped`.

---

## Phase 3: User Story 2 — `--type` Flag Forces Entry Classification (P2)

**Goal**: E-2. `holmes import <doc> --type pitfall` creates a pending entry with `type: pitfall` regardless of LLM classification.

**Independent Test**: Import a naturally-`guideline` document with `--type pitfall`. Assert created pending entry has `type: pitfall` in frontmatter.

- [X] T003 [US2] Add `force_type: Optional[str] = None` parameter to `ImportAgentRunner.__init__()`; store as `self.force_type`; pass `force_type=self.force_type` to `ThreePhaseImportPipeline` in `run()` in `holmes/kb/agent/runner.py`
- [X] T004 [US2] Add `force_type: Optional[str] = None` parameter to `ThreePhaseImportPipeline.__init__()`; after each `extractor.run()` call, if `self.force_type` is set, parse draft frontmatter and overwrite `type:` field then re-serialize before calling `_validate_and_repair_draft()`; also store `force_type` in `ctx["force_type"]` in `holmes/kb/agent/pipeline.py`
- [X] T005 [US2] In `import_cmd()`, validate `kb_type` against `VALID_KB_TYPES = {"pitfall", "model", "guideline", "process", "decision"}` and exit with clear error if invalid; pass `force_type=kb_type` to `ImportAgentRunner(...)` in `holmes/cli.py`
- [X] T006 [P] [US2] Write unit tests for E-2: assert pipeline with `force_type="pitfall"` produces draft with `type: pitfall` even when extractor returns `type: guideline`; assert `force_type=None` leaves type unchanged; assert invalid `--type` value exits with error code 1 in `tests/test_pipeline.py`

**Checkpoint**: `python -m pytest tests/test_pipeline.py tests/test_tools.py -q` passes. Manually verify: `--type pitfall` on guideline doc → pending entry has `type: pitfall`.

---

## Phase 4: Polish — Full Validation

**Purpose**: Confirm all 571 existing tests still pass after both fixes.

- [X] T007 [P] Run full test suite `python -m pytest -q` from `kb/` directory and confirm all tests pass with zero failures (regression guard)

---

## Dependencies & Execution Order

### Phase Dependencies

- **US1 (Phase 2)**: No dependencies — start immediately (T001 → T002 parallel)
- **US2 (Phase 3)**: No dependencies on US1 — T003 → T004 → T005 sequential within phase; T006 [P] parallel
- **Polish (Phase 4)**: Depends on all phases complete

### Within Each Phase

- T001 → T002 [P] (US1): T001 implements, T002 tests
- T003 → T004 → T005 (US2): runner → pipeline → cli (bottom-up dependency chain)
- T006 [P] (US2): tests in different file, parallel with T003–T005

### Parallel Opportunities

- US1 and US2 are independent (different files) — can run in parallel
- T002 [P] and T006 [P] are test tasks that can run parallel with implementation in same story

---

## Parallel Example

```
[US1] T001 (tools.py) → T002 [P] (test_tools.py)
[US2] T003 (runner.py) → T004 (pipeline.py) → T005 (cli.py) → T006 [P] (test_pipeline.py)
[US1+US2 parallel] Start both tracks simultaneously
```

---

## Implementation Strategy

### MVP First (US1 Only — P1 Highest Impact)

1. Complete Phase 2: US1 (T001–T002)
2. **STOP and VALIDATE**: Run `python -m pytest tests/test_tools.py -q` — all pass
3. Manual smoke test: two imports of same doc → second skips

### Incremental Delivery

1. US1 (D-5) → eliminates duplicate pending entries (most user-visible bug)
2. US2 (E-2) → restores `--type` override (correctness issue, less disruptive)
3. Polish → full regression validation (T007)

---

## Notes

- `[P]` tasks touch different files with no cross-dependency
- T001 already marked `[X]` — implemented during plan research phase
- E-2 fix order matters within US2: runner.py must accept `force_type` before pipeline.py can receive it; cli.py passes it last
- Do NOT run T007 until T001–T006 are all complete
- All new tests extend existing test files — no new test files needed
