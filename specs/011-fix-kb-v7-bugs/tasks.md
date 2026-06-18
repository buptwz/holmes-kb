# Tasks: 修复 Holmes KB v7 报告问题

**Input**: Design documents from `specs/011-fix-kb-v7-bugs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md

**Organization**: Tasks grouped by user story (6 stories: US1-US2 P1, US3-US4-US5 P2, US6 P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/pending.py`, `kb/holmes/kb/skill/manager.py`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`

---

## Phase 1: Setup

**Purpose**: Verify baseline before surgical fixes

- [X] T001 Verify existing test suite passes (367 tests) via `cd kb && python -m pytest --tb=short -q`

---

## Phase 2: Foundational

**Purpose**: Confirm exact locations for all 6 fixes before editing

- [X] T002 Read `kb/holmes/kb/skill/manager.py` lines 462-484 to confirm detect_commands() backtick filter location
- [X] T003 [P] Read `kb/holmes/cli.py` lines 525-544 to confirm kb_write_pending() signature
- [X] T004 [P] Read `kb/holmes/cli.py` lines 813-864 to confirm kb_reject() dry-run guard
- [X] T005 [P] Read `kb/holmes/cli.py` lines 1212-1258 to confirm kb_archive_orphans() structure
- [X] T006 [P] Read `kb/holmes/cli.py` lines 510-522 to confirm pending table CREATED column

**Checkpoint**: All fix locations confirmed

---

## Phase 3: User Story 1 — detect-commands 补充过滤规则 (Priority: P1)

**Goal**: backtick 路径中跳过 JVM 参数、配置键、方法调用、配置块开头

**Independent Test**: detect_commands() on JVM/config-key/method-call/config-block text returns empty or correct results

### Implementation for User Story 1

- [X] T007 [US1] Add 4 backtick filter rules to detect_commands() in `kb/holmes/kb/skill/manager.py` (~line 472): after existing `=`/`:` check, add startswith("-X"), regex config-key match, alpha+`(` method call, endswith("{") config block
- [X] T008 [P] [US1] Add test class TestDetectCommandsBacktickFilters in `kb/tests/test_skill_manager.py` (5 scenarios: JVM arg filtered, config key filtered, method call filtered, config block filtered, real command redis-cli ping not filtered)

**Checkpoint**: detect_commands() returns [] for all 4 false-positive categories

---

## Phase 4: User Story 2 — amend-pending 命令 (Priority: P1)

**Goal**: 新增 `holmes kb amend-pending <id>` 命令，支持修复 Gate 1 失败的 pending 内容

**Independent Test**: write invalid pending → Gate 1 fails → amend with valid content → confirm succeeds

### Implementation for User Story 2

- [X] T009 [US2] Add `amend-pending` command to `kb/holmes/cli.py` (after kb_write_pending, ~line 544): @kb.command("amend-pending"), accepts pending_id arg + --content/--file options (mutually exclusive), reads original pending file, merges metadata (preserve id/pending_since/source/source_session/pending, re-derive suggested_type/suggested_category from new content), writes back to same path, outputs "✓ Amended: <id>"
- [X] T010 [P] [US2] Add test class TestAmendPending in `kb/tests/test_integration.py` (4 scenarios: amend with --content replaces content, amend with --file replaces content, amend on nonexistent id errors with exit 1, amend preserves pending_since/id/source metadata)

**Checkpoint**: amend-pending replaces content and keeps system metadata intact

---

## Phase 5: User Story 3 — write-pending --file 选项 (Priority: P2)

**Goal**: write-pending 接受 --file path/to/entry.md，与 --content 互斥

**Independent Test**: write-pending --file and --content produce same pending entry

### Implementation for User Story 3

- [X] T011 [US3] Modify kb_write_pending() in `kb/holmes/cli.py` (~line 525): change --content to required=False, add --file option (click.Path(exists=True)), add mutual-exclusion logic in function body (both→error, neither→error, --file→read file content)
- [X] T012 [P] [US3] Add test class TestWritePendingFile in `kb/tests/test_integration.py` (4 scenarios: --file writes pending, nonexistent --file errors, both --content and --file errors, neither errors)

**Checkpoint**: write-pending --file produces identical result to --content with same file content

---

## Phase 6: User Story 4 — archive-orphans --dry-run (Priority: P2)

**Goal**: archive-orphans --dry-run 打印将被归档 ID 不执行归档

**Independent Test**: archive-orphans --dry-run prints IDs, directory unchanged

### Implementation for User Story 4

- [X] T013 [US4] Add --dry-run flag to kb_archive_orphans() in `kb/holmes/cli.py` (~line 1212): skip archive_orphan() calls when dry_run=True, output "(dry run)" suffix in text/JSON modes
- [X] T014 [P] [US4] Add test class TestArchiveOrphansDryRun in `kb/tests/test_integration.py` (3 scenarios: dry-run prints IDs without moving files, dry-run output contains "(dry run)", normal mode behavior unchanged)

**Checkpoint**: archive-orphans --dry-run leaves filesystem unchanged

---

## Phase 7: User Story 5 — reject 单条 --dry-run (Priority: P2)

**Goal**: reject <id> --dry-run 打印条目不删除，消除"requires --stale-days"错误

**Independent Test**: reject <id> --dry-run prints entry ID, file not deleted

### Implementation for User Story 5

- [X] T015 [US5] Modify kb_reject() in `kb/holmes/cli.py` (~line 828): remove `if dry_run and stale_days is None: error` guard; in single-entry mode, if dry_run: print pending_id and "(dry run)" message, skip delete_pending() and append_log() calls
- [X] T016 [P] [US5] Add test class TestRejectSingleDryRun in `kb/tests/test_integration.py` (2 scenarios: reject <id> --dry-run prints ID with "(dry run)" and file not deleted, reject <id> without --dry-run still deletes file)

**Checkpoint**: reject <id> --dry-run no longer errors; consistent with batch dry-run behavior

---

## Phase 8: User Story 6 — pending 表格 CREATED 列 (Priority: P3)

**Goal**: pending 表格 CREATED 列显示 pending_since 而非 created_at

**Independent Test**: old-format pending entry shows non-empty CREATED in table

### Implementation for User Story 6

- [X] T017 [US6] Modify pending table display in kb_pending() (or equivalent) in `kb/holmes/cli.py` (~line 521): change `str(e['created_at'])[:10]` to `str(e['pending_since'])[:10]`
- [X] T018 [P] [US6] Add test class TestPendingTableCreatedColumn in `kb/tests/test_integration.py` (2 scenarios: old-format entry without created_at shows pending_since in CREATED column, new-format entry with created_at still shows non-empty CREATED)

**Checkpoint**: CREATED column is non-empty for all pending entries in table mode

---

## Phase 9: Polish & Validation

**Purpose**: Validate all 6 fixes together, ensure no regressions

- [X] T019 Run full test suite and verify 367 + new tests all pass: `cd kb && python -m pytest --tb=short -q`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup + Foundational (Phase 1-2)**: No dependencies
- **US1 (Phase 3)**: Modifies `manager.py` — parallel with cli.py and pending.py work
- **US2, US3, US4, US5, US6 (Phase 4-8)**: All modify `cli.py` — sequential within cli.py edits
- **Polish (Phase 9)**: Depends on all story phases

### Parallel Opportunities

```bash
# After Phase 2:
manager.py track: US1 (T007-T008)
cli.py track:     US2 → US3 → US4 → US5 → US6 (sequential due to same file)
test track:       All test tasks [P] can run alongside their impl tasks
```

---

## Implementation Strategy

### MVP First (P1 bugs: US1-US2)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: US1 (detect-commands filters)
4. Phase 4: US2 (amend-pending)
5. **VALIDATE**: Run tests

### Full Delivery

6. Phase 5: US3 (write-pending --file)
7. Phase 6: US4 (archive-orphans --dry-run)
8. Phase 7: US5 (reject single --dry-run)
9. Phase 8: US6 (pending table CREATED)
10. Phase 9: Polish

---

## Notes

- US1: Add import re at top of manager.py if not already present (check first)
- US2: amend-pending shares --content/--file mutual-exclusion logic with write-pending (US3) — implement US3 first or keep logic inline
- US3: `--content required=False` — add runtime check since click won't enforce it
- US5: dry-run in single mode: print pending_id + summary line with "(dry run)", exit 0 without deleting
- US6: `pending_since` is guaranteed non-empty by list_pending() → no null guard needed
- Test file check: `CliRunner` in click 8.2.1 has no `mix_stderr` param — use `result.output` for all checks
