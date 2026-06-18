# Tasks: 修复 Holmes KB v6 报告问题

**Input**: Design documents from `specs/010-fix-kb-v6-bugs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md

**Organization**: Tasks grouped by user story (5 stories: US1-US2 P1, US3-US4 P2, US5 P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/pending.py`, `kb/holmes/kb/skill/manager.py`, `CLAUDE.md`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`

---

## Phase 1: Setup

**Purpose**: Verify baseline before surgical fixes

- [X] T001 Verify existing test suite passes (354 tests) via `cd kb && python -m pytest --tb=short -q`

---

## Phase 2: Foundational

**Purpose**: Confirm exact locations for all 5 fixes before editing

- [X] T002 Read kb/holmes/kb/skill/manager.py to confirm auto_create_skill run.sh comment with `{{placeholder}}` (~line 570-575)
- [X] T003 [P] Read kb/holmes/cli.py to confirm kb_reject() (~line 804) and kb_search() (~line 354) and kb_list() (~line 999)
- [X] T004 [P] Read kb/holmes/kb/pending.py to confirm list_pending() pending_since fallback branches (~line 119-130)

**Checkpoint**: All fix locations confirmed

---

## Phase 3: User Story 1 — auto-create 注释单花括号 (Priority: P1)

**Goal**: run.sh 注释示例使用 `{placeholder}` 单花括号，消除误导

**Independent Test**: `auto_create_skill()` 生成的 run.sh 不含 `{{placeholder}}` 双花括号

### Implementation for User Story 1

- [X] T005 [US1] Fix `{{placeholder}}` → `{placeholder}` in run.sh comment fallback line in auto_create_skill() in kb/holmes/kb/skill/manager.py (~line 572)
- [X] T006 [P] [US1] Add test class TestAutoCreatePlaceholderComment in kb/tests/test_skill_manager.py (2 scenarios: no double braces in comment, SKILL_PARAM_ block still present)

**Checkpoint**: generated run.sh comments contain only single-brace syntax

---

## Phase 4: User Story 2 — reject --dry-run (Priority: P1)

**Goal**: `holmes kb reject --stale-days N --dry-run` 预览待删条目但不执行删除

**Independent Test**: 3 条超期 pending + `reject --stale-days 1 --dry-run` → 文件数不变，输出含 `(dry run)`

### Implementation for User Story 2

- [X] T007 [US2] Add --dry-run option to kb_reject() in kb/holmes/cli.py (when dry-run + stale-days: print IDs with "(dry run)" suffix, no deletion; --dry-run without --stale-days: error)
- [X] T008 [US2] Add test class TestRejectDryRun in kb/tests/test_integration.py (4 scenarios: dry-run prints IDs, dry-run no deletion, dry-run output contains "(dry run)", dry-run without stale-days errors)

**Checkpoint**: `holmes kb reject --stale-days 0 --dry-run` lists entries without deleting

---

## Phase 5: User Story 3 — detect-commands 文档约束 (Priority: P2)

**Goal**: CLAUDE.md 明确说明 detect-commands 只应接收 Resolution 段落

**Independent Test**: CLAUDE.md 包含 "Resolution" 和 "detect" 关键字的约束说明

### Implementation for User Story 3

- [X] T009 [P] [US3] Add detect-commands input constraint note to CLAUDE.md (specify that only ## Resolution section content should be passed, not full entry text)

**Checkpoint**: CLAUDE.md contains clear detect-commands usage constraint

---

## Phase 6: User Story 4 — --type 无效值警告 (Priority: P2)

**Goal**: `search/list --type <invalid>` 输出 stderr 警告并列出有效类型

**Independent Test**: `search "q" --type invalid_xyz` → stderr 包含 "Warning" 和有效类型列表，exit 0

### Implementation for User Story 4

- [X] T010 [US4] Add --type validation warning to kb_search() in kb/holmes/cli.py (infer valid types from kb_root subdirs; warn to stderr if kb_type not in valid types; --json mode: warning to stderr, stdout stays valid JSON)
- [X] T011 [US4] Add --type validation warning to kb_list() in kb/holmes/cli.py (same logic as kb_search, consistent behavior)
- [X] T012 [US4] Add test class TestTypeWarning in kb/tests/test_integration.py (4 scenarios: search invalid type warns, list invalid type warns, valid type no warning, --json mode warning to stderr)

**Checkpoint**: both `search` and `list` warn on invalid --type

---

## Phase 7: User Story 5 — pending_since_source 字段 (Priority: P3)

**Goal**: `list_pending()` 每条记录包含 `pending_since_source: "field"|"created_at"|"mtime"`

**Independent Test**: `list_pending()` 返回的所有条目包含 `pending_since_source` 且值合法

### Implementation for User Story 5

- [X] T013 [P] [US5] Add pending_since_source field to list_pending() return dicts in kb/holmes/kb/pending.py (track which branch filled pending_since: "field"/"created_at"/"mtime")
- [X] T014 [P] [US5] Add test class TestPendingSinceSource in kb/tests/test_pending.py (3 scenarios: field→"field", created_at→"created_at", neither→"mtime")

**Checkpoint**: all list_pending() dicts contain pending_since_source

---

## Phase 8: Polish & Validation

**Purpose**: Validate all 5 fixes together, ensure no regressions

- [X] T015 Run full test suite and verify 354 + new tests all pass: `cd kb && python -m pytest --tb=short -q`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup + Foundational (Phase 1-2)**: No dependencies
- **US1 (Phase 3)**: Modifies `manager.py` — parallel with cli.py and pending.py work
- **US2, US4 (Phase 4, 6)**: Both modify `cli.py` — sequential within cli.py
- **US3 (Phase 5)**: Modifies `CLAUDE.md` only — parallel with everything
- **US5 (Phase 7)**: Modifies `pending.py` only — parallel with everything
- **Polish (Phase 8)**: Depends on all story phases

### Parallel Opportunities

```bash
# After Phase 2:
manager.py track: US1 (T005-T006)
cli.py track:     US2 → US4 (T007-T008 → T010-T012, sequential)
CLAUDE.md track:  US3 (T009, fully parallel)
pending.py track: US5 (T013-T014, fully parallel)
```

---

## Implementation Strategy

### MVP First (P1 bugs: US1-US2)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1 (placeholder fix)
4. Phase 4: US2 (dry-run)
5. **VALIDATE**: Run tests

### Full Delivery

6. Phase 5: US3 (CLAUDE.md doc)
7. Phase 6: US4 (type warning)
8. Phase 7: US5 (pending_since_source)
9. Phase 8: Polish

---

## Notes

- US1: Only the `{{placeholder}}` fallback comment line needs fixing — confirm actual rendered output first (T002)
- US2: `--dry-run` without `--stale-days` should error with clear message
- US4: valid types inferred from `kb_root` subdirs at runtime; exclude `.history`, `contributions`, `skills`, dot-dirs
- US5: `pending_since_source` is memory-only, not written to disk
- US3: doc-only change, no code modification, no tests needed
