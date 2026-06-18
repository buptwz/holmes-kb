# Tasks: 修复 Holmes KB v4 报告问题

**Input**: Design documents from `specs/008-fix-kb-v4-bugs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md

**Organization**: Tasks grouped by user story (7 stories: US1-US4 P1 bugs, US5-US7 P2 features).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/pending.py`, `kb/holmes/kb/skill/manager.py`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`

---

## Phase 1: Setup

**Purpose**: Verify baseline before surgical fixes

- [X] T001 Verify existing test suite passes (307 tests) via `cd kb && python -m pytest --tb=short -q`

---

## Phase 2: Foundational

**Purpose**: Confirm exact line locations for all 7 fixes before editing

- [X] T002 Read kb/holmes/cli.py to locate kb_merge() sys.exit(1) at ~line 808, Gate 3 preview at ~line 648, kb_show() at ~line 371, kb_history() at ~line 992, import_cmd() at ~line 1+ (confirm exact line numbers)
- [X] T003 [P] Read kb/holmes/kb/pending.py to locate list_pending() return dict (confirm line numbers for pending_since fix)
- [X] T004 [P] Read kb/holmes/kb/skill/manager.py to locate detect_commands() and CMD_PATTERN (confirm line numbers for YAML strip + SQL filter)

**Checkpoint**: All fix locations confirmed

---

## Phase 3: User Story 1 — merge exit 码修正 (Priority: P1)

**Goal**: `holmes kb merge` returns exit code 0 after conflict isolation, not 1

**Independent Test**: `holmes kb merge` with conflicts present → `echo $?` = 0; output contains `holmes kb resolve`

### Implementation for User Story 1

- [X] T005 [US1] Remove sys.exit(1) and add next-step echo in kb_merge() in kb/holmes/cli.py
- [X] T006 [US1] Add test class TestMergeExitCode in kb/tests/test_integration.py (3 scenarios: with conflicts, no conflicts, nothing to merge)

**Checkpoint**: `holmes kb merge` exits 0 even when conflicts are isolated

---

## Phase 4: User Story 2 — Gate 3 内部字段剥离 (Priority: P1)

**Goal**: Gate 3 preview strips internal fields before display

**Independent Test**: `holmes kb confirm <id>` Gate 3 preview contains no `pending`, `source`, `suggested_type`, etc.

### Implementation for User Story 2

- [X] T007 [US2] Add internal-field stripping logic in Gate 3 preview section of kb_confirm() in kb/holmes/cli.py (fm.loads → pop fields → fm.dumps)
- [X] T008 [US2] Add test class TestGate3FieldStripping in kb/tests/test_integration.py (3 scenarios: all internal fields absent, short entry, long entry with --show path)

**Checkpoint**: Gate 3 preview shows only KB-destined fields

---

## Phase 5: User Story 3 — pending_since 字段暴露 (Priority: P1)

**Goal**: `list_pending()` includes `pending_since` in returned dicts

**Independent Test**: `holmes kb pending --json` → each record has non-empty `pending_since`

### Implementation for User Story 3

- [X] T009 [P] [US3] Add `pending_since` field to returned dict in list_pending() in kb/holmes/kb/pending.py
- [X] T010 [P] [US3] Add test class TestPendingSince in kb/tests/test_pending.py (3 scenarios: new entry has pending_since, old entry without pending_since returns "", list format unchanged)

**Checkpoint**: `holmes kb pending --json` includes `pending_since` for all entries

---

## Phase 6: User Story 4 — CMD_PATTERN 误报修复 (Priority: P1)

**Goal**: `detect_commands()` strips YAML frontmatter and filters SQL from CMD_PATTERN results

**Independent Test**: Input with YAML frontmatter + SQL + real shell commands → only shell commands returned

### Implementation for User Story 4

- [X] T011 [P] [US4] Add YAML frontmatter stripping at start of detect_commands() in kb/holmes/kb/skill/manager.py
- [X] T012 [P] [US4] Add SQL keyword filter to CMD_PATTERN finditer results in detect_commands() in kb/holmes/kb/skill/manager.py
- [X] T013 [P] [US4] Add test class TestDetectCommandsFalsePositives in kb/tests/test_skill_manager.py (3 scenarios: YAML frontmatter filtered, SQL filtered, real commands preserved)

**Checkpoint**: `detect_commands()` false positive rate = 0 for YAML and SQL content

---

## Phase 7: User Story 5 — show --with-evidence (Priority: P2)

**Goal**: `holmes kb show <id> --with-evidence` displays evidence summary from sidecar

**Independent Test**: Entry with sidecar evidence → output shows `Evidence: N sessions (<contributors>) — last: <date>`

### Implementation for User Story 5

- [X] T014 [US5] Add `--with-evidence` flag to kb_show() decorator and load_evidence() call in kb/holmes/cli.py
- [X] T015 [US5] Add test class TestShowWithEvidence in kb/tests/test_integration.py (3 scenarios: with sidecar, no sidecar shows "Evidence: none", without flag unchanged)

**Checkpoint**: `holmes kb show PT-DB-005 --with-evidence` shows evidence summary

---

## Phase 8: User Story 6 — history --show (Priority: P2)

**Goal**: `holmes kb history <id> --show <snapshot>` displays snapshot content

**Independent Test**: `holmes kb history PT-APP-001 --show <name>` → terminal shows full snapshot content

### Implementation for User Story 6

- [X] T016 [US6] Add `--show` option to kb_history() in kb/holmes/cli.py with path-traversal safety check (Path(name).name == name)
- [X] T017 [US6] Add test class TestHistoryShow in kb/tests/test_integration.py (3 scenarios: valid snapshot shown, nonexistent snapshot error, path traversal rejected, no --show shows list)

**Checkpoint**: `holmes kb history <id> --show <name>` works and rejects traversal attempts

---

## Phase 9: User Story 7 — import --dry-run 无参数提示 (Priority: P2)

**Goal**: `import --dry-run` with no LLM and no classification params shows helpful hint

**Independent Test**: `holmes import <file> --dry-run` (no api_key, no --type) → output contains `LLM not configured`

### Implementation for User Story 7

- [X] T018 [US7] Add no-LLM/no-params hint to import_cmd() in kb/holmes/cli.py (condition: api_key empty AND kb_type/category/title/tags all None)
- [X] T019 [US7] Add test class TestDryRunHint in kb/tests/test_integration.py (3 scenarios: no LLM no params shows hint, with --type no hint, with api_key no hint)

**Checkpoint**: Dry-run hint appears only when meaningful

---

## Phase 10: Polish & Validation

**Purpose**: Validate all 7 fixes together, ensure no regressions

- [X] T020 Run full test suite and verify all existing 307 + new tests pass: `cd kb && python -m pytest --tb=short -q`
- [X] T021 [P] Run quickstart.md manual verification scenarios for US1 and US4 (exit code and detect_commands)
- [X] T022 [P] Run quickstart.md manual verification scenarios for US3, US5, US6, US7 (pending_since, with-evidence, history --show, dry-run hint)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1
- **US1 (Phase 3)**: Depends on Phase 2; modifies cli.py
- **US2 (Phase 4)**: Depends on Phase 2; modifies cli.py (sequential after US1)
- **US3 (Phase 5)**: Depends on Phase 2; modifies pending.py — **parallel with US1/US2**
- **US4 (Phase 6)**: Depends on Phase 2; modifies skill/manager.py — **parallel with US1/US2/US3**
- **US5 (Phase 7)**: Depends on Phase 2; modifies cli.py (sequential after US1, US2)
- **US6 (Phase 8)**: Depends on Phase 2; modifies cli.py (sequential after US1, US2, US5)
- **US7 (Phase 9)**: Depends on Phase 2; modifies cli.py (sequential after US1, US2, US5, US6)
- **Polish (Phase 10)**: Depends on all story phases

### User Story Dependencies

- **US3, US4**: Independent files — can run in parallel with all cli.py stories
- **US1, US2, US5, US6, US7**: All modify cli.py — must run sequentially

### Parallel Opportunities

```bash
# After Phase 2, run these in parallel (different files):
US3 → pending.py
US4 → skill/manager.py
US1 → cli.py (then US2, US5, US6, US7 sequentially)
```

---

## Implementation Strategy

### MVP First (P1 bugs only: US1-US4)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: US1 (merge exit code)
4. Complete Phase 4: US2 (Gate 3 fields)
5. Complete Phase 5: US3 (pending_since)
6. Complete Phase 6: US4 (CMD_PATTERN)
7. **VALIDATE**: Run test suite — all 307 + new tests pass

### Full Delivery

8. Complete Phase 7: US5 (show --with-evidence)
9. Complete Phase 8: US6 (history --show)
10. Complete Phase 9: US7 (dry-run hint)
11. Complete Phase 10: Polish

---

## Notes

- All fixes are surgical — no new modules, no new files
- Each fix targets a single function in a confirmed location
- Test classes follow naming convention `Test<Feature>` in existing test files
- Path traversal safety (US6): `Path(name).name == name` before reading snapshot
- SQL filter (US4): reuse existing `_SQL_KEYWORDS` frozenset already in manager.py
- Internal fields to strip (US2): `pending`, `pending_since`, `source`, `source_session`, `suggested_type`, `suggested_category`
