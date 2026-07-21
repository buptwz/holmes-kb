# Feature Specification: 修复 Holmes KB v4 报告问题

**Feature Branch**: `008-fix-kb-v4-bugs`

**Created**: 2026-06-06

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - merge 命令 exit 码修正 (Priority: P1)

用户执行 `holmes kb merge` 后，KB 中的 git 冲突被成功隔离到 `contributions/conflicts/`，但命令返回 exit code 1。用户（或 CI 脚本）看到非零退出码，误以为操作失败，触发告警或错误处理流程。

**Why this priority**: exit 码是 CLI 工具与自动化脚本通信的核心契约，错误的 exit 码直接导致误报，影响 CI/CD 集成。

**Independent Test**: 制造一个 git 冲突并执行 `holmes kb merge`，`echo $?` 输出 0；输出中包含引导用户解决隔离冲突的 next-step 提示。

**Acceptance Scenarios**:

1. **Given** KB 中存在无法自动解决的冲突，**When** 执行 `holmes kb merge`，**Then** 命令退出码为 0，输出中包含 `holmes kb resolve` 的提示
2. **Given** 所有冲突均可自动解决，**When** 执行 `holmes kb merge`，**Then** 命令退出码为 0
3. **Given** 没有任何冲突，**When** 执行 `holmes kb merge`，**Then** 命令退出码为 0

---

### User Story 2 - Gate 3 预览剥离内部字段 (Priority: P1)

用户在 `holmes kb confirm` 的 Gate 3 预览阶段看到 `pending: true`、`source: auto`、`suggested_type: pitfall` 等内部系统字段，这些字段不会写入正式 KB 条目，但出现在预览中干扰用户对实际知识内容的审核判断。

**Why this priority**: Gate 3 的核心价值是让用户审核"即将写入 KB 的内容"，展示内部字段违背了这个设计意图。

**Independent Test**: 执行 `holmes kb confirm <id>` 到 Gate 3，预览中不出现 `pending`、`pending_since`、`source`、`source_session`、`suggested_type`、`suggested_category` 字段。

**Acceptance Scenarios**:

1. **Given** pending 条目含内部字段，**When** Gate 3 展示预览（短条目），**Then** 预览内容不含任何内部字段
2. **Given** 短条目内容不含内部字段，**When** 用户审核，**Then** 用户能准确判断最终入库内容
3. **Given** 长条目触发 --show 提示路径，**When** Gate 3 显示提示，**Then** 提示内容不受影响

---

### User Story 3 - pending_since 字段暴露 (Priority: P1)

用户执行 `holmes kb pending --json` 或通过自动化脚本获取 pending 列表时，返回数据中没有 `pending_since` 字段——这是 pending 条目入队时间的可靠记录，而 `created_at` 往往为空。用户无法基于入队时间实现老化过滤或批量清理。

**Why this priority**: `pending_since` 是自动化 pending 管理的基础字段，缺失会阻断批量清理等关键运营场景。

**Independent Test**: 执行 `holmes kb pending --json`，每个条目包含非空的 `pending_since` 字段。

**Acceptance Scenarios**:

1. **Given** pending 条目在入队时记录了 `pending_since`，**When** 执行 `holmes kb pending --json`，**Then** 每条记录包含 `pending_since` 字段且值非空
2. **Given** pending 条目没有 `pending_since` 字段（老数据），**When** 列表查询，**Then** 该字段显示为空字符串或 null（不崩溃）
3. **Given** 非 JSON 模式的列表，**When** 正常显示，**Then** 已有列表格式不变（向后兼容）

---

### User Story 4 - detect-commands fallback 路径过滤 (Priority: P1)

用户对整个 KB 条目内容执行 `detect-commands` 时，`CMD_PATTERN` fallback 路径（匹配 `$ command`、backtick 和已知 CLI 工具）将 YAML frontmatter 字段（如 `category: database`）和错误消息文本（如 `FATAL: remaining connection slots`）误识别为 shell 命令，产生大量噪声结果。

**Why this priority**: 误报直接影响 Agent 基于 `detect-commands` 构建的 skill，导致生成无效的 `run.sh`，P1 功能可用性问题。

**Independent Test**: 对含 YAML frontmatter 和错误消息文本的 KB 条目内容执行 `detect-commands`，`WHERE state = 'idle'`、`category: database`、`FATAL: remaining connection slots` 均不出现在结果中。

**Acceptance Scenarios**:

1. **Given** 文本含 YAML frontmatter（`key: value` 格式），**When** `detect-commands` 分析，**Then** frontmatter 行不出现在结果中
2. **Given** 文本含 SQL 片段（非代码块，backtick 模式匹配），**When** `detect-commands` 分析，**Then** SQL 语句不出现在结果中
3. **Given** 文本含真正的 shell 命令（`$ redis-cli info`、backtick 命令），**When** `detect-commands` 分析，**Then** 命令正常返回，无误过滤

---

### User Story 5 - show 命令 evidence 汇总 (Priority: P2)

用户执行 `holmes kb show PT-DB-005` 时，看到 `evidence: []`，但该条目 maturity 是 `proven`，用户不理解为什么证据为空但已达到最高 maturity。实际证据存储在 sidecar 文件中，`show` 命令没有读取。

**Why this priority**: 造成用户对 KB 数据正确性的质疑，降低信任度，但不阻断功能，因此 P2。

**Independent Test**: 对有 sidecar evidence 的条目执行 `holmes kb show <id> --with-evidence`，输出中显示 evidence 汇总（session 数量、贡献者、最近日期）。

**Acceptance Scenarios**:

1. **Given** 条目有 sidecar evidence 文件，**When** 执行 `holmes kb show <id> --with-evidence`，**Then** 输出显示 evidence 汇总行（条目数、贡献者列表、最近时间）
2. **Given** 条目没有 sidecar evidence，**When** 执行 `--with-evidence`，**Then** 输出 `Evidence: none`，不报错
3. **Given** 不传 `--with-evidence`，**When** 执行普通 `show`，**Then** 行为与之前完全一致（向后兼容）

---

### User Story 6 - history --show 选项 (Priority: P2)

用户执行 `holmes kb history PT-APP-001` 看到快照列表，想对比纠错前后的内容，但没有命令可以直接查看快照文件内容，必须手动找到快照文件路径然后 `cat`，路径在系统内部不透明。

**Why this priority**: 版本历史功能的核心价值是允许用户审计变更，没有查看能力使历史功能价值大打折扣，P2。

**Independent Test**: 执行 `holmes kb history <id> --show <snapshot-name>`，终端输出该快照的完整内容。

**Acceptance Scenarios**:

1. **Given** 条目有历史快照，**When** 执行 `history <id> --show <snapshot-name>`，**Then** 终端输出快照的完整 Markdown 内容
2. **Given** 快照名不存在，**When** 执行 `--show`，**Then** 输出明确错误信息，不崩溃
3. **Given** 不传 `--show`，**When** 执行 `history <id>`，**Then** 展示快照列表（原有行为不变）

---

### User Story 7 - import --dry-run 无参数提示 (Priority: P2)

用户在无 API Key 环境执行 `holmes import <file> --dry-run`（不带 `--type/--category/--title` 等参数），看到原始文件内容输出，frontmatter 为空，不知道 LLM 会如何分类该文件，也不知道应该怎么办。

**Why this priority**: UX 改善，不影响功能正确性，P2。

**Independent Test**: 执行 `holmes import <file> --dry-run`（不带额外参数），输出中包含 `LLM not configured` 或 `Use --type/--category/--title` 的提示信息。

**Acceptance Scenarios**:

1. **Given** 无 API Key 且不带分类参数，**When** 执行 `--dry-run`，**Then** 输出提示：LLM 未配置，建议用 `--type/--category/--title/--tags` 手动指定参数
2. **Given** 带了 `--type` 参数，**When** 执行 `--dry-run`，**Then** 正常展示预览，不显示该提示（不误报）
3. **Given** 有 API Key，**When** 执行 `--dry-run`，**Then** 正常展示预览（原有行为，虽然仍跳过 LLM）

---

### Edge Cases

- `merge` 无冲突时 exit 码始终为 0
- Gate 3 预览剥离后内容为空时，显示 `(empty content)` 而不是空白页面
- `detect-commands` 对纯空输入不崩溃，返回空列表
- `history --show` 传入含路径分隔符的快照名时，拒绝跨目录访问（安全边界）
- `pending --json` 中老数据缺少 `pending_since` 时，字段值为空字符串不导致崩溃

## Requirements

### Functional Requirements

- **FR-001**: `merge` 命令在冲突隔离后必须返回 exit code 0，并输出引导用户执行 `holmes kb resolve` 的 next-step 提示
- **FR-002**: Gate 3 预览必须在展示前剥离内部字段（`pending`, `pending_since`, `source`, `source_session`, `suggested_type`, `suggested_category`），仅展示实际 KB 字段
- **FR-003**: `list_pending()` 返回的每个条目字典必须包含 `pending_since` 字段
- **FR-004**: `detect-commands` 的 `CMD_PATTERN` fallback 路径必须过滤 SQL 关键字；同时若输入文本包含 YAML frontmatter 块，在分析前先剥离
- **FR-005**: `holmes kb show` 支持 `--with-evidence` 选项，读取 sidecar evidence 文件并汇总展示
- **FR-006**: `holmes kb history <id>` 支持 `--show <snapshot-name>` 选项，输出指定快照的完整内容
- **FR-007**: `import --dry-run` 在无 API Key 且未提供分类参数时，输出明确的 next-step 提示

### Key Entities

- **Pending Entry**: 含 `pending_since` 时间戳的内部字段集合；Gate 3 展示时应剥离这些字段
- **Evidence Sidecar**: `contributions/evidence/<id>/` 下的 JSON 文件，记录 session_id、contributor、date
- **Version Snapshot**: `contributions/history/<id>/` 下的 Markdown 快照文件，含完整条目历史内容

## Success Criteria

### Measurable Outcomes

- **SC-001**: `merge` 命令成功隔离冲突时 exit 码准确率从 0% 提升至 100%（始终为 0）
- **SC-002**: Gate 3 预览不再出现任何内部字段，用户审核准确率提升至 100%
- **SC-003**: `pending --json` 中 `pending_since` 字段覆盖率达到 100%（新数据），老数据降级为空字符串
- **SC-004**: `detect-commands` 对含 YAML frontmatter 和 SQL 的完整条目输入的误报率降至 0
- **SC-005**: 全部 7 个问题修复后，现有测试套件（307 个测试）保持 100% 通过率，新增测试覆盖所有场景

## Assumptions

- 历史快照文件存储位置为 `contributions/history/<id>/`（基于现有 `save_snapshot` 实现）
- `--with-evidence` 选项不修改默认 `show` 行为，完全向后兼容
- `detect-commands` 的 YAML frontmatter 检测定义为：文本开头含 `---\n...\n---` 模式
- merge 命令的设计意图是"隔离=成功处理，不是失败"，exit 1 是历史遗留问题
- 快照名安全验证：只允许文件名（不含路径分隔符），防止目录遍历
