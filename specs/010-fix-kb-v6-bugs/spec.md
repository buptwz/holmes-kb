# Feature Specification: 修复 Holmes KB v6 报告问题

**Feature Branch**: `010-fix-kb-v6-bugs`

**Created**: 2026-06-06

**Status**: Draft

**Input**: Holmes KB v6 usage report — 5 issues identified

## User Scenarios & Testing *(mandatory)*

### User Story 1 - auto-create 注释语法修正 (Priority: P1)

用户运行 `holmes kb skill auto-create --cmd "psql -h {HOST}"` 后，阅读生成的 run.sh 注释，看到 `{{placeholder}}` 双花括号示例，按照注释操作使用双花括号，结果生成损坏的脚本变量赋值。修复后注释应与实现保持一致，使用单花括号。

**Why this priority**: 误导性文档直接造成用户伤害——用户读了注释、照着做、脚本损坏。一行字符串修改即可根治。

**Independent Test**: `auto_create_skill()` 生成的 run.sh 注释中无 `{{placeholder}}`，只有 `{placeholder}`

**Acceptance Scenarios**:

1. **Given** 用户运行 `auto-create --cmd "psql -h {HOST}"`, **When** 查看 run.sh, **Then** 注释示例使用单花括号 `{HOST}` 而非 `{{HOST}}`
2. **Given** run.sh 注释, **When** 用户按注释新建 `auto-create --cmd "psql -h {{HOST}}"`, **Then** 生成的脚本损坏（边界条件：用户误用双花括号仍不是我们能保护的范围）

---

### User Story 2 - reject --stale-days 加 --dry-run (Priority: P1)

运维用户在批量清理 pending 前希望先预览将要删除的条目，再确认执行，防止误传参数（如 `--stale-days 0`）导致无法撤销的大批量删除。

**Why this priority**: 批量删除无确认机制，`--stale-days 0` 会清空所有有时间戳的 pending 条目，数据无法恢复。

**Independent Test**: `holmes kb reject --stale-days 3 --dry-run` 打印将要删除的条目列表但不删除任何文件

**Acceptance Scenarios**:

1. **Given** 3 条超期 pending 条目, **When** `reject --stale-days 1 --dry-run`, **Then** 打印 3 条 ID 列表，pending 目录下文件数不变
2. **Given** `reject --stale-days 1 --dry-run` 输出, **Then** 输出包含 `(dry run)` 标记
3. **Given** `reject --stale-days 1`（不带 `--dry-run`）, **Then** 行为与原来一致，直接删除

---

### User Story 3 - detect-commands 文档约束 (Priority: P2)

KB 维护者需要知道 `detect-commands` 的正确使用方式：只传 `## Resolution` 段落内容，而非整条条目，以避免单词标识符（表名、配置项名）被误识别为命令。

**Why this priority**: 文档变更零代码成本，根治误报的最低成本方案。单词标识符无法通过负向过滤排除，只能通过输入范围约束解决。

**Independent Test**: CLAUDE.md agent context 包含关于 detect-commands 输入范围的明确说明

**Acceptance Scenarios**:

1. **Given** CLAUDE.md, **When** 查看 detect-commands 相关说明, **Then** 明确指出只应传入 Resolution 段落内容
2. **Given** 误报示例 `pg_stat_activity`, **When** 只传 Resolution 段落, **Then** 该标识符不出现在输出中（因为 Resolution 段落通常只有命令行）

---

### User Story 4 - --type 无效值警告 (Priority: P2)

用户在 `search` 或 `list` 命令中拼错 `--type` 参数（如 `pitfal` 而非 `pitfall`）时，当前静默返回空列表，用户无法区分"该类型下无结果"和"类型名拼错了"。修复后应输出警告并列出有效类型。

**Why this priority**: 静默空结果会让用户误以为 KB 没有相关条目，而实际上只是类型名拼错了。

**Independent Test**: `search "timeout" --type invalid_type` 在返回空列表的同时输出警告和有效类型列表

**Acceptance Scenarios**:

1. **Given** KB 中有 pitfall 条目, **When** `search "timeout" --type pitfal`, **Then** 输出 warning 包含有效类型且返回空列表（非报错退出）
2. **Given** `list --type invalid_type`, **Then** 同样输出 warning 包含有效类型
3. **Given** `search "timeout" --type pitfall`（正确类型）, **Then** 无 warning，正常返回结果
4. **Given** `--json` 模式 + 无效 type, **Then** 警告输出到 stderr，stdout 仍为合法 JSON `[]`

---

### User Story 5 - pending_since_source 字段 (Priority: P3)

自动化脚本使用 `holmes kb pending --json` 时，需要知道 `pending_since` 是真实记录的时间戳还是 mtime 兜底值，以便在 git clone 场景下正确处理（mtime 在克隆时被重置，不可靠）。

**Why this priority**: 只影响高级自动化场景，不影响日常操作，但增加了自动化工具的可观测性。

**Independent Test**: `list_pending()` 返回的每条记录包含 `pending_since_source: "field"` 或 `"mtime"` 或 `"created_at"`

**Acceptance Scenarios**:

1. **Given** 有真实 `pending_since` 字段的条目, **When** `list_pending()`, **Then** `pending_since_source == "field"`
2. **Given** 无 `pending_since` 但有 `created_at` 的条目, **When** `list_pending()`, **Then** `pending_since_source == "created_at"`
3. **Given** 两者均无的条目, **When** `list_pending()`, **Then** `pending_since_source == "mtime"`

---

### Edge Cases

- `reject --stale-days 0 --dry-run`：显示所有有时间戳的条目（不删除）
- `--type` 警告：KB 为空时无有效类型可列，输出通用提示
- `--type` 警告在 `--json` 模式下：警告走 stderr，不污染 JSON 输出
- `pending_since_source` 字段在现有 pending 条目上向后兼容

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: auto-create 生成的 run.sh 注释中 `{placeholder}` 示例必须使用单花括号，与实现一致
- **FR-002**: `reject --stale-days N` 必须支持 `--dry-run` 选项，打印待删条目 ID 但不执行删除
- **FR-003**: `--dry-run` 输出必须包含 `(dry run)` 标记，明确告知用户未实际删除
- **FR-004**: CLAUDE.md agent context 必须包含 detect-commands 只传 Resolution 段落的说明
- **FR-005**: `search --type <invalid>` 必须向用户输出警告，列出有效类型，且以非零退出码以外的方式处理（返回空结果，警告到 stderr）
- **FR-006**: `list --type <invalid>` 必须与 search 行为一致：警告 + 空结果
- **FR-007**: `list_pending()` 返回的每条记录必须包含 `pending_since_source` 字段，值为 `"field"` / `"created_at"` / `"mtime"`

### Key Entities

- **PendingEntry**: 新增 `pending_since_source` 属性，标识 `pending_since` 的来源
- **ValidKbTypes**: 已知有效 KB 类型集合，用于 `--type` 参数校验

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: auto-create 生成的所有 run.sh 注释中不含 `{{placeholder}}` 双花括号
- **SC-002**: `reject --stale-days N --dry-run` 执行后 pending 目录文件数不变
- **SC-003**: 对 100% 的无效 `--type` 输入，`search` 和 `list` 均输出可见警告
- **SC-004**: `list_pending()` 所有返回条目包含 `pending_since_source` 字段，且值仅为三个合法值之一
- **SC-005**: 354 个现有测试全部继续通过，新增测试覆盖所有 5 个用户故事

## Assumptions

- 有效 KB 类型从 KB 根目录的子目录名推断（pitfall, model, runbook 等），不硬编码
- `--dry-run` 不需要交互式 `y/N` 确认；作为独立标志足够
- detect-commands 文档约束只修改 CLAUDE.md（项目级 agent context），不修改代码
- `pending_since_source` 字段只在 `list_pending()` 返回的内存字典中，不持久化写入磁盘
- `--type` 警告在 `--json` 模式下输出到 stderr 以保持 JSON stdout 合法
