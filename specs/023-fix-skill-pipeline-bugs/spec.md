# Feature Specification: Import Pipeline v3 回归缺陷修复

**Feature Branch**: `023-fix-skill-pipeline-bugs`

**Created**: 2026-06-10

**Status**: Draft

**Input**: 修复回归测试报告 v1 中三个未修复的缺陷：Skill 脚本裸文本崩溃（P0）、语义去重 UPDATE 路径失效（P1）、OPTIONAL Skill 候选提示缺失（P2）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skill 脚本可执行（QA-18 裸文本修复）(Priority: P1) 🎯 MVP

SRE 导入一份含中文步骤说明的故障处置文档后，系统生成的 `run.sh` 可直接用 `bash run.sh` 执行，不因步骤序号（`1. 确认磁盘 I/O...`）等裸文本行导致 `set -euo pipefail` 崩溃。

**Why this priority**: 当前所有包含步骤说明的 Skill 脚本（约 58 个）无法执行，Skill 功能完全不可用，影响最大。

**Independent Test**: 导入含编号步骤的故障文档 → `bash -n run.sh` 语法检查通过，`bash run.sh` 正常运行。

**Acceptance Scenarios**:

1. **Given** 故障文档的 Resolution 章节含有 `1. 确认磁盘 I/O 瓶颈`、`2. 检查 TiKV Raft Log` 等编号步骤，**When** 系统提取命令生成 run.sh，**Then** 编号步骤行不出现在 run.sh 中，run.sh 仅包含合法 bash 命令或注释。
2. **Given** 生成的 run.sh，**When** 执行 `bash -n run.sh`，**Then** 退出码为 0，无语法错误。
3. **Given** 不含编号步骤的文档，**When** 系统提取命令，**Then** 行为不变，所有合法命令保留。

---

### User Story 2 - 语义去重正确走 UPDATE 路径（TC-D-02）(Priority: P2)

同根因的更新版文档被导入时，系统检测到现有语义相似条目并调用更新操作，而不是重新创建，避免知识库长期积累冗余条目。

**Why this priority**: 重复条目导致知识库质量下降，但不影响即时可用性，优先级低于 Skill 可执行性。

**Independent Test**: 导入与现有条目同根因的文档 → 输出 `0 created, 1 updated`，KB 中不新增冗余条目。

**Acceptance Scenarios**:

1. **Given** KB 中已存在 entry-A（某故障根因），**When** 导入内容相似（同根因、更新版）的文档，**Then** 输出 `0 created, 1 updated, 0 skipped`，entry-A 被更新而非重复创建。
2. **Given** 无语义相似条目，**When** 导入全新文档，**Then** 正常走 create 路径，输出 `1 created`。
3. **Given** 导入完全相同文档（hash 匹配），**When** 系统处理，**Then** 输出 `0 skipped`，不触发 update。

---

### User Story 3 - OPTIONAL Skill 候选提示在更新路径出现（TC-S-02）(Priority: P3)

包含 1-2 条命令的文档被导入并更新现有条目时，系统在报告摘要中输出 `skill candidate` 提示，提醒 SRE 该文档可能值得创建 Skill，而不是静默跳过。

**Why this priority**: 仅影响 SRE 发现 skill 候选的体验，不影响 KB 数据正确性，优先级最低。

**Independent Test**: 导入含 1-2 条命令且语义匹配现有条目的文档（走 update 路径）→ 报告摘要含 `skill candidate` 提示。

**Acceptance Scenarios**:

1. **Given** KB 中已存在 entry-A，**When** 导入含 1 条 bash 命令的相似文档（走 update 路径），**Then** report.suggestions 含 `skill candidate` 字样的提示。
2. **Given** KB 中已存在 entry-A，**When** 导入含 2 条 bash 命令的相似文档（走 update 路径），**Then** report.suggestions 含 `skill candidate` 字样的提示。
3. **Given** 走 create 路径（非 update），**When** 文档含 1-2 条命令，**Then** 现有 OPTIONAL 路径行为不变（已有测试覆盖）。

---

### Edge Cases

- 文档中既有编号步骤又有合法命令行：只过滤编号步骤，保留命令行。
- 编号步骤在代码块内（如 `` ` `` 包裹）：仍需过滤，因为已在 code block 提取阶段处理。
- 语义相似度阈值边界：刚好在阈值边缘的文档，走 create 还是 update 由现有阈值逻辑决定，本次不改变阈值。
- update_kb_entry 调用失败：错误应传播到 report.errors，不静默吞掉。
- OPTIONAL Skill + update 路径且 Skill 已存在：不重复创建，仅输出 suggestion。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 命令提取模块必须过滤以 `数字.`、`数字)` 开头（后跟空格）的行，不得将其写入 Skill 运行脚本。
- **FR-002**: 被过滤的行不影响同一代码块中其他合法命令行的提取。
- **FR-003**: Import pipeline 的语义去重分支，在判断为 UPDATE 时，必须调用 `update_kb_entry` 工具（而非 `write_kb_entry`），并传入匹配条目的 `entry_id` 和包含新内容的 patch。
- **FR-004**: 语义去重 UPDATE 分支执行后，KB 中同 entry_id 的条目内容被更新，不新增重复条目。
- **FR-005**: `_finalize_skill_generation`（或等效逻辑）必须在 `update_kb_entry` 执行后也触发 Skill 评估，并将 OPTIONAL 判断结果（1-2 条命令）作为 `skill candidate` 写入 report.suggestions。
- **FR-006**: 上述三项修复均不改变现有通过测试的行为；新增测试覆盖三个回归场景。

### Key Entities

- **SkillScript (run.sh)**: 可执行 bash 脚本，只含合法 shell 命令和注释，不含裸文本步骤描述。
- **ImportReport**: 记录 created/updated/skipped 计数及 suggestions 列表；update 路径下 suggestions 须包含 skill candidate 提示。
- **KBEntry**: 知识库条目；语义去重后 entry_id 不变，content 被 patch 更新。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 所有包含编号步骤说明的 Skill run.sh 通过 `bash -n` 语法检查，执行不崩溃（当前 0% → 目标 100%）。
- **SC-002**: 同根因文档导入后 `updated` 计数 ≥ 1、`created` 计数为 0（当前始终 created，UPDATE 路径成功率 0% → 目标 ≥ 95%）。
- **SC-003**: 含 1-2 条命令且走 update 路径的导入，report.suggestions 含 `skill candidate`（当前 0% → 目标 100%）。
- **SC-004**: 回归测试套件新增测试均通过，既有测试通过率不下降（维持 ≥ 680 passed）。

## Assumptions

- 过滤规则仅针对 `^\d+[.)]\s` 模式（数字序号后跟 `.` 或 `)` 再跟空格），不扩展到字母序号（`a.`、`A)`）或其他裸文本形式。
- 语义去重阈值和相似度算法不在本次修改范围内，仅修复 prompt 指令让 LLM 正确调用 `update_kb_entry`。
- `_finalize_skill_generation` 改造范围：仅在 update 路径结束时追加 skill 评估，不重构整体 skill 生成流程。
- 现有 58 个已生成的 Skill 脚本不在本次修复范围内（需用户手动重新导入或单独工具修复）。
- 测试使用 mock/stub，不依赖真实 LLM 调用。
