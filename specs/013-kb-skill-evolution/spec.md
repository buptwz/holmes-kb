# Feature Specification: Holmes KB Autonomous Import Agent

**Feature Branch**: `013-kb-skill-evolution`

**Created**: 2026-06-07

**Status**: Draft

**Input**: 升级 `holmes import` 为一个自主 agent 驱动的 KB 全生命周期管理入口。用户只需提供原始素材，系统自动完成：内容理解、分类存储、去重合并、skill 生成判断、skill 质量整理，并保证幂等性与内容正确性。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 一条命令，自动生成并更新知识库 (Priority: P1)

用户将一份事故报告、运维日志、或技术文档传给 `holmes import`，系统自动完成从原始素材到结构化知识条目的全流程：识别知识类型、分配到正确 category、生成规范的 frontmatter 和各内容章节、检查是否与现有条目重复、写入知识库。整个过程无需用户指定类型、目录或格式。

**Why this priority**: 这是本 feature 的核心价值。没有这条，其他所有能力都失去意义。

**Independent Test**: 给定一段事故描述文本，运行 `holmes import`，验证 KB 中生成了结构完整、字段正确的条目。

**Acceptance Scenarios**:

1. **Given** 一段描述"PostgreSQL 连接数耗尽导致服务不可用，重启 PgBouncer 恢复"的文本，**When** 运行 `holmes import`，**Then** KB 中创建一条 `type: pitfall`、`category: database` 的条目，包含完整的 Symptoms、Root Cause、Resolution 章节。
2. **Given** 一份描述系统部署流程的文档，**When** 运行 `holmes import`，**Then** 系统识别为 `type: process` 并生成对应结构的条目。
3. **Given** 一段只有症状描述、缺少根因的稀薄输入，**When** 运行 `holmes import`，**Then** 生成 `maturity: draft` 条目，缺失字段留空，日志明确提示"未检测到根因分析，Root Cause 字段待补全"。
4. **Given** 一篇包含两个独立问题的长文档，**When** 运行 `holmes import`，**Then** 系统识别为多知识点，询问用户"检测到 2 个独立问题，分别建条目还是合并为一条？"，按用户选择执行。

---

### User Story 2 — Agent 内容正确性保障 (Priority: P1)

import agent 在生成知识条目时，所有关键字段内容（根因、解决步骤、命令）必须有源文本依据，不允许 LLM 自行推断补全。agent 写完草稿后，必须对照原文自我验证，再提交写入。这保证了知识库内容的可信度。

**Why this priority**: 与 US1 并列 P1。全自动意味着没有人工审核兜底，agent 自身的正确性机制是唯一的质量保障。错误的命令比没有命令危害更大。

**Independent Test**: 给定一段刻意省略了根因的输入，验证生成条目的 Root Cause 字段为空而非 LLM 编造内容。

**Acceptance Scenarios**:

1. **Given** 源文本中未提及任何 shell 命令，**When** import 运行，**Then** 生成条目的 Resolution 中不出现任何命令行，skill 生成判断为"不生成"。
2. **Given** 源文本包含命令 `pg_dump -h {host} -d {db}`，**When** import 运行，**Then** 生成的条目和 skill 中的命令与源文本完全一致，不被修改或"优化"。
3. **Given** agent 完成草稿生成，**When** 自我验证阶段发现草稿中某字段内容无法在源文本中找到对应片段，**Then** agent 自动删除该字段内容并标记为待补全，而不是保留推断内容。
4. **Given** 分类置信度低于阈值，**When** import 运行，**Then** 系统向用户展示"我认为这是 pitfall/database，是否正确？"并等待确认，不自动写入。

---

### User Story 3 — 幂等性：重复 import 不产生重复知识 (Priority: P1)

对同一份素材多次运行 `holmes import` 结果完全相同：第一次创建条目，后续运行检测到内容 hash 匹配则跳过，不产生重复条目。如果素材有新增内容（hash 不同），则智能合并更新。

**Why this priority**: 幂等性是自动化系统的基础可靠性要求。没有幂等保证，用户无法放心地在 CI 或定期任务中运行 import。

**Independent Test**: 对同一文本运行两次 `holmes import`，验证第二次输出"已存在，跳过"且 KB 条目数量不变。

**Acceptance Scenarios**:

1. **Given** 某文本已被 import 过（`source_hash` 存入条目 frontmatter），**When** 再次 import 同一文本，**Then** 系统输出 `✓ skipped (already imported)` 并退出，KB 不变。
2. **Given** 某文本在上次 import 后新增了一段 Resolution 内容（hash 不同），**When** 再次 import，**Then** 系统识别为"同源更新"，将新内容合并进现有条目，更新 `updated_at`，不新建条目。
3. **Given** 两份内容相同但文件名不同的文档，**When** 分别 import，**Then** 第二次识别为重复（content hash 相同）并跳过，不依赖文件路径。
4. **Given** 同一文档描述的是与现有条目**相同根因**的问题（即真正的重复知识），**When** import 运行，**Then** 系统合并更新现有条目而非新建。
5. **Given** 同一文档描述的是与现有条目**相关但根因不同**的问题，**When** import 运行，**Then** 系统新建条目并在双方 `related_entries` 字段中建立关联。

---

### User Story 4 — 智能交互确认 (Priority: P2)

import agent 对高置信度决策自动执行，对低置信度或影响较大的决策暂停并以清晰语言询问用户。用户只需回答关键岔路口问题，无需理解 KB 内部结构。提供 `--no-interactive` 模式供无人值守场景使用。

**Why this priority**: 交互确认既是 UX 设计，也是 accuracy gate——用户的判断弥补了 agent 置信度不足的部分。

**Independent Test**: 给定一段分类模糊的输入，验证系统询问分类确认；给定 `--no-interactive`，验证系统自动选择默认值不暂停。

**Acceptance Scenarios**:

1. **Given** agent 对 KB 类型判断置信度低，**When** import 运行（默认交互模式），**Then** 系统输出"我认为这是 guideline/networking，是否正确？[Y/n/其他类型]"并等待用户输入。
2. **Given** 发现与现有条目高度相似，**When** import 运行，**Then** 系统展示现有条目摘要并询问"找到相似条目 PT-DB-001，更新它还是新建？[u=更新/n=新建]"。
3. **Given** 检测到 skill 生成候选，**When** import 运行，**Then** 系统询问"检测到多步骤流程，建议创建 skill `pg-connection-recovery`，是否确认？[Y/n]"。
4. **Given** 用户运行 `holmes import --no-interactive`，**When** 遇到不确定决策，**Then** 系统自动选择保守默认值（草稿条目、不合并、不生成 skill）并在报告中记录所有自动决策。
5. **Given** agent 对所有决策置信度均高，**When** import 运行，**Then** 全程无交互，直接完成并输出摘要报告。

---

### User Story 5 — Skill 自动生成与管理 (Priority: P2)

import 完成条目写入后，agent 根据明确标准判断是否为本条目生成 skill。判断结果确定后，再对同 category 范围内的现有 skill 做增量质量整理（合并重复、拆分过大、标记过时）。skill 的所有写入操作与 KB 条目写入使用同样的原子写入机制。

**Why this priority**: skill 是知识的可执行化，是 KB 自进化的核心产出。质量整理防止 skill 库随时间腐化。

**Independent Test**: 给定一个包含多步骤带参数命令的 KB 条目，验证 import 后自动生成对应 skill；给定两个描述高度相似的 skill，验证 curator 报告识别为合并候选。

**Acceptance Scenarios**:

1. **Given** 条目 Resolution 中包含 3 步以上命令且有 `{parameter}` 占位符，**When** import 完成，**Then** agent 标注为"推荐生成 skill"并向用户确认，确认后创建 skill 并标记 `agent_created: true`。
2. **Given** 条目 Resolution 中只有一条无参数的简单命令，**When** import 完成，**Then** agent 在报告中标注"可选生成 skill（单步骤命令）"但不主动询问，用户可手动触发。
3. **Given** 条目中的命令已被现有 skill 覆盖，**When** import 完成，**Then** agent 自动执行 `skill link` 而不是新建 skill，报告中说明"已关联至现有 skill: pg-connection-recovery"。
4. **Given** import 后同 category 内存在两个描述高度相似的 agent-created skill，**When** 增量整理运行，**Then** 报告标注"合并候选：check-pg-connections 与 check-pg-pool，建议合并"，不自动合并，等待用户或 agent 决策。
5. **Given** 一个 skill 的 `patch_count` 为 0 且其关联 KB 条目在 skill 创建后有过更新，**When** 增量整理运行，**Then** 报告标注"更新候选：skill 内容可能落后于关联条目的最新变更"。
6. **Given** agent 决定合并 skill A 到 skill B，**When** 执行 `manage --action delete --name A --absorbed-into B`，**Then** skill A 目录删除，`.skill_usage.json` 记录 `absorbed_into: B`，skill B 保持完整。

---

### User Story 6 — Dry-run 与可观测性 (Priority: P2)

用户可运行 `holmes import --dry-run` 预览 import 将执行的所有操作而不实际写入。每次 import 结束后输出结构化摘要报告；`--verbose` 模式展示每条决策的详细推理。

**Why this priority**: 可观测性是用户建立对自动化系统信任的关键。dry-run 尤其对初次使用和批量处理场景不可缺少。

**Independent Test**: 对一份新文档运行 `--dry-run`，验证 KB 未被修改，但输出完整的执行计划。

**Acceptance Scenarios**:

1. **Given** 运行 `holmes import --dry-run <source>`，**Then** 系统输出完整执行计划（将创建哪些条目、更新哪些条目、生成哪些 skill、跳过哪些），且 KB 目录无任何文件变更。
2. **Given** 运行 `holmes import <source>`（正常模式），**When** 完成后，**Then** 输出摘要：`✓ 1 created, 0 updated, 1 skipped (duplicate) | skill: 1 generated, 0 merged | 1 suggestion: check-connections may warrant a skill`。
3. **Given** 运行 `holmes import --verbose <source>`，**Then** 输出每条分类决策的置信度、每个字段的源文本依据、每个 skill 判断的推理过程。
4. **Given** import 中某步骤失败（如 skill 生成时内容校验未通过），**Then** 摘要报告中标注 `⚠ skill generation failed: <reason>`，已成功写入的 KB 条目保留，不回滚。

---

### Edge Cases

- 输入为空或纯噪音（无有效知识点）→ 报错退出，提示"无法从输入中提取有效知识，请提供更多上下文"。
- 输入文档超长（>50,000 字）→ agent 分段处理，每段独立提取知识点后合并去重，不截断。
- source_hash 冲突（不同内容产生相同 hash）→ 极低概率，发生时以内容比对为准，不依赖 hash 唯一性保证最终决策。
- `--absorbed-into` 指向不存在的 skill → 拒绝删除并报错，防止内容丢失。
- skill SKILL.md 内容校验失败 → 不写入磁盘，在报告中标注失败原因，相关 KB 条目正常写入。
- 批量 import 目录（`holmes import --dir ./docs/`）→ 按文件逐个处理，单文件失败不中断其余文件的处理，最终报告汇总所有结果。

---

## Requirements *(mandatory)*

### Functional Requirements

**Import Pipeline**

- **FR-001**: `holmes import <source>` MUST accept 单行文本、文件路径（`--file`）、目录（`--dir`）、stdin pipe 四种输入形式。
- **FR-002**: import agent MUST 自动判断 KB 类型（pitfall/model/guideline/process/decision）和 category，无需用户指定。
- **FR-003**: 对分类置信度低的决策，系统 MUST 在默认交互模式下暂停并询问用户确认；`--no-interactive` 模式下自动选择保守默认值并在报告中记录。
- **FR-004**: import agent MUST 在生成每个关键字段（根因、命令、解决步骤）时，标注对应源文本片段；无源文本依据的字段 MUST 留空，不得推断补全。
- **FR-005**: import agent MUST 在写入前执行自我验证：对照源文本检查草稿中每个关键字段，删除无依据内容。
- **FR-006**: 信息不足的输入 MUST 生成 `maturity: draft` 条目，日志和摘要报告中 MUST 明确列出哪些字段缺失及原因。

**幂等性**

- **FR-007**: 每个 KB 条目 frontmatter MUST 存储 `source_hash`（输入内容的 SHA-256 hash 前 16 位）。
- **FR-008**: import 开始时 MUST 检查 `source_hash`：完全匹配则跳过；hash 不同但根因相同则合并更新；根因不同则新建并关联。
- **FR-009**: 根因相同的判断依据 MUST 是内容语义比对，不依赖标题字符串匹配。

**Skill 生成与管理**

- **FR-010**: import agent MUST 在条目写入后评估 skill 生成价值，评估依据：命令步骤数（≥3 步为推荐）、参数占位符存在（推荐）、现有 skill 覆盖情况（已覆盖则链接不新建）。
- **FR-011**: 不确定是否生成 skill 时，系统 MUST 默认跳过，在报告中标注建议，不自动创建。
- **FR-012**: 所有 skill 写入 MUST 通过内容校验（frontmatter 有 name/description、正文非空、≤100,000 字符）。
- **FR-013**: skill 内的命令 MUST 来自源文本，不得由 LLM 编造；如无源文本依据则不生成 skill。
- **FR-014**: import 完成后 MUST 对同 category 范围内的 agent-created skill 执行增量质量检查，识别：合并候选（描述关键词 Jaccard 相似度 > 阈值）、过大候选（body > 3,000 字）、更新候选（patch_count=0 且关联条目有更新）。
- **FR-015**: skill 质量整理结果 MUST 以建议形式输出到报告，不自动执行合并/拆分，等待用户或后续 agent 操作。

**原子写入与可靠性**

- **FR-016**: 所有文件写入 MUST 使用原子写入模式（临时文件 + rename），每个文件要么完整写入要么不变。
- **FR-017**: import 完成后 MUST 执行 `git commit`，以 git history 作为 pipeline 级回滚机制。
- **FR-018**: 单个步骤失败（如 skill 校验）不得回滚已成功的步骤（KB 条目写入），失败信息记入报告。

**可观测性**

- **FR-019**: `--dry-run` 模式 MUST 输出完整执行计划，不写入任何文件，不执行 git commit。
- **FR-020**: 每次 import 结束 MUST 输出结构化摘要（created/updated/skipped 计数，skill 操作，建议列表）。
- **FR-021**: `--verbose` 模式 MUST 展示每条决策的置信度、源文本依据、推理过程。

### Key Entities

- **ImportSource**: 原始输入素材。字段：`raw_text`、`source_hash`、`file_path`（可选）。
- **KBEntry**: KB 知识条目（现有格式，新增 `source_hash` 和 `import_confidence` 字段）。
- **SkillUsageRecord**: skill 操作元数据 sidecar（`.skill_usage.json`）。字段：`created_at`、`agent_created`、`use_count`、`last_used_at`、`patch_count`、`last_patched_at`、`absorbed_into`（可选）。
- **ImportReport**: import 运行结果摘要。字段：`created`、`updated`、`skipped`、`skills_generated`、`skills_merged`、`suggestions`、`warnings`、`errors`。
- **CuratorFinding**: 增量质量检查结果。字段：`finding_type`（merge_candidate/oversized/update_candidate）、`skill_names`、`reason`。

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户只需运行 `holmes import <source>`，无需指定类型、category 或任何参数，即可完成 KB 条目的创建或更新。
- **SC-002**: 对同一素材运行两次 import，第二次输出 `skipped (already imported)`，KB 条目数量不变——100% 幂等。
- **SC-003**: import 生成的条目中，关键字段（根因、命令）100% 有源文本依据，不出现无依据的推断内容。
- **SC-004**: 用户确认环节每次只提一个问题，整个 import 流程用户回答问题不超过 3 次（针对单份文档）。
- **SC-005**: dry-run 模式运行后，KB 目录 `git diff` 为空——零副作用。
- **SC-006**: 所有文件写入操作不产生半写状态；进程中途被 kill 后，KB 目录中每个文件要么是完整旧版本要么是完整新版本。
- **SC-007**: import 对单份文档（≤10,000 字）的总处理时间不超过 30 秒（不含用户交互等待时间）。

---

## Clarifications

### Session 2026-06-07

- Q: LLM API 调用失败时怎么处理？ → A: 每个知识点独立重试；重试失败则提示"知识点提取失败：<原因>"并跳过，继续处理下一个知识点；不中止整个 pipeline。
- Q: `draft` 条目如何晋升为正式条目？ → A: 沿用现有 003-kb-governance 设计：import 仍走 pending → confirm 流程（高置信度时 agent 自动 confirm，低置信度时询问用户）；maturity 晋升（draft→verified→proven）由证据系统（evidence 数组）驱动，不是 import 的职责。
- Q: FR-009 与 Assumptions 矛盾：去重的根因相同判断，使用关键词启发式还是 LLM 语义判断？ → A: 使用 LLM 在 import agent 的 tool-use 循环内做语义判断，不引入向量数据库；LLM 直接比对两条内容的根因语义，判断是否描述同一根本原因。

## Assumptions

- import agent 通过 Anthropic SDK 的 tool-use 循环实现，不复用 claude-code TUI 框架；工具函数直接调用现有 KB Python 函数。
- 去重根因判断（FR-009）及 skill 合并候选检测（FR-014）均在 import agent 的 tool-use 循环内由 LLM 完成语义比对，不引入向量嵌入数据库；skill 合并候选检测使用关键词 Jaccard 相似度作为初筛，再由 LLM 做最终判断。
- `source_hash` 使用输入内容的 SHA-256 前 16 位；极低概率的 hash 碰撞以内容比对作为最终裁决。
- git 作为 pipeline 级回滚机制，要求 KB 目录在 git 仓库中。
- 批量 import（`--dir`）逐文件处理，不支持跨文件的知识合并（单文件内的多知识点合并支持）。
- LLM API 调用失败时，针对失败的知识点自动重试；重试仍失败则在摘要报告中标注"知识点提取失败：<原因>"并跳过，继续处理其余知识点；不中止整个 pipeline。
- skill 安全扫描（防止恶意命令）超出本 feature 范围；内容校验仅覆盖结构正确性。
- 现有 KB 条目格式（Markdown + YAML frontmatter）保持不变，仅新增 `source_hash` 和 `import_confidence` 两个字段，不影响人工可读性。
