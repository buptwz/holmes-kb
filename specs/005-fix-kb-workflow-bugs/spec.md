# Feature Specification: 修复 Holmes KB 核心工作流缺陷

**Feature Branch**: `005-fix-kb-workflow-bugs`

**Created**: 2026-06-05

**Status**: Draft

**Input**: 用户全功能实操测试报告（holmes-kb v0.1.0 + holmes-agent v2.6.0）

---

## Clarifications

### Session 2026-06-05

- Q: `session list/show` 命令不存在但 README 有记录，是实现命令还是删除文档？ → A: 从文档中删除相关记录，不在本次迭代中新增实现。
- Q: CLI 文档与实现不符时，修复方向是改文档还是改代码？ → A: 修改文档以匹配现有代码实现，代码参数名保持不变。

---

## 背景

Holmes 的核心价值主张是"每次排障自动沉淀知识"——工程师在 Agent 协助下解决问题后，知识自动流入 KB，供团队未来复用。当前版本存在多处缺陷，使这一闭环完全无法走通，同时多个日常工作流存在文档与实现不符、操作障碍等问题，影响用户信任和日常使用效率。

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Agent 自动沉淀知识完整闭环 (Priority: P1)

工程师与 Agent 协作排查并解决了一个生产问题（例如 Kafka Full GC 导致 Rebalance）。问题解决后，工程师告知 Agent"已解决"。Agent 提取关键知识并写入 KB 待审区（pending）。工程师运行一条确认命令，知识正式入库，可被未来 Agent session 检索和复用。

**Why this priority**: 这是产品最核心的价值闭环。当前因 pending 条目缺少必需字段，确认时永远失败，所有 Agent 自动提取的知识均无法入库，产品核心价值主张完全无法兑现。

**Independent Test**: 可独立测试：Agent 调用写入工具 → 生成 pending 条目 → 运行 `holmes kb confirm <id>` → 验证条目成功进入 KB 正式区，且正式条目中不含任何待审内部字段。

**Acceptance Scenarios**:

1. **Given** Agent 完成一次排障 session，**When** Agent 调用知识提取写入工具，**Then** 生成的 pending 条目包含所有 KB 必需字段（包括 maturity），无字段缺失。
2. **Given** pending 条目已生成，**When** 工程师运行 `holmes kb confirm <pending_id>`，**Then** Gate 1 验证通过，无"缺少必需字段"类错误。
3. **Given** 确认流程完成，**When** 检查正式条目内容，**Then** 条目中不包含任何待审内部字段（如 `pending: true`、`source: auto`、`suggested_type`、`suggested_category` 等），仅保留标准 KB 字段。
4. **Given** 正式条目已入库，**When** Agent 搜索相关关键词，**Then** 新条目出现在搜索结果中，可被正常读取。

---

### User Story 2 — Skill 自动发现与创建 (Priority: P1)

工程师解决问题后，Agent 读取 KB 中与该问题相关的条目（含操作步骤），识别出条目中的可执行诊断命令，向工程师确认是否自动创建一个可复用的诊断 Skill。工程师确认后，该命令被封装为 Skill，与 KB 条目关联，供未来 session 直接执行。

**Why this priority**: Skill 系统将知识从"文字描述"升级为"可执行诊断"，是产品的差异化功能。当前命令识别仅能处理单行纯命令字符串，无法从正常的段落文本或代码块中提取命令，导致整个自动化链路断裂，该功能实际不可用。

**Independent Test**: 可独立测试：向命令检测工具传入包含代码块和混合文本的 KB 条目片段 → 验证工具返回正确识别的命令列表，而非空数组。

**Acceptance Scenarios**:

1. **Given** 一段包含 triple-backtick 代码块的 KB Resolution 文本，**When** 调用命令检测功能，**Then** 代码块内的命令被正确识别并返回（不返回空数组）。
2. **Given** 一段包含行内 backtick 命令的文本（如 `` `redis-cli CONFIG GET maxclients` ``），**When** 调用命令检测功能，**Then** 行内命令被正确识别。
3. **Given** 一段包含 `$` 前缀命令的文本（如 `$ systemctl restart redis`），**When** 调用命令检测功能，**Then** 命令被正确识别。
4. **Given** 一段多行混合文本（中文说明 + 命令 + 注释），**When** 调用命令检测功能，**Then** 返回的结果只包含命令行，不包含纯文字说明。

---

### User Story 3 — 知识修正工作流 (Priority: P2)

工程师发现某条 KB 条目存在错误或过时信息，提交一份修正提案（标注要替换的条目 ID）。KB 维护者（或工程师本人）确认修正提案，系统自动保存原始条目快照后，将修正内容替换为正式条目，整个流程可通过脚本/CI 自动化执行。

**Why this priority**: 修正工作流是 KB 知识治理的重要环节。当前修正提案会被误判为"重复条目"，需要两次手动确认，且无法通过管道/脚本自动化，使 CI 场景下的知识维护完全不可行。

**Independent Test**: 可独立测试：以脚本方式（`echo "y" | holmes kb confirm <correction-id>`）运行完整修正流程 → 验证流程一次性通过，原始条目被正确替换，快照被保存。

**Acceptance Scenarios**:

1. **Given** 一份带 `corrects: <entry_id>` 字段的 pending 修正提案，**When** 运行确认命令，**Then** 系统跳过重复检测步骤，直接进入预览确认。
2. **Given** 修正提案确认流程，**When** 通过管道 `echo "y" | holmes kb confirm <id>` 执行，**Then** 流程成功完成，只需一次 `y` 确认。
3. **Given** 修正成功完成，**When** 查看原条目历史，**Then** 原始版本已被保存为版本快照，修正后的内容已替换原条目。

---

### User Story 4 — CLI 命令行为可预测 (Priority: P2)

工程师按照 Holmes README 文档的指引操作 CLI，所有文档中描述的命令参数和行为与实际实现完全一致，不会因为文档过时而遇到报错，也不需要通过试错来发现真实参数名。

**Why this priority**: 文档与实现不符会直接损害用户信任，并增加上手摩擦。当前有多处明确的文档/实现不一致，工程师按文档操作直接报错。

**Independent Test**: 可独立测试：逐条按 README 文档执行相关命令，验证所有命令均按预期运行。

**Acceptance Scenarios**:

1. **Given** README 中 `resolve` 命令示例（使用 `--side A/B` 参数），**When** 工程师按文档执行，**Then** 命令正常运行（文档与实际参数一致）。
2. **Given** README 中 `lint --report <path>` 示例，**When** 工程师按文档执行，**Then** 命令正常运行（文档与实际行为一致）。
3. **Given** README 中 `skill list --entry <id>` 示例，**When** 工程师按文档执行，**Then** 命令正常运行（文档与实际参数一致）。

---

### User Story 5 — KB 条目 ID 大小写不敏感查询 (Priority: P3)

工程师在终端或 Agent session 中查询 KB 条目时，无论输入 `PT-DB-002` 还是 `pt-db-002`，均能找到该条目，不因大小写不同而返回"条目不存在"。

**Why this priority**: 工程师在实际操作中习惯小写输入，大小写敏感查询会造成不必要的查询失败，降低使用体验。

**Independent Test**: 可独立测试：对同一条目分别用大写、小写、混合大小写 ID 执行 `kb show` 命令，均应返回相同内容。

**Acceptance Scenarios**:

1. **Given** KB 中存在 ID 为 `PT-DB-002` 的条目，**When** 执行 `holmes kb show pt-db-002`，**Then** 返回该条目完整内容（而非"Entry not found"）。
2. **Given** KB 中存在 ID 为 `PT-DB-002` 的条目，**When** 执行 `holmes kb show PT-DB-002`，**Then** 返回该条目完整内容。

---

### Edge Cases

- 若 Agent 写入 pending 时内容本身已包含 `maturity` 字段（如显式指定 `maturity: verified`），应保留原有值而非强制覆盖为 `draft`。
- 命令检测功能面对仅包含注释行（`# comment`）的代码块时，应返回空列表而非将注释识别为命令。
- 修正提案确认时，若目标条目在此期间被删除，应给出明确错误提示并中止流程。
- `kb show` 大小写不敏感查询返回时，展示的条目 ID 应使用原始存储的大写格式，不因查询时小写输入而改变。

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统向待审区写入条目时，MUST 自动补充 `maturity` 字段为 `draft`（若调用方未提供）。
- **FR-002**: 待审条目经确认进入正式 KB 后，正式条目 MUST 不包含任何待审状态字段（`pending`、`pending_since`、`source`、`source_session`、`suggested_type`、`suggested_category`）。
- **FR-003**: 命令检测功能 MUST 能从 triple-backtick 代码块中识别命令行。
- **FR-004**: 命令检测功能 MUST 能从行内 backtick（`` `command` ``）和 `$` 前缀格式中识别命令行。
- **FR-005**: 带 `corrects` 字段的修正提案在执行确认流程时，MUST 跳过重复条目检测步骤（Gate 2）。
- **FR-006**: `kb show` 命令 MUST 以大小写不敏感的方式匹配条目 ID。
- **FR-007**: README 文档中描述的命令参数 MUST 与实际实现完全一致；修复方向为更新文档匹配代码（代码参数名不变）。具体涉及：`resolve --keep`（非 `--side`）、`lint --report`（flag，不接文件路径）、`skill list <entry_id>`（位置参数，非 `--entry`）。
- **FR-008**: README 中关于 `session list` 和 `session show` 命令的记录 MUST 被删除（这两个命令在当前版本中不存在，不在本次范围内实现）。

### Key Entities

- **待审条目（Pending Entry）**: 知识写入流程中的中间状态，包含完整 KB 字段加待审状态字段；确认后状态字段应被清除。
- **正式条目（KB Entry）**: 经三门验证后进入 KB 的标准知识单元，只包含标准 KB 字段。
- **修正提案（Correction Proposal）**: 特殊的待审条目，通过 `corrects` 字段关联要替换的正式条目 ID，确认流程与普通待审条目不同。
- **诊断 Skill（Diagnostic Skill）**: 与 KB 条目关联的可执行脚本，由命令检测功能从条目文本中识别并创建。

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Agent 自动提取并写入的知识，100% 能通过 `holmes kb confirm` 完成入库，不再因必需字段缺失而失败。
- **SC-002**: 经确认入库的正式条目，0 个包含待审内部字段（`pending`、`source`、`suggested_type` 等）。
- **SC-003**: 向命令检测功能传入包含 triple-backtick 代码块的典型 KB Resolution 文本，命令识别率达到 90% 以上（相比当前 0%）。
- **SC-004**: 修正工作流可通过单次 `echo "y"` 管道完成自动化确认，无需手动两次输入。
- **SC-005**: README 文档中所列的所有命令示例，100% 按文档执行成功，0 处因参数名不符而报错。
- **SC-006**: 使用全小写 ID 查询已存在的条目，成功返回条目内容（当前返回"Entry not found"）。

---

## Assumptions

- 本规约基于用户全功能实操测试报告（holmes-kb v0.1.0 + holmes-agent v2.6.0），所有问题均有明确复现路径。
- `maturity` 字段的默认值为 `draft`，这是新写入知识的合理初始状态，与现有 `holmes import` 路径行为一致。
- 命令检测功能的改进针对 KB 条目中的 Resolution 段落，假设代码块主要使用 triple-backtick 格式。
- 文档修正范围限于已确认的三处不符（`resolve --side` vs `--keep`、`lint --report <path>` vs flag、`skill list --entry` vs 位置参数），不包括全面文档审查。
- ID 大小写不敏感处理仅针对查询（`kb show`、`kb search`），存储格式保持原有大写规范不变。
- P3 级别的 `update-refs` 输出格式改进、`setup` 连通性校验、KB overview 优化等体验问题不在本次修复范围内。
