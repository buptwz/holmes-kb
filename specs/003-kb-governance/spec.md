# Feature Specification: KB Access Control & Governance

**Feature Branch**: `003-kb-governance`

**Created**: 2026-06-01

**Status**: Draft

---

## Clarifications

### Session 2026-06-01

- Q: 只读保护是针对 Agent 的软约束，还是针对所有工具的硬约束？ → A: 软约束——CLAUDE.md 指令 + holmes CLI 拦截约束 Agent 行为；维护者可直接操作文件系统绕过。
- Q: Agent 读取条目后如何更新引用记录？ → A: session 结束时批量调用 `holmes kb update-refs --ids <id1,id2,...>`，追加 evidence 记录；不在每次读取时触发单条写入，避免多人协作 git 冲突。
- Q: 写入 pending 时标题与已确认条目重复，操作结果是什么？ → A: 硬拒绝——返回错误，写入不执行；Agent 应改用修正工作流（`corrects: <id>`）提交修正提案。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 已确认知识只读保护 (Priority: P1)

维护者希望已通过人工审核确认的知识条目（`verified` / `proven`）不被 Agent 直接修改，确保知识库中成熟知识的完整性和可信度。

**Why this priority**: 这是整个治理体系的基础。没有只读保护，其他所有机制都失去意义。

**Independent Test**: 配置知识库后，Agent 通过 holmes CLI 尝试直接写入 `verified` 或 `proven` 条目时被 CLI 拦截并返回错误；Agent 对 `draft` 条目的修改通过 write-pending 提交；维护者直接操作文件系统不受此约束。

**Acceptance Scenarios**:

1. **Given** 知识库中存在 `maturity: verified` 的条目 PT-DB-001，**When** Agent 通过 holmes CLI 尝试直接覆盖写入该文件，**Then** CLI 拦截操作并返回错误，条目内容不变
2. **Given** 知识库中存在 `maturity: proven` 的条目，**When** Agent 读取该条目，**Then** 读取成功，内容完整返回
3. **Given** 知识库中存在 `maturity: draft` 的条目，**When** Agent 通过 `write-pending` 提交对该条目的修改，**Then** 修改进入 pending 等待人工确认

---

### User Story 2 — Agent 沉淀新知识到私有暂存区 (Priority: P1)

Agent 在排查问题或完成工作后，将新经验沉淀到专属的待审区（pending），不直接进入公共知识库，等待人工确认后才发布。

**Why this priority**: 与 US1 并列最高优先级。沉淀机制是知识增长的来源，但必须与只读保护配套使用。

**Independent Test**: Agent 调用沉淀命令后，新条目出现在 `pending/` 目录；公共知识库目录（`pitfall/` 等）内容不变；执行 `holmes kb confirm` 后条目从 pending 移入公共区，evidence 数组中出现第一条记录，maturity 变为 `verified`。

**Acceptance Scenarios**:

1. **Given** Agent 完成一次排查，**When** Agent 写入新知识，**Then** 新条目出现在 `pending/` 目录，`maturity: draft`
2. **Given** pending 中存在条目，**When** 维护者执行 `holmes kb confirm <id>`，**Then** 条目移入对应类型目录，evidence 数组追加第一条 human 审核记录，maturity 提升为 `verified`，pending 中该条目删除
3. **Given** pending 中存在条目，**When** 维护者执行 `holmes kb reject <id>`，**Then** 条目从 pending 中删除，公共区不受影响

---

### User Story 3 — 修正已确认知识的工作流 (Priority: P2)

当 Agent 或维护者发现某条已确认知识存在错误或过时内容时，能够提交一个"修正提案"，经人工审核后替换原条目，全程不直接修改原内容。

**Why this priority**: 知识必然会老化或出错。没有修正机制，知识库会逐渐失去可信度。

**Independent Test**: 对 `verified` 条目 PT-DB-001 提交修正提案后，pending 中出现一条 `corrects: PT-DB-001` 的草稿；确认后原条目内容被更新，修正历史可追溯。

**Acceptance Scenarios**:

1. **Given** 已确认条目 PT-DB-001，**When** Agent/维护者提交修正提案（声明 `corrects: PT-DB-001`），**Then** pending 中出现新草稿，原条目内容不变
2. **Given** pending 中存在修正提案，**When** 维护者确认该提案，**Then** 原条目内容被提案内容替换，`updated_at` 更新，原版本内容保留在历史快照中
3. **Given** pending 中存在修正提案，**When** 维护者拒绝该提案，**Then** 原条目不受影响，提案从 pending 删除

---

### User Story 4 — 知识成熟度自动衰减与归档 (Priority: P3)

长期未被 Agent 引用的已确认知识自动降级成熟度，持续无人引用的 draft 条目归档移出活跃索引，提醒维护者重新审查可能已过时的内容。

**Why this priority**: 解决知识库"静默老化"问题。长期未引用的条目是潜在的过时候选，需要机制识别出来。

**Independent Test**: 将一条 `proven` 条目的 evidence 最后记录日期手动设为 13 个月前，运行衰减检查命令后，该条目 `maturity` 降为 `verified`；将 `verified` 条目最后引用日期设为 7 个月前，运行后降为 `draft`；`draft` 条目持续无引用经 Lint 标记后归档。

**Acceptance Scenarios**:

1. **Given** `proven` 条目超过 12 个月未被引用，**When** 运行成熟度衰减检查，**Then** 该条目 `maturity` 降为 `verified`，`updated_at` 更新
2. **Given** `verified` 条目超过 6 个月未被引用，**When** 运行成熟度衰减检查，**Then** 该条目 `maturity` 降为 `draft`
3. **Given** `proven` 条目在 12 个月内被引用过，**When** 运行衰减检查，**Then** 成熟度不变
4. **Given** Agent session 结束，**When** Agent 批量调用 `holmes kb update-refs --ids <id,...>`，**Then** 每个条目的 evidence 数组追加本次 session 引用记录，`last_referenced` 更新
5. **Given** `draft` 条目持续无 evidence 记录且 Lint 标记为孤儿，**When** 运行归档命令，**Then** 条目移入 `contributions/archive/`，从活跃索引移除

---

### User Story 5 — Evidence 驱动的成熟度自动晋升 (Priority: P2)

知识条目的成熟度根据跨 session/项目的实际引用证据自动晋升，无需人工手动指定成熟度等级，确保成熟度反映真实的验证广度。

**Why this priority**: 成熟度应该是对知识可信度的客观度量，而非人工标签。

**Independent Test**: 一条 `draft` 条目在第一次被 confirm 后变为 `verified`；在第二个不同 session 通过 update-refs 引用后，evidence 数组有 ≥2 条来自不同 session 且有 ≥2 位 contributor 的记录，自动晋升为 `proven`。

**Acceptance Scenarios**:

1. **Given** `draft` 条目，**When** 维护者执行 `holmes kb confirm`，**Then** evidence 追加第一条审核记录（contributor: 维护者），`maturity` 自动变为 `verified`
2. **Given** `verified` 条目，**When** 来自不同 session 的 `update-refs` 使 evidence 数组中不同项目/session 记录数 ≥2 且 contributor 去重数 ≥2，**Then** `maturity` 自动晋升为 `proven`
3. **Given** `verified` 条目，**When** 同一 session 多次引用，**Then** evidence 去重，不重复计入晋升计数

---

### Edge Cases

- Agent 写入内容与现有已确认条目标题完全相同时，CLI 返回错误并拒绝写入；Agent 应改用修正工作流（声明 `corrects: <id>`）提交修正提案
- 修正提案本身有误需再次修正时，可对 pending 中的提案直接编辑（draft 可改）
- 条目被衰减降为 `draft` 后 Agent 修改了内容，维护者可通过历史快照查阅降级前版本；decay 降级时自动保存 VersionSnapshot
- 批量衰减操作中途失败时，已处理的条目变更保留，失败原因记录日志，支持重试
- 多人协作时同一条目发生成熟度冲突（一方升级、另一方降级），保留较低值并标记 `contradiction: true`，通知维护者裁决
- 同一 session 引用同一条目多次，evidence 去重，只记录一条

---

## Requirements *(mandatory)*

### Functional Requirements

**只读保护（Agent 软约束）**
- **FR-001**: holmes CLI MUST 在 Agent 尝试直接写入 `maturity: verified` 或 `maturity: proven` 条目时拦截并返回错误；维护者直接操作文件系统不受此约束
- **FR-002**: 系统 MUST 允许对任意成熟度条目的读取操作
- **FR-003**: Agent 对 `draft` 条目的修改 MUST 通过 `write-pending` 提交，不提供直接写入公共区 draft 条目的 CLI 命令

**沉淀与发布**
- **FR-004**: 系统 MUST 提供写入 pending 区的命令，新条目初始 `maturity: draft`；若标题与任意已确认条目（`verified`/`proven`）完全匹配且未声明 `corrects`，MUST 返回错误并拒绝写入
- **FR-005**: 系统 MUST 提供 `confirm` 命令，将 pending 条目移入公共区并向 evidence 数组追加第一条人工审核记录；maturity 由 evidence 数量自动派生（≥1 条 → `verified`）
- **FR-006**: 系统 MUST 提供 `reject` 命令，从 pending 删除条目且不影响公共区

**修正工作流**
- **FR-007**: 系统 MUST 支持在 pending 条目中声明 `corrects: <entry-id>` 字段
- **FR-008**: 确认带有 `corrects` 字段的提案时，系统 MUST 用提案内容替换原条目，并记录 VersionSnapshot；原条目 evidence 数组保留
- **FR-009**: 系统 MUST 保留被替换条目的历史快照，支持查阅（`holmes kb history <id>`）

**引用追踪与成熟度晋升**
- **FR-010**: 系统 MUST 提供 `holmes kb update-refs --ids <id,...>` 命令，在 session 结束时批量向每个条目的 evidence 数组追加本次引用记录（含 session_id、contributor、date）；同一 session 对同一条目去重
- **FR-011**: maturity 晋升规则由 evidence 数组自动派生：evidence 中不同 session 数 ≥2 且 contributor 去重数 ≥2 时，`verified` 自动晋升为 `proven`
- **FR-012**: 条目 MUST 包含 `contributors` 字段，记录参与验证的贡献者列表；`confirm` 和 `update-refs` 操作时自动追加当前操作者

**成熟度衰减与归档**
- **FR-013**: 系统 MUST 提供衰减检查命令：`proven` 超 12 个月未引用（evidence 最后记录日期）降为 `verified`；`verified` 超 6 个月未引用降为 `draft`；降级时保存 VersionSnapshot
- **FR-014**: 衰减操作 MUST 记录变更原因（`decay: unreferenced N months`）
- **FR-015**: 系统 MUST 提供归档命令，将 Lint 标记为孤儿的 `draft` 条目移入 `contributions/archive/`，从活跃索引移除
- **FR-016**: 多人协作发生成熟度冲突时，系统 MUST 保留较低 maturity 值并在条目中写入 `contradiction: true`，通知维护者裁决

### Key Entities

- **KbEntry**: 知识条目，包含 `maturity`（draft/verified/proven）、`evidence`（EvidenceRecord 数组）、`contributors`（贡献者列表）、`updated_at`、可选 `corrects`、可选 `contradiction` 字段
- **EvidenceRecord**: 单条引用证据，含 `session_id`、`contributor`、`date`、`project`（可选）、`context`（可选）
- **PendingEntry**: 待审条目，含 `source`（agent/human）、可选 `corrects: <entry-id>`
- **VersionSnapshot**: 条目被修正或衰减降级时保存的历史快照，含原始内容、`replaced_at` 时间戳

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Agent 通过 holmes CLI 对已确认知识的直接写入尝试 100% 被拦截，误拦截率为 0
- **SC-002**: 修正提案从提交到确认发布的完整流程可在 5 分钟内完成（人工操作时间不计）
- **SC-003**: 成熟度衰减检查命令在知识库规模 ≤1000 条时执行时间 <10 秒
- **SC-004**: 所有条目修改均有可追溯的变更记录，历史版本可通过 `holmes kb history <id>` 随时查阅
- **SC-005**: 衰减机制能识别出超过阈值的全部候选条目，漏检率为 0
- **SC-006**: evidence 数组在多人并发写入场景下 git 合并无冲突（append-only 追加语义）

---

## Assumptions

- 知识库以 Git 仓库形式存储；只读保护为软约束，通过 holmes CLI 拦截实现，维护者可直接操作文件系统
- 成熟度衰减是离线批量操作（手动触发或定期 cron），不要求实时触发
- 版本历史快照存储在知识库内部 `.history/` 目录，不依赖 Git 历史
- 引用追踪通过 session 结束时批量调用 `update-refs` 实现，CLAUDE.md 约束 Agent 在每次 session 结束时执行；evidence 为 append-only 数组，天然支持多人 git 合并
- 修正提案复用现有 pending → confirm 流程，不引入独立审批系统
- 衰减阈值（12个月/6个月）为默认值，可通过 `kb-config.yml` 覆盖
- maturity 由 evidence 数量自动派生；`confirm` 追加第一条 evidence → `verified`；≥2 不同 session + ≥2 contributor → `proven`
- 所有写入（包括对 draft 条目的修改）均通过 pending → confirm 流程，保证人工审核节点不被绕过
