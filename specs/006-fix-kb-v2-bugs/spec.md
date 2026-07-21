# Feature Specification: 修复 Holmes KB v2 报告缺陷

**Feature Branch**: `006-fix-kb-v2-bugs`

**Created**: 2026-06-06

**Status**: Draft

**Input**: User description: "修复 Holmes KB v2 报告中的四个新缺陷：(1) 纠错路径 confirm 后残留 pending 内部字段污染正式条目；(2) lint conflict_count 统计含已解决冲突导致计数虚高；(3) skill run --json 模式始终退出 0 不传播实际 exit code；(4) detect_commands 提取 SQL 语句作为 shell 命令"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 纠错路径内部字段清理 (Priority: P1)

运维工程师通过 `holmes kb confirm` 确认一个纠错提案（含 `corrects` 字段的 pending 条目）。确认后查看正式条目时，不应看到任何 pending 生命周期字段（`pending`, `pending_since`, `source`, `source_session`, `suggested_type`, `suggested_category`）。

**Why this priority**: 纠错工作流是 KB 质量保障的核心路径。字段残留导致条目语义错误（`pending: true` 出现在已发布条目中），并且可能误导下游 Agent 解析条目时读到错误的 `source: auto` 信息。P1 因其直接影响数据正确性。

**Independent Test**: 执行 `echo "y" | holmes kb confirm <correction-pending-id>` 后，`holmes kb show <corrected-id>` 的输出中不含 `pending`、`pending_since`、`source`、`source_session`、`suggested_type`、`suggested_category` 任何字段。

**Acceptance Scenarios**:

1. **Given** 一个含 `corrects: PT-DB-001` 的 pending 条目，**When** 用户 confirm 该条目，**Then** 被替换的正式条目不含任何 pending 内部字段。
2. **Given** 正式条目已写入，**When** 通过 `holmes kb show` 查看，**Then** frontmatter 中不出现 `pending: true` 或 `source: auto`。
3. **Given** 正常路径（无 corrects）的 pending 条目，**When** confirm，**Then** 行为不变（回归：普通路径仍正确清理字段）。

---

### User Story 2 — lint conflict_count 准确计数 (Priority: P2)

运维工程师运行 `holmes kb lint` 检查 KB 健康状态。已通过 `holmes kb resolve` 解决的冲突不应再计入 `Conflicts` 统计，只有 `status: pending_review` 的冲突才计数。

**Why this priority**: 虚高的冲突计数导致运维人员误判系统状态，在 CI/CD 监控集成（`lint --report`）中会触发误报告警。P2 因其影响可观测性准确性。

**Independent Test**: 执行 `holmes kb resolve <conflict-id> --keep B` 后，`holmes kb lint` 输出的 `Conflicts` 计数减少 1。

**Acceptance Scenarios**:

1. **Given** 存在 2 个冲突（1 个已解决，1 个待处理），**When** 运行 `holmes kb lint`，**Then** `Conflicts: 1`（不是 2）。
2. **Given** `holmes kb lint --report` 的 JSON 输出，**When** 所有冲突均已解决，**Then** `conflict_count: 0`。
3. **Given** 冲突目录为空，**When** 运行 lint，**Then** `Conflicts: 0`。

---

### User Story 3 — skill run 退出码一致性 (Priority: P2)

Agent 或脚本通过 `holmes kb skill run <name> --json` 执行 skill 后，使用 `$?` 检查执行是否成功。skill 脚本失败时，CLI 应返回非零退出码，无论是否使用 `--json` 模式。

**Why this priority**: Agent 依赖 `$?` 判断 skill 是否成功执行。当前 `--json` 模式始终返回 0，Agent 必须额外解析 JSON 中的 `exit_code` 字段，增加集成复杂度，且在 bash pipeline 中行为不可预测。P2 因其影响 Agent 集成质量。

**Independent Test**: 执行一个会失败的 skill（`exit 1` 的脚本），`echo $?` 在 `--json` 和非 `--json` 模式下均返回非零值。

**Acceptance Scenarios**:

1. **Given** 一个脚本以 exit code 1 退出的 skill，**When** 运行 `holmes kb skill run <name> --json`，**Then** CLI 退出码为 1。
2. **Given** 一个成功执行的 skill，**When** 运行 `holmes kb skill run <name> --json`，**Then** CLI 退出码为 0，JSON 输出完整。
3. **Given** `--json` 模式下 skill 失败，**When** 检查 CLI 退出码，**Then** 退出码与 JSON 中的 `exit_code` 字段值一致。

---

### User Story 4 — detect_commands SQL 关键字过滤 (Priority: P3)

Agent 使用 `detect-commands` 从 KB 条目的 Resolution 文本中提取可执行命令，随后自动调用 `skill auto-create` 创建 skill。SQL 语句（`SELECT`, `SHOW`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER` 等开头的行）不应被识别为 shell 命令。

**Why this priority**: SQL 写入 run.sh 后脚本无法执行，但失败只在 `skill run` 时才暴露，对 Agent 透明度低。P3 因为发生场景较特定（需要 SQL 内容在代码块中），但影响 Agent 自动化工作流完整性。

**Independent Test**: 向 `detect-commands` 传入含 SQL 的代码块（如 `SHOW SLAVE STATUS\G`），返回结果不包含该 SQL 行。

**Acceptance Scenarios**:

1. **Given** 含 `SHOW SLAVE STATUS\G` 的代码块，**When** 调用 `detect-commands`，**Then** 返回列表中不包含该行。
2. **Given** 同一代码块中混合了 shell 命令（`mysqladmin stop-slave`）和 SQL，**When** 调用 `detect-commands`，**Then** shell 命令被返回，SQL 被过滤。
3. **Given** 纯 shell 内容的代码块，**When** 调用 `detect-commands`，**Then** 所有命令均被正常返回（无误过滤）。

---

### Edge Cases

- 纠错路径中，`post.metadata` 如果本来就不含某个 pending 字段（如旧格式条目），清理操作应静默跳过（不报错）。
- `contributions/conflicts/` 目录中存在格式损坏的 JSON 文件，lint 统计时应跳过该文件而不是报错。
- `skill run` 中 skill 脚本被信号终止（SIGTERM 等），退出码为负数或 128+N，CLI 应原样传播该码。
- `detect_commands` 中，SQL 关键字匹配应大小写不敏感（`show`, `SHOW`, `Show` 均过滤）。
- 代码块中首行是 SQL、次行是 shell 命令，两者应分别正确处理。

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 纠错路径 `confirm` 在写入最终条目前，MUST 清除所有 pending 内部字段（`pending`, `pending_since`, `source`, `source_session`, `suggested_type`, `suggested_category`）。
- **FR-002**: `lint` 的 `conflict_count` MUST 只统计 `status == "pending_review"` 的冲突文件，已解决的冲突（其他 status）不计入。
- **FR-003**: `skill run` 命令 MUST 在 `--json` 模式下，于输出 JSON 后将 skill 脚本的实际退出码传播给 CLI 调用方（`sys.exit(result.exit_code)`）。
- **FR-004**: `detect_commands`（含代码块提取路径）MUST 过滤以 SQL DML/DDL 关键字开头的行，不将其作为候选命令返回。
- **FR-005**: 上述所有修复 MUST 有对应自动化测试覆盖，确保回归安全。
- **FR-006**: SQL 关键字过滤 MUST 大小写不敏感。
- **FR-007**: `lint` 在遇到格式损坏的冲突 JSON 文件时 MUST 跳过该文件而不中断统计。

### Key Entities

- **PendingEntry 内部字段集合**: `{pending, pending_since, source, source_session, suggested_type, suggested_category}` — 仅在 pending 生命周期存在的字段，进入正式 KB 后必须清除。
- **ConflictRecord**: `contributions/conflicts/<id>.json` 中含 `status` 字段（`pending_review` | `resolved` | 其他）的冲突记录。
- **CommandCandidate**: `detect_commands()` 返回的候选命令对象，含 `line`（命令行文本）和 `suggested_name`。
- **SQL 关键字黑名单**: `SELECT, SHOW, INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, REPLACE, DESCRIBE, EXPLAIN`（大小写不敏感）。

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 纠错 confirm 后，正式条目中 pending 内部字段数为 0（可通过 `holmes kb show` 验证）。
- **SC-002**: `holmes kb lint` 的 `conflict_count` 与实际未解决冲突数一致，误差为 0。
- **SC-003**: `skill run --json` 失败时，CLI 退出码与 JSON `exit_code` 字段值 100% 一致。
- **SC-004**: `detect_commands` 对 SQL 关键字开头行的误识别率为 0%（不产生误报命令）。
- **SC-005**: 已有 280 个测试全部继续通过（无回归），新增测试覆盖 4 个修复点，每个修复点至少 2 个测试用例。

---

## Assumptions

- 目标受众为运维工程师和 Agent 自动化流程，修复不引入新的用户可见交互。
- SQL 关键字黑名单范围：DML（SELECT/INSERT/UPDATE/DELETE/REPLACE）+ DDL（CREATE/DROP/ALTER/TRUNCATE）+ 查询类（SHOW/DESCRIBE/EXPLAIN），共 12 个关键字。
- `skill run --json` 模式下的退出码改变向后兼容：之前始终返回 0 的行为是 bug 而非特性，无需版本兼容层。
- `lint` 的 conflict_count 修复仅影响计数逻辑，不修改冲突文件内容或格式。
- 本特性不涉及 `holmes-agent`（TypeScript）侧的任何改动，仅修改 Python KB 包。

---

## Clarifications

### Session 2026-06-06

- Q: `skill run --json` 退出码行为改变是否需要文档说明？→ A: 行为统一为"传播实际退出码"，无需额外文档，只需修复 bug 并更新测试。
- Q: SQL 关键字过滤适用于 `CMD_PATTERN` 路径还是仅 `_extract_code_block_lines` 路径？→ A: 仅适用于代码块路径（`_extract_code_block_lines`），因为 `CMD_PATTERN` 已要求 `$` 前缀或已知工具名，SQL 不满足。
