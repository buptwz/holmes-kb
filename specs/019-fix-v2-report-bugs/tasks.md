---

description: "Task list for Import Pipeline v2 Report Bug Fixes (019)"

---

# Tasks: Import Pipeline v2 Report Bug Fixes

**Input**: Design documents from `specs/019-fix-v2-report-bugs/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ quickstart.md ✅

**Organization**: Tasks grouped by user story. US1 (crash fix) is P0 and blocks verification of everything else. US2–US5 are independent code fixes. US6 is data cleanup.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

**Purpose**: Verify working environment and existing test baseline.

- [X] T001 Run existing test suite (`cd kb && python -m pytest tests/ -q`) and record baseline pass count to confirm no pre-existing failures

---

## Phase 2: Foundational

No shared infrastructure work needed — all fixes are isolated to specific functions.

---

## Phase 3: User Story 1 — CommandCandidate Crash Fix (Priority: P1) 🎯 MVP

**Goal**: Every `holmes import` completes without TypeError; run.sh gets actual commands; SKILL.md gets params block for {PARAM} placeholders.

**Independent Test**: `holmes import <document-with-commands> --no-interactive` → exit 0, `✓ N created` summary line.

- [X] T002 [US1] In `runner.py` `_dispatch_tool()`, change `tool_input["resolution_commands"] = det_cmds` to `tool_input["resolution_commands"] = [c.line for c in det_cmds]` (det_cmds is list[CommandCandidate], not list[str])
- [X] T003 [US1] In `runner.py` `_dispatch_tool()`, change `_PARAM_RE_DISPATCH.findall(cmd)` to `_PARAM_RE_DISPATCH.findall(cmd.line)` in the param_names extraction loop
- [X] T004 [US1] In `runner.py` `_run_skill_and_curation()`, change `_PARAM_RE.findall(cmd)` to `_PARAM_RE.findall(cmd.line)` in the param_names extraction loop
- [X] T005 [US1] In `runner.py` `_run_skill_and_curation()`, store `cmd_lines = [c.line for c in extracted_commands]` and use `cmd_lines` instead of `extracted_commands` for `"resolution_commands"` in the `create_skill_for_entry` call
- [X] T006 [US1] Add unit tests in `kb/tests/test_agent_runner.py`: mock `detect_commands` to return `[CommandCandidate(line="kubectl get pods", ...)]`; verify no TypeError and param_names are correctly extracted when command contains `{NAMESPACE}`

**Checkpoint**: After T002–T006, `holmes import` completes without crash. `SKILL.md` contains `params:` block; `run.sh` contains actual commands.

---

## Phase 4: User Story 2 — --type Flag Respected End-to-End (Priority: P2)

**Goal**: `--type guideline` always produces `type: guideline` in the final pending entry, even if LLM would classify differently.

**Independent Test**: Import pitfall document with `--type guideline`; check pending entry frontmatter has `type: guideline`.

- [X] T007 [US2] In `kb/holmes/kb/agent/pipeline.py` `run()`, add `"force_type": self.force_type or ""` to the `ctx` dict so it flows to all tool handlers
- [X] T008 [US2] In `kb/holmes/kb/agent/tools.py` `write_kb_entry()`, after parsing frontmatter, read `force_type = ctx.get("force_type", "") or ""`; if non-empty set `post.metadata["type"] = force_type` and `post.metadata["suggested_type"] = force_type` before writing
- [X] T009 [US2] Add unit test in `kb/tests/test_tools.py` (or `test_pipeline.py`): construct ctx with `force_type="guideline"`, call `write_kb_entry` with content having `type: pitfall`; assert resulting file has `type: guideline`

**Checkpoint**: After T007–T009, `--type guideline` is preserved through Phase 3 LLM loop.

---

## Phase 5: User Story 3 — Re-import Is a No-Op (Priority: P2)

**Goal**: Importing the same document twice creates exactly 1 pending entry; second import returns `skipped`.

**Independent Test**: Import same doc 3× → pending count increases by 1 total.

- [X] T010 [US3] In `kb/holmes/kb/agent/tools.py` `write_kb_entry()`, before calling `write_pending()`, check `if source_hash and not force: existing_id, _ = _find_entry_by_hash(kb_root, source_hash); if existing_id: return {"pending_id": existing_id, "dry_run": False, "action": f"Skipped: duplicate source hash already in KB ({existing_id})", "duplicate": True}`
- [X] T011 [US3] In `kb/holmes/kb/agent/runner.py` `_maybe_post_process()`, ensure the `write_kb_entry` duplicate-skip case (when `result.get("duplicate")` is True) does NOT add the entry to `_created_entry_contents` (since the content would be empty string — the entry already exists)
- [X] T012 [US3] Add unit tests in `kb/tests/test_tools.py`: (a) import same source_hash twice → second call returns `duplicate=True`; (b) import with `force=True` → skips hash check and creates new entry; (c) empty source_hash → skips hash check normally

**Checkpoint**: After T010–T012, re-importing identical document is idempotent.

---

## Phase 6: User Story 4 — Skill Gate Bypass Fix (Priority: P3)

**Goal**: User answering "n" to skill creation prompt means 0 skill directories are created (neither by tool loop nor fallback).

**Independent Test**: Import with prompt="n"; verify skills/ directory unchanged.

- [X] T013 [US4] In `kb/holmes/kb/agent/runner.py` `__init__`, add `self._skill_evaluated_entries: set[str] = set()` to track entry_ids handled by the tool loop
- [X] T014 [US4] In `kb/holmes/kb/agent/runner.py` `_dispatch_tool()`, at the top of the `create_skill_for_entry` block (before the interactive gate check), add `self._skill_evaluated_entries.add(tool_input.get("entry_id", ""))` so both confirmed and declined entries are tracked
- [X] T015 [US4] In `kb/holmes/kb/agent/runner.py` `_finalize_skill_generation()`, at the start of the loop body, add `if pending_id in self._skill_evaluated_entries: continue` to skip already-handled entries
- [X] T016 [US4] Add unit tests in `kb/tests/test_agent_runner.py`: verify `_finalize_skill_generation` skips entries whose pending_id is in `_skill_evaluated_entries`; verify entries NOT in the set are still processed by fallback

**Checkpoint**: After T013–T016, user rejection is respected end-to-end.

---

## Phase 7: User Story 5 — Existing Similar Skill Linked (Priority: P3)

**Goal**: Fallback skill generation uses entry title for similarity check, preventing duplicate skills for same-topic entries.

**Independent Test**: Import two same-topic documents; second entry links to existing skill.

- [X] T017 [US5] In `kb/holmes/kb/agent/runner.py`, update `_run_skill_and_curation` signature to add `description: Optional[str] = None` parameter and forward it as `advisor.advise(entry_id, resolution_text, self.kb_root, description=description)`
- [X] T018 [US5] In `kb/holmes/kb/agent/runner.py` `_finalize_skill_generation()`, after parsing entry frontmatter, extract `title: Optional[str] = str(post.metadata.get("title", "")) or None` and pass it as `description=title` to `_run_skill_and_curation()`
- [X] T019 [US5] Add unit test in `kb/tests/test_agent_runner.py`: mock `SkillAdvisor.advise` to capture the `description` kwarg; verify it receives the entry's title when called from `_finalize_skill_generation`

**Checkpoint**: After T017–T019, Jaccard similarity check fires with title context in fallback path.

---

## Phase 8: User Story 6 — KB Data Quality Cleanup (Priority: P3)

**Goal**: Fix PT-DB-002 duplicate sections, PT-DB-005 body_additions, delete test junk files.

**Independent Test**: `grep "^## " PT-DB-002.md` shows each section once; `grep body_additions PT-DB-005.md` returns empty; test files absent.

- [ ] T020 [US6] Fix `/home/wangzhi/holmes-kb/pitfall/database/PT-DB-002.md`: remove the first (Redis) Symptoms/Root Cause/Resolution block (lines 19–30), keeping only the second (HikariCP) block which has kubectl commands and matches the skill_ref; update the title to reflect HikariCP content
- [ ] T021 [US6] Fix `/home/wangzhi/holmes-kb/pitfall/database/PT-DB-005.md`: remove the `body_additions:` and `additional_context:` frontmatter keys; the existing markdown body (Symptoms/Root Cause/Resolution from line ~39) is canonical
- [ ] T022 [US6] Delete `/home/wangzhi/holmes-kb/pitfall/database/PT-DB-TEST2.md`
- [ ] T023 [US6] Delete `/home/wangzhi/holmes-kb/pitfall/network/PT-NET-TEST.md`

**Checkpoint**: After T020–T023, KB entries render correctly; no test junk in committed KB.

---

## Phase 9: Polish & Validation

- [X] T024 Run full test suite (`cd kb && python -m pytest tests/ -q`) and verify pass count ≥ baseline from T001 plus new tests; zero failures
- [ ] T025 Run quickstart.md scenario 4 (re-import no-op): import same doc twice, verify second run shows `0 created` or `skipped` in output

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** (T001): No dependencies — run immediately
- **Phase 3** (T002–T006): Depends on T001 baseline; must complete before US2–US5 can be verified end-to-end (crash blocks all)
- **Phase 4** (T007–T009): Independent of US1 code; can start in parallel with US1 (different files)
- **Phase 5** (T010–T012): Independent; `tools.py` is a different file from US1's `runner.py`
- **Phase 6** (T013–T016): All in `runner.py`; run after T002–T005 complete to avoid merge conflicts
- **Phase 7** (T017–T019): All in `runner.py`; run after Phase 6 complete
- **Phase 8** (T020–T023): Fully independent (KB data files, not source code)
- **Phase 9** (T024–T025): Depends on all prior phases complete

### Parallel Opportunities

- T007–T009 (pipeline.py + tools.py) can run in parallel with T002–T006 (runner.py)
- T010–T012 (tools.py dedup) can run in parallel with T013–T016 (runner.py skill tracking)
- T020–T023 (KB data) can run in parallel with any code phase

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. T001 — verify baseline
2. T002–T006 — fix CommandCandidate crash
3. T024 — run tests, verify crash gone
4. **STOP and validate**: imports no longer crash

### Full Delivery

Complete phases in order 1 → 3 → 4/5 (parallel) → 6 → 7 → 8 → 9.

---

## Notes

- All 4 CommandCandidate fixes are in `runner.py` and must be sequential (same file)
- T010 and T011 are related (tools.py write + runner.py post-process) — do together
- KB data fixes (T020–T023) are entirely independent; can be done any time
- Constitution: 验证原则 requires tests for each fix (T006, T009, T012, T016, T019)
