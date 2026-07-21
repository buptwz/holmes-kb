# Tasks: Holmes KB Autonomous Import Agent

**Input**: Design documents from `specs/013-kb-skill-evolution/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md, quickstart.md

**Organization**: Tasks grouped by user story (6 stories: US1-US3 P1, US4-US6 P2).

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/`, `kb/holmes/kb/agent/`, `kb/holmes/kb/skill/`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_agent_runner.py`, `kb/tests/test_dedup.py`, `kb/tests/test_skill_advisor.py`, `kb/tests/test_curator.py`, `kb/tests/test_skill_usage.py`

---

## Phase 1: Setup

- [X] T001 Verify existing test suite passes via `cd kb && python -m pytest --tb=short -q`
- [X] T002 Add `anthropic>=0.27.0` to dependencies in `kb/pyproject.toml` and run `pip install anthropic` in active venv
- [X] T003 Create `kb/holmes/kb/agent/` package: `mkdir -p kb/holmes/kb/agent && touch kb/holmes/kb/agent/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core shared infrastructure required by all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 Implement `kb/holmes/kb/atomic.py` with `atomic_write(path: Path, content: str) -> None` using tempfile.mkstemp + os.replace per research.md R-003
- [X] T005 [P] Add `compute_source_hash(content: str) -> str` to `kb/holmes/kb/importer.py`: `hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]` per research.md R-002
- [X] T006 [P] Implement `kb/holmes/kb/agent/report.py` with `ImportReport` and `CuratorFinding` dataclasses per data-model.md Entity 4/5; add `format_summary() -> str` (FR-020 format) and `format_verbose() -> str` (FR-021) methods
- [X] T007 Implement `kb/holmes/kb/skill/usage.py` with `SkillUsageRecord` dataclass (data-model.md Entity 3) and functions: `read_usage(skill_dir)`, `write_usage(skill_dir, record)` using atomic_write from T004, `bump_use(skill_dir)`, `bump_patch(skill_dir)`, `mark_agent_created(skill_dir)`
- [X] T008 Implement `kb/holmes/kb/agent/tools.py` with all 9 agent tool functions (data-model.md Entity 6): `check_source_hash`, `write_kb_entry`, `update_kb_entry`, `read_kb_entries_by_category`, `compare_root_cause`, `verify_content`, `evaluate_skill`, `create_skill_for_entry`, `report_item`; each function returns a dict; uses atomic_write (T004) and compute_source_hash (T005)

**Checkpoint**: Foundation ready — all user story phases can now begin.

---

## Phase 3: User Story 1 — 一条命令，自动生成并更新知识库 (Priority: P1) 🎯 MVP

**Goal**: `holmes import <file>` triggers the full Anthropic tool-use agent pipeline, classifies the document, writes it to pending, and outputs an ImportReport summary.

**Independent Test**: Given an incident markdown file, run `holmes import`, verify a pending entry appears in `holmes kb pending` and the summary shows `1 created`.

### Tests for User Story 1

- [X] T009 [P] [US1] Add `TestAutonomousImport` class to `kb/tests/test_integration.py`: 3 scenarios — (1) single file creates pending entry, (2) `--dir` batch processes 3 files, (3) content <50 chars exits code 1
- [X] T010 [P] [US1] Create `kb/tests/test_agent_runner.py` with `TestAgentRunnerLoop`: 2 scenarios — (1) agent tool-use loop terminates on `end_turn`, (2) tool results are appended to messages list between iterations

### Implementation for User Story 1

- [X] T011 [US1] Implement `kb/holmes/kb/agent/runner.py` with `ImportAgentRunner` class: `__init__(kb_root, cfg, no_interactive, verbose, dry_run)`, `run(source_text, file_path=None) -> ImportReport`; implement Anthropic tool-use loop per research.md R-001; dispatch to tool functions from T008; call `git_commit()` via `subprocess.run` (R-004) after all writes succeed
- [X] T012 [US1] Update `kb/holmes/cli.py` `import_cmd`: replace single-shot `import_document()` call with `ImportAgentRunner(...)..run()`; add `--no-interactive` flag; add `--dir <directory>` option that globs `*.md,*.txt,*.rst` and processes each file; stdin (`-`) support; preserve existing `--type`, `--category`, `--dry-run`, `--force` flags

**Checkpoint**: US1 fully functional — `holmes import <file>` and `holmes import --dir` both work end-to-end.

---

## Phase 4: User Story 2 — Agent 内容正确性保障 (Priority: P1)

**Goal**: Agent self-verifies every key field has source text support; fields without basis are cleared to empty; no hallucinated commands reach the KB.

**Independent Test**: Given input with no shell commands, verify generated entry's Resolution section contains no command-line content.

### Tests for User Story 2

- [X] T013 [P] [US2] Add `TestAgentVerification` class to `kb/tests/test_integration.py`: 3 scenarios — (1) input with no commands produces entry with no commands in Resolution, (2) command in source text preserved exactly in entry, (3) low-confidence field (no source support) cleared to empty
- [X] T014 [P] [US2] Add `TestContentVerifier` class to `kb/tests/test_agent_runner.py`: 2 scenarios — (1) `verify_content` tool call with unsupported field returns cleared field list, (2) all-supported draft returns empty unsupported list

### Implementation for User Story 2

- [X] T015 [US2] Implement `kb/holmes/kb/agent/verifier.py` with `ContentVerifier`: `verify(source_text, draft_content) -> VerifyResult`; sends source + draft to LLM; parses JSON `{verified_fields, unsupported_fields, confidence}`; returns list of fields to clear per research.md R-006
- [X] T016 [US2] Wire verifier into `kb/holmes/kb/agent/runner.py`: before calling `write_kb_entry` tool, call `ContentVerifier.verify()`; if unsupported_fields non-empty, strip those fields from draft and add warning to ImportReport; if confidence < 0.7, set `maturity: draft`

**Checkpoint**: US2 verified — hallucinated fields are cleared before write; low-confidence entries get draft maturity.

---

## Phase 5: User Story 3 — 幂等性：重复 import 不产生重复知识 (Priority: P1)

**Goal**: Exact same source → skip. Same root cause → merge update. Different root cause → new entry + related_entries link.

**Independent Test**: Run `holmes import` on the same file twice; verify second run outputs `skipped (already imported)` and KB entry count unchanged.

### Tests for User Story 3

- [X] T017 [P] [US3] Add `TestIdempotency` class to `kb/tests/test_integration.py`: 5 scenarios — (1) exact source_hash match skips, (2) updated source (different hash, same root cause) merges, (3) different root cause creates new entry with related_entries link, (4) same content different filename skips, (5) first import of new content creates entry
- [X] T018 [P] [US3] Create `kb/tests/test_dedup.py` with `TestSemanticDedup`: 3 scenarios — (1) LLM returns same_root_cause=true → DeduResult.MERGE, (2) same_root_cause=false → DeduResult.NEW_WITH_LINK, (3) no category candidates → DeduResult.CREATE

### Implementation for User Story 3

- [X] T019 [US3] Implement `kb/holmes/kb/agent/dedup.py` with `SemanticDeduplicator`: `check(source_hash, new_summary, category) -> DeduResult`; scan existing KB entries for source_hash match first (exact skip); if no hash match, retrieve same-category entries and call `compare_root_cause` LLM tool; return SKIP / MERGE(entry_id) / NEW_WITH_LINK(entry_id) / CREATE per research.md R-005
- [X] T020 [US3] Wire SemanticDeduplicator into `kb/holmes/kb/agent/runner.py`: compute source_hash at start of `run()`; call dedup before any write; on SKIP append to `report.skipped` and return early; on MERGE call `update_kb_entry` tool; on NEW_WITH_LINK create entry and call `update_kb_entry` on existing to add `related_entries`; on CREATE proceed normally

**Checkpoint**: US3 verified — all 5 idempotency scenarios pass.

---

## Phase 6: User Story 4 — 智能交互确认 (Priority: P2)

**Goal**: Low-confidence decisions (< 0.7) pause and prompt user; `--no-interactive` suppresses all gates and logs auto-decisions.

**Independent Test**: With monkeypatched LLM returning confidence=0.5 for classification, verify `click.prompt` is called; with `--no-interactive`, verify no prompt and auto-decision logged to report.

### Tests for User Story 4

- [X] T021 [P] [US4] Add `TestInteractiveGates` class to `kb/tests/test_integration.py`: 4 scenarios — (1) low-confidence classification triggers type prompt (mock input), (2) dedup MERGE ambiguity triggers update/new prompt, (3) `--no-interactive` skips all prompts, (4) `--no-interactive` logs all auto-decisions to ImportReport.auto_decisions

### Implementation for User Story 4

- [X] T022 [US4] Add confirmation gate helpers to `kb/holmes/kb/agent/runner.py`: `_gate_classification(type, confidence)` uses `click.confirm/prompt` or returns default if no_interactive; `_gate_dedup(existing_id, title)` asks update/new or defaults to new; `_gate_skill_create(name)` confirms skill creation or skips; all auto-decisions appended to `report.auto_decisions`
- [X] T023 [US4] Update `kb/holmes/cli.py` import_cmd: when `--verbose`, print `report.auto_decisions` block after summary; ensure `--no-interactive` is passed through to ImportAgentRunner

**Checkpoint**: US4 verified — interactive gates work; --no-interactive mode is fully headless.

---

## Phase 7: User Story 5 — Skill 自动生成与管理 (Priority: P2)

**Goal**: Agent generates skills for multi-step command entries; incremental curator identifies merge/oversized/update candidates in the same category.

**Independent Test**: Import an entry with ≥3 steps and `{parameter}` placeholders; verify skill directory created under `skills/` and `.skill_usage.json` has `agent_created: true`.

### Tests for User Story 5

- [X] T024 [P] [US5] Add `TestSkillGeneration` class to `kb/tests/test_integration.py`: 5 scenarios — (1) ≥3 steps + `{param}` creates skill, (2) 1-step simple command skips skill (suggestion in report), (3) existing skill matching commands → link not create, (4) delete skill with `--absorbed-into` sets tombstone in `.skill_usage.json`, (5) curator finds merge candidate after import
- [X] T025 [P] [US5] Create `kb/tests/test_skill_advisor.py` with `TestSkillAdvisor`: 3 scenarios — (1) step_count < 3 → Recommendation.SKIP, (2) step_count ≥ 3 + placeholder → Recommendation.RECOMMENDED, (3) existing skill covers same commands → Recommendation.LINK
- [X] T026 [P] [US5] Create `kb/tests/test_curator.py` with `TestSkillCurator`: 3 scenarios — (1) Jaccard > 0.6 between two skill descriptions → merge_candidate finding, (2) SKILL.md body > 3000 chars → oversized finding, (3) patch_count=0 and linked entry updated_at > skill created_at → update_candidate finding
- [X] T027 [P] [US5] Create `kb/tests/test_skill_usage.py` with `TestSkillUsageRecord`: 5 scenarios — (1) read_usage on absent file returns default zeros, (2) write_usage creates `.skill_usage.json` atomically, (3) bump_use increments use_count, (4) mark_agent_created sets agent_created=true, (5) absorbed_into set correctly on tombstone

### Implementation for User Story 5

- [X] T028 [US5] Implement `kb/holmes/kb/agent/skill_advisor.py` with `SkillAdvisor`: `advise(entry_id, resolution_text, kb_root) -> SkillRecommendation`; call existing `detect_commands()` from `kb/holmes/kb/skill/manager.py` on resolution_text; count steps; check for `{...}` placeholder regex; scan `entry.skill_refs` for existing skills; return RECOMMENDED/OPTIONAL/LINK(name)/SKIP per research.md R-007
- [X] T029 [US5] Implement `kb/holmes/kb/agent/curator.py` with `SkillCurator`: `curate(kb_root, category) -> list[CuratorFinding]`; scan `skills/` for agent-created skills (have `.skill_usage.json` with `agent_created: true`) in same category; compute Jaccard on description word sets (R-008); check body length; check update_candidate condition; return list of CuratorFinding
- [X] T030 [US5] Wire SkillAdvisor + SkillCurator into `kb/holmes/kb/agent/runner.py`: after `write_kb_entry`, call `SkillAdvisor.advise()`; if RECOMMENDED, call `_gate_skill_create()` (US4 gate), then `create_skill_for_entry` tool + `mark_agent_created(skill_dir)`; if OPTIONAL, append suggestion to report without prompting; if LINK, call `create_skill_for_entry` with link-only mode; run `SkillCurator.curate()` for same category; append CuratorFindings to `report.suggestions`

**Checkpoint**: US5 verified — skill creation, linking, and curation suggestions all work.

---

## Phase 8: User Story 6 — Dry-run 与可观测性 (Priority: P2)

**Goal**: `--dry-run` produces complete execution plan with zero file writes; `--verbose` shows per-decision reasoning; structured summary always printed.

**Independent Test**: Run `holmes import --dry-run <file>`; verify `git diff` on KB directory is empty; verify stdout contains "Would create" lines.

### Tests for User Story 6

- [X] T031 [P] [US6] Add `TestDryRunAndObservability` class to `kb/tests/test_integration.py`: 4 scenarios — (1) `--dry-run` leaves KB unchanged (git diff empty), (2) `--dry-run` stdout contains "Would create", (3) `--verbose` output includes confidence score and source fragment, (4) single-item failure mid-batch writes summary with error count, not crash

### Implementation for User Story 6

- [X] T032 [US6] Wire dry_run flag through `kb/holmes/kb/agent/runner.py`: in all write tool functions (`write_kb_entry`, `update_kb_entry`, `create_skill_for_entry`), check `self.dry_run`; if True, append "Would {action}: {description}" to `report.suggestions` and skip actual write; skip git_commit() call
- [X] T033 [US6] Implement `format_verbose()` in `kb/holmes/kb/agent/report.py`: per-entry block with confidence, source fragment per field, skill decision reasoning, curator findings; output matches contracts/cli-contracts.md Contract 5 verbose format
- [X] T034 [US6] Update `kb/holmes/cli.py` import_cmd output: always print `format_summary()` at end; if `--verbose`, print `format_verbose()` block; if `--dry-run`, prefix output with `[DRY RUN]` and print "No files written." at end

**Checkpoint**: US6 verified — dry-run zero-side-effects; verbose shows full decision trace.

---

## Phase 9: Polish & Validation

- [X] T035 [P] Audit all file writes in `kb/holmes/kb/agent/runner.py` and `kb/holmes/kb/skill/usage.py`: confirm every path.write_text() has been replaced with atomic_write() from `kb/holmes/kb/atomic.py`
- [X] T036 [P] Add `git_commit(kb_root, message)` helper to `kb/holmes/kb/agent/runner.py` using subprocess.run per research.md R-004; verify non-zero return code (nothing to commit) is treated as non-fatal
- [X] T037 Run full test suite and confirm all tests pass: `cd kb && python -m pytest --tb=short -q`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — BLOCKS US2-US6 (runner.py is the integration point)
- **US2 (Phase 4)**: Depends on US1 (runner.py must exist to wire verifier)
- **US3 (Phase 5)**: Depends on US1 (runner.py must exist to wire dedup)
- **US4 (Phase 6)**: Depends on US1 (confirmation gates added to runner.py)
- **US5 (Phase 7)**: Depends on US1 + US4 (skill gate uses US4 gate helpers)
- **US6 (Phase 8)**: Depends on US1 (dry_run wired into runner.py); US6 report depends on US2-US5 being complete
- **Polish (Phase 9)**: Depends on all user stories

### Within Each User Story

- Tests must be written first (verified: constitution 验证原则 requires all modules have tests)
- Models/dataclasses before services
- Services before wiring into runner.py
- Story complete before Polish phase

### Parallel Opportunities

- T004, T005, T006 (Phase 2): all independent, run in parallel
- T009, T010 (US1 tests): parallel
- T013, T014 (US2 tests): parallel
- T017, T018 (US3 tests): parallel
- T024, T025, T026, T027 (US5 tests): all parallel
- T035, T036 (Polish): parallel

---

## Implementation Strategy

### MVP First (US1 + US2 + US3 = P1)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL)
3. Complete Phase 3: US1 — basic agent pipeline works
4. Complete Phase 4: US2 — content correctness guaranteed
5. Complete Phase 5: US3 — idempotency guaranteed
6. **STOP and VALIDATE**: Run `holmes import` end-to-end; check quickstart.md Scenarios 1-3 pass
7. Ship as P1 complete

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 + US2 + US3 → P1 complete; `holmes import` fully autonomous and correct
3. US4 → interactive confirmation; `--no-interactive` for CI
4. US5 → skill generation; KB becomes self-evolving
5. US6 → dry-run + verbose; full observability
6. Polish → atomic write audit + test suite green

---

## Notes

- [P] = different files, no blocking dependency on prior task in same phase
- Tests required by constitution (验证原则: 禁止只写不测)
- All file writes must use `atomic_write()` from `kb/holmes/kb/atomic.py`
- anthropic SDK tool-use loop pattern is in research.md R-001 — use it verbatim
- Confidence threshold for interactive gate: < 0.7 (wired as constant in runner.py)
- Jaccard threshold for merge_candidate: > 0.6 (wired as constant in curator.py)
- Skill body oversized threshold: > 3,000 chars (wired as constant in curator.py)
