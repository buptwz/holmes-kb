# Feature Specification: Import Pipeline 永远新建策略

**Feature Branch**: `024-reimport-lifecycle`

**Created**: 2026-06-10

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Re-import 文档产生新版本知识而非覆盖旧知识 (Priority: P1)

SRE 发现之前 import 的一份运维文档提取质量较差（命令不完整、分类错误），修正文档后重新执行 `holmes import`。

当前行为：dedup pass 尝试找到"同根因"的旧条目进行 update，匹配逻辑复杂且不准确，产生内容混乱或错误覆盖。

期望行为：re-import 直接产生一批新的正确条目，旧条目继续存在。新条目开始积累 evidence，旧条目 evidence 停止新增，decay 机制基于 evidence 最新时间逐步降级旧条目。新旧知识的有效性竞争完全由 evidence 时间线决定，import 不参与判断。

**Why this priority**: 这是整个知识库生命周期模型的基础假设——import 负责生产知识，evidence 时间线负责判断有效性，两者职责分离。

**Independent Test**: 对同一主题文档执行两次 import（第二次内容有修改），验证 KB 中产生两批独立条目，旧条目内容未被修改。

**Acceptance Scenarios**:

1. **Given** 已有从文档 v1 import 的 KB 条目，**When** 导入内容不同的文档 v2（相同主题），**Then** 新条目被创建，旧条目内容、maturity、evidence 均不变
2. **Given** 导入文档 v2 后，**Then** v2 产生的新条目拥有独立的 Skill（若命令数量达到阈值），与旧条目的 Skill 互不干扰
3. **Given** 完全相同内容的文档被 import 两次，**Then** 第二次通过文档级 hash 预检查直接跳过，不产生重复条目

---

### User Story 2 - 单次 Import 内部去重防止同文档冗余 (Priority: P2)

一份文档中两个段落描述了本质相同的知识点，Reader 阶段识别出两个 KP，Extractor 提取了两份几乎相同的草稿。

当前行为：两份草稿都走 create 路径，产生两个近乎重复的条目。

期望行为：在单次 import 内部，同一次导入提取出根因相同的多个草稿只保留一份。这是 import 内部的质量保障，与跨文档"永远新建"策略不冲突。

**Why this priority**: 防止 Reader 偶发重复识别在单次 import 内污染 KB，不影响跨文档策略。

**Independent Test**: 构造一个包含两段描述同一问题的文档，import 后验证只创建一个条目。

**Acceptance Scenarios**:

1. **Given** 同一文档中提取出两个根因相同的 KP 草稿，**When** import 运行，**Then** 只创建一个条目，另一个草稿被丢弃并在 ImportReport 中标注
2. **Given** 同一文档中的两个 KP 草稿根因不同，**Then** 两个条目都被正常创建

---

### Edge Cases

- 文档 v2 与 v1 主题完全不同：正常新建，不影响 v1 的任何条目
- 文档 v2 与 v1 改动极小（修正一个错别字）：hash 不同 → 正常新建 v2 条目；v1 条目存留，由 evidence 时间线处理

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Import pipeline MUST 移除跨文档的 root-cause dedup 逻辑（`_run_dedup_pass` 中的跨条目匹配），每次 import 只新建条目，不更新已有条目
- **FR-002**: LLM writer 的 system prompt MUST 同步移除"发现同根因条目则调用 `update_kb_entry`"的指令，与 FR-001 保持一致
- **FR-003**: 文档级 hash 预检查 MUST 保留——完全相同的文档重复导入时直接跳过
- **FR-004**: 单次 import 内部 MUST 保留草稿级去重——同一次 import 中根因相同的多个草稿只保留一份，丢弃的草稿在 ImportReport 中标注
- **FR-005**: 新建条目 MUST 走现有的 Skill 评估逻辑，命令数量达到阈值则创建新 Skill

### Key Entities

- **KB Entry**: 知识条目，每次 import 独立新建，不与历史条目合并
- **Evidence**: 条目被实际引用/验证的记录，其最新时间决定条目有效性（而非 maturity 高低）
- **Skill**: 与 KB 条目一对一关联，随条目新建而创建

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: re-import 修正后的文档，旧条目内容 100% 不变，新条目完整创建且包含正确 Skill
- **SC-002**: re-import 完全相同的文档，第二次 import 在 hash 预检查阶段退出，KB 无任何变化
- **SC-003**: 包含重复知识点的文档 import 后，KB 中该主题只新增一个条目（单次 import 内去重生效）
- **SC-004**: 新建条目的 Skill 创建率与现有 pipeline 一致，不因策略变更而降低

## Assumptions

- `update_kb_entry` 工具保留但从 import pipeline 主流程中移除调用（仅供手动或外部工具使用）
- 单次 import 内部草稿去重沿用现有相似度阈值（root-cause 相似度 ≥ 0.8）
- 旧条目清理、Skill 孤儿清理、搜索排序优化等延伸问题见 `docs/technical-debt.md`
