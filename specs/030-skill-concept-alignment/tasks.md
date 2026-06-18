# Tasks: Skill Concept Alignment (Anthropic Agent Skills)

**Input**: Design documents from `specs/030-skill-concept-alignment/`

**Feature Branch**: `030-skill-concept-alignment`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/skill-python-api.md ✅

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

---

## Phase 1: Setup

**Purpose**: No new project structure needed; this is a refactor of an existing Python package.

- [X] T001 Read and understand current `kb/holmes/kb/skill/template.py`, `manager.py`, `runner.py` before any modifications
- [X] T002 Read `kb/holmes/kb/agent/skill_advisor.py`, `tools.py`, `runner.py` to understand current pipeline integration
- [X] T003 Read `kb/tests/conftest.py`, `test_skill_manager.py`, `test_skill_data_model.py`, `test_skill_edge.py`, `test_skill_cli.py`, `test_skill_runner.py` to understand existing test coverage

---

## Phase 2: Foundational (Data Model — Blocks All User Stories)

**Purpose**: Simplify `SkillDefinition` and `SkillSummary`; update `generate_skill_template()` and `create_skill()`. Everything else depends on these changes.

**⚠️ CRITICAL**: US1, US2, US3, US4 all depend on the simplified data model and new template format.

- [X] T004 Simplify `SkillDefinition` in `kb/holmes/kb/skill/manager.py`: remove `version`, `platforms`, `timeout`, `params`, `prerequisites` fields; keep only `name`, `description`, `content` (FR-001)
- [X] T005 Remove `SkillParam` class from `kb/holmes/kb/skill/manager.py` (FR-001, removed with `params`)
- [X] T006 Simplify `SkillSummary` in `kb/holmes/kb/skill/manager.py`: remove `version`, `platforms` fields; keep `name`, `description`, `linked_entries` (FR-002)
- [X] T007 Rewrite `generate_skill_template()` in `kb/holmes/kb/skill/template.py`: frontmatter only `name`+`description`; body from `instructions` param (or default three-section placeholder); remove `generate_run_sh_template()` entirely (FR-004)
- [X] T008 Update `create_skill()` signature in `kb/holmes/kb/skill/manager.py`: replace `platforms`, `commands`, `param_names` params with `instructions: str = ""`; remove `scripts/` dir and `run.sh` creation logic (FR-005)
- [X] T009 Update `parse_skill_md()` in `kb/holmes/kb/skill/manager.py` to be backward compatible: read `name`/`description` from frontmatter regardless of extra keys; return `SkillDefinition(name, description, content)` (FR-001 backward compat)

**Checkpoint**: Data model simplified, `create_skill()` takes new signature — foundational work complete.

---

## Phase 3: User Story 2 — SKILL.md Format Correctness (Priority: P1)

**Goal**: `validate_skill_md()` enforces Anthropic Agent Skills standard; all new skill creation produces valid SKILL.md.

**Independent Test**: `pytest kb/tests/test_skill_manager.py -k "validate"` — validate_skill_md tests pass; create_skill produces valid SKILL.md.

### Implementation

- [X] T010 [US2] Add `validate_skill_md(path: Path) -> tuple[bool, str]` to `kb/holmes/kb/skill/manager.py`: required keys `name`/`description`; allowed keys `{name, description, license, allowed-tools, metadata, compatibility}`; name ≤64 chars kebab-case; description ≤1024 chars no angle brackets (FR-003)
- [X] T011 [US2] Add `validate_skill_name()` enforcement inside `validate_skill_md()` for name field (FR-003)
- [X] T012 [US2] Update `list_skills()` in `kb/holmes/kb/skill/manager.py` to return `SkillSummary` with only `name`, `description`, `linked_entries` — no `version`/`platforms` (FR-002, FR-015)
- [X] T013 [US2] Update the default three-section placeholder body in `generate_skill_template()` in `kb/holmes/kb/skill/template.py` to use correct skill-creator format: `## When to Use`, `## Resolution Steps`, `## Key Points` (FR-004, R-002)
- [X] T014 [US2] Write tests in `kb/tests/test_skill_manager.py`: `validate_skill_md()` valid (only name+description frontmatter → True); invalid old keys (version, timeout → False with error msg); missing required field (→ False); `create_skill()` does NOT create `scripts/` dir or `run.sh`; new `SkillDefinition` has no `version`/`platforms` (FR-021)

**Checkpoint**: `validate_skill_md()` works; `create_skill()` produces compliant SKILL.md. US2 fully testable.

---

## Phase 4: User Story 1 — Import Pipeline Auto-generates Agent Skills (Priority: P1)

**Goal**: `holmes import` with ≥3 commands in Resolution creates a SKILL.md with LLM-generated three-section body; OPTIONAL/SKIP/LINK paths unchanged.

**Independent Test**: Run `holmes import` on a document with ≥3 commands in Resolution; inspect resulting `SKILL.md` — passes `validate_skill_md()`, body has three sections.

### Implementation

- [X] T015 [US1] Add `_generate_skill_instructions(entry_content: str, resolution_text: str) -> tuple[str, str]` to `ImportAgentRunner` in `kb/holmes/kb/agent/runner.py`: calls `self._provider.simple_complete()` with skill-creator methodology prompt; returns `(description, instructions_body)`; on failure returns `("", "")` for graceful degradation (FR-007, R-004)
- [X] T016 [US1] Design LLM prompt in `_generate_skill_instructions()`: requires `DESCRIPTION:` line + markdown body starting with `# {title}`; body has `## When to Use`, `## Resolution Steps`, `## Key Points`; max 50 lines; parse `DESCRIPTION:` from response (R-004)
- [X] T017 [US1] Update `_run_skill_and_curation()` in `kb/holmes/kb/agent/runner.py`: on RECOMMENDED, call `_generate_skill_instructions(entry_content, resolution_text)` first; pass `instructions` to `create_skill_for_entry`; remove `cmd_lines`/`param_names` extraction logic (FR-008)
- [X] T018 [US1] Remove T014 block from `_dispatch_tool()` in `kb/holmes/kb/agent/runner.py` — no longer force-override `resolution_commands` (FR-009)
- [X] T019 [US1] Update `_IMPORT_SYSTEM_PROMPT` in `kb/holmes/kb/agent/runner.py` step 6: tell LLM that when calling `create_skill_for_entry`, it MUST provide `instructions` param (structured agent instructions with three sections) (FR-010)
- [X] T020 [US1] Update `create_skill_for_entry` tool in `kb/holmes/kb/agent/tools.py`: add `instructions: str` param; remove `resolution_commands: list[str]` and `param_names: list[str]` params; pass `instructions` to `create_skill()` call (FR-011)
- [X] T021 [US1] Update `TOOL_DEFINITIONS` dict/list in `kb/holmes/kb/agent/tools.py`: sync schema to match new `create_skill_for_entry` input (add `instructions`, remove `resolution_commands`/`param_names`) (FR-011)
- [X] T022 [US1] Remove `auto_create_skill()`, `_inject_param_bindings()`, `_slugify()`, `_generate_skill_md()` from `kb/holmes/kb/agent/runner.py` or wherever they live (FR-012)
- [X] T023 [US1] Verify `detect_commands()` and `CommandCandidate` remain in `kb/holmes/kb/skill/manager.py` (kept for counting only, not for run.sh generation) (FR-013)
- [X] T024 [US1] Write tests in `kb/tests/test_skill_manager.py` or new test file: skill advisor RECOMMENDED on ≥3 commands, OPTIONAL on 1-2, SKIP on 0, LINK when skill_refs exists (FR-021)
- [X] T025 [US1] Write tests in `kb/tests/` for `_generate_skill_instructions()`: mock `self._provider.simple_complete()`; verify returned tuple contains description and three-section markdown body; verify graceful degradation on LLM failure (FR-021)
- [X] T026 [US1] Write tests for `create_skill_for_entry` tool: verify `instructions` param is accepted; verify it calls `create_skill(instructions=...)` (FR-021)

**Checkpoint**: Import pipeline generates valid agent-skill SKILL.md. US1 fully testable end-to-end.

---

## Phase 5: User Story 3 — Complete Old Paradigm Removal (Priority: P1)

**Goal**: `runner.py` (bash execution), `auto_create_skill`, all old-paradigm code deleted; zero references to `run.sh`/`SkillExecution`/`generate_run_sh_template` in main source.

**Independent Test**: `grep -r "run\.sh\|auto_create_skill\|SkillExecution\|generate_run_sh_template" kb/holmes/` — zero results.

### Implementation

- [X] T027 [US3] Delete `kb/holmes/kb/skill/runner.py` (bash script execution module) (FR-017)
- [X] T028 [US3] Delete `kb/tests/test_skill_runner.py` (runner test file) (FR-018)
- [X] T029 [US3] Remove fixtures from `kb/tests/conftest.py`: `make_skill_with_script`, `run_sh_echo`, `run_sh_env`, `skill_with_prereqs`, `skill_with_required_param` (FR-019)
- [X] T030 [US3] Update `kb/tests/test_skill_data_model.py`: remove all assertions about `version`/`platforms`/`timeout`/`params`/`prerequisites`/`run.sh` fields (FR-020)
- [X] T031 [US3] Update `kb/tests/test_skill_edge.py`: remove EDGE-005/006/007/009 (runner-dependent tests); retain remaining edge case tests (FR-020, R-006)
- [X] T032 [US3] Scan and update `kb/tests/test_skill_manager.py`: remove `auto_create_skill`/`run_skill`/`run.sh`-related tests; keep `detect_commands` tests (FR-020)
- [X] T033 [US3] Verify zero references to deleted symbols in `kb/holmes/` source (run `grep -r "runner\|run_sh\|auto_create_skill\|SkillExecution\|generate_run_sh_template" kb/holmes/kb/skill/` — only `runner.py` deletion if any) (SC-004)

**Checkpoint**: All old-paradigm code gone; `pytest kb/tests/` passes with no import errors from deleted modules.

---

## Phase 6: User Story 4 — CLI Alignment (Priority: P2)

**Goal**: `holmes kb skill --help` shows only `list` and `read`; JSON output fields match new data model; `kb show` displays skill with `[skill]` label.

**Independent Test**: `holmes kb skill --help` — only `list`/`read` shown; `holmes kb skill list --json` — output has `name`, `description`, `linked_entries`, no `version`/`platforms`.

### Implementation

- [X] T034 [US4] Remove CLI commands from `kb/holmes/cli.py`: `skill create`, `skill link`, `skill unlink`, `skill run`, `skill detect-commands`, `skill auto-create` (FR-014)
- [X] T035 [US4] Update `skill list` command in `kb/holmes/cli.py`: `--json` output fields `name`/`description`/`linked_entries` only — no `version`/`platforms` (FR-015)
- [X] T036 [US4] Update `skill read` command in `kb/holmes/cli.py`: `--json` output fields `name`/`content` only — no `scripts_path`/`has_run_script` (FR-015)
- [X] T037 [US4] Update `kb show <id>` in `kb/holmes/cli.py`: skill section label changed from `[可执行]`/`[executable]` to `[skill]`; display name and description (FR-016)
- [X] T038 [US4] Update `kb/tests/test_skill_cli.py`: remove test cases for `skill create/link/unlink/run/detect-commands/auto-create`; add tests that these commands return "No such command"; verify `list --json` and `read --json` field correctness (FR-020, FR-021, R-006)

**Checkpoint**: CLI shows only readonly skill commands; JSON output is clean. US4 fully testable.

---

## Phase 7: User Story 5 — KB Template & Docs Alignment (Priority: P2)

**Goal**: `kb-template/` has no `run.sh`; `docs/reference.md` has no `skill run`/`detect-commands`/`--platform`; `docs/kb-management.md` describes skill as agent instruction package.

**Independent Test**: `grep -r "run\.sh" kb-template/` — zero results; `grep "skill run\|detect-commands\|--platform" docs/reference.md` — zero results.

### Implementation

- [X] T039 [P] [US5] Check `kb-template/skills/` for any `run.sh` files and remove if present (FR-022, R-007 confirms no skills/ dir exists — verify and document)
- [X] T040 [P] [US5] Update `docs/reference.md`: remove `holmes kb skill run` entry, `holmes kb skill detect-commands` entry, `holmes kb skill create` `--platform` doc, `skill create/link/unlink/auto-create` entries; update skill section to show only `list`/`read` (FR-023, R-008)
- [X] T041 [P] [US5] Update `docs/kb-management.md`: replace "skill 是 bash 脚本执行包" with "skill 是 agent 指令包，由 import 自动生成"; remove manual skill creation / skill run operations docs (FR-024, R-008)

**Checkpoint**: All documentation reflects new agent-skill concept. US5 complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, cleanup, and success criteria verification.

- [X] T042 Run full test suite: `pytest kb/tests/` — all remaining tests pass, no regressions (SC-003)
- [X] T043 Verify SC-004: `grep -r "run\.sh\|auto_create_skill\|SkillExecution\|generate_run_sh_template" kb/holmes/` — zero results in source (excluding deleted files)
- [X] T044 Verify SC-005: `holmes kb skill --help` — only `list` and `read` displayed
- [X] T045 Verify SC-006: `kb-template/` has no `run.sh`; `docs/reference.md` has no `skill run`/`detect-commands`/`--platform`
- [X] T046 [P] Update `MEMORY.md` and any agent context files to reflect skill concept change (new paradigm, removed runner.py)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — read existing code
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user story phases
- **US2 (Phase 3)**: Depends on Phase 2 (simplified SkillDefinition, new template)
- **US1 (Phase 4)**: Depends on Phase 2 + Phase 3 (validate_skill_md, new create_skill)
- **US3 (Phase 5)**: Depends on Phase 2 — can run in parallel with US2/US1 for deletion tasks, but run tests only after US1/US2 complete
- **US4 (Phase 6)**: Depends on Phase 2 (new SkillSummary fields); can run in parallel with US1/US2/US3
- **US5 (Phase 7)**: Independent of all source changes; can run in parallel with any phase
- **Polish (Phase 8)**: Depends on all user story phases complete

### User Story Dependencies

- **US2 (P1)**: Starts after Foundational — validate_skill_md and format tests
- **US1 (P1)**: Starts after Foundational — import pipeline + LLM generation
- **US3 (P1)**: Starts after Foundational — deletions independent; test updates after US1/US2
- **US4 (P2)**: Starts after Foundational — CLI changes independent of US1/US2/US3
- **US5 (P2)**: Fully independent — docs/template changes can happen any time

### Within Each User Story

- Data model before services before tools before tests
- Read/understand existing code before modifying (Phase 1)
- Delete old code (US3) after new code is in place (US1, US2)
- CLI changes (US4) after data model is finalized (Phase 2)

### Parallel Opportunities

- T004–T009 (Foundational) — most can be done in sequence (same file `manager.py`)
- T039, T040, T041 (US5 docs) — all `[P]`, different files, fully independent
- US4 (T034–T038) can proceed in parallel with US1 (T015–T026) after Phase 2
- US5 (T039–T041) can proceed in parallel with any phase

---

## Parallel Example: Foundational Phase

```bash
# Sequential within manager.py (same file — no parallelism):
T004: Simplify SkillDefinition
T005: Remove SkillParam
T006: Simplify SkillSummary
T007: Rewrite generate_skill_template() in template.py   # different file, parallel with T004–T006
T008: Update create_skill() signature
T009: Update parse_skill_md()

# Fully parallel after Phase 2:
US1 (T015–T026): Import pipeline  ←→  US4 (T034–T038): CLI
US5 (T039–T041): Docs              ←→  any other phase
```

---

## Implementation Strategy

### MVP First (US2 + US1 Only — P1 Stories)

1. Complete Phase 1: Read existing code
2. Complete Phase 2: Foundational data model (CRITICAL — blocks everything)
3. Complete Phase 3: US2 — validate_skill_md + format tests
4. Complete Phase 4: US1 — import pipeline + LLM generation
5. **STOP and VALIDATE**: `pytest kb/tests/`, `holmes import` smoke test
6. Proceed to US3 cleanup, US4 CLI, US5 docs

### Incremental Delivery

1. Phase 1 + 2 → Foundation ready (simplified data model)
2. Phase 3 (US2) → Format validation works
3. Phase 4 (US1) → Import pipeline generates agent skills (MVP!)
4. Phase 5 (US3) → Old paradigm fully removed, tests clean
5. Phase 6 (US4) → CLI aligned
6. Phase 7 (US5) → Docs updated
7. Phase 8 → Full validation pass

---

## Notes

- `[P]` tasks = different files, no dependencies — safe to run in parallel
- `[Story]` label maps task to user story for traceability
- `detect_commands()` and `CommandCandidate` MUST be kept (FR-013) — only used for counting
- `parse_skill_md()` MUST remain backward compatible (reads old fields without error)
- LLM failure in `_generate_skill_instructions()` → graceful degradation (empty instructions → default placeholder body), never blocks import
- T027 (delete runner.py) and T028 (delete test_skill_runner.py) are irreversible — confirm before executing
- No `run.sh` anywhere in the new system; `scripts/` subdirs are optional and agent-managed
