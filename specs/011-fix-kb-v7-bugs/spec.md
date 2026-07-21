# Feature Specification: 修复 Holmes KB v7 报告问题

**Feature Branch**: `011-fix-kb-v7-bugs`

**Created**: 2026-06-06

**Status**: Draft

**Input**: Holmes KB v7 usage report — 6 issues identified

## User Scenarios & Testing *(mandatory)*

### User Story 1 - detect-commands 补充过滤规则 (Priority: P1)

KB 自动化工作流调用 detect-commands 分析 Resolution 段落时，JVM 启动参数（`-Xmx4g`）、点号分隔的配置键（`session.timeout.ms`）、方法调用（`emitter.on()`）、配置块开头（`upstream backend {`）仍被误识别为命令。补充 4 条 backtick 路径过滤规则后，非 bash 技术栈的误报率应大幅降低。

**Why this priority**: detect-commands 是 skill 自动发现的核心，误报率 80% 会让 Agent 自动化工作流产生大量无效建议，直接影响 KB 质量。

**Independent Test**: 传入含 JVM 参数/配置键/方法调用/配置块的文本，detect_commands() 返回空列表或只返回真实命令

**Acceptance Scenarios**:

1. **Given** `` `-Xmx4g -Xms4g` `` 文本, **When** detect_commands(), **Then** 结果不含该条目
2. **Given** `` `session.timeout.ms` `` 文本, **When** detect_commands(), **Then** 结果不含该条目
3. **Given** `` `emitter.on()` `` 文本, **When** detect_commands(), **Then** 结果不含该条目
4. **Given** `` `upstream backend {` `` 文本, **When** detect_commands(), **Then** 结果不含该条目
5. **Given** `` `redis-cli ping` `` 文本, **When** detect_commands(), **Then** 结果包含该命令

---

### User Story 2 - amend-pending 命令 (Priority: P1)

用户提交的 pending 条目通过 write-pending 写入后，在 Gate 1 验证时失败（如缺少必填字段 maturity）。当前无法修复 pending 内容，只能 reject 后重新写入，操作繁琐且容易重复提交。新增 `holmes kb amend-pending <id>` 命令，支持直接修改 pending 内容后重新触发 Gate 1 验证。

**Why this priority**: Gate 1 失败的 pending 条目会永久积压，无法推进到 confirm 流程。这是功能缺失，而非体验问题。

**Independent Test**: 写入一条缺少 maturity 字段的 pending，Gate 1 拒绝后用 amend-pending 修复，之后 confirm 成功

**Acceptance Scenarios**:

1. **Given** pending 条目 Gate 1 失败, **When** `amend-pending <id> --content "..."`, **Then** pending 文件内容被替换，条目可重新 confirm
2. **Given** pending 条目, **When** `amend-pending <id> --file path/to/fixed.md`, **Then** 文件内容读取后替换 pending
3. **Given** 不存在的 pending id, **When** amend-pending, **Then** 友好错误提示，exit 1
4. **Given** 新内容 Gate 1 仍失败, **When** 后续 confirm, **Then** Gate 1 正常拦截（amend 不绕过验证）

---

### User Story 3 - write-pending --file 选项 (Priority: P2)

用户通过 `write-pending --content "$(cat file.md)"` 方式提交条目时，子shell + 命令替换的用法对非 bash 熟练用户不直观，且大文件内容通过命令行传入有潜在限制。新增 `--file <path>` 选项，直接读取文件内容。

**Why this priority**: 接口易用性问题，不阻断功能，但影响日常操作体验。

**Independent Test**: `write-pending --file path/to/entry.md` 与 `write-pending --content "$(cat path/to/entry.md)"` 效果完全相同

**Acceptance Scenarios**:

1. **Given** 有效 Markdown 文件, **When** `write-pending --file path/to/entry.md`, **Then** 成功写入 pending，返回 pending_id
2. **Given** 不存在的文件路径, **When** `write-pending --file noexist.md`, **Then** 错误提示，exit 1
3. **Given** 同时提供 --content 和 --file, **Then** 报错，要求只选其一
4. **Given** 既无 --content 也无 --file, **Then** 报错提示必须提供其一

---

### User Story 4 - archive-orphans --dry-run (Priority: P2)

`archive-orphans` 将无 evidence 的 draft 条目归档，操作不可撤销。用户在执行前希望预览将被归档的条目列表，与其他批量命令（reject --stale-days、decay）行为一致。

**Why this priority**: 一致性问题 + 安全网。数据归档操作不可逆，缺少预览会让谨慎用户不敢使用。

**Independent Test**: `archive-orphans --dry-run` 打印将被归档的条目 ID 列表，目录内容不变

**Acceptance Scenarios**:

1. **Given** 2 个 draft 无 evidence 条目, **When** `archive-orphans --dry-run`, **Then** 打印 2 个 ID，文件未移动
2. **Given** `archive-orphans --dry-run` 输出, **Then** 包含 `(dry run)` 标记
3. **Given** `archive-orphans`（无 --dry-run）, **Then** 行为与原来一致，实际归档

---

### User Story 5 - 单条 reject 支持 --dry-run (Priority: P2)

`holmes kb reject <pending_id>` 单条操作当前若加 `--dry-run` 会报错 `--dry-run requires --stale-days`，与批量模式不一致。单条操作虽然影响范围小，但一致的 --dry-run 行为能降低用户的心理负担。

**Why this priority**: 一致性 bug，修复成本低，消除用户困惑。

**Independent Test**: `reject <pending_id> --dry-run` 打印该条目信息但不删除文件

**Acceptance Scenarios**:

1. **Given** 存在的 pending_id, **When** `reject <id> --dry-run`, **Then** 打印该 ID，文件未删除，输出含 `(dry run)`
2. **Given** `reject <id>`（无 --dry-run）, **Then** 行为与原来一致，实际删除

---

### User Story 6 - pending 表格 CREATED 列显示兜底值 (Priority: P3)

`holmes kb pending`（无 --json）显示的表格中，CREATED 列对老格式 pending 条目显示空白，因为这些条目的 `created_at` 字段为空。由于 `list_pending()` 已经通过 `pending_since_source` 提供兜底值，表格显示也应使用同样的兜底逻辑，让用户能直观判断条目年龄。

**Why this priority**: 纯 UI 改善，不改变数据模型，改动很小。

**Independent Test**: 老格式 pending 条目在表格中 CREATED 列显示非空值（mtime 日期而非空白）

**Acceptance Scenarios**:

1. **Given** 无 created_at 字段的老格式 pending 条目, **When** `holmes kb pending`（表格模式）, **Then** CREATED 列显示 pending_since 值（非空白）
2. **Given** 有 created_at 字段的新格式条目, **Then** CREATED 列显示 created_at（原有行为不变）

---

### Edge Cases

- amend-pending 修改后内容仍然触发 Gate 2 重复检测（除非原条目已有 corrects 字段）
- write-pending --file 与 --corrects 可以组合使用
- archive-orphans --dry-run + --json 输出格式与实际执行一致
- reject --dry-run 对不存在的 pending_id 仍报错（保持与非 dry-run 一致）
- pending 表格 CREATED 列的兜底值来自 pending_since（已由 list_pending 填充），无需再次读取 mtime

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: detect_commands() 在 backtick 路径中跳过：以 `-X` 开头的内容（JVM 参数）
- **FR-002**: detect_commands() 在 backtick 路径中跳过：匹配 `\w+\.\w+` 且不含空格的内容（配置键）
- **FR-003**: detect_commands() 在 backtick 路径中跳过：以字母开头且包含 `(` 的内容（方法调用）
- **FR-004**: detect_commands() 在 backtick 路径中跳过：以 `{` 结尾的内容（配置块开头）
- **FR-005**: 新增 `holmes kb amend-pending <id>` 命令，支持 `--content` 和 `--file` 两种输入
- **FR-006**: amend-pending 替换 pending 文件内容后，保留原有 pending 元数据（id、pending_since、source 等）
- **FR-007**: `write-pending` 新增 `--file <path>` 选项，读取文件内容后等价于 `--content`
- **FR-008**: `write-pending` 的 `--content` 和 `--file` 互斥，两者同时提供时报错
- **FR-009**: `archive-orphans` 新增 `--dry-run` 选项，打印将被归档的 ID 列表不执行归档
- **FR-010**: `reject` 命令的 `--dry-run` 在单条模式（提供 pending_id 时）同样有效，不报错
- **FR-011**: `holmes kb pending`（表格模式）CREATED 列使用 `pending_since` 字段值显示，非空

### Key Entities

- **PendingEntry**: amend-pending 替换 `content` 但保留 `pending` 相关元字段
- **CommandCandidate**: detect_commands 过滤逻辑增加 4 个 backtick 模式规则

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: detect_commands() 对 JVM/配置键/方法调用/配置块等场景的误报率降至 0%（4 类各有对应过滤规则）
- **SC-002**: 通过 amend-pending 修复 Gate 1 失败条目的操作步骤数 ≤ 2（amend + confirm）
- **SC-003**: write-pending --file 与 --content 路径在功能上 100% 等价
- **SC-004**: archive-orphans --dry-run 不移动任何文件（100% 安全预览）
- **SC-005**: reject --dry-run 在单条和批量模式下行为一致
- **SC-006**: pending 表格 CREATED 列对 100% 条目非空
- **SC-007**: 367 个现有测试全部继续通过，新增测试覆盖所有 6 个用户故事

## Assumptions

- amend-pending 保留原有 pending_since / id / source 等元字段，只替换用户内容部分
- FR-002 的配置键过滤使用正则 `^\w[\w.]*\w$`（全匹配无空格），不含 `-` 的点号分隔形式
- FR-003 方法调用过滤：以字母开头 + 含 `(`，覆盖 `emitter.on()`、`emitter.setMaxListeners(20)` 等形态
- pending 表格 CREATED 列目前显示 created_at，修改后显示 pending_since（已由 list_pending 兜底填充）
- --dry-run 统一约定：打印操作摘要 + `(dry run)` 标记，exit 0
