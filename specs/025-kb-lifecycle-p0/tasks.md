# Tasks: Knowledge Lifecycle P0 — Evidence, Maturity, Search

**Input**: Design documents from `/specs/025-kb-lifecycle-p0/`

**Prerequisites**: plan.md, spec.md, research.md

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: Verify baseline before making changes.

- [X] T001 Run existing test suites and record baseline: `cd kb && python -m pytest -q` and `cd agent && python -m pytest -q 2>/dev/null || echo "agent tests N/A"`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: US1 (engine.py) and US3 (search.py) touch entirely different files and are fully independent. No shared blocking prerequisites. This phase verifies test file existence.

- [X] T002 Check that `agent/tests/` directory exists and `agent/tests/test_engine.py` exists; if not, create a minimal test module with `import pytest` header and an empty placeholder

**Checkpoint**: Test infrastructure confirmed — US1 and US3 can proceed in parallel.

---

## Phase 3: User Story 1 — Evidence 写回 (Priority: P1) 🎯 MVP

**Goal**: agent 读取 KB 条目时自动记录 entry_id；session 结束时批量调用 `append_evidence()` 写入 evidence sidecar。

**Independent Test**: 使用 mock 工具环境，令 engine 执行 `kb_read_entry` 工具成功调用，然后触发 session 结束事件，断言 `session.kb_refs` 包含对应 entry_id 且 `append_evidence()` 被调用。

### Implementation for User Story 1

- [X] T003 [US1] In `agent/holmes/agent/engine.py` chat() method: after `result = await self._exec_tool(tool, tool_input)` succeeds and `status != "error"`, add block — if `tool_name == "kb_read_entry"` and `entry_id := tool_input.get("entry_id", "")` is truthy and not in `self._session.kb_refs`, append it to `self._session.kb_refs`; apply to BOTH the `requires_confirmation` approved path and the non-confirmation path
- [X] T004 [US1] Add private method `_flush_evidence(self) -> None` to AgentEngine class in `agent/holmes/agent/engine.py`: import `append_evidence` from `holmes.kb.store` and `date` from `datetime`; guard on `self._kb_root` and non-empty `self._session.kb_refs`; for each entry_id call `append_evidence(self._kb_root, entry_id, {"session_id": self._session.id, "contributor": self._session.id, "date": date.today().isoformat()})` wrapped in try/except; log each result with `logger.info`
- [X] T005 [US1] In `agent/holmes/agent/engine.py` chat() method, `_InternalStopEvent` handler: call `self._flush_evidence()` immediately before `yield DoneEvent(...)`

### Tests for User Story 1

- [X] T006 [US1] Add `test_engine_records_kb_ref_on_successful_read` to `agent/tests/test_engine.py`: create AgentEngine with mock session and kb_root; simulate successful `kb_read_entry` tool call with `entry_id="PT-001"`; assert `"PT-001"` in `session.kb_refs`
- [X] T007 [US1] Add `test_engine_does_not_record_kb_ref_on_error` to `agent/tests/test_engine.py`: simulate `kb_read_entry` call returning `ToolResult(is_error=True)`; assert `session.kb_refs` is empty
- [X] T008 [US1] Add `test_engine_deduplicates_kb_refs` to `agent/tests/test_engine.py`: simulate `kb_read_entry` called twice with same `entry_id="PT-001"`; assert `session.kb_refs` has exactly one entry
- [X] T009 [US1] Add `test_engine_flushes_evidence_on_done` to `agent/tests/test_engine.py`: mock `holmes.kb.store.append_evidence`; set `session.kb_refs = ["PT-001"]` and `engine._kb_root = Path("/tmp/kb")`; call `engine._flush_evidence()`; assert `append_evidence` was called once with `entry_id="PT-001"` and record containing `session_id` and `date`

**Checkpoint**: US1 complete — session evidence is automatically recorded on KB entry reads.

---

## Phase 4: User Story 2 — Maturity 自动更新验证 (Priority: P2)

**Goal**: 确认 P0-2 由 `append_evidence()` 自动实现，无需额外代码；运行现有 store 测试验证 maturity 链式更新正常工作。

**Independent Test**: 运行 `kb/tests/test_store.py` 中与 `append_evidence` + `derive_maturity` 相关的测试，全部通过即验证 US2 已就绪。

### Implementation for User Story 2

- [X] T010 [US2] Verify `append_evidence()` maturity chain: in `kb/holmes/kb/store.py` lines 289–297, confirm the existing code loads all evidence, calls `derive_maturity()`, and writes updated maturity only when rank increases — no code change required; add a comment `# P0-2: maturity auto-update is handled here` above the block for clarity; run `cd kb && python -m pytest tests/test_store.py -q -k "evidence or maturity"` and confirm passage

**Checkpoint**: US2 verified — maturity auto-updates via existing `append_evidence()` logic.

---

## Phase 5: User Story 3 — 搜索按 Evidence 新鲜度排序 (Priority: P3)

**Goal**: `LinearScanBackend.search()` 以 `last_evidence_date` 为主排序键；无 evidence 的条目排在有 evidence 条目之后；关键词过滤逻辑不变。

**Independent Test**: 准备两条关键词相同的 KB 条目（一条有近期 evidence sidecar，一条无），执行搜索，有 evidence 的条目在结果中位置靠前。

### Implementation for User Story 3

- [X] T011 [US3] Add `last_evidence_date: Optional[str] = None` field to `SearchResult` dataclass in `kb/holmes/kb/search.py`; ensure `Optional` is imported from `typing`
- [X] T012 [US3] In `LinearScanBackend.search()` in `kb/holmes/kb/search.py`: add imports `from holmes.kb.store import load_evidence, get_last_evidence_date` at top of file; inside the scan loop, after computing `hits` but before `results.append(...)`, add: `evidence = load_evidence(self._kb_root, str(meta.get("id", md_file.stem)))` and `led = get_last_evidence_date(evidence)`; pass `last_evidence_date=led` to `SearchResult(...)` constructor
- [X] T013 [US3] Update sort key in `LinearScanBackend.search()` in `kb/holmes/kb/search.py`: replace `results.sort(key=lambda r: r.score, reverse=True)` with `results.sort(key=lambda r: (r.last_evidence_date or "", r.score), reverse=True)`

### Tests for User Story 3

- [X] T014 [US3] Add `test_search_ranks_evidence_entry_higher` to `kb/tests/test_search.py`: create two temp KB entries with identical keywords; write a sidecar evidence JSON file for one (recent date); call `search()`; assert entry with evidence appears at index 0
- [X] T015 [US3] Add `test_search_no_evidence_falls_back_to_score` to `kb/tests/test_search.py`: two entries both with no evidence but different keyword hit ratios; call `search()`; assert higher hit-ratio entry appears first

**Checkpoint**: US3 complete — search results prioritize recently-validated knowledge.

---

## Phase 6: Polish & Validation

**Purpose**: 全套回归检查，确认三个 P0 无互相干扰。

- [X] T016 Run full KB test suite: `cd kb && python -m pytest -q` — confirm no regressions
- [X] T017 Run full agent test suite: `cd agent && python -m pytest -q 2>/dev/null || echo "agent suite done"` — confirm no regressions
- [X] T018 Manual smoke test: import a KB entry, start an agent session and simulate `kb_read_entry` tool call, end session, inspect evidence sidecar file to confirm record written and maturity updated

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Phase 1
- **US1 (Phase 3)**: Depends on Phase 2; independent of US3
- **US2 (Phase 4)**: Depends on US1 (needs append_evidence to be called from engine)
- **US3 (Phase 5)**: Depends on Phase 2; **fully independent of US1 and US2**
- **Polish (Phase 6)**: Depends on US1 + US2 + US3 completion

### Within Each User Story

- T003 → T004 → T005: sequential (same file engine.py, each builds on previous)
- T006, T007, T008, T009: sequential (all add to same test file)
- T011 → T012 → T013: sequential (same file search.py, T012 depends on T011 for field)
- T014, T015: sequential (same test file)

### Parallel Opportunities

- **US1 (Phase 3) and US3 (Phase 5)** can be worked in parallel by different developers — zero file overlap
- T010 (US2) can be done in parallel with US3 (Phase 5) after US1 is complete

---

## Parallel Example: US1 + US3 Simultaneously

```text
# Developer A — US1 (engine.py):
T003 → T004 → T005 → T006 → T007 → T008 → T009

# Developer B — US3 (search.py) — no dependency on US1:
T011 → T012 → T013 → T014 → T015
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational check
3. Complete Phase 3: US1 (evidence write-back)
4. **STOP and VALIDATE**: agent reads KB entry → check evidence sidecar written
5. Proceed to US2 verification, then US3

### Incremental Delivery

1. Setup + Foundational → infrastructure verified
2. US1 → evidence feedback loop live (most critical P0)
3. US2 → maturity auto-update verified (free from US1)
4. US3 → search freshness ranking live
5. Polish → full regression check

---

## Notes

- No new external dependencies (uses existing `store.py` functions)
- `update_references()` in store.py is a separate legacy path using `reference_count`; do NOT remove it — it may be called from CLI commands; our new path uses `append_evidence()` only
- Evidence sidecar directory: `contributions/evidence/<entry_id>/<session_id>.json` — created automatically by `append_evidence()`
- Session dedup: `append_evidence()` already deduplicates by `session_id`; the engine-side dedup in `session.kb_refs` is a secondary guard to avoid unnecessary sidecar writes
- Baseline test count: 731 tests; final count should be 731 + ~6 new tests = ~737
