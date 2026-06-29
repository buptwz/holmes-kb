# Tasks: M4 — Agent 1 DAG Extraction Harness

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M4-agent1/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Tests**: Included (Constitution: 所有业务流程必须有自动化验证)

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup (Package Structure)

**Purpose**: Create the `dag/` package skeleton and verify existing pipeline stub.

- [X] T001 Create `kb/holmes/kb/agent/dag/` directory with empty `__init__.py`
- [X] T002 [P] Verify `kb/holmes/kb/agent/pipeline.py` contains `_run_dag_pipeline()` stub raising `NotImplementedError`
- [X] T003 [P] Confirm `kb/tests/` directory exists and baseline test count (684) documented

---

## Phase 2: Foundational (Data Model + Formatter + Prompt)

**Purpose**: Core types and stateless utilities that all other modules depend on.

**CRITICAL**: Must be complete before harness/tools implementation.

- [X] T004 [P] Implement `DAGNode`, `DAGEdge`, `DAGGraph`, `Agent1Session` dataclasses + `NodeType`/`Complexity` enums in `kb/holmes/kb/agent/dag/schema.py`
- [X] T005 [P] Write unit tests for schema dataclass construction, validation rules, and enum values in `kb/tests/test_dag_schema.py`
- [X] T006 [P] Implement `dag_to_markdown(graph, title, source_file) -> str` in `kb/holmes/kb/agent/dag/formatter.py` (三-section format per blueprint spec)
- [X] T007 [P] Implement `markdown_to_dag(text) -> DAGGraph` in `kb/holmes/kb/agent/dag/formatter.py` (lenient regex parser for user-edited files)
- [X] T008 Write round-trip tests for formatter: `dag_to_markdown → markdown_to_dag` in `kb/tests/test_dag_formatter.py`
- [X] T009 [P] Write the complete three-phase system prompt in `kb/holmes/kb/agent/dag/prompt1.py` (Phase 1 study / Phase 2 draft / Phase 3 review, tool descriptions, forbidden items, termination checklist)
- [X] T010 [P] Export `Agent1Harness`, `DAGGraph`, `run_agent1` from `kb/holmes/kb/agent/dag/__init__.py`

**Checkpoint**: `schema.py`, `formatter.py`, `prompt1.py`, `__init__.py` complete; tests pass.

---

## Phase 3: User Story 3 — output_dag Validation (P1)

**Goal**: Implement the 5-rule structural validation gate in `tools1.py`.

**Independent Test**: Call `output_dag()` with deliberately invalid DAGs (one violation each); verify correct error returned for each of the 5 rules.

### Tests for US3

- [X] T011 [P] [US3] Write unit tests for all 5 validation rules (1 test per rule, plus multi-error case) in `kb/tests/test_dag_tools1.py`

### Implementation for US3

- [X] T012 [P] [US3] Implement `write_dag(content, state_dir, source_hash) -> dict` in `kb/holmes/kb/agent/dag/tools1.py` using `atomic_write()`
- [X] T013 [P] [US3] Implement `read_dag(state_dir, source_hash) -> dict` in `kb/holmes/kb/agent/dag/tools1.py`
- [X] T014 [US3] Implement `output_dag(state_dir, source_hash) -> dict` in `kb/holmes/kb/agent/dag/tools1.py`: parse `.dag.md` via `formatter.markdown_to_dag()`, run 5 validation rules, write `.dag.json` on success, return descriptive error on failure
- [X] T015 [US3] Implement validation rule 1 in `tools1.py`: at least one root node (no parent references)
- [X] T016 [US3] Implement validation rule 2 in `tools1.py`: no dangling edges (all targets exist)
- [X] T017 [US3] Implement validation rule 3 in `tools1.py`: cycle detection via DFS (excluding `is_back_edge=True` edges), include cycle path in error
- [X] T018 [US3] Implement validation rule 4 in `tools1.py`: process nodes have `section_heading` or non-empty `description`
- [X] T019 [US3] Implement validation rule 5 in `tools1.py`: non-END nodes have at least one outgoing edge
- [X] T020 [US3] Implement multi-root support: validation rule 1 accepts multiple roots (for `multi_incident` documents); verify each root reaches at least one END node

**Checkpoint**: `tools1.py` complete; all US3 tests pass; `output_dag` correctly validates/rejects DAGs.

---

## Phase 4: User Story 1 + User Story 2 — Agent Loop + Tool Whitelist (P1)

**Goal**: Implement `Agent1Harness` with the full three-phase agent loop, 5-tool whitelist, and connect `_run_dag_pipeline()` to Agent 1.

**Independent Test**: Run `Agent1Harness` against a mock provider that makes 3 turns of tool calls; verify whitelist blocks non-whitelisted calls, and that loop terminates when `output_dag` succeeds.

### Tests for US1/US2

- [X] T021 [P] [US1] Write integration test for `Agent1Harness._run_loop()` with mock provider (3 turns, valid `output_dag` at turn 3) in `kb/tests/test_dag_harness1.py`
- [X] T022 [P] [US2] Write whitelist rejection tests: verify `{"error": "tool not allowed"}` returned for `write_kb_entry`, `check_source_hash`, etc. in `kb/tests/test_dag_harness1.py`

### Implementation for US1/US2

- [X] T023 [US1] Implement `Agent1Harness.__init__()` in `kb/holmes/kb/agent/dag/harness1.py`: accept `kb_root`, `cfg`, `provider`, `source_hash`, `source_file`, `no_interactive`, `dry_run`
- [X] T024 [US2] Implement `Agent1Harness._execute_tool()` in `kb/holmes/kb/agent/dag/harness1.py`: whitelist check (`_ALLOWED_TOOLS = {"Read", "Grep", "write_dag", "read_dag", "output_dag"}`); non-whitelisted → `{"error": "tool not allowed: {name}"}`; whitelisted → dispatch to handler
- [X] T025 [US1] Implement `Agent1Harness._run_loop()` in `kb/holmes/kb/agent/dag/harness1.py`: message array management, per-turn tool dispatch, `output_dag` termination signal, `maxTurns=300` check
- [X] T026 [US1] Implement `Agent1Harness.run()` in `kb/holmes/kb/agent/dag/harness1.py`: initialize messages with source document context, call `_run_loop()`, return `ImportReport`
- [X] T027 [US1] Wire tool DEFINITIONS for all 5 tools (including `Read`/`Grep` from `DOC_ACCESS_TOOL_DEFINITIONS`) in `harness1.py`; pass to `provider.complete()` on every turn
- [X] T028 [US1] Implement `run_agent1()` top-level function in `kb/holmes/kb/agent/dag/__init__.py` (see contract in `contracts/agent1-interface.md`)
- [X] T029 [US1] Replace `raise NotImplementedError("DAG pipeline (M4)")` in `kb/holmes/kb/agent/pipeline.py` with call to `run_agent1()`
- [X] T030 [US1] Write pipeline integration test: `_run_dag_pipeline()` with a mock provider completes without `NotImplementedError` in `kb/tests/test_dag_pipeline.py`

**Checkpoint**: US1 and US2 fully functional; existing 684 tests still pass; `holmes import` on a pitfall doc runs Agent 1 end-to-end.

---

## Phase 5: User Story 4 — Crash Recovery (P2)

**Goal**: Write `session.json` every 20 turns; load it on `--resume` to continue without restarting.

**Independent Test**: Mock a 25-turn run, verify `session.json` written at turn 20 with correct `turn_count`; then call `run_agent1(resume=True)` and verify loop continues from turn 20.

### Tests for US4

- [X] T031 [P] [US4] Write crash recovery tests: session written at turn 20 and 40, correct `turn_count` stored; `--resume` restores messages in `kb/tests/test_dag_harness1.py`

### Implementation for US4

- [X] T032 [US4] Implement crash recovery snapshot in `Agent1Harness._run_loop()` in `kb/holmes/kb/agent/dag/harness1.py`: every 20 turns write `Agent1Session` to `_import-state/<hash>.session.json` via `atomic_write()`; overwrite on each write
- [X] T033 [US4] Implement `--resume` support in `Agent1Harness.run()` in `kb/holmes/kb/agent/dag/harness1.py`: if `resume=True`, load `session.json`, restore `messages` and `turn_count`, call `_run_loop()` from restored state
- [X] T034 [US4] Implement `SessionLoadError` handling in `harness1.py`: if `session.json` missing or corrupted, log error and return ImportReport with error message (do not crash silently)
- [X] T035 [US4] Implement `MaxTurnsExceededError` in `harness1.py`: raise when `turn_count >= 300`; catch in `run()` and write to `report.errors`

**Checkpoint**: Crash recovery works; `--resume` continues from snapshot; `MaxTurnsExceededError` handled cleanly.

---

## Phase 6: User Story 5 — --no-interactive Mode + Interactive Menu (P2)

**Goal**: Show `[1/2/3]` menu after `output_dag` success; `--no-interactive` auto-selects [2].

**Independent Test**: Mock successful `output_dag`; verify menu printed and option [2] auto-selected when `no_interactive=True`; verify `report.auto_decisions` contains "DAG 未经用户确认".

### Tests for US5

- [X] T036 [P] [US5] Write tests for interactive menu: option [2] auto-selected when `no_interactive=True`; ImportReport records "DAG 未经用户确认" in `kb/tests/test_dag_harness1.py`

### Implementation for US5

- [X] T037 [US5] Implement post-loop interactive menu in `kb/holmes/kb/agent/dag/harness1.py`: after `output_dag` success, display node count summary and `[1] 编辑 / [2] 跳过 / [3] 稍后` prompt using `click.prompt()`
- [X] T038 [US5] Implement option `[1]` handler in `harness1.py`: open `_import-state/<hash>.dag.md` in `$EDITOR` via `click.edit()`; wait for user to press Enter; mark for Step 2.5 continuation
- [X] T039 [US5] Implement option `[2]` handler in `harness1.py`: proceed directly to Step 2.5 stub (currently a no-op placeholder)
- [X] T040 [US5] Implement option `[3]` handler in `harness1.py`: print "状态已保存到 `_import-state/<hash>.dag.md`，稍后运行 `holmes import --resume` 继续" and return
- [X] T041 [US5] Implement `--no-interactive` auto-select in `harness1.py`: when `self.no_interactive=True`, skip menu, call option [2] handler, append "DAG 未经用户确认" to `report.auto_decisions`

**Checkpoint**: Interactive menu works; `--no-interactive` batch imports proceed without prompts.

---

## Phase 7: User Story 6 — --resume --skip-edit (P3)

**Goal**: Running `holmes import --resume --skip-edit` skips the editing menu entirely.

**Independent Test**: With a completed `.dag.md` and `.dag.json` present, run `run_agent1(resume=True, skip_edit=True)`; verify no menu prompt and pipeline proceeds.

### Tests for US6

- [X] T042 [P] [US6] Write test for `--resume --skip-edit`: verify no interactive prompt and Step 2.5 called directly in `kb/tests/test_dag_harness1.py`

### Implementation for US6

- [X] T043 [US6] Add `skip_edit: bool = False` parameter to `Agent1Harness.__init__()` and `run_agent1()` in `kb/holmes/kb/agent/dag/harness1.py` and `__init__.py`
- [X] T044 [US6] Implement `--skip-edit` logic: when `skip_edit=True`, bypass the `[1/2/3]` menu entirely and go directly to the option [2] handler
- [X] T045 [US6] Implement `--resume` multi-state selection in `kb/holmes/kb/agent/dag/harness1.py`: if `resume=True` and no `source_hash` provided, scan `_import-state/*.session.json`, present numbered list, ask user to pick; parse `source_file` from each for human-readable labels

**Checkpoint**: `--resume --skip-edit` works; multi-state selection presented when multiple sessions exist.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: HolmesLogger spans, observability, test validation, and cleanup.

- [X] T046 [P] Implement HolmesLogger span recording in `kb/holmes/kb/agent/dag/harness1.py`: `agent1.read` (Phase 1 turns), `agent1.draft` (first `write_dag` call), `agent1.review[N]` (each subsequent review turn); wrap in `try/except ImportError` guard for M8 not-yet-merged scenarios
- [X] T047 [P] Add `phase_traces` population in `Agent1Harness.run()`: append `"Agent1: {n} nodes, {p} process nodes extracted"` to `report.phase_traces` after `output_dag` success
- [X] T048 Validate total test count: run `pytest kb/tests/ -q --tb=no` and confirm new tests added with no regressions against 684 baseline
- [X] T049 [P] Verify all 6 acceptance files are importable: `python -c "from holmes.kb.agent.dag import Agent1Harness, DAGGraph, run_agent1"`
- [X] T050 [P] Code style check: run `flake8 kb/holmes/kb/agent/dag/` to ensure Google style compliance

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all US phases
- **US3 (Phase 3)**: Depends on Phase 2 (needs `schema.py`, `formatter.py`)
- **US1/US2 (Phase 4)**: Depends on Phase 2 AND Phase 3 (needs `tools1.py` + `formatter.py`)
- **US4 (Phase 5)**: Depends on Phase 4 (extends `harness1.py`)
- **US5 (Phase 6)**: Depends on Phase 4 (extends `harness1.py`)
- **US6 (Phase 7)**: Depends on Phase 5 and Phase 6 (--resume uses session from Phase 5)
- **Polish (Phase 8)**: Depends on Phases 3–7

### User Story Dependencies

- **US3 (P1)**: Can start after Foundational — independent of US1/US2 (only needs schema+formatter)
- **US1/US2 (P1)**: Depends on US3 being complete (needs `output_dag` to terminate loop)
- **US4 (P2)**: Extends US1/US2 harness — depends on Phase 4
- **US5 (P2)**: Extends US1/US2 post-loop — depends on Phase 4
- **US6 (P3)**: Depends on US4 (resume uses session.json) and US5 (skip-edit uses menu)

### Within Each Phase

- Tests → Models → Tools → Harness → Integration
- `schema.py` and `formatter.py` and `prompt1.py` can be written in parallel (Phase 2)
- `tools1.py` validation rules (T015–T020) can be written in parallel within Phase 3

### Parallel Opportunities

- T004, T006, T009, T010 (all in Phase 2) — different files, no deps
- T011, T012, T013 (all in Phase 3) — different concerns, different files
- T021, T022 (both test files in Phase 4) — write in parallel
- T031, T036, T042 (test tasks across phases) — can scaffold tests before implementations are complete

---

## Parallel Example: Phase 2 (Foundational)

```bash
# All can run simultaneously:
Task T004: "schema.py — dataclasses + enums"
Task T006: "formatter.py — dag_to_markdown()"
Task T007: "formatter.py — markdown_to_dag()"
Task T009: "prompt1.py — system prompt text"
Task T010: "__init__.py — exports"

# Then sequentially:
Task T005: "test_dag_schema.py — after T004"
Task T008: "test_dag_formatter.py — after T006+T007"
```

---

## Implementation Strategy

### MVP First (US3 + US1/US2 Only — Phases 1–4)

1. Complete Phase 1: Package structure
2. Complete Phase 2: Foundational (schema, formatter, prompt)
3. Complete Phase 3: US3 (output_dag validation)
4. Complete Phase 4: US1+US2 (harness loop + whitelist)
5. **STOP and VALIDATE**: `holmes import doc.md` on a sample pitfall doc produces `.dag.md`
6. Continue with Phases 5–8 for crash recovery and interactive features

### Incremental Delivery

1. Phases 1–4 → Core Agent 1 extraction working
2. Phase 5 → Crash recovery (production safety)
3. Phase 6 → Interactive menu (user experience)
4. Phase 7 → `--resume --skip-edit` (batch automation)
5. Phase 8 → Observability and final validation

### Parallel Strategy (if needed)

- Developer A: Phase 2 (schema + formatter + prompt)
- Developer B: Read existing `pipeline.py` and `runner.py` to prepare Phase 4 integration
- After Phase 2: Developer A takes Phase 3 (tools1), Developer B takes Phase 4 prep

---

## Notes

- [P] tasks = different files, no dependencies — can run in parallel
- [Story] label maps task to specific user story for traceability
- Tests MUST be written alongside implementation (Constitution: 禁止只写不测)
- `_ALLOWED_TOOLS` constant in `harness1.py` must be a Python `frozenset` for immutability
- `prompt1.py` must embed the full system prompt verbatim — no dynamic construction from partial strings
- The `output_dag` loop termination signal is implemented as a sentinel in the tool result dict: `{"_terminate": true, ...}`
- Step 2.5 (parse + normalize) is NOT implemented in M4; option [2] handler is a no-op placeholder to be filled by M5/future module
- `_import-state/` directory creation: `harness1.py` must `mkdir -p` on first `write_dag` call
