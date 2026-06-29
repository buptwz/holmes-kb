# Feature Specification: M5 — Agent 2 双源知识生成

**Feature Branch**: `dev-M5`

**Created**: 2026-06-24

**Status**: Draft

**Module**: M5 of 037-dag-import-pipeline

## Overview

Agent 2 是 Holmes KB DAG 导入流水线的第二个 LLM agent。它接收 Agent 1 生成的 `.dag.json`（规范化排查树）和原始文档，通过四阶段工具调用循环生成结构化的 pitfall entry（路由骨架）和 process entry（步骤详情），写入 `_pending/<type>/<category>/` 待审批。

本模块还负责 Step 2.5（解析规范化与交叉验证）、Entry ID 预生成、7 条 lint 校验、ImportReport 生成，以及 `--retry-entry` 单节点重试功能。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 标准导入（≤20 process 节点）(Priority: P1)

工程师将一份故障排查文档通过 `holmes import doc.md --type pitfall` 导入。Agent 1 提取 DAG 后，Step 2.5 对 DAG 进行解析规范化和交叉验证，用户确认后 Agent 2 以拓扑逆序生成所有 KB entries，最后打印 ImportReport。

**Why this priority**: 这是最常见的主路径，直接交付可用 KB entries。

**Independent Test**: 给定一份含 5-10 个 process 节点的故障排查文档，运行完整 import 后，在 `_pending/` 下能看到 1 个 pitfall root + N 个 process entries，ImportReport 显示生成成功数量。

**Acceptance Scenarios**:

1. **Given** Agent 1 已生成 `.dag.json`（含 8 个 process 节点），**When** Step 2.5 解析验证通过且用户确认，**Then** Agent 2 以拓扑逆序生成 9 个 entries（8 process + 1 pitfall root），全部写入 `_pending/<type>/<category>/`。
2. **Given** 所有 entries 生成完毕，**When** `finalize()` 被调用，**Then** 7 条 lint 规则自动运行，ImportReport 在终端打印，末尾固定显示"下一步"操作提示。
3. **Given** entry frontmatter，**Then** 必填字段（title, description, type, kb_status, source_hash, source_file, import_trace_id, maturity, decay_status, next_decay_check, contributors）全部存在且非空。

---

### User Story 2 - Step 2.5 交互编辑（Priority: P2）

Agent 1 完成后，用户选择 [1] 编辑 `.dag.md`，修改后系统执行解析规范化（识别自然语言写法）和交叉验证（Grep 原文验证 section_heading 存在），将编辑识别结果和内容验证结果合并在一屏展示，用户一次确认。

**Why this priority**: 用户编辑 DAG 是保证质量的关键步骤，需要系统准确识别编辑内容。

**Independent Test**: 用户在 `.dag.md` 中写"这步比较复杂"，Step 2.5 识别为 `complexity: process`；写"如果修复失败跳到N7"，识别为 edge 条件；两个识别结果加上内容验证结果合并展示，用户一次 Y 确认。

**Acceptance Scenarios**:

1. **Given** 用户在 `.dag.md` 写了自然语言写法（如"这步比较复杂"），**When** Step 2.5 运行，**Then** 系统识别并展示"✓ 新增节点...complexity=process"；section_heading Grep 不到的节点标注"⚠ 找不到"。
2. **Given** `--no-interactive` 模式，**When** Step 2.5 运行，**Then** 解析和验证仍然执行，最终确认自动接受，report.auto_decisions 追加"DAG 未经用户确认"。
3. **Given** `.dag.md` 含悬空节点或循环引用，**When** Step 2.5 解析，**Then** 不进入 Agent 2，终端打印错误信息并提示修改。

---

### User Story 3 - 大树分批子 agent 模式（>20 process 节点）(Priority: P2)

文档含 >20 个 process 节点时，Agent 2 自动切换到分批子 agent 模式：每批 10 个节点启动独立 sub-agent，批次间通过 `{id: 标题}` 摘要表传递术语上下文。

**Why this priority**: 大文档是实际工程场景的常见情况，必须避免 context 累积导致的质量下降。

**Independent Test**: 给定含 25 个 process 节点的 DAG，import 后产生 3 批（10+10+5+1 pitfall root），每批生成 entries 写入 pending，术语保持一致。

**Acceptance Scenarios**:

1. **Given** DAG 含 25 个 process 节点，**When** Agent 2 启动，**Then** 分 3 批（每批 10 节点）运行，每批独立 sub-agent，最后 pitfall root 由独立 sub-agent 生成。
2. **Given** 批次间，**Then** 已写 entries 的 `{id: 标题}` 摘要表作为输入传递给下一批，保证术语一致性。

---

### User Story 4 - 单节点重试（Priority: P3）

某个 entry 格式校验失败（如缺少 ## Steps section），用户运行 `holmes import --retry-entry N7` 重新生成该节点，不影响其他已生成的 entries，且复用同一 import-seq 保证 ID 幂等。

**Why this priority**: 单节点重试降低了失败代价，提升了工程师工作效率。

**Independent Test**: 已生成 8 个 entries，N7 写入失败；运行 `--retry-entry N7` 后，仅 N7 重新生成，其他 entries 不变，N7 的 entry ID 与第一次尝试相同。

**Acceptance Scenarios**:

1. **Given** N7 entry 格式校验失败未写入 pending，**When** 运行 `holmes import --retry-entry N7`，**Then** 仅 N7 重新生成，entry ID 与原 import-seq 幂等，其余 entries 不受影响。

---

### Edge Cases

- `section_heading=null` 且 Grep 定位失败：frontmatter 写入 `content_source: description_match_failed`，进入 ImportReport.warnings，不阻断其他 entries 生成。
- `write_entry` 格式校验失败后 agent 重试仍失败：entry 不写入 pending，进入 ImportReport.errors，可用 `--retry-entry` 重试。
- `username` 未配置：import 终止，提示用户在 `~/.holmes/config.json` 配置 `username`。
- maxTurns 超限：进入 ImportReport.errors，已写文件作为 checkpoint，重启时跳过已写节点。
- `--resume` 时发现多个 pending state：交互式选择界面（非 `--no-interactive` 模式）。
- pitfall root 由 simple 节点构成（无 process 子节点）：只生成 1 个 pitfall root，无 process entries；lint `tree_completeness` 通过。

## Requirements *(mandatory)*

### Functional Requirements

**Step 2.5 — 解析规范化与交叉验证**

- **FR-001**: Step 2.5 MUST 在 Agent 1 完成后（用户选 [1] 或 [2]）立即执行，不需要用户额外命令。
- **FR-002**: 解析规范化 MUST 识别以下用户自然语言写法并转换：`"这步比较复杂"→complexity:process`、`"如果X跳到NY"→edge条件`、新增节点无 ID→自动分配、section 写成"第三节"→打 uncertain。
- **FR-003**: 交叉验证 MUST 对每个节点的 `section_heading` Grep 原文验证存在；并随机抽取 min(10, 节点总数) 个节点做 LLM 语义一致性抽检。
- **FR-004**: 编辑识别结果和内容验证结果 MUST 合并为一屏展示，用户只需一次确认（Y/需要修改）。
- **FR-005**: 解析失败（悬空节点、循环引用）MUST 打印 error，不进入 Agent 2。
- **FR-006**: `--no-interactive` 模式下 MUST 自动接受，Step 2.5 仍执行解析和验证，`report.auto_decisions` 追加"DAG 未经用户确认"。

**Entry ID 预生成**

- **FR-007**: 生成开始前 MUST 预生成所有 entry ID：process 节点格式 `{source-name-slug}-{node-id}-{import-seq}`，pitfall root 格式 `{source-name-slug}-root-{import-seq}`。
- **FR-008**: 所有 entry ID MUST 写入 `.dag.json` 的 `entry_ids` 字段，Agent 2 通过 `read_dag()` 获取。
- **FR-009**: 重试时 MUST 复用同一 `import-seq`，保证 ID 幂等。

**Agent 2 — 四阶段 Loop**

- **FR-010**: Agent 2 工具集 MUST 限制为 6 个：`Read`、`Grep`、`read_dag`、`write_entry`、`read_entry`、`finalize`；其他工具返回 "tool not allowed" error。
- **FR-011**: Agent 2 MUST 按拓扑逆序生成 entries（叶节点 → 父节点 → pitfall root）。
- **FR-012**: `write_entry` MUST 内置格式校验：必填 frontmatter 字段全部存在且非空；必需 sections 存在；child_entry_ids 中 ID 全部在 DAG ID 表中；parent_id 在 DAG ID 表中。校验失败返回 error（不抛异常），agent 修正后重试。
- **FR-013**: Agent 2 MUST 在写 pitfall root 前通过 `read_entry(child_id)` 获取子节点真实标题，Resolution 的路由链接文案来自子节点真实标题。
- **FR-014**: `child_entry_ids` 和 `parent_id` 字段 MUST 附带标题注释（`# 标题`）。
- **FR-015**: Agent 2 MUST 在 Phase 4 Consistency review 中抽查 5-10 个 entry（随机 + section_heading=null 必查），有问题通过 `write_entry` 覆盖修正。
- **FR-016**: maxTurns MUST = `50 × process 节点数`（上限 1000）。
- **FR-017**: ≤20 个 process 节点使用全局视野模式（单 agent loop）；>20 个使用分批子 agent 模式（每批 10 节点）。
- **FR-018**: 已写文件 MUST 作为天然 checkpoint：重启时扫描 `_pending/` 下已有文件，跳过已写节点。

**Entry 格式**

- **FR-019**: pitfall entry frontmatter MUST 包含：`title, description, type=pitfall, pitfall_structure=tree, kb_status=pending, source_hash, source_file, import_trace_id, child_entry_ids（含注释）, maturity=draft, decay_status=active, next_decay_check（today+180天）, contributors（config.username + role=initiator + date=today）, tags`。
- **FR-020**: pitfall entry MUST 包含 sections：`## Symptoms, ## Root Cause, ## Resolution`（含路由链接）。
- **FR-021**: process entry frontmatter MUST 包含：`title, description, type=process, kb_status=pending, parent_id（含注释）, child_entry_ids（若有，含注释）, source_hash, source_file, import_trace_id, maturity=draft, decay_status=active, next_decay_check, contributors, tags`。
- **FR-022**: process entry MUST 包含 section：`## Steps`（含编号步骤和路由逻辑）。
- **FR-023**: 所有 entries MUST 只使用原文 section 中存在的内容，允许重组为结构化格式，不补充原文没有的信息。
- **FR-024**: `username` 未配置时 MUST 终止 import 并提示用户配置。

**Lint 与 ImportReport**

- **FR-025**: `finalize()` 调用后 MUST 自动运行 7 条 lint 规则（parent_id_consistency, child_entry_ids_consistency, tree_completeness, no_cycle, pitfall_has_root, source_file_consistent, evidence_fields_present）。
- **FR-026**: lint 失败 MUST 写入 ImportReport.errors，但不阻断已写 entries；pending 展示时显示 ⚠ 警告。
- **FR-027**: ImportReport MUST 包含：✓ 生成成功数量、⚠ 格式校验失败 entry 列表（含 retry 命令）、⚠ lint 警告条数、"下一步"操作提示（`holmes kb pending` + `holmes kb approve <root-id>`）。
- **FR-028**: 所有 entries 写入 `_pending/<type>/<category>/`（不按 entry 类型分目录，按 category 分）。

**单节点重试**

- **FR-029**: `holmes import --retry-entry <node-id>` MUST 重新生成指定节点，复用同一 import-seq，不影响其他已生成 entries。

**可观测性（依赖 M8）**

- **FR-030**: HolmesLogger span MUST 写入：`step25.parse`, `step25.validate`, `agent2.node[<id>]`, `agent2.root`, `lint`；每个 span 记录 duration_ms, llm_calls, tokens, result(ok/error/warning)。

### Key Entities

- **DAGGraph**: 从 `.dag.json` 读取的完整排查树，含节点 ID 表、section_heading、entry_ids（预生成后写入）。
- **pitfall entry**: 整棵树的路由骨架，`type=pitfall`, `pitfall_structure=tree`，含路由链接到 process entries。
- **process entry**: 单个排查步骤的详情，`type=process`，含 `parent_id` 和可选 `child_entry_ids`。
- **ImportReport**: 记录生成结果、格式校验失败、lint 警告、下一步操作。
- **import-seq**: 3 位序号（如 `001`），重试时复用同一值以保证 ID 幂等。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 对于含 10 个 process 节点的标准文档，从 Step 2.5 确认到所有 entries 写入 pending 成功完成，生成 11 个 entries（10 process + 1 pitfall root）。
- **SC-002**: 格式校验完整：所有生成的 pitfall entries 必填字段覆盖率 100%（由 write_entry 内置校验保证）。
- **SC-003**: 树结构一致：lint 通过率 ≥ 95%（parent_id/child_entry_ids 双向引用一致）。
- **SC-004**: 单节点重试功能可用：`--retry-entry <id>` 仅重新生成指定节点，其他 entries 不受影响。
- **SC-005**: ImportReport 末尾固定展示"下一步"操作提示，用户明确知道后续步骤。
- **SC-006**: `content_source: description_match_failed` 情况下 entry 仍写入 pending，在 ImportReport.warnings 中可见。

## Assumptions

- M4 已完成：`.dag.json` 文件由 Agent 1 生成并存放在 `_import-state/<hash>.dag.json`，M5 读取此文件作为输入。
- M6a 已完成或可以直接写文件：`write_entry` 使用 `atomic_write()` 直接写入 `_pending/<type>/<category>/`。
- `config.username` 已配置：M5 不尝试从其他来源推断用户名；未配置时直接报错退出。
- HolmesLogger（M8）是可选依赖：若未安装则 span 写入静默跳过，不影响主流程。
- category 取自 DAG 的 pitfall entry 分类（由 Agent 2 从文档内容推断），默认为 `general`。
- Simple 节点不生成独立 entry，inline 写在父 entry 的 Resolution 中。
- Agent 2 与 Agent 1 的 conversation context 完全独立，仅通过文件系统通信（`.dag.json`）。
- 分批子 agent 使用同一 LLMProvider 实例，通过独立 messages 数组实现 context 隔离。
