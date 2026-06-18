# Tasks: Three-Phase Import Agent

**Input**: Design documents from `specs/015-three-phase-import-agent/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Organization**: Tasks grouped by user story. Foundation phase (Phase 2) blocks all stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no incomplete dependencies
- **[Story]**: Mapped user story (US1–US4)

---

## Phase 1: Setup

**Purpose**: Create new module skeleton so later tasks have clean file targets.

- [X] T001 Create `holmes/kb/agent/phases/` sub-package with `holmes/kb/agent/phases/__init__.py`
- [X] T002 Create empty module files: `holmes/kb/agent/knowledge_map.py`, `holmes/kb/agent/doc_access.py`, `holmes/kb/agent/pipeline.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: KnowledgeMap data model + DocumentCursor + doc_access tools must exist before any phase agent can be built.

**⚠️ CRITICAL**: All user story phases depend on this phase being complete.

- [X] T003 Implement `KnowledgePoint` and `KnowledgeMap` dataclasses with JSON serialization and validation (section_end > section_start, unique IDs) in `holmes/kb/agent/knowledge_map.py`
- [X] T004 [P] Implement `DocumentCursor` class with `read_range(start, end)`, `coverage_pct()`, `find_section(heading)`, and `read_ranges` tracking in `holmes/kb/agent/doc_access.py`
- [X] T005 [P] Implement `read_document_range`, `get_read_coverage`, `search_in_document` tool functions backed by `DocumentCursor` in `holmes/kb/agent/doc_access.py`
- [X] T006 Register all three doc_access tool definitions and handlers in `TOOL_DEFINITIONS` and `TOOL_HANDLERS` in `holmes/kb/agent/tools.py`
- [X] T007 [P] Extend `ImportReport` dataclass with `knowledge_map: KnowledgeMap | None = None` and `phase_traces: list[str] = field(default_factory=list)` in `holmes/kb/agent/report.py`
- [X] T008 [P] Write unit tests for `KnowledgeMap` serialization, `KnowledgePoint` validation, and `extracted` state transition in `tests/test_knowledge_map.py`
- [X] T009 [P] Write unit tests for `DocumentCursor`: range read, coverage percentage, search, boundary clamping in `tests/test_doc_access.py`

**Checkpoint**: Run `python -m pytest tests/test_knowledge_map.py tests/test_doc_access.py -q` — both test files must pass before proceeding.

---

## Phase 3: User Story 1 — Large Document Import Without Data Loss (P1) 🎯 MVP

**Goal**: Documents up to 20,000 characters import with zero falsely-cleared fields; `ctx["source_text"]` is always the full untruncated source throughout the pipeline.

**Independent Test**: Import `tests/fixtures/large_runbook_15k.md` (create a 15K-char fixture with resolution section after char 8000). Verify no `CLEARED` warnings and the resolution field is populated.

- [X] T010 [US1] Implement `ReaderAgent` class with fresh LLM message loop, doc_access tools registered in its context, and a `run(source_text, ctx) -> KnowledgeMap` method in `holmes/kb/agent/phases/reader.py`
- [X] T011 [US1] Implement diminishing returns detection in `ReaderAgent`: stop when 2 consecutive reading passes each yield 0 new `KnowledgePoint`s; set `knowledge_map.diminishing_returns = True` in `holmes/kb/agent/phases/reader.py`
- [X] T012 [US1] Define `READER_SYSTEM_PROMPT` and `COVERAGE_THRESHOLD = 95.0` and `DIMINISHING_WINDOW = 2` as named constants in `holmes/kb/agent/phases/reader.py`
- [X] T013 [US1] Implement `ThreePhaseImportPipeline` class with `run(source_text, file_path) -> ImportReport` method — calls `ReaderAgent`, sets `ctx["source_text"] = source_text` (full, never truncated), stores `knowledge_map` on report in `holmes/kb/agent/pipeline.py`
- [X] T014 [US1] Wire `ImportAgentRunner.run()` to delegate to `ThreePhaseImportPipeline` while preserving identical method signature; remove `_MAX_SOURCE_CHARS` truncation from the prompt path in `holmes/kb/agent/runner.py`
- [X] T015 [P] [US1] Write unit tests for `ReaderAgent` with mocked `LLMProvider`: verify it terminates on diminishing returns, produces a valid `KnowledgeMap`, and passes `ctx["source_text"]` through untouched in `tests/test_reader_phase.py`
- [X] T016 [US1] Create test fixture `tests/fixtures/large_runbook_15k.md` — a 15,000-character document with title on line 1 and resolution section (`## Resolution`) after character 9,000

**Checkpoint**: `holmes import tests/fixtures/large_runbook_15k.md --verbose` must show zero `CLEARED` warnings and a populated resolution field.

---

## Phase 4: User Story 2 — Multi-Knowledge-Point Independent Extraction (P1)

**Goal**: A document with N distinct knowledge points produces N separate KB entries; no content from KP-A appears in KP-B's entry.

**Independent Test**: Import a 3-KP fixture document. Assert exactly 3 pending entries created, each mentioning only its own incident's keywords.

- [X] T017 [US2] Implement `ExtractorAgent` class in `holmes/kb/agent/phases/extractor.py` — `run(kp: KnowledgePoint, knowledge_map: KnowledgeMap, ctx: dict) -> str` starts a fresh `messages = []`, has access to doc_access tools, and returns draft entry Markdown
- [X] T018 [US2] Define `EXTRACTOR_SYSTEM_PROMPT` as a named constant in `holmes/kb/agent/phases/extractor.py`; prompt must instruct the agent to use only the knowledge point's section (via `read_document_range`) and ignore other sections
- [X] T019 [US2] Implement serial KP extraction loop in `ThreePhaseImportPipeline`: iterate `knowledge_map.knowledge_points`, call `ExtractorAgent.run()` per KP, mark `kp.extracted = True` after success, append phase trace to `report.phase_traces` in `holmes/kb/agent/pipeline.py`
- [X] T020 [US2] Add KnowledgeMap coverage gate before extraction starts: only begin extraction when `knowledge_map.coverage_pct >= COVERAGE_THRESHOLD` or `knowledge_map.diminishing_returns is True` in `holmes/kb/agent/pipeline.py`
- [X] T021 [P] [US2] Write unit tests for `ExtractorAgent` context isolation: mock LLM, run two Extractors sequentially, verify `messages` list for KP-2 contains no tool results from KP-1's extraction in `tests/test_extractor_phase.py`
- [X] T022 [P] [US2] Create test fixture `tests/fixtures/multi_kp_postmortem.md` — document with 3 clearly distinct incidents (Redis, MySQL, Nginx) each under its own `##` heading

**Checkpoint**: `holmes import tests/fixtures/multi_kp_postmortem.md` must create exactly 3 pending entries. Grep each entry for sibling incident names — they must not appear.

---

## Phase 5: User Story 3 — Reliable Skill Generation (P2)

**Goal**: Chinese runbooks with `## 诊断步骤` / `## 解决方案` sections containing ≥ 2 shell commands always produce a Skill recommendation.

**Independent Test**: Import `tests/fixtures/redis_runbook_zh.md` (create fixture). Import report must contain `skill candidate:` or `Would create skill:`.

- [X] T023 [US3] Integrate `VerifierAgent` into `ThreePhaseImportPipeline`: after each draft entry is produced by `ExtractorAgent`, run `ContentVerifier.verify()` with `source_text = ctx["source_text"]` (full original), apply CLEARED fields, then write to pending in `holmes/kb/agent/pipeline.py`
- [X] T024 [US3] Wire `_finalize_skill_generation` to run after all KPs are extracted and verified: pass fully-verified entry content (not truncated draft) to `SkillAdvisor` in `holmes/kb/agent/pipeline.py`
- [X] T025 [US3] Create test fixture `tests/fixtures/redis_runbook_zh.md` — Chinese runbook with `## 诊断步骤` containing `redis-cli INFO replication` and `redis-cli DEBUG SLEEP 0`
- [X] T026 [P] [US3] Write unit tests for `VerifierAgent` full-doc access: mock provider, assert `source_text[:6000]` used is the full 12K string (not truncated), assert no false CLEARED on fields present in chars 5000–9000 in `tests/test_verifier_phase.py`
- [X] T027 [P] [US3] Extend `tests/test_skill_runner.py` with test for Chinese runbook Skill generation: assert Skill recommendation present for fixture with `## 诊断步骤` + 2 bash commands

**Checkpoint**: `holmes import tests/fixtures/redis_runbook_zh.md` must show `skill candidate:` or `Would create skill:` in the report output.

---

## Phase 6: User Story 4 + Polish — Consistent Quality & Observability

**Goal**: Batch verbose output shows per-entry traces; quality consistent across document sizes; all 455 existing tests pass.

**Independent Test**: Run full test suite (`pytest -q`) — 455 tests pass. Run batch import with `--verbose` — each entry shows a trace block.

- [X] T028 [US4] Fix batch verbose output in `holmes/cli.py`: for `--dir` imports, output per-entry `DecisionTrace` block after each entry's summary line (L-W4 fix)
- [X] T029 [US4] Surface `knowledge_map` in `--verbose` output: add `format_verbose()` section showing KP count, coverage_pct, reading_passes, diminishing_returns status in `holmes/kb/agent/report.py`
- [X] T030 [P] [US4] Write `ThreePhaseImportPipeline` integration tests covering all 7 quickstart scenarios (T-01 through T-07 from quickstart.md) in `tests/test_pipeline.py`
- [X] T031 [P] Validate all 455 existing tests pass after refactor: run `python -m pytest -q` from `kb/` directory and confirm zero failures
- [X] T032 [P] Remove now-dead `_MAX_SOURCE_CHARS` truncation constant and the `prompt_source` construction branch from `holmes/kb/agent/runner.py` (cleanup after T014 delegation is verified working)
- [X] T033 Update `CLAUDE.md` detect-commands usage note to reflect that `_extract_resolution_section` now searches Chinese headers in addition to English ones

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Phase 2 complete — delivers MVP (large doc quality)
- **US2 (Phase 4)**: Depends on Phase 3 complete (uses `ThreePhaseImportPipeline` from T013)
- **US3 (Phase 5)**: Depends on Phase 4 complete (needs `ExtractorAgent` output to wire Verifier)
- **US4/Polish (Phase 6)**: Depends on Phase 5 complete

### User Story Dependencies

- **US1 (P1)**: Must precede US2 — `ThreePhaseImportPipeline` skeleton (T013) is created here
- **US2 (P1)**: Must precede US3 — serial extraction loop (T019) is extended for verification
- **US3 (P2)**: Must precede US4 polish — full pipeline must be functional before cleanup
- **US4 (P2)**: Final polish, cleanup, and validation

### Within Each Phase

- Data model tasks (T003, T004, T005) before tool registration (T006)
- Report extension (T007) can run in parallel with T003–T005
- Tests (T008, T009) can be written in parallel with implementations

### Parallel Opportunities

- T004 + T005 + T007 (Phase 2): different files, no dependencies on each other
- T008 + T009 (Phase 2): different test files, parallel
- T015 + T016 (Phase 3): test file and fixture file, parallel
- T021 + T022 (Phase 4): test file and fixture file, parallel
- T026 + T027 (Phase 5): different test files, parallel
- T030 + T031 + T032 (Phase 6): independent validation tasks, parallel

---

## Parallel Examples

### Phase 2 Parallel Block
```
[P] T004: DocumentCursor in doc_access.py
[P] T005: Tool functions in doc_access.py (same file as T004 — run after T004)
[P] T007: ImportReport extension in report.py
[P] T008: KnowledgeMap tests
[P] T009: DocumentCursor tests
```

### Phase 3 Parallel Block
```
[P] T015: ReaderAgent tests in test_reader_phase.py
[P] T016: 15K fixture file
```

---

## Implementation Strategy

### MVP First (US1 Only — Large Doc Quality)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundation (T003–T009)
3. Complete Phase 3: US1 (T010–T016)
4. **STOP and VALIDATE**: `holmes import` on a 15K-char document — zero false CLEARED warnings
5. All 455 existing tests still pass

### Incremental Delivery

1. Setup + Foundation → KnowledgeMap + doc_access tools available
2. US1 → Large docs import cleanly (biggest quality impact, W1-F1 root fix)
3. US2 → Multi-KP docs produce isolated entries
4. US3 → Chinese Skill generation works reliably
5. US4 → Batch verbose, cleanup, full validation

---

## Notes

- `[P]` tasks touch different files with no cross-dependency
- Each US phase is independently testable — stop and validate at each checkpoint
- Do NOT remove `_MAX_SOURCE_CHARS` (T032) until T014 delegation is confirmed working in tests
- Constitution requires all new modules to have test coverage (验证原则)
- The existing `verifier.py` (`ContentVerifier`) is reused, not replaced — only its call site changes
- All fixture files go in `tests/fixtures/` to keep test data co-located with tests
