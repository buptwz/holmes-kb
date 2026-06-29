# Tasks: M5 — Agent 2 双源知识生成

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M5-agent2/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/tools2-interface.md ✅

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1–US4)
- Paths relative to repo root: `kb/holmes/kb/agent/dag/` and `kb/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create file skeletons and establish package structure for all new modules.

- [X] T001 Create `kb/holmes/kb/agent/dag/id_gen.py` skeleton (module docstring + public API stubs: `generate_entry_ids`, `get_or_create_import_seq`)
- [X] T002 [P] Create `kb/holmes/kb/agent/dag/tools2.py` skeleton (module docstring + TOOLS2_DEFINITIONS list + TOOLS2_HANDLERS dict stubs)
- [X] T003 [P] Create `kb/holmes/kb/agent/dag/harness2.py` skeleton (module docstring + Agent2Harness class stub)
- [X] T004 [P] Create `kb/holmes/kb/agent/dag/prompt2.py` skeleton (module docstring + AGENT2_SYSTEM_PROMPT stub)
- [X] T005 [P] Create `kb/holmes/kb/agent/dag/lint.py` skeleton (module docstring + LintResult dataclass + run_lint stub)
- [X] T006 [P] Create `kb/holmes/kb/agent/dag/report2.py` skeleton (module docstring + print_agent2_report stub)
- [X] T007 [P] Create `kb/holmes/kb/agent/dag/step25.py` skeleton (module docstring + ParseResult dataclass + run_step25 stub)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: ID 预生成和 tools2 工具集是所有 user story 的前提依赖。

**⚠️ CRITICAL**: Phases 3-6 cannot begin until this phase is complete.

### Entry ID Generation

- [X] T008 Implement `generate_entry_ids(dag_json_path)` in `kb/holmes/kb/agent/dag/id_gen.py`:
  - Read existing `.dag.json`; if `entry_ids` already present, return as-is (idempotent)
  - Call `get_or_create_import_seq(state_dir)` to determine 3-digit seq
  - For each process node: `{source_name_slug}-{node_id}-{import_seq}`; pitfall root: `{source_name_slug}-root-{import_seq}`
  - Write `entry_ids` + `import_seq` fields back to `.dag.json` via `atomic_write()`
- [X] T009 Implement `get_or_create_import_seq(state_dir)` in `kb/holmes/kb/agent/dag/id_gen.py`:
  - Scan `_import-state/*.dag.json` for max existing `import_seq`; return incremented value
  - Default to `"001"` if none found
- [X] T010 [P] Write tests for `id_gen.py` in `kb/tests/test_id_gen.py`:
  - Test idempotency: calling twice returns same entry_ids
  - Test seq allocation: first call → `001`, second doc → `002`
  - Test process node ID format: `{slug}-{node_id}-{seq}`
  - Test pitfall root ID format: `{slug}-root-{seq}`

### Agent 2 Tools (tools2.py)

- [X] T011 Implement `tool_read_dag2(ctx, tool_input)` in `kb/holmes/kb/agent/dag/tools2.py`:
  - Read `.dag.json` including `entry_ids` and `import_seq` fields
  - Return full dag data including nodes list and entry_ids dict
- [X] T012 [P] Implement `tool_read_entry(ctx, tool_input)` in `kb/holmes/kb/agent/dag/tools2.py`:
  - Scan `_pending/<type>/<category>/` for `<entry_id>.md`; also scan already-written in ctx
  - Return `{"title": ..., "content": ..., "frontmatter": {...}}`; error if not found
- [X] T013 [P] Implement `tool_write_entry(ctx, tool_input)` in `kb/holmes/kb/agent/dag/tools2.py`:
  - Parse frontmatter from content; run format validation (all required fields, required sections, ID refs in entry_ids)
  - On failure: return `{"error": "..."}` (no write)
  - On `content_source: description_match_failed` in frontmatter: write + return warning
  - On success: `atomic_write()` to `_pending/<type>/<category>/<entry_id>.md`; append to `ctx["written_entries"]`
- [X] T014 [P] Implement `tool_finalize(ctx, tool_input)` in `kb/holmes/kb/agent/dag/tools2.py`:
  - Set `ctx["_terminate"] = True`
  - Invoke `run_lint(ctx)` from `lint.py` and store results in `ctx["lint_results"]`
  - Return `{"_terminate": true, "success": true, "lint_passed": N, "lint_failed": M, "lint_errors": [...]}`
- [X] T015 [P] Complete TOOLS2_DEFINITIONS and TOOLS2_HANDLERS in `kb/holmes/kb/agent/dag/tools2.py`:
  - Import `tool_read, tool_grep` from `tools1.py`; add to handlers
  - Tool definitions for all 6 tools (Anthropic input_schema format)
- [X] T016 [P] Write tests for `tools2.py` in `kb/tests/test_tools2.py`:
  - `test_write_entry_missing_field`: validation fails on missing frontmatter field → returns error dict
  - `test_write_entry_missing_section`: pitfall entry missing ## Symptoms → error
  - `test_write_entry_invalid_child_id`: child_entry_id not in entry_ids table → error
  - `test_write_entry_success`: valid entry written to correct path
  - `test_write_entry_description_match_failed`: content_source warning returned + file written
  - `test_read_entry_found`: reads back a written entry with title extracted
  - `test_read_entry_not_found`: returns error dict
  - `test_finalize_sets_terminate`: ctx["_terminate"] becomes True
  - `test_tool_whitelist_enforcement`: unlisted tool name → error dict

**Checkpoint**: Tools ready — harness2 implementation can begin.

---

## Phase 3: User Story 1 — 标准导入（≤20 process 节点）(Priority: P1) 🎯 MVP

**Goal**: 给定 .dag.json，Agent 2 以拓扑逆序生成所有 entries 并写入 `_pending/`，打印 ImportReport。

**Independent Test**: `python -m pytest kb/tests/test_harness2.py -k "test_full_loop"` — 给定 mock LLM + 5节点 DAG，验证 5 process entries + 1 pitfall root 写入 pending，lint 通过，report 包含"下一步"提示。

### lint.py

- [X] T017 Implement 7 lint rules in `kb/holmes/kb/agent/dag/lint.py`:
  - `parent_id_consistency`: all process entries' parent_id exists in written entries set
  - `child_entry_ids_consistency`: all child_entry_ids items exist in written entries set
  - `tree_completeness`: all process nodes in DAG have corresponding written entry; no orphaned entries
  - `no_cycle`: child_entry_ids graph has no cycles (DFS)
  - `pitfall_has_root`: at least one entry has no parent_id and type=pitfall
  - `source_file_consistent`: all entries share same source_file and source_hash
  - `evidence_fields_present`: maturity, decay_status, next_decay_check, contributors all present in all entries
  - Each rule returns `LintResult(rule, passed, message)`
- [X] T018 [P] Write tests for `lint.py` in `kb/tests/test_lint.py`:
  - One test per rule testing both pass and fail cases (14 tests minimum)
  - `test_no_cycle_detects_cycle`: entries with circular child_entry_ids → fails
  - `test_tree_completeness_missing_node`: DAG node without entry → fails

### prompt2.py

- [X] T019 [P] Implement AGENT2_SYSTEM_PROMPT in `kb/holmes/kb/agent/dag/prompt2.py`:
  - Four-phase workflow section (Study → process entries → pitfall root → Review)
  - Key constraints section (only original content, IDs from DAG, pitfall root last)
  - section_heading location strategy (Grep → Read range; null → Grep keywords; fallback → content_source: description_match_failed)
  - Format constraints section: pitfall required frontmatter fields list; process required frontmatter fields list; required sections list
  - Child_entry_ids/parent_id title annotation instructions

### report2.py

- [X] T020 [P] Implement `print_agent2_report(report, dag_title, root_ids)` in `kb/holmes/kb/agent/dag/report2.py`:
  - Print separator line + "Import 完成: {source_file}"
  - Print pitfall root(s) list
  - Print "✓ 生成成功 N 个 entries" (1 pitfall root + N process)
  - Print "⚠ 格式校验失败 M 个 entries" with retry commands (`holmes import --retry-entry <node_id>`)
  - Print "⚠ Lint 警告 K 条"
  - Print fixed "下一步" section (`holmes kb pending` + `holmes kb approve <root-id>`)
- [X] T021 [P] Write tests for `report2.py` in `kb/tests/test_report2.py`:
  - `test_report_success_only`: no errors/warnings → shows success count + 下一步
  - `test_report_with_failures`: format errors → shows retry commands
  - `test_report_with_lint_warnings`: lint failures → shows warning count
  - `test_report_always_shows_next_steps`: 下一步 section always present

### harness2.py (core loop)

- [X] T022 Implement `Agent2Harness.__init__` in `kb/holmes/kb/agent/dag/harness2.py`:
  - Parameters: `kb_root, cfg, provider, source_hash, source_file, dag_json_path, no_interactive, dry_run, verbose`
  - Load `dag_json` from dag_json_path; build `entry_ids` dict; compute `max_turns = min(50 * process_count, 1000)`
  - Build `ctx` dict with all required keys; init `_logger`
- [X] T023 Implement `Agent2Harness.run(retry_nodes=None)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - Validate `cfg.username` is non-empty (abort with clear error if missing)
  - Scan `_pending/` for already-written entries matching import_seq → build `written_node_ids` set
  - If `retry_nodes`: skip all nodes not in retry_nodes
  - Call `_run_loop()` with initial user message
  - After loop: call `print_agent2_report()` and log spans
  - Return `ImportReport`
- [X] T024 Implement `Agent2Harness._run_loop(messages, ctx)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - Standard tool-use loop: `provider.complete()` → tool dispatch → `provider.append_tool_results()`
  - Check `ctx["_terminate"]` after each tool batch → break loop
  - Check `turn_count >= max_turns` → raise `MaxTurnsExceededError`
  - Whitelist enforcement via `_execute_tool()` (same pattern as harness1)
- [X] T025 Implement `Agent2Harness._build_initial_messages(written_node_ids)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - User message: dag title + source_file + entry_ids table + already-written nodes list + instruction to start Phase 1 Study
- [X] T026 [P] Implement HolmesLogger span recording in `kb/holmes/kb/agent/dag/harness2.py`:
  - Spans: `agent2.node[<id>]` for each process entry write, `agent2.root` for pitfall root write, `lint` after finalize
  - Import pattern matches harness1._init_logger / _log
- [X] T027 [P] Write tests for `harness2.py` in `kb/tests/test_harness2.py`:
  - `test_username_missing_aborts`: cfg.username="" → ImportReport with error, no LLM calls
  - `test_max_turns_exceeded`: mock LLM never calls finalize → error in report after max_turns
  - `test_tool_whitelist_harness2`: non-whitelisted tool → error dict, loop continues
  - `test_full_loop_5_nodes`: MockLLMProvider calls write_entry×5 + write_entry×1(root) + finalize → 6 files in pending
  - `test_checkpoint_skip_written`: pre-existing written entries → harness skips them in initial message
  - `test_finalize_terminates_loop`: finalize() sets _terminate → loop exits cleanly

### Integration into pipeline

- [X] T028 [US1] Implement `run_agent2(...)` entry point function in `kb/holmes/kb/agent/dag/__init__.py`:
  - Call `generate_entry_ids(dag_json_path)` first; then create `Agent2Harness` and call `.run()`
  - Expose in `__all__`
- [X] T029 [US1] Wire Agent 2 into `Agent1Harness._handle_option_proceed()` in `kb/holmes/kb/agent/dag/harness1.py`:
  - After Step 2.5 confirmation: call `run_agent2(...)` with same cfg/provider/kb_root/source_hash/source_file
  - Replace stub comment with real call
- [X] T030 [US1] Write integration test in `kb/tests/test_harness2.py`:
  - `test_agent2_generates_correct_entry_structure`: end-to-end with MockLLMProvider + real file I/O in tmp_path; verify frontmatter fields, child_entry_ids annotations, parent_id annotations

**Checkpoint**: US1 complete — `holmes import doc.md --type pitfall` produces entries in `_pending/`.

---

## Phase 4: User Story 2 — Step 2.5 交互编辑 (Priority: P2)

**Goal**: Step 2.5 解析规范化（自然语言识别）+ 交叉验证（Grep 原文）+ 合并一屏展示 + 用户一次确认。

**Independent Test**: `python -m pytest kb/tests/test_step25.py` — 给定修改后的 .dag.md，验证自然语言写法被正确识别，section_heading 验证通过/失败正确标注，ParseResult 结构正确。

- [X] T031 [US2] Implement `run_step25(dag_md_path, source_text, provider, cfg, no_interactive)` in `kb/holmes/kb/agent/dag/step25.py`:
  - Re-parse `.dag.md` with `markdown_to_dag()`
  - LLM single call: identify recognized edits + uncertain items from diff vs pre-edit DAG
  - Programmatic cross-validation: Grep `source_text` for each node's `section_heading`; collect warnings for not-found
  - Detect structural errors (dangling nodes, cycles) via existing `_validate_dag()` from tools1.py
  - Return `ParseResult` dataclass
- [X] T032 [US2] Implement `display_step25_result(parse_result)` + user confirmation prompt in `kb/holmes/kb/agent/dag/step25.py`:
  - Print "编辑识别:" section with ✓ / ⚠ items
  - Print "内容验证:" section with ✓ / ⚠ items
  - Print summary line "共 N 个节点，将生成 M 个 entries"
  - Structural errors: print "解析失败，无法继续:" and return False (block Agent 2)
  - Normal: prompt "确认并开始生成？[Y / 需要修改]"; `--no-interactive` auto-accepts; return True
- [X] T033 [US2] Implement complexity self-assessment output in `kb/holmes/kb/agent/dag/step25.py`:
  - After user confirmation, before Agent 2 starts: check thresholds (>20 total nodes, >4 depth, >10 process nodes)
  - Print relevant tip strings (non-blocking)
- [X] T034 [US2] Wire `run_step25()` into `Agent1Harness._handle_option_proceed()` in `kb/holmes/kb/agent/dag/harness1.py`:
  - Call `run_step25()` before calling `run_agent2()`; if returns False → print error, return without Agent 2
- [X] T035 [P] [US2] Write tests for `step25.py` in `kb/tests/test_step25.py`:
  - `test_natural_language_complexity`: "这步比较复杂" in node description → recognized_edits contains complexity=process recognition
  - `test_section_heading_not_found`: section_heading not in source_text → validation_warnings contains warning
  - `test_structural_error_dangling_node`: dangling edge → validation_errors non-empty, display returns False
  - `test_no_interactive_auto_accepts`: `no_interactive=True` → no prompt, returns True
  - `test_complexity_thresholds`: >10 process nodes → complexity tip printed (captured stdout)
  - `test_display_merged_screen`: ParseResult with mix of ✓ and ⚠ → output contains both sections

**Checkpoint**: US2 complete — interactive DAG editing + verification flow works end-to-end.

---

## Phase 5: User Story 3 — 大树分批子 agent 模式（>20 process 节点）(Priority: P2)

**Goal**: >20 process 节点时，每批 10 节点启动独立 sub-agent（独立 messages 数组），通过 `{id: 标题}` 摘要表传递术语上下文。

**Independent Test**: `python -m pytest kb/tests/test_harness2.py -k "batch"` — 给定 25 节点 DAG + MockLLMProvider，验证分 3 批（10+10+5）运行，每批消息历史独立，pitfall root 最后由独立 sub-agent 生成。

- [X] T036 [US3] Implement `_run_batch_mode(process_nodes, written_summary)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - Split process_nodes into batches of 10
  - For each batch: create fresh `messages = []`; build batch-specific user message (DAG + batch node list + written_summary); run inner loop
  - After each batch: collect `{entry_id: title}` from newly written entries → update `written_summary`
  - After all process batches: run pitfall root sub-agent (fresh messages, full written_summary)
- [X] T037 [US3] Extend `Agent2Harness.run()` to detect and route to batch mode in `kb/holmes/kb/agent/dag/harness2.py`:
  - If `process_count > 20`: call `_run_batch_mode()` instead of single `_run_loop()`
  - maxTurns per batch = `min(50 * 10, 1000)` = 500
- [X] T038 [US3] Implement `_build_batch_messages(batch_nodes, title_summary, is_root_batch)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - User message format: DAG entry_ids table + batch node list + `{id: title}` summary table (for context) + instructions
  - Root batch: receives all child entry titles for route link generation
- [X] T039 [P] [US3] Write batch mode tests in `kb/tests/test_harness2.py`:
  - `test_batch_mode_triggered_above_20`: 25 process nodes → `_run_batch_mode` called, not `_run_loop`
  - `test_batch_mode_independent_contexts`: each batch starts with empty messages list
  - `test_batch_title_summary_passed`: written_summary from batch N passed to batch N+1
  - `test_root_batch_runs_last`: pitfall root generated after all process batches complete

**Checkpoint**: US3 complete — large document import works with batch sub-agent mode.

---

## Phase 6: User Story 4 — 单节点重试（Priority: P3）

**Goal**: `holmes import --retry-entry <node-id>` 重新生成单个失败节点，复用同一 import-seq，不影响其他 entries。

**Independent Test**: `python -m pytest kb/tests/test_harness2.py -k "retry"` — 给定已写 5/6 entries，--retry-entry N7 → 只生成 N7，其余 entries 不变，N7 的 entry_id 与原 seq 相同。

- [X] T040 [US4] Add `--retry-entry` flag to `holmes import` CLI command in `kb/holmes/cli.py`:
  - Option: `--retry-entry TEXT` — node ID to retry
  - When set: locate `.dag.json` for the document (via `--source` or most recent), call `run_agent2(..., retry_nodes=[node_id])`
- [X] T041 [US4] Implement retry routing in `Agent2Harness.run(retry_nodes)` in `kb/holmes/kb/agent/dag/harness2.py`:
  - `retry_nodes` list limits which nodes the agent generates
  - Already-written entries for the same import_seq remain untouched
  - import_seq reused from `.dag.json` (idempotent — same entry_id)
- [X] T042 [P] [US4] Write retry tests in `kb/tests/test_harness2.py`:
  - `test_retry_entry_single_node`: run with retry_nodes=["N7"] → only N7 entry generated
  - `test_retry_entry_reuses_import_seq`: entry_id from retry == original entry_id (same seq)
  - `test_retry_does_not_touch_other_entries`: pre-existing entries unchanged

**Checkpoint**: US4 complete — single-node retry works, ID idempotency confirmed.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T043 [P] Complete HolmesLogger span recording in all new modules (`step25.py`, `id_gen.py`, `harness2.py`): spans `step25.parse`, `step25.validate`, `agent2.node[<id>]`, `agent2.root`, `lint` with duration_ms, llm_calls, tokens, result fields
- [X] T044 [P] Add `run_agent2` and `Agent2Harness` to `kb/holmes/kb/agent/dag/__init__.py` `__all__` exports
- [X] T045 [P] Run full test suite and fix any regressions: `python -m pytest kb/tests/ -x` — all existing tests must still pass
- [ ] T046 Verify `holmes import doc.md --type pitfall` end-to-end: entries written to `_pending/`, ImportReport printed with "下一步" section, lint results shown

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — can start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 completion — BLOCKS all user stories
- **Phase 3 (US1)**: Depends on Phase 2 completion — core loop, integrations
- **Phase 4 (US2)**: Depends on Phase 2 completion — can parallel with Phase 3
- **Phase 5 (US3)**: Depends on Phase 3 completion (extends harness2)
- **Phase 6 (US4)**: Depends on Phase 3 completion (extends harness2.run())
- **Phase 7 (Polish)**: Depends on Phases 3–6 completion

### Within Each Phase

- Tests can be written (and should fail) before implementation
- Tools (T011-T015) before harness2 (T022-T027)
- Lint (T017) before finalize integration (T014)
- harness2 core loop (T022-T024) before integration (T028-T029)

### Parallel Opportunities

- T001-T007 (Phase 1 skeletons): all parallel
- T010, T016 (tests for id_gen, tools2): parallel with each other, and with T008-T015 implementation
- T017, T019, T020 (lint, prompt2, report2): parallel with each other
- T026, T027 (logger spans, harness tests): parallel

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup skeletons
2. Complete Phase 2: id_gen + tools2 (with tests)
3. Complete Phase 3: lint + prompt2 + report2 + harness2 + integration
4. **STOP and VALIDATE**: `holmes import doc.md --type pitfall` works end-to-end
5. Check pending entries have correct frontmatter and annotations

### Incremental Delivery

1. Phase 1+2 → tools foundation ready
2. Phase 3 → US1 done (MVP — standard import works)
3. Phase 4 → US2 done (Step 2.5 verification flow)
4. Phase 5 → US3 done (large document support)
5. Phase 6 → US4 done (single-node retry)
6. Phase 7 → polish + final validation

---

## Notes

- `write_entry` tool MUST return error dict (not raise exception) on validation failure — agent sees error and retries
- `finalize()` MUST set `ctx["_terminate"] = True` to break the harness loop
- `pitfall root` MUST be written last (all process entries must exist first for title annotations)
- `parent_id` and `child_entry_ids` annotations (`# 标题`) require `read_entry()` calls before `write_entry()`
- Constitution: all modules MUST have tests (`kb/tests/test_*.py`)
- Constitution: no hardcoded values — `username` always from `cfg.username`
