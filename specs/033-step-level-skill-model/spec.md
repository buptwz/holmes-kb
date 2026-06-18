# Feature Specification: 步骤级 Skill 模型

**Feature Branch**: `033-step-level-skill-model`

**Created**: 2026-06-17

**Status**: Draft

---

## 背景

Feature 031/032 完善了 MCP 通道读写链路。压力测试（硬件排查场景，含 Intel E810 TX Hang 5 阶段文档、服务器上电排查 20 步 6 分支文档）暴露了 Skill 执行层的核心缺陷：

- **SKILL.md 内容截断**：多阶段 Resolution 生成的 SKILL.md 只包含第一个子章节，后续阶段全部丢失
- **无步骤级 skill 调用机制**：agent 读取 KB 条目后不知道哪些步骤有对应 skill 可以调用
- **单一形态模型不满足复杂场景**：当前"一个条目 → 一个 skill"粒度过粗，不适合多阶段、多分支的硬件排查流程
- **linked_entries 不含 pending 条目**：新导入的知识在 confirm 前对 agent 不可见（skill 的 linked_entries 为空）

**核心目标**：引入步骤级 skill 模型，使 agent 能在复杂硬件排查场景中完整、准确地执行分阶段排查任务。

**KB 条目 vs Skill 的职责边界**：

| | KB 条目 | Skill |
|---|---------|-------|
| **定位** | 诊断决策树 | 操作执行单元 |
| **内容** | 完整排查流程、分支逻辑、人工判断点 | 单一分支的具体操作步骤 |
| **粒度** | 一个问题一个条目 | 一个操作分支一个 skill |

---

## User Scenarios & Testing

### User Story 1 — 完整执行多阶段排查（形态 A：整体封装）(Priority: P1)

agent 读取一个线性 Resolution 的 KB 条目，按 skill 执行完整多阶段操作，不因标题层级丢失任何阶段。

**Why this priority**: Bug-1 导致 agent 执行的 skill 只有第一阶段，剩余阶段完全丢失，在真实排查场景中会造成危险的不完整操作。

**Independent Test**: 导入含 `### 阶段一` ~ `### 阶段五` 子章节的 Resolution 文档，验证生成的 SKILL.md 包含全部 5 个阶段内容。无需其他功能即可独立验证。

**Acceptance Scenarios**:

1. **Given** Resolution 含多个 `###` 子章节（如阶段一~五），**When** import pipeline 生成 SKILL.md（形态 A），**Then** SKILL.md 包含全部子章节内容，无截断
2. **Given** 生成的 SKILL.md，**When** agent 通过 `kb_read(skill_name)` 读取，**Then** 返回完整 body，步骤数与原文一致
3. **Given** Resolution 为单一线性流程（≤10 步，无明显分支），**When** SkillAdvisor 判断为 RECOMMENDED，**Then** 选择形态 A，生成一个 skill 包含完整内容

---

### User Story 2 — 步骤级 skill 调用（形态 B：分步封装）(Priority: P1)

agent 读取含分支结构的 KB 条目（20 步、6 条独立操作分支），按决策树执行，在指定步骤调用对应 skill，其余 inline 步骤直接执行，人工判断点暂停等待工程师。

**Why this priority**: 复杂硬件排查流程不适合整体封装为单个 skill，agent 需要按需调用对应分支的 skill，其余步骤轻量执行。

**Independent Test**: 导入含明确分支结构的文档（步骤 > 10 且有 ≥ 3 个并列操作路径），验证生成多个 skill（每个分支一个），KB 条目 `skill_refs` 列出所有 skill，Resolution 中有 skill 调用标记。

**Acceptance Scenarios**:

1. **Given** Resolution 含 skill 调用标记（`> skill: skill-name` 或 `` `[skill:skill-name]` ``），**When** import pipeline 处理，**Then** 识别标记，按每个被引用步骤生成独立 SKILL.md
2. **Given** Resolution 步骤 > 10 且有 ≥ 3 个并列操作路径，**When** 无手动标注时，**Then** pipeline 自动按分支拆分，每个分支生成一个 skill
3. **Given** KB 条目含多个 skill，**When** agent 调用 `kb_read(entry_id)`，**Then** 响应的 `skill_invocations` 字段明确列出每个 skill 在哪个步骤被调用（`{step: "Step 3", skill: "..."}`）
4. **Given** 步骤为 inline 步骤（1-3 条简单命令，无分支），**Then** 该步骤不生成独立 skill，保留在 KB 条目 Resolution 原文中
5. **Given** 步骤为人工干预点（`> **人工xxx点**`），**Then** 该步骤不生成 skill，作为流程节点标注保留

---

### User Story 3 — 导入后立即可用（pending 条目可见性）(Priority: P1)

agent 导入文档后，可通过 `kb_read(skill_name)` 读取新生成 skill 的 `linked_entries`，看到关联的 pending 条目；也可通过 `kb_read(pending_id)` 直接读取 pending 条目内容，无需等待人工 confirm。

**Why this priority**: 用户导入知识后期望立即可用。当前 linked_entries 为空、pending 条目无法读取，使导入的知识对 agent 完全不可见，严重影响使用体验。

**Independent Test**: 导入一份文档，获得 pending entry ID；调用 `kb_read(skill_name)` 检查 `linked_entries` 含该 pending ID；调用 `kb_read(pending_id)` 返回内容而非 "Entry not found"。无需 confirm 即可验证。

**Acceptance Scenarios**:

1. **Given** 导入文档后生成 pending 条目（`pending-YYYYMMDD-HHMMSS-xxxx`）和关联 skill，**When** agent 调用 `kb_read(skill_name)`，**Then** `linked_entries` 包含该 pending 条目 ID（标注 `pending: true`）
2. **Given** pending 条目存在，**When** agent 调用 `kb_read(pending_id)`，**Then** 返回完整 Markdown 内容，响应中含 `pending: true` 字段标识
3. **Given** pending 条目被 confirm 后，**When** agent 调用 `kb_read(skill_name)`，**Then** `linked_entries` 中该条目从 `pending: true` 变为正式 entry ID

---

### User Story 4 — 解析 Resolution 中的 skill 标记（FR-1 语法）(Priority: P1)

工程师在源文档 Resolution 中手动标注某步骤使用特定 skill，import pipeline 识别标记并生成对应 skill，KB 条目 `skill_refs` 自动同步。

**Why this priority**: 手动标注是强制触发形态 B 的入口，支持工程师精确控制 skill 粒度，是步骤级 skill 模型的基础语法。

**Independent Test**: 源文档 Resolution 含 `> skill: e810-firmware-upgrade`，import 后验证生成 `skills/e810-firmware-upgrade/SKILL.md`，KB 条目 `skill_refs: [e810-firmware-upgrade]`。

**Acceptance Scenarios**:

1. **Given** Resolution 含 blockquote 标记 `> skill: skill-name`，**When** import 处理，**Then** 识别该标记，生成对应 skill，`skill_refs` 含该名称
2. **Given** Resolution 含 inline 标记 `` `[skill:skill-name]` ``，**When** import 处理，**Then** 同样识别并生成对应 skill
3. **Given** 同一 Resolution 含多个 skill 标记，**When** import 处理，**Then** 每个标记对应一个独立 SKILL.md，`skill_refs` 列出全部 skill 名称
4. **Given** Resolution 无任何 skill 标记，**When** import 处理，**Then** 不触发形态 B，按原有形态 A 或 SKIP 逻辑执行

---

### Edge Cases

- Resolution 包含 100+ 行内容时，形态 A 生成的 SKILL.md 不截断，完整包含所有内容
- 单个 skill 提取内容超过 100 行时，发出警告并建议拆分（不阻断生成）
- skill 标记的 skill name 含非法字符（不符合 `[a-z0-9-]` 规则）时，跳过该标记，记录警告
- Resolution 中同一 skill name 出现多次标记，只生成一个 SKILL.md，`skill_refs` 去重
- pending 条目被 confirm 时，`linked_entries` 正确更新（移除 pending 标记）
- `kb_read(pending_id)` 且 pending 条目不存在时，返回 "Entry not found"（行为与正式条目一致）
- 形态 B 生成多个 skill 时，每个 skill 内容只包含对应步骤，不重复包含其他步骤内容

---

## Requirements

### Functional Requirements

**Bug-1 + FR-4：SKILL.md 内容完整性保证**

- **FR-001**: 修复 `skill_advisor.py` / `pipeline.py` 中的 Resolution 提取逻辑，当 Resolution 包含多级标题（`###` 子章节）时，提取完整 Resolution 内容而非仅第一个子章节
- **FR-002**: 形态 A 生成的 SKILL.md body 必须包含完整 Resolution，不因 `###` 标题截断
- **FR-003**: 形态 B 每个被引用步骤生成的 SKILL.md 必须包含该步骤的完整内容（含子步骤、blockquote、多行命令）

**Bug-3：pending 条目可见性**

- **FR-004**: `_compute_linked_entries()` 扩展扫描范围，包含 `contributions/pending/` 目录，返回的 `linked_entries` 中 pending 条目标注 `{id: "pending-xxx", pending: true}`
- **FR-005**: `read_entry()` / `_read_entry()` 支持读取 pending 条目（调用 `list_entries` 时使用 `include_pending=True`），响应中含 `pending: true` 字段

**FR-1：Skill 调用标记语法**

- **FR-006**: 实现 `extract_skill_markers(resolution_text: str) -> list[dict]` 函数，解析 Resolution 文本，返回 skill 调用位置列表（`{skill_name, step_heading, marker_type: "blockquote"|"inline"}`）
- **FR-007**: 支持 blockquote 形式：`> skill: <name>`（独立行）
- **FR-008**: 支持 inline 形式：`` `[skill:<name>]` ``（行内）
- **FR-009**: skill name 需符合 `[a-z0-9][a-z0-9-]*[a-z0-9]` 规则，不合规则的标记记录警告并跳过

**FR-2 + FR-3：SkillAdvisor 双模式**

- **FR-010**: SkillAdvisor 新增形态判断逻辑：
  - 若 Resolution 含 skill 标记 → 形态 B（步骤级）
  - 若 Resolution 步骤 > 10 且 ≥ 3 个并列操作路径（无标注）→ 自动识别分支 → 形态 B
  - 否则按现有 RECOMMENDED / OPTIONAL / SKIP 逻辑 → 形态 A 或不生成
- **FR-011**: 形态 B 模式下，对每个被标注步骤（或自动识别的分支）分别调用 skill 生成，生成独立 SKILL.md，skill name 来自标记或自动生成
- **FR-012**: 形态 A 与形态 B 选择结果写入 import report，可查询
- **FR-013**: 生成的所有 skill name 写入 KB 条目 `skill_refs` 字段

**FR-5：kb_read 返回 skill_invocations**

- **FR-014**: `kb_read(entry_id)` 响应新增 `skill_invocations` 字段（list），格式：`[{step: "<heading_text>", skill: "<skill_name>"}]`
- **FR-015**: `skill_invocations` 通过解析 KB 条目 Resolution 中的 skill 标记动态提取，无需额外存储字段
- **FR-016**: 无 skill 标记时 `skill_invocations` 返回空列表 `[]`

### Key Entities

- **形态 A（条目级 skill）**：整个 Resolution 封装为一个 skill；适用于线性流程（≤10 步，无明显分支）
- **形态 B（步骤级 skill）**：Resolution 内特定步骤调用独立 skill；适用于含分支、人工干预点、或 >10 步的复杂流程
- **skill 调用标记**：`> skill: name`（blockquote）或 `` `[skill:name]` ``（inline），标注 Resolution 中某步骤调用某 skill
- **`skill_invocations`**：从 Resolution 文本动态解析的 skill 调用位置列表，不需要额外存储
- **`linked_entries` (含 pending)**：读取 skill 时动态计算，扫描所有已确认 entry + pending 目录，pending 条目标注 `pending: true`

---

## Success Criteria

- **SC-001**: 内容完整性验证：导入含 5 个 `###` 子章节的 Resolution 文档，生成 SKILL.md 包含全部 5 个阶段，行数与原 Resolution 一致（不截断）
- **SC-002**: 步骤级 skill 验证：导入含 skill 标记（`> skill: name`）的文档，对每个标记生成独立 SKILL.md，`skill_refs` 包含全部被标记 skill 名称
- **SC-003**: 自动拆分验证：导入 >10 步且 ≥3 个并列分支的文档（无手动标记），pipeline 自动生成多个 skill，每个 skill 对应一个分支
- **SC-004**: pending 可见性验证：导入文档后立即（不 confirm）可通过 `kb_read(skill_name)` 看到 `linked_entries` 含 pending 条目；可通过 `kb_read(pending_id)` 读取 pending 内容
- **SC-005**: skill_invocations 验证：`kb_read(entry_id)` 响应的 `skill_invocations` 精确列出每个 skill 被调用的步骤标题
- **SC-006**: 回归验证：现有形态 A 行为（线性 Resolution + 整体封装）保持不变；所有现有 KB 测试无回归

---

## Assumptions

- Bug-2（`holmes import` CLI 未接入 ImportAgentRunner）已在 Feature 031 修复，不在本 Feature 范围内
- `extract_skill_markers()` 作为纯文本解析函数实现，不依赖 LLM
- 形态 B 的自动分支识别可基于结构规则（步骤数、并列标题模式），不需要 LLM 分类
- `skill_invocations` 通过解析 Resolution 文本实时提取，不需要额外持久化存储
- Pending 条目的 `skill_refs` 字段在 `write_pending()` 时已正确写入，问题仅在查询侧扫描范围不足
- 形态 A 截断 Bug 根因在 Resolution 提取时以 `###` 作为终止边界，修复只需修改提取逻辑，不涉及 LLM prompt 大的改动
- 每个拆分出的 skill 步骤数建议不超过 10 步；超过时发出警告但不阻断生成
