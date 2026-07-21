# Tasks: Three-Phase Pipeline Stability Fixes (D-1~D-7)

**Input**: Design documents from `specs/016-fix-pipeline-stability/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks grouped by user story. No foundational blocking phase — all fixes are independent or sequentially within a story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: Mapped user story (US1–US5)

---

## Phase 1: Setup

**Purpose**: No new files or project initialization needed — all fixes are within existing files.

*(No tasks — skip to Phase 2)*

---

## Phase 2: User Story 1 — Multi-Section Document Produces Expected KB Entries (P1) 🎯 MVP

**Goal**: D-1 + D-2. Extractor drafts no longer silently dropped due to YAML format errors; shell commands are copied verbatim so `resolution_commands` is not falsely CLEARED.

**Independent Test**: Import `tests/fixtures/multi_kp_postmortem.md`. Assert 3 pending entries created (0 dropped). Each entry's resolution section contains the original commands from the source (not paraphrased).

- [X] T001 [US1] Update `EXTRACTOR_SYSTEM_PROMPT` to add verbatim command copy instruction for `## Resolution` section (D-2) in `holmes/kb/agent/phases/extractor.py`
- [X] T002 [US1] Add `_validate_and_repair_draft(draft) -> tuple[str, str | None]` static method to `ExtractorAgent`: strip prose preamble, ensure closing `---`, validate `frontmatter.loads()`, return `("", error)` if unrecoverable (D-1) in `holmes/kb/agent/phases/extractor.py`
- [X] T003 [US1] In `ThreePhaseImportPipeline._run_extraction_loop()`, call `_validate_and_repair_draft()` on each KP draft before adding to user prompt; append to `report.errors` on failure and `continue` (do not crash) (D-1) in `holmes/kb/agent/pipeline.py`
- [X] T004 [P] [US1] Write unit tests for D-1 (malformed draft: missing closing `---`, prose preamble, unrecoverable YAML) and D-2 (assert `EXTRACTOR_SYSTEM_PROMPT` contains verbatim-copy instruction) by extending `tests/test_extractor_phase.py`

**Checkpoint**: `python -m pytest tests/test_extractor_phase.py -q` passes. `_validate_and_repair_draft` handles all three malformed-draft cases.

---

## Phase 3: User Story 2 — Runbook Import Produces a Usable Skill (P1)

**Goal**: D-6. Generated Skill `run.sh` contains actual commands from the entry's resolution section, not a blank placeholder.

**Independent Test**: Import `tests/fixtures/redis_runbook_zh.md` (dry_run=False). Assert `scripts/run.sh` of the created Skill contains `redis-cli INFO replication` and `redis-cli DEBUG SLEEP 0`.

- [X] T005 [US2] Add optional `commands: list[str] | None = None` parameter to `create_skill()` in `holmes/kb/skill/manager.py`; when `commands` is non-empty, write them to `scripts/run.sh` body instead of the placeholder TODO comment (D-6)
- [X] T006 [US2] Add `resolution_commands` (array of strings, optional) to the `create_skill_for_entry` tool input schema and pass it to `create_skill()` in `holmes/kb/agent/tools.py` (D-6)
- [X] T007 [US2] In `ImportAgentRunner._run_skill_and_curation()`, call `detect_commands(resolution_text)` and include the result as `resolution_commands` when invoking `create_skill_for_entry` for RECOMMENDED skills in `holmes/kb/agent/runner.py` (D-6)
- [X] T008 [P] [US2] Write unit test for D-6: mock `SkillAdvisor` to return RECOMMENDED, provide resolution_text with 2 redis-cli commands, assert created `run.sh` contains those commands verbatim in `tests/test_skill_runner.py`

**Checkpoint**: `python -m pytest tests/test_skill_runner.py -q` passes. Skill `run.sh` test asserts real commands present.

---

## Phase 4: User Story 3 — Single-Incident Document Creates One Focused Entry (P2)

**Goal**: D-3. Reader produces 1 knowledge point for a single-incident document, not 7–8.

**Independent Test**: Import `tests/fixtures/large_runbook_15k.md` with mocked LLM. Assert `knowledge_map.knowledge_points` has exactly 1 entry spanning the full document.

- [X] T009 [P] [US3] Update `READER_SYSTEM_PROMPT` to add KP scoping instruction: "One incident = ONE pitfall KP; do not split symptoms/root-cause/resolution of the same incident into separate KPs" (D-3) in `holmes/kb/agent/phases/reader.py`
- [X] T010 [P] [US3] Write unit test for D-3: assert `READER_SYSTEM_PROMPT` contains the scoping instruction; assert a single-incident mock scenario produces ≤ 2 KPs in `tests/test_reader_phase.py`

**Checkpoint**: `python -m pytest tests/test_reader_phase.py -q` passes.

---

## Phase 5: User Story 4 — Import Failures Are Reported, Not Silently Dropped (P2)

**Goal**: D-4 + D-5. When Reader returns 0 KPs, a warning appears in the report. Semantic deduplication is triggered in the extraction loop.

**Independent Test (D-4)**: Mock Reader to return 0 KPs. Assert `report.warnings` contains "No knowledge points identified". **Independent Test (D-5)**: Mock `compare_root_cause` to return high similarity. Assert `report.updated` contains the existing entry (not `report.created`).

- [X] T011 [US4] In `ThreePhaseImportPipeline.run()`, after `reader.run()` returns, add: if `len(knowledge_map.knowledge_points) == 0`, append "No knowledge points identified — ..." to `report.warnings` (D-4) in `holmes/kb/agent/pipeline.py`
- [X] T012 [US4] In `ThreePhaseImportPipeline._run_extraction_loop()`, update the pre-extracted drafts user prompt to include dedup as step 0: "Call `compare_root_cause` first; if similarity ≥ 0.8, call `write_kb_entry` with `update=True`" (D-5) in `holmes/kb/agent/pipeline.py`
- [X] T013 [P] [US4] Write unit tests for D-4 (0-KP warning present in report) and D-5 (extraction loop prompt contains `compare_root_cause` instruction) by extending `tests/test_pipeline.py`

**Checkpoint**: `python -m pytest tests/test_pipeline.py -q` passes. Both D-4 and D-5 tests pass.

---

## Phase 6: User Story 5 — Verbose Trace Shows Clear, Non-Contradictory Field Status (P3)

**Goal**: D-7. No field appears as both `(verified)` and `[CLEARED]` in the same verbose trace block.

**Independent Test**: Simulate two verify_content updates on the same `DecisionTrace` (first marks field as verified, second as CLEARED). Assert field is only in `unsupported_fields` (last write wins); `format_verbose()` shows it only once as `[CLEARED]`.

- [X] T014 [US5] In `holmes/kb/agent/tools.py`, enforce last-write-wins in `DecisionTrace` mutation: when adding a field to `field_sources`, remove it from `unsupported_fields`; when adding to `unsupported_fields`, remove from `field_sources` (D-7). Locate the `write_kb_entry` and/or `verify_content` trace update sites.
- [X] T015 [P] [US5] Write unit test for D-7: construct `DecisionTrace`, apply two conflicting updates for same field, assert mutual exclusion holds and `format_verbose()` output contains only one trace line per field in `tests/test_agent_runner.py`

**Checkpoint**: `python -m pytest tests/test_agent_runner.py -q` passes.

---

## Phase 7: Polish — Full Validation

**Purpose**: Confirm all 546 existing tests still pass after all 7 fixes.

- [X] T016 [P] Run full test suite `python -m pytest -q` from `kb/` directory and confirm 546 tests pass with zero failures (regression guard)

---

## Dependencies & Execution Order

### Phase Dependencies

- **US1 (Phase 2)**: No dependencies — start immediately (D-2 prompt before D-1 code, both in `extractor.py`)
- **US2 (Phase 3)**: No dependencies on US1 — `manager.py` → `tools.py` → `runner.py` sequential within phase
- **US3 (Phase 4)**: No dependencies — prompt-only change in `reader.py`
- **US4 (Phase 5)**: No dependencies — both fixes in `pipeline.py`; T011 before T012 (same file, different methods)
- **US5 (Phase 6)**: No dependencies — `tools.py` change independent of all above
- **Polish (Phase 7)**: Depends on all phases complete

### Within Each Phase

- T001 → T002 → T003 (US1): same file, sequential
- T004 [P] (US1): different file, can run parallel with T002/T003
- T005 → T006 → T007 (US2): bottom-up dependency across 3 files
- T008 [P] (US2): different file, can run parallel with T005-T007
- T009 [P] + T010 [P] (US3): different files, parallel
- T011 → T012 (US4): same file, sequential
- T013 [P] (US4): different file, parallel with T011/T012
- T014 + T015 [P] (US5): different files, parallel

### Parallel Opportunities

- US3, US4, US5 phases are independent and can run in parallel with each other
- Within each US: test tasks [P] can run in parallel with implementation tasks
- US1 and US2 can run in parallel (different files)

---

## Parallel Examples

### US1 + US2 Parallel Block
```
[US1] T001 → T002 → T003 (extractor.py, pipeline.py)
[US1] T004 [P] (test_extractor_phase.py) — parallel with T002/T003
[US2] T005 → T006 → T007 (manager.py → tools.py → runner.py)
[US2] T008 [P] (test_skill_runner.py) — parallel with T005-T007
```

### US3 + US4 + US5 Parallel Block (after US1/US2)
```
[US3] T009 [P] (reader.py) ─┐
[US3] T010 [P] (test_reader) ┘  → parallel
[US4] T011 → T012 (pipeline.py)
[US4] T013 [P] (test_pipeline.py)
[US5] T014 (tools.py)
[US5] T015 [P] (test_agent_runner.py)
```

---

## Implementation Strategy

### MVP First (US1 Only — P1 Highest Impact)

1. Complete Phase 2: US1 (T001–T004)
2. **STOP and VALIDATE**: Run `python -m pytest tests/test_extractor_phase.py -q` — all pass
3. Manual smoke test: check that 3-incident document no longer drops KPs

### Incremental Delivery

1. US1 (D-1+D-2) → fixes the silent-drop crisis (60-80% KP failure rate)
2. US2 (D-6) → fixes empty Skill run.sh
3. US3 (D-3) → reduces KP over-splitting
4. US4 (D-4+D-5) → adds failure reporting + restores dedup
5. US5 (D-7) → cleans up verbose trace noise
6. Polish → full regression validation (T016)

---

## Notes

- `[P]` tasks touch different files with no cross-dependency
- D-2 (prompt) MUST come before D-1 (code) within US1 — reduces malformed draft frequency which simplifies validation
- D-6 is bottom-up: `manager.py` (lowest) → `tools.py` (schema) → `runner.py` (caller)
- Constitution 验证原则: each fix has a corresponding test task
- Do NOT run T016 until all T001–T015 are complete
- All new tests extend existing test files — no new test files needed
