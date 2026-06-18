# Tasks: 修复 Holmes KB v5 报告问题

**Input**: Design documents from `specs/009-fix-kb-v5-bugs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md

**Organization**: Tasks grouped by user story (9 stories: US1-US3 P1, US4-US5 P2, US6-US9 P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/pending.py`, `kb/holmes/kb/skill/manager.py`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`

---

## Phase 1: Setup

**Purpose**: Verify baseline before surgical fixes

- [X] T001 Verify existing test suite passes (328 tests) via `cd kb && python -m pytest --tb=short -q`

---

## Phase 2: Foundational

**Purpose**: Confirm exact locations for all 9 fixes before editing

- [X] T002 Read kb/holmes/kb/skill/manager.py to confirm _SQL_KEYWORDS location (~line 37) and CMD_PATTERN backtick loop (~line 455) and auto_create_skill run.sh template (~line 555)
- [X] T003 [P] Read kb/holmes/cli.py to confirm kb_reject() (~line 787), kb_search() (~line 340), kb_show() (~line 371), kb_history() (~line 1014), and @cli group decorator (~line 38)
- [X] T004 [P] Read kb/holmes/kb/pending.py to confirm list_pending() return dict (~line 123)

**Checkpoint**: All fix locations confirmed

---

## Phase 3: User Story 1 — SQL 从句补全 (Priority: P1)

**Goal**: `detect-commands` filters SQL clause keywords (WHERE/FROM/GROUP/HAVING/ORDER/LIMIT/JOIN/ON)

**Independent Test**: Input with `WHERE state = 'idle'` and `FROM pg_stat_activity` → neither appears in output

### Implementation for User Story 1

- [X] T005 [P] [US1] Add SQL clause keywords to _SQL_KEYWORDS frozenset in kb/holmes/kb/skill/manager.py (append: where, from, group, having, order, limit, join, on)
- [X] T006 [P] [US1] Add test class TestSQLClauseFilter in kb/tests/test_skill_manager.py (3 scenarios: WHERE/FROM filtered, real commands preserved, case-insensitive)

**Checkpoint**: `detect_commands()` filters all SQL clause keywords

---

## Phase 4: User Story 2 — backtick 误报过滤 (Priority: P1)

**Goal**: backtick path in CMD_PATTERN skips content containing `=` or `:`

**Independent Test**: `` `FATAL: slots` `` and `` `max_connections = 300` `` not in output; `` `redis-cli info` `` still detected

### Implementation for User Story 2

- [X] T007 [P] [US2] Add = / : filter to CMD_PATTERN backtick path in detect_commands() in kb/holmes/kb/skill/manager.py
- [X] T008 [P] [US2] Add test class TestBacktickFalsePositives in kb/tests/test_skill_manager.py (4 scenarios: colon filtered, equals filtered, real command kept, mixed text)

**Checkpoint**: backtick false positive rate = 0 for config values and error messages

---

## Phase 5: User Story 3 — run.sh SKILL_PARAM 注释 (Priority: P1)

**Goal**: Every generated run.sh includes SKILL_PARAM_* usage comment block

**Independent Test**: `auto_create_skill()` output run.sh contains `SKILL_PARAM_` in a comment

### Implementation for User Story 3

- [X] T009 [P] [US3] Add SKILL_PARAM comment block to run_sh_content template in auto_create_skill() in kb/holmes/kb/skill/manager.py
- [X] T010 [P] [US3] Add test class TestAutoCreateSkillParamComment in kb/tests/test_skill_manager.py (3 scenarios: comment present when $VAR used, comment present with {placeholder}, comment present with no params)

**Checkpoint**: all generated run.sh files contain SKILL_PARAM guidance

---

## Phase 6: User Story 4 — pending 批量 reject (Priority: P2)

**Goal**: `holmes kb reject --stale-days N` deletes all pending entries older than N days

**Independent Test**: 3 old entries + `reject --stale-days 1` → all deleted, output shows count

### Implementation for User Story 4

- [X] T011 [US4] Add --stale-days option to kb_reject() in kb/holmes/cli.py (make pending_id optional, add batch logic with cutoff comparison)
- [X] T012 [US4] Add test class TestBatchReject in kb/tests/test_integration.py (4 scenarios: batch deletes old entries, created_at fallback, zero results, backward compat single)

**Checkpoint**: `holmes kb reject --stale-days 30` deletes correct entries

---

## Phase 7: User Story 5 — pending mtime 兜底 (Priority: P2)

**Goal**: `list_pending()` fills `pending_since` from file mtime when both date fields are empty

**Independent Test**: old entry with no dates → `pending_since` is non-empty ISO string after `list_pending()`

### Implementation for User Story 5

- [X] T013 [P] [US5] Add mtime fallback to pending_since in list_pending() in kb/holmes/kb/pending.py (priority: pending_since > created_at > mtime)
- [X] T014 [P] [US5] Add test class TestPendingMtimeFallback in kb/tests/test_pending.py (3 scenarios: both empty→mtime used, created_at only→created_at used, pending_since→original kept)

**Checkpoint**: `list_pending()` never returns empty `pending_since` for existing files

---

## Phase 8: User Story 6 — search --type 过滤 (Priority: P3)

**Goal**: `holmes kb search <query> --type <type>` filters results by entry type

**Independent Test**: KB with pitfall + model entries matching same query; `--type pitfall` returns only pitfall

### Implementation for User Story 6

- [X] T015 [US6] Add --type option to kb_search() in kb/holmes/cli.py (post-filter results by kb_type, case-insensitive)
- [X] T016 [US6] Add test class TestSearchTypeFilter in kb/tests/test_integration.py (3 scenarios: type filter works, no filter returns all, nonexistent type returns empty)

**Checkpoint**: `holmes kb search --type pitfall` returns only pitfall entries

---

## Phase 9: User Story 7 — show --with-evidence 位置调整 (Priority: P3)

**Goal**: Evidence summary line appears before content body, not after

**Independent Test**: `show --with-evidence` output: Evidence line appears before first `##` section heading

### Implementation for User Story 7

- [X] T017 [US7] Move Evidence output block before click.echo(content) in kb_show() in kb/holmes/cli.py
- [X] T018 [US7] Add test class TestShowEvidencePosition in kb/tests/test_integration.py (2 scenarios: evidence before content, no --with-evidence unchanged)

**Checkpoint**: Evidence line is visible without scrolling on short entries

---

## Phase 10: User Story 8 — history --show 内部字段过滤 (Priority: P3)

**Goal**: `history --show` output strips `replaced_at/replaced_by/snapshot_reason`

**Independent Test**: snapshot with internal fields → output contains none of those field names

### Implementation for User Story 8

- [X] T019 [US8] Add fm.loads/pop/fm.dumps stripping of internal fields in kb_history() --show path in kb/holmes/cli.py
- [X] T020 [US8] Add test class TestHistoryShowFieldStrip in kb/tests/test_integration.py (2 scenarios: internal fields absent, knowledge fields present)

**Checkpoint**: `history --show` output is clean knowledge content

---

## Phase 11: User Story 9 — holmes --version (Priority: P3)

**Goal**: `holmes --version` and `holmes -v` output version number

**Independent Test**: `holmes --version` exits 0 and prints version string

### Implementation for User Story 9

- [X] T021 [US9] Add click.version_option to @cli group in kb/holmes/cli.py (use importlib.metadata with fallback to "0.1.0")
- [X] T022 [US9] Add test class TestHolmesVersion in kb/tests/test_integration.py (2 scenarios: --version outputs version, -v also works)

**Checkpoint**: `holmes --version` returns `0.1.0`

---

## Phase 12: Polish & Validation

**Purpose**: Validate all 9 fixes together, ensure no regressions

- [X] T023 Run full test suite and verify 328 + new tests all pass: `cd kb && python -m pytest --tb=short -q`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup + Foundational (Phase 1-2)**: No dependencies
- **US1, US2, US3 (Phase 3-5)**: All modify `skill/manager.py` — sequential within that file; can be parallel with cli.py work
- **US4, US6, US7, US8, US9 (Phase 6, 8-11)**: All modify `cli.py` — must be sequential
- **US5 (Phase 7)**: Modifies `pending.py` — parallel with cli.py and manager.py work
- **Polish (Phase 12)**: Depends on all story phases

### Parallel Opportunities

```bash
# After Phase 2:
manager.py track: US1 → US2 → US3 (sequential, same file)
cli.py track:     US4 → US6 → US7 → US8 → US9 (sequential, same file)
pending.py track: US5 (independent)

# US1, US2, US3 can run parallel with US4-US9 chain
# US5 can run parallel with everything
```

---

## Implementation Strategy

### MVP First (P1 bugs: US1-US3)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1 (SQL clauses)
4. Phase 4: US2 (backtick filter)
5. Phase 5: US3 (SKILL_PARAM comment)
6. **VALIDATE**: Run tests

### Full Delivery

7. Phase 6: US4 (batch reject)
8. Phase 7: US5 (mtime fallback)
9. Phase 8: US6 (search --type)
10. Phase 9: US7 (evidence position)
11. Phase 10: US8 (snapshot fields)
12. Phase 11: US9 (--version)
13. Phase 12: Polish

---

## Notes

- US1, US2, US3 all modify `skill/manager.py` — implement sequentially
- US4, US6, US7, US8, US9 all modify `cli.py` — implement sequentially
- US5 modifies `pending.py` — fully parallel
- backtick filter (US2): check `m.group(2) is not None` to identify backtick path before applying =/:  filter
- mtime (US5): `datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()`
- version (US9): `importlib.metadata.version("holmes-kb")` with `except PackageNotFoundError: return "0.1.0"`
