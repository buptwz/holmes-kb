# Feature Specification: 修复 Holmes KB v5 报告问题

**Feature Branch**: `009-fix-kb-v5-bugs`

**Created**: 2026-06-06

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - detect-commands SQL 从句补全 (Priority: P1)

用户对含多行 SQL 的 KB 条目内容执行 `detect-commands` 时，SQL 语句的第二行（`WHERE`、`FROM`、`GROUP BY` 等从句关键字开头）被误识别为 shell 命令，导致生成无效的技能脚本。

**Why this priority**: 直接影响 Agent 基于 KB 条目构建技能的质量；上一轮修复只过滤了 SQL 主句，从句误报仍然大量存在。

**Independent Test**: 对含多行 SQL（包含 `WHERE state = 'idle'`、`FROM pg_stat_activity`、`GROUP BY query`）的文本执行 `detect-commands`，这些 SQL 从句行不出现在结果中。

**Acceptance Scenarios**:

1. **Given** 文本含多行 SQL 从句（`WHERE/FROM/GROUP/HAVING/ORDER/LIMIT/JOIN/ON` 开头），**When** 执行 `detect-commands`，**Then** 这些行不出现在结果中
2. **Given** 文本含真正的 shell 命令（如 `redis-cli info`、`pg_dump`），**When** 执行 `detect-commands`，**Then** 命令正常返回，无过滤
3. **Given** 从句关键字大小写混用（如 `Where`、`WHERE`、`where`），**When** 分析，**Then** 均被过滤（大小写不敏感）

---

### User Story 2 - backtick 路径误报过滤 (Priority: P1)

用户对 KB 条目正文（含 `` `FATAL: remaining connection slots` ``、`` `max_connections = 300` ``、`` `pg_stat_activity` `` 等内联文字引用）执行 `detect-commands` 时，这些内联代码引用被误识别为 shell 命令。

**Why this priority**: 实测结果显示 5 条检测结果全部是误报，技能系统完全不可用；与 US1 共同构成 `detect-commands` 可用性的根本修复。

**Independent Test**: 对含 `` `FATAL: remaining connection slots are reserved...` ``、`` `max_connections = 300` ``、`` `pg_stat_activity` `` 的文本执行 `detect-commands`，这三行均不出现在结果中；但 `` `redis-cli info` `` 仍被正确识别。

**Acceptance Scenarios**:

1. **Given** 文本含错误消息的 backtick 引用（含 `:` 字符），**When** 分析，**Then** 该内容不出现在结果中
2. **Given** 文本含配置值赋值的 backtick 引用（含 `=` 字符），**When** 分析，**Then** 该内容不出现在结果中
3. **Given** 文本含真正的 backtick 命令（如 `` `redis-cli info` ``），**When** 分析，**Then** 命令正常返回
4. **Given** 文本含纯名词的 backtick 引用（如 `` `pg_stat_activity` ``，无 `=`/`:` 且不是已知 CLI 工具），**When** 分析，**Then** 被过滤掉

---

### User Story 3 - auto-create run.sh SKILL_PARAM 注释模板 (Priority: P1)

用户执行 `holmes kb skill auto-create --cmd "psql -h $HOST -U admin"` 时，生成的 `run.sh` 没有说明如何使用通过 `--param` 传入的参数（`$SKILL_PARAM_*` 变量），用户不知道如何修改脚本使参数生效。

**Why this priority**: 技能参数化是 skill 系统的核心使用场景，没有引导直接导致参数传入后无效。

**Independent Test**: 执行 `holmes kb skill auto-create --name "check-pg" --cmd "psql -h \$HOST" --desc "..."` 后，生成的 `run.sh` 头部包含说明 `SKILL_PARAM_*` 变量用法的注释块。

**Acceptance Scenarios**:

1. **Given** 创建 skill 时命令含 `$VAR` 变量，**When** 查看生成的 `run.sh`，**Then** 文件头部包含说明 `SKILL_PARAM_*` 变量用法的注释块
2. **Given** 创建 skill 时命令含 `{placeholder}` 变量，**When** 查看 `run.sh`，**Then** 变量赋值行仍然生成，注释不破坏现有逻辑
3. **Given** 创建 skill 时命令不含任何变量，**When** 查看 `run.sh`，**Then** 注释块仍然存在作为使用指引

---

### User Story 4 - pending 批量 reject (Priority: P2)

用户积压了 18 条 pending 条目，需要批量清理超期条目，但 `holmes kb reject` 每次只能处理一条，手动逐条执行效率极低。

**Why this priority**: 随着 Agent 使用量增长，pending 积压成为运营瓶颈；`pending_since` 字段已提供可靠时间基准，现在可以实现批量操作。

**Independent Test**: 执行 `holmes kb reject --stale-days 30`，所有 `pending_since` 早于 30 天前的条目被删除；输出显示删除数量。

**Acceptance Scenarios**:

1. **Given** 有 5 条 pending_since 超过 30 天的条目，**When** 执行 `reject --stale-days 30`，**Then** 5 条均被删除，输出删除数量
2. **Given** pending_since 为空但 created_at 有值，**When** 批量 reject，**Then** 以 created_at 作为时间基准
3. **Given** 所有条目均未超期，**When** 执行 `reject --stale-days 30`，**Then** 输出 `Rejected: 0 stale entries`
4. **Given** 执行 `reject <pending_id>`（原有单条用法），**When** 操作，**Then** 原有行为不变

---

### User Story 5 - pending 无日期兜底 (Priority: P2)

旧格式 pending 条目的 `pending_since` 和 `created_at` 均为空，在 `--json` 输出中无任何时间信息，无法用于自动化老化过滤，批量 reject 会跳过它们造成永久积压。

**Why this priority**: 与 US4 联动——若不修复，批量 reject 对老数据无效，积压条目永久无法被清理。

**Independent Test**: 对 `pending_since` 和 `created_at` 均为空的 pending 条目执行 `holmes kb pending --json`，该条目的 `pending_since` 字段返回文件的实际修改时间（非空字符串）。

**Acceptance Scenarios**:

1. **Given** pending 条目 `pending_since` 和 `created_at` 均为空，**When** 调用 `pending --json`，**Then** `pending_since` 返回该文件的系统修改时间（非空）
2. **Given** pending 条目有 `pending_since` 值，**When** 调用 `pending --json`，**Then** 返回原有值（不覆盖）
3. **Given** pending 条目 `pending_since` 为空但 `created_at` 有值，**When** 调用，**Then** 返回 `created_at` 值（不使用 mtime）

---

### User Story 6 - search --type 过滤 (Priority: P3)

用户搜索 "timeout" 时，结果混合了所有类型的条目，KB 规模增大后需要按类型过滤。

**Why this priority**: P3 因为现有搜索仍然可用，只是精度不足；随 KB 规模增长影响会越来越大。

**Independent Test**: 执行 `holmes kb search "timeout" --type pitfall`，结果只包含 `type: pitfall` 的条目。

**Acceptance Scenarios**:

1. **Given** KB 含 pitfall 和 model 两类条目都匹配查询词，**When** 执行 `search --type pitfall`，**Then** 只返回 pitfall 类型
2. **Given** 不传 `--type`，**When** 搜索，**Then** 返回所有类型（向后兼容）
3. **Given** 传入不存在的 type，**When** 搜索，**Then** 返回空结果，不报错

---

### User Story 7 - show --with-evidence 位置调整 (Priority: P3)

执行 `holmes kb show <id> --with-evidence` 时，Evidence 汇总行追加在整个条目内容末尾，长条目时用户需要滚动到底部才能看到。

**Why this priority**: P3 纯 UX 改善，不影响功能正确性；调整后用户体验明显改善，实现成本极低。

**Independent Test**: 执行 `holmes kb show <id> --with-evidence`，Evidence 汇总行出现在正文内容之前。

**Acceptance Scenarios**:

1. **Given** 条目有 sidecar evidence，**When** 执行 `--with-evidence`，**Then** Evidence 行出现在正文内容之前
2. **Given** 不传 `--with-evidence`，**When** 执行普通 `show`，**Then** 行为与之前完全一致

---

### User Story 8 - history --show 过滤内部字段 (Priority: P3)

执行 `holmes kb history <id> --show <snapshot>` 时，快照内容包含 `replaced_at`、`replaced_by`、`snapshot_reason` 内部字段，干扰用户阅读原始知识内容。

**Why this priority**: P3 纯 UX 改善，v4 新增的快照查看功能已可用，只是阅读体验有噪声。

**Independent Test**: 执行 `holmes kb history <id> --show <snapshot>`，输出不含 `replaced_at`、`replaced_by`、`snapshot_reason` 字段。

**Acceptance Scenarios**:

1. **Given** 快照文件含内部字段，**When** 执行 `--show`，**Then** 输出不含 `replaced_at/replaced_by/snapshot_reason`
2. **Given** 快照的知识内容字段（type/title/maturity 等），**When** 输出，**Then** 正常显示

---

### User Story 9 - holmes --version (Priority: P3)

用户执行 `holmes --version` 时命令不存在，无法通过命令行确认当前安装版本。

**Why this priority**: P3 运维便利性改善，不影响核心功能。

**Independent Test**: 执行 `holmes --version`，终端输出当前版本号字符串。

**Acceptance Scenarios**:

1. **Given** Holmes CLI 已安装，**When** 执行 `holmes --version`，**Then** 输出版本号（如 `0.1.0`）
2. **Given** 执行 `holmes -v`，**When** 运行，**Then** 同样输出版本号

---

### Edge Cases

- `detect-commands` 对纯空输入不崩溃，返回空列表
- `reject --stale-days 0` 拒绝所有 pending（所有条目均"超期"）
- `reject --stale-days` 为负数时报错，不执行
- `search --type` 大小写不敏感（`Pitfall` 和 `pitfall` 等效）
- mtime 兜底：文件系统操作失败时，返回空字符串（不崩溃）
- `history --show` 快照剥离内部字段后内容为空时，正常输出（不崩溃）
- backtick 过滤规则：含 `=` 或 `:` 均过滤，不受内容长度影响

## Requirements

### Functional Requirements

- **FR-001**: `detect-commands` 的关键字过滤列表必须包含 SQL 从句关键字 `where/from/group/having/order/limit/join/on`（大小写不敏感）
- **FR-002**: `detect-commands` 的 backtick 路径必须过滤含 `=` 或 `:` 字符的 backtick 内容
- **FR-003**: `skill auto-create` 生成的 `run.sh` 必须包含说明 `SKILL_PARAM_*` 变量用法的注释块
- **FR-004**: `holmes kb reject` 必须支持 `--stale-days N` 选项，批量删除超期 pending 条目
- **FR-005**: `list_pending()` 在 `pending_since` 和 `created_at` 均为空时，必须用文件 mtime 填充 `pending_since`
- **FR-006**: `holmes kb search` 必须支持 `--type` 选项按条目类型过滤结果
- **FR-007**: `holmes kb show --with-evidence` 的 Evidence 汇总行必须出现在正文内容之前
- **FR-008**: `holmes kb history --show` 输出时必须过滤 `replaced_at/replaced_by/snapshot_reason` 字段
- **FR-009**: `holmes --version` 必须输出当前版本号

### Key Entities

- **SQL 关键字过滤列表**: 主句（select/show/insert...）+ 从句（where/from/group...）合并集合
- **Pending 条目时间基准优先级**: `pending_since` > `created_at` > 文件 mtime
- **快照内部字段**: `replaced_at/replaced_by/snapshot_reason`，仅供系统溯源使用

## Success Criteria

### Measurable Outcomes

- **SC-001**: `detect-commands` 对含完整多行 SQL + inline backtick 引用的 KB 条目，误报率降至 0%
- **SC-002**: `skill auto-create` 生成的每个 `run.sh` 均包含 `SKILL_PARAM_*` 使用说明（100% 覆盖率）
- **SC-003**: `reject --stale-days` 结合 mtime 兜底后，所有 pending 条目均有时间基准可参与批量操作
- **SC-004**: 全部 9 个问题修复后，现有测试套件（328 个测试）100% 通过，新增测试覆盖所有场景

## Assumptions

- SQL 关键字过滤大小写不敏感（与现有过滤逻辑一致）
- backtick 过滤规则：含 `=` 或 `:` 视为非命令（涵盖配置赋值和错误消息两类主要误报）
- `pending_since` 兜底优先级链：现有值 > `created_at` > 文件 mtime
- `reject --stale-days` 使用与 mtime 兜底一致的时间基准优先级
- `search --type` 与 KB 条目 frontmatter `type` 字段大小写不敏感匹配
- `holmes --version` 版本号来源于包的 `pyproject.toml` `version` 字段
- `history --show` 剥离内部字段与 Gate 3 预览剥离方式一致（fm.loads → pop → fm.dumps）
