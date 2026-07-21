# Tasks: 修复 Holmes KB v8 报告问题

**Input**: Design documents from `specs/012-fix-kb-v8-bugs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contracts.md

**Organization**: Tasks grouped by user story (7 stories: US1-US2 P1, US3-US6 P2, US7 P3).

## Path Conventions

- Source: `kb/holmes/cli.py`, `kb/holmes/kb/skill/manager.py`
- Tests: `kb/tests/test_integration.py`, `kb/tests/test_skill_manager.py`

---

## Phase 1: Setup

- [X] T001 Verify existing test suite passes (387 tests) via `cd kb && python -m pytest --tb=short -q`

---

## Phase 2: Foundational

- [X] T002 Read `kb/holmes/cli.py` lines 560-600 to confirm kb_amend_pending() structure
- [X] T003 [P] Read `kb/holmes/kb/skill/manager.py` lines 34-60 to confirm _CODE_BLOCK_RE and _extract_code_block_lines
- [X] T004 [P] Read `kb/holmes/cli.py` lines 698-714 to confirm Gate 3 confirm structure
- [X] T005 [P] Read `kb/holmes/cli.py` lines 983-1036 to confirm kb_resolve_conflict exits
- [X] T006 [P] Read `kb/holmes/cli.py` lines 1087-1097 to confirm kb_list decorator
- [X] T007 [P] Read `kb/holmes/cli.py` lines 1177-1214 to confirm kb_history not-found branches

---

## Phase 3: User Story 1 — amend-pending updated_at (Priority: P1)

- [X] T008 [US1] In kb_amend_pending() in `kb/holmes/cli.py`: after `new_post.metadata.update(preserved)`, inject `updated_at = now().isoformat()` and `setdefault("created_at", original.metadata.get("created_at", ""))`
- [X] T009 [P] [US1] Add test class TestAmendPendingUpdatedAt in `kb/tests/test_integration.py` (3 scenarios: amend injects updated_at, amend preserves original created_at, amend with no original created_at doesn't error)

---

## Phase 4: User Story 2 — detect-commands code block lang filter (Priority: P1)

- [X] T010 [US2] In `kb/holmes/kb/skill/manager.py`: change _CODE_BLOCK_RE to capture lang tag `r"```([a-z]*)\n(.*?)```"`, add `_SHELL_LANGS = frozenset({"", "bash", "sh", "shell", "zsh"})`, update _extract_code_block_lines to check lang and use group(2)
- [X] T011 [P] [US2] Add test class TestDetectCommandsCodeBlockLangFilter in `kb/tests/test_skill_manager.py` (5 scenarios: nginx block filtered, python block filtered, bash block kept, no-lang block kept, shell block kept)

---

## Phase 5: User Story 3 — write-pending frontmatter validation (Priority: P2)

- [X] T012 [US3] In kb_write_pending() in `kb/holmes/cli.py`: after content is resolved (post --file read), check `if not content.strip().startswith("---"):` → error + exit 1
- [X] T013 [P] [US3] Add test class TestWritePendingFrontmatterValidation in `kb/tests/test_integration.py` (4 scenarios: empty content rejected, plain text rejected, valid frontmatter accepted, --file with no frontmatter rejected)

---

## Phase 6: User Story 4 — Gate 3 long content yes confirm (Priority: P2)

- [X] T014 [US4] In kb_confirm() in `kb/holmes/cli.py`: in the `if len(_preview_raw) > 800:` branch, replace `click.confirm("Confirm this entry?", default=True)` with `click.prompt("Type 'yes' to confirm this entry")` → check `.lower() == "yes"` → if not, echo "Aborted." + sys.exit(0)
- [X] T015 [P] [US4] Add test class TestGate3LongContentConfirm in `kb/tests/test_integration.py` (3 scenarios: long content with 'yes' input confirms, long content with 'y' input aborts, short content still uses Y/n default)

---

## Phase 7: User Story 5 — resolve auto-rebuild index (Priority: P2)

- [X] T016 [US5] In kb_resolve_conflict() in `kb/holmes/cli.py`: before the final `click.echo(f"✓ Conflict ... resolved ...")` in both --keep and --manual paths, import and call `rebuild_index_files(kb_root)` + echo "✓ Index rebuilt."
- [X] T017 [P] [US5] Add test class TestResolveRebuildsIndex in `kb/tests/test_integration.py` (2 scenarios: resolve output contains "Index rebuilt", resolve auto-rebuilds index so entry appears in list)

---

## Phase 8: User Story 6 — list --maturity filter (Priority: P2)

- [X] T018 [US6] In kb_list() decorator in `kb/holmes/cli.py`: add `@click.option("--maturity", "kb_maturity", default=None)` to decorator; in function body add maturity param, warn on invalid value, filter entries list
- [X] T019 [P] [US6] Add test class TestListMaturityFilter in `kb/tests/test_integration.py` (5 scenarios: --maturity draft returns only drafts, --maturity proven returns only proven, combined --maturity + --type, --json mode also filters, invalid --maturity warns)

---

## Phase 9: User Story 7 — history exit codes (Priority: P3)

- [X] T020 [US7] In kb_history() in `kb/holmes/cli.py`: change `return` to `sys.exit(1)` in `--show` not-found branch; change `return` to `sys.exit(1)` in `not snapshots` branch
- [X] T021 [P] [US7] Add test class TestHistoryExitCodes in `kb/tests/test_integration.py` (4 scenarios: nonexistent entry exits 1, existing entry exits 0, --show nonexistent exits 1, --show valid exits 0)

---

## Phase 10: Polish & Validation

- [X] T022 Run full test suite: `cd kb && python -m pytest --tb=short -q`
