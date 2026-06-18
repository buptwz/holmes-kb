# Tasks: Import Pipeline v3 回归缺陷修复

**Input**: Design documents from `/specs/023-fix-skill-pipeline-bugs/`

**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ quickstart.md ✅

**Organization**: Tasks grouped by user story. US1-US3 均含实现 + 测试任务，互相独立，可按优先级顺序或并行执行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

本次为纯 bug 修复，无需额外 setup 步骤。所有目标文件已存在，可直接进入实现阶段。

**Checkpoint**: 可直接进入 Phase 2。

---

## Phase 2: User Story 1 — Skill 命令检测通用化（QA-18）(Priority: P1) 🎯 MVP

**Goal**: `_extract_code_block_lines()` 信任代码块语言声明，不再使用 case-by-case 启发式过滤；`detect_commands()` 行内检测仅保留 `$ command` 模式。

**Independent Test**: 导入含编号步骤的文档 → run.sh 只含代码块内容（不含步骤说明行）；SQL 块内容在 sql 块中被识别为命令；`# 注释` 行被过滤。

> **实际实现与原计划的差异**: 原计划仅修复编号步骤行过滤（`^\d+[.)]\s` 正则）。实际实现更彻底：
> 删除了 `_CMD_PREFIXES`（26 行工具白名单）、`_SQL_KEYWORDS`（17 词 SQL 黑名单）、所有 5 个反引号特例过滤器。
> 新原则：信任代码块语言声明（`_SHELL_LANGS` 白名单保留）；代码块内所有非空非注释行均为可执行命令；行内检测仅保留 `\$\s+([^\n`]{5,120})` 模式。

### Implementation for User Story 1

- [X] T001 [US1] 在 `kb/holmes/kb/skill/manager.py` 中重构 `_extract_code_block_lines()` 和 `detect_commands()`：删除 `_CMD_PREFIXES`、`_SQL_KEYWORDS`，简化 `CMD_PATTERN` 为仅 `$ command` 模式；`_extract_code_block_lines()` 仅跳过 `#` 注释行，不做其他内容过滤

### Tests for User Story 1

- [X] T002 [P] [US1] 在 `kb/tests/test_skill_manager.py` 中新增测试类 `TestExtractCodeBlockLinesTrustLanguage`：(a) bash 块内命令行全部返回；(b) sql 块内 SQL 语句被视为命令；(c) `# 注释` 行被过滤；删除已失效的 `TestExtractCodeBlockLinesNumberedFilter`、`TestBacktickFalsePositives`、`TestDetectCommandsBacktickFilters` 等旧测试类

**Checkpoint**: T001/T002 通过，代码块语言信任原则验证（Scenario 1 in quickstart.md）。

---

## Phase 3: User Story 2 — 语义去重程序化 Phase 2.5（TC-D-02）(Priority: P2)

**Goal**: 在 LLM Writer 循环前插入程序化去重 Pass，通过 `read_kb_entries_by_category` + `compare_root_cause` 程序化比较，同根因文档直接走 UPDATE 路径。

**Independent Test**: 导入与现有条目同根因的文档 → 输出 `0 created, 1 updated`，KB 中无新增重复条目。

> **实际实现与原计划的差异**: 原计划仅修复 LLM prompt（将 `write_kb_entry update=True` 改为 `update_kb_entry`）。实际实现更彻底：
> 发现 LLM 驱动的去重不可靠（LLM 不知道要对哪些现有条目调用 compare_root_cause）。
> 新方案：在 `pipeline.py` 中新增 Phase 2.5 程序化去重 Pass（`_run_dedup_pass()`），在 LLM Writer 循环前执行；同时从 LLM writer 的 user_prompt 中删除 compare_root_cause 相关步骤，避免 LLM 重复执行。

### Implementation for User Story 2

- [X] T003 [US2] 在 `kb/holmes/kb/agent/pipeline.py` 中新增 `_run_dedup_pass()` 方法：遍历 `kp_drafts`，程序化调用 `read_kb_entries_by_category` + `compare_root_cause`；匹配条目（same_root_cause=True, confidence≥0.8）直接通过 `atomic_write` 更新，加入 report.updated；返回已处理的 KP ID 集合。在 extractor 后、LLM writer 前调用此方法，从 `kp_drafts` 移除已处理条目

### Tests for User Story 2

- [X] T004 [P] [US2] 在 `kb/tests/test_pipeline.py` 中新增测试类 `TestPipelineProgrammaticDedup`：验证 `_run_dedup_pass` 方法存在；LLM writer 的 user_prompt 不包含 `compare_root_cause`（不让 LLM 重复执行）；`_run_dedup_pass` 程序化调用 `compare_root_cause`

**Checkpoint**: T003/T004 通过，Scenario 2（同根因文档走 UPDATE 路径）手动验证。

---

## Phase 4: User Story 3 — OPTIONAL Skill 候选提示（TC-S-02，update 路径）(Priority: P3)

**Goal**: `update_kb_entry` 执行后，`_finalize_skill_generation()` 也对更新条目评估 Skill，若为 OPTIONAL（1-2 条命令），写入 `report.suggestions` 的 `skill candidate` 提示。

**Independent Test**: 导入含 1-2 条命令且走 update 路径的文档 → report.suggestions 含 `skill candidate`。

### Implementation for User Story 3

- [X] T005 [US3] 在 `kb/holmes/kb/agent/runner.py` 的 `ImportAgentRunner.__init__()` 中新增字段：`self._updated_entry_ids: set[str] = set()`（与 `_created_entry_contents` 在同一区域初始化，约第 111 行）

- [X] T006 [US3] 在 `kb/holmes/kb/agent/runner.py` 的 `_handle_tool_result()` 中，找到 `elif name == "update_kb_entry" and result.get("success") and not self.dry_run:` 的 report.updated.append 行（约第 335-336 行），追加：`self._updated_entry_ids.add(str(tool_input.get("entry_id", "")))`（在 `report.updated.append(...)` 同一分支内）

- [X] T007 [US3] 在 `kb/holmes/kb/agent/runner.py` 的 `ImportAgentRunner` 类中新增辅助方法 `_read_entry_content(self, entry_id: str) -> str`：使用 `from holmes.kb.store import list_entries`（注意：不是 `holmes.kb.importer`）遍历 `list_entries(self.kb_root)`，找到 `entry.id.upper() == entry_id.upper()` 的条目，读取对应 `.md` 文件内容并返回；找不到时返回 `""`。方法放在 `_extract_resolution_section()` 附近（约第 444 行之后）

- [X] T008 [US3] 在 `kb/holmes/kb/agent/runner.py` 的 `_finalize_skill_generation()` 方法末尾（约第 508 行，处理完 `_created_entry_contents` 循环之后），追加对 `_updated_entry_ids` 的处理：遍历 `self._updated_entry_ids`，跳过已在 `self._skill_evaluated_entries` 中的 entry_id；调用 `self._read_entry_content(entry_id)` 读取内容；提取 resolution section；解析 frontmatter 取 category/title；调用 `self._run_skill_and_curation(entry_id, resolution_text, category, report, description=title)`

### Tests for User Story 3

- [X] T009 [P] [US3] 在 `kb/tests/test_skill_advisor.py` 中新增测试类 `TestFinalizeSkillForUpdatedEntries`：
  - (a) mock `update_kb_entry` 成功 + `_read_entry_content` 返回含 1 条命令的内容 → `report.suggestions` 含 `skill candidate`
  - (b) mock `update_kb_entry` 成功 + `_read_entry_content` 返回含 2 条命令的内容 → `report.suggestions` 含 `skill candidate`
  - (c) mock `update_kb_entry` 成功 + `_read_entry_content` 返回含 0 条命令的内容 → `report.suggestions` 不含 `skill candidate`
  - (d) 已在 `_skill_evaluated_entries` 中的 entry → finalize 不重复触发

**Checkpoint**: T005-T009 通过，Scenario 3（update 路径 OPTIONAL suggestion）手动验证。

---

## Final Phase: Polish & 验证

- [X] T010 在 `023-fix-skill-pipeline-bugs` 分支上运行 `cd kb && python -m pytest tests/ -q`，确认通过数 ≥ 680（基线），所有新增测试通过
- [X] T011 [P] 验证 quickstart.md Scenario 4（正常文档不受 US1 过滤影响）手动正常

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即可开始
- **US1/US2/US3 (Phase 2-4)**: 无共同前置依赖，彼此独立，可并行
- **Polish (Final)**: 依赖所有 US 完成

### User Story Dependencies

- US1、US2、US3 相互独立，无跨 story 代码依赖
- US3 内部：T005 → T006 → T007 → T008 → T009（顺序依赖同文件改动）

### Within Each User Story

- 实现任务（T001/T003/T005-T008）先于对应测试任务（T002/T004/T009）
- 同一 story 内标 [P] 的任务（测试）可并行于其他 story 的任务

---

## Parallel Opportunities

```bash
# 三个 US 可并行（不同文件）：
T001: manager.py 过滤规则        ← 独立
T003: pipeline.py prompt 修正   ← 独立
T005-T008: runner.py update 路径 ← 独立

# 各 US 的测试任务标 [P]，可与其他 US 实现并行：
T002: test_skill_manager.py      ← 并行
T004: test_pipeline.py           ← 并行
T009: test_skill_advisor.py      ← 并行
```

---

## Implementation Strategy

### MVP First (US1 Only — QA-18 修复)

1. T001: 修复 `_extract_code_block_lines()` 过滤规则
2. T002: 补充测试
3. T010: 验证基线通过
4. **STOP and VALIDATE**: Skill run.sh 可执行性问题修复，可交付

### Incremental Delivery

1. T001-T002 → US1 (P0 修复，Skill 功能恢复)
2. T003-T004 → US2 (TC-D-02，UPDATE 路径恢复)
3. T005-T009 → US3 (TC-S-02，OPTIONAL suggestion 覆盖 update 路径)
4. T010-T011: 全量验证

---

## Notes

- 所有新增测试必须不依赖真实 LLM（使用 mock/stub/spy）
- US3 的 `_read_entry_content()` 复用 `tools.py` 中 `update_kb_entry` 已有的 `list_entries` 模式，无需引入新依赖
- T008 追加的 update 路径 skill 评估：由 SkillAdvisor 根据命令数量决定是否输出 OPTIONAL suggestion，与 create 路径逻辑完全一致
- `_skill_evaluated_entries` 去重机制已存在，T008 无需额外去重逻辑
