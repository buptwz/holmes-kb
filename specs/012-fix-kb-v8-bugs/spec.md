# Feature Specification: 修复 Holmes KB v8 报告问题

**Feature Branch**: `012-fix-kb-v8-bugs`

**Created**: 2026-06-07

**Status**: Draft

**Input**: Holmes KB v8 usage report — 7 issues identified

## User Scenarios & Testing *(mandatory)*

### User Story 1 - amend-pending 自动注入 updated_at (Priority: P1)

用户用 `amend-pending` 修复 Gate 1 失败的 pending 条目内容后，执行 `confirm` 仍报 `Missing required field: 'updated_at'`。需要在 `amend-pending` 写回时自动注入 `updated_at`，并保留原有 `created_at`。

**Why this priority**: amend-pending 是 v7 新增的核心功能，若 confirm 仍然失败则等同于未修复。

**Independent Test**: 用 amend-pending 修复内容后，confirm 能通过 Gate 1

**Acceptance Scenarios**:

1. **Given** pending 条目缺少 maturity，**When** amend-pending 修复后执行 confirm，**Then** Gate 1 不再报 `Missing required field: 'updated_at'`
2. **Given** amend-pending 写回的文件，**Then** `updated_at` 字段存在且为当前时间
3. **Given** 原始 pending 有 `created_at`，**When** amend-pending，**Then** `created_at` 被保留
4. **Given** 原始 pending 无 `created_at`，**When** amend-pending，**Then** 不因缺少 `created_at` 报错

---

### User Story 2 - detect-commands 代码块语言过滤 (Priority: P1)

`detect_commands()` 提取所有语言标签的代码块内容，导致 nginx 配置块中的指令被误识别为 shell 命令。只有 bash/sh/shell/zsh/（无标签）代码块应被提取，其他语言块应直接跳过。

**Why this priority**: 代码块误报是 v8 中唯一未修复的误报路径，影响 skill 自动发现质量。

**Independent Test**: 含 nginx 代码块的文本传入 detect_commands()，返回空列表

**Acceptance Scenarios**:

1. **Given** `` ```nginx `` 代码块含配置指令，**When** detect_commands()，**Then** 不返回任何条目
2. **Given** `` ```bash `` 代码块含 shell 命令，**When** detect_commands()，**Then** 正常提取命令
3. **Given** 无语言标签的代码块含 shell 命令，**When** detect_commands()，**Then** 正常提取命令
4. **Given** `` ```python `` / `` ```yaml `` 代码块，**Then** 均被跳过
5. **Given** `` ```shell `` / `` ```zsh `` 代码块含命令，**Then** 正常提取

---

### User Story 3 - write-pending 基础校验 (Priority: P2)

用户提交无 frontmatter（无 `---` 块）的内容时，`write-pending` 成功创建 pending 条目，但 `confirm` 时报出多条错误。应在写入时拒绝无 frontmatter 内容并给出提示。

**Why this priority**: 提前拦截无效输入，减少用户困惑和无效 pending 积压。

**Independent Test**: `write-pending --content "no frontmatter"` 返回错误信息，exit 1

**Acceptance Scenarios**:

1. **Given** `--content ""` 空内容，**When** write-pending，**Then** 错误提示 + exit 1
2. **Given** `--content "plain text without frontmatter"`，**When** write-pending，**Then** 错误提示 + exit 1
3. **Given** 有效 frontmatter 内容，**When** write-pending，**Then** 正常写入（原有行为不变）
4. **Given** `--file` 指向无 frontmatter 文件，**When** write-pending，**Then** 错误提示 + exit 1

---

### User Story 4 - Gate 3 长条目强制 yes 确认 (Priority: P2)

当 pending 内容超过 800 字符时，Gate 3 仍使用 `[Y/n]` 默认确认，用户可直接按 Enter 跳过审核。改为要求输入 `yes` 才能通过，强制有意识操作。

**Why this priority**: Gate 3 是质量关卡，长条目的默认确认使关卡形同虚设。

**Independent Test**: 长条目 confirm 时，直接按 Enter 或输入 `y` 不能确认，输入 `yes` 才通过

**Acceptance Scenarios**:

1. **Given** 内容 >800 字符的 pending 条目，**When** confirm，**Then** 提示说明需输入 `yes`
2. **Given** 用户输入 `y` 或直接 Enter，**Then** 不通过（中止或重新提示）
3. **Given** 用户输入 `yes`，**Then** 条目成功确认
4. **Given** 内容 ≤800 字符的 pending 条目，**When** confirm，**Then** 行为与原来一致（`[Y/n]` 默认）

---

### User Story 5 - resolve 后自动重建 index (Priority: P2)

`resolve` 成功后被恢复的 entry 在 `list` 和 `search` 中不可见，因为 index 未更新。需要在 resolve 结束时自动重建 index。

**Why this priority**: resolve 后 entry 不可搜索，影响工作流连贯性。

**Independent Test**: resolve 后立即执行 `list`，被恢复的 entry 可见

**Acceptance Scenarios**:

1. **Given** resolve 成功，**When** 立即执行 `list`，**Then** 被恢复的 entry 出现在列表中
2. **Given** resolve 成功，**Then** 输出包含 index 已重建的提示
3. **Given** resolve 命令，**Then** exit 码行为与原来一致

---

### User Story 6 - list --maturity 过滤 (Priority: P2)

`list` 不支持按成熟度过滤，运营者需要手动 JSON 过滤才能找到 draft 或 proven 条目。新增 `--maturity` 选项，与现有 `--type` 过滤保持一致。

**Why this priority**: maturity 是 KB 的核心概念，过滤能力缺失是功能性缺口。

**Independent Test**: `list --maturity draft` 只返回 maturity 为 draft 的条目

**Acceptance Scenarios**:

1. **Given** KB 含混合成熟度条目，**When** `list --maturity draft`，**Then** 只返回 draft 条目
2. **Given** `list --maturity proven`，**Then** 只返回 proven 条目
3. **Given** `list --maturity` 与 `--type` 组合，**Then** 两个过滤条件同时生效
4. **Given** `list --json --maturity draft`，**Then** JSON 输出也只含 draft 条目
5. **Given** `list --maturity invalid_xyz`，**Then** 警告无效值，返回空列表，exit 0

---

### User Story 7 - history 命令 exit 码 (Priority: P3)

`history NONEXISTENT` exit 0 与其他命令的「未找到」exit 1 不一致。脚本无法通过 exit 码区分「找到结果」和「未找到」。

**Why this priority**: exit 码一致性问题，修复成本低，提升脚本可靠性。

**Independent Test**: `history NONEXISTENT` 返回 exit 1

**Acceptance Scenarios**:

1. **Given** 不存在的 entry ID，**When** `history NONEXISTENT`，**Then** exit 1
2. **Given** 存在快照的 entry，**When** `history PT-APP-002`，**Then** exit 0
3. **Given** `history <id> --show NONEXISTENT.md`，**Then** exit 1
4. **Given** `history <id> --show VALID.md`，**Then** exit 0

---

### Edge Cases

- write-pending 校验只检测 frontmatter 存在（`---` 块），不校验字段完整性（Gate 1 负责）
- Gate 3 强制 yes 仅当内容 >800 字符时生效；≤800 字符保持 `[Y/n]` 默认
- resolve 重建 index：仅重建 index 文件，不改变 entry 内容
- list --maturity 无效值：警告后返回空列表，exit 0（与 --type 无效值行为一致）
- history exit 1：`history` 无参数时保持原有 usage 提示行为

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `amend-pending` 写回时自动设置 `updated_at` 为当前 UTC 时间
- **FR-002**: `amend-pending` 写回时保留原始 `created_at`（若存在）
- **FR-003**: `detect_commands()` 代码块提取只处理语言标签为 bash/sh/shell/zsh/（空）的块
- **FR-004**: `write-pending` 校验内容包含 frontmatter（含 `---` 分隔符），否则 exit 1
- **FR-005**: `confirm` Gate 3：内容 >800 字符时，改为要求输入 `yes` 的显式确认
- **FR-006**: `resolve` 命令结束时自动调用 index 重建并输出提示
- **FR-007**: `list` 命令新增 `--maturity` 选项，过滤返回结果
- **FR-008**: `list --maturity <invalid>` 输出警告，返回空列表，exit 0
- **FR-009**: `history <nonexistent_id>` 返回 exit 1
- **FR-010**: `history <id> --show <nonexistent_snapshot>` 返回 exit 1

### Key Entities

- **PendingEntry**: amend-pending 现在系统注入 `updated_at`/`created_at`
- **CommandCandidate**: 代码块提取增加语言标签白名单过滤
- **EntryListFilter**: list 命令新增 maturity 维度过滤

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: amend-pending 后执行 confirm，Gate 1 通过率 100%（不再报 updated_at 缺失）
- **SC-002**: detect_commands() 对非 shell 代码块的误报率降至 0%
- **SC-003**: write-pending 对无 frontmatter 内容的拦截率 100%
- **SC-004**: Gate 3 长条目确认需要显式 `yes` 输入，单字符响应不通过
- **SC-005**: resolve 后 list 命令立即返回被恢复的 entry
- **SC-006**: list --maturity 过滤准确率 100%
- **SC-007**: history 对不存在场景返回 exit 1（与 show 命令一致）
- **SC-008**: 387 个现有测试全部继续通过，新增测试覆盖所有 7 个用户故事

## Assumptions

- FR-004 frontmatter 检测：检查内容是否以 `---` 开头（去除首尾空白后），使用简单字符串检查
- FR-003 语言标签白名单：`{"", "bash", "sh", "shell", "zsh"}`，小写匹配
- FR-005 强制 yes：使用 `click.prompt` 替换 `click.confirm`，接受 `yes`（大小写不敏感）
- FR-006 resolve 重建：调用现有 `rebuild_index_files(kb_root)` 函数，输出「Index rebuilt」提示
- list --maturity 与 --type 可以同时使用（AND 逻辑）
