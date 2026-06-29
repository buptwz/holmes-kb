# Feature Specification: M8 — 可观测性与日志

**Feature Branch**: `dev-M8`

**Created**: 2026-06-23

**Status**: Draft

**Input**: User description: "M8 — 为 Holmes KB CLI 实现完整的日志与可观测性系统"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 文档导入全链路追踪 (Priority: P1)

工程师运行 `holmes import gpu-troubleshooting.md`，导入完成后能通过 `holmes log show gpu-troubleshooting` 查看该文档从导入到上线的完整操作时间线，包括每个阶段耗时和 LLM 调用情况。

**Why this priority**: 核心可观测性需求，其他所有日志功能都依赖 Logger 写入能力。

**Independent Test**: 运行 `holmes import <file>`，随后检查 `~/.holmes/logs/<today>.jsonl` 中是否有对应 trace 记录，再运行 `holmes log show <trace_id>` 验证 span 树输出。

**Acceptance Scenarios**:

1. **Given** 已配置 username，**When** 运行 `holmes import gpu-troubleshooting.md`，**Then** `~/.holmes/logs/<today>.jsonl` 中写入至少一条 `trace: gpu-troubleshooting` 的 JSON 记录，同时 `.log` 文件有对应人类可读行
2. **Given** 日志文件存在，**When** 运行 `holmes log show gpu-troubleshooting`，**Then** 输出包含 trace_id 头部和按时间顺序排列的 span 树
3. **Given** 日志写入正常，**When** 单条 `write_span` 调用，**Then** `.jsonl` 行包含 `ts/trace/span/level/msg` 五个必填字段，`.log` 行格式为 `{ts} [{level}] {trace} | {span} | {msg}`

---

### User Story 2 - 缺少 username 时阻断导入 (Priority: P2)

工程师在未配置 username 的机器上运行 `holmes import`，系统写入 ERROR 日志并给出明确的修复指引，而不是静默失败或以匿名身份执行。

**Why this priority**: 防止因缺少用户标识而产生无法追溯的操作记录，是数据质量保障的前置条件。

**Independent Test**: 删除/清空 config.json 中的 username 字段，运行 `holmes import <file>`，验证日志写入 ERROR 记录且命令以非零退出码终止。

**Acceptance Scenarios**:

1. **Given** `config.username` 为空字符串，**When** 运行 `holmes import doc.md`，**Then** 终止导入，打印 `run: holmes config set username <name>`，日志中有 `level: ERROR, msg: config.username not set` 的记录
2. **Given** `config.username` 已配置，**When** 运行 `holmes import doc.md`，**Then** 正常执行，不输出 username 相关错误

---

### User Story 3 - 日志查询：列表与详情 (Priority: P2)

工程师运行 `holmes log list` 查看所有文档的操作历史摘要，再用 `holmes log show` 深入查看某份文档的完整操作时间线，支持 `--json` 和 `--since` 过滤。

**Why this priority**: 日志可查询性是可观测性的核心价值，支持运维审计和问题排查。

**Independent Test**: 在已有日志文件的环境中运行 `holmes log list`，验证三类 trace（import / draft / session）均正确分类显示。

**Acceptance Scenarios**:

1. **Given** `~/.holmes/logs/` 中有多条 jsonl 记录（含 import、mcp.draft、session-* trace），**When** 运行 `holmes log list`，**Then** 每个 trace 显示一行摘要，格式含 trace_id、类型、最后事件日期
2. **Given** 某 trace 有多个 span，**When** 运行 `holmes log show <trace_id>`，**Then** 按时间顺序输出完整 span 树（含缩进格式）
3. **Given** 同一 trace 跨多天，**When** 运行 `holmes log show <trace_id> --since 2026-06-01`，**Then** 只显示指定日期之后的事件
4. **Given** 任意 trace，**When** 运行 `holmes log show <trace_id> --json`，**Then** 输出原始 JSON Lines（未经格式化）

---

### User Story 4 - 实时 verbose 输出 (Priority: P3)

工程师运行 `holmes import doc.md --verbose`，每个 span 完成时实时打印到终端，无需等待导入结束后才能查看进度。

**Why this priority**: 调试时的辅助能力，不影响核心日志写入。

**Independent Test**: 运行 `holmes import <file> --verbose`，验证终端实时出现 span 日志行（与 `.log` 文件格式一致）。

**Acceptance Scenarios**:

1. **Given** 运行 `holmes import doc.md --verbose`，**When** 某个 span 完成，**Then** 该 span 的人类可读日志行立即打印到 stdout（不等待导入完成）
2. **Given** 运行 `holmes import doc.md`（不加 --verbose），**When** span 完成，**Then** 终端无 span 级输出（只有最终摘要）

---

### User Story 5 - 日志滚动与清理 (Priority: P3)

日志文件按天滚动，运行 `rotate()` 后 30 天前的文件被自动删除，防止日志目录无限增长。

**Why this priority**: 运维保障，防止磁盘占满。

**Independent Test**: 在 `~/.holmes/logs/` 中手动创建 31 天前的 `.log` 和 `.jsonl` 文件，调用 `rotate()`，验证旧文件被删除、新文件保留。

**Acceptance Scenarios**:

1. **Given** `~/.holmes/logs/` 中有 31 天前的 `2026-05-23.log` 和 `2026-05-23.jsonl`，**When** 调用 `rotate()`，**Then** 两个旧文件被删除
2. **Given** `~/.holmes/logs/` 中有今天的 `.log` 和 `.jsonl`，**When** 调用 `rotate()`，**Then** 今天的文件保留不变
3. **Given** `~/.holmes/logs/` 中有非日期格式的文件（如 `README.txt`），**When** 调用 `rotate()`，**Then** 该文件不被删除（跳过）

---

### Edge Cases

- `~/.holmes/logs/` 目录不存在时，`HolmesLogger.__init__` 自动创建，不抛异常
- `write_span` 并发写入同一文件时，使用追加模式（`a`），不丢失数据
- `--since` 参数格式错误（非 YYYY-MM-DD）时，打印错误提示并退出
- trace_id 相同但来自不同日期文件时，`log show` 聚合所有文件的事件
- `holmes log show <不存在的 trace_id>`：输出 `No events found for trace: <trace_id>` 并退出 0

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供 `HolmesLogger` 类，支持 `write_span(trace_id, span, level, msg, **extra)` 方法，同时写入 `.log`（人类可读）和 `.jsonl`（JSON Lines）两个文件
- **FR-002**: 每条 `.jsonl` 记录 MUST 包含 `ts`、`trace`、`span`、`level`、`msg` 五个必填字段，附加 `**extra` 中的任意字段
- **FR-003**: `.log` 格式 MUST 为 `{ts} [{level:<5}] {trace_id} | {span} | {msg} {extra_str}`（extra 为空时不追加尾随空格）
- **FR-004**: 日志文件 MUST 按 UTC 日期命名（`YYYY-MM-DD.log` / `YYYY-MM-DD.jsonl`），存放于 `~/.holmes/logs/`
- **FR-005**: `HolmesLogger` MUST 支持 `verbose: bool` 参数，为 True 时 `write_span` 同时打印人类可读行到 stdout
- **FR-006**: `HolmesLogger` MUST 提供 `rotate()` 方法，删除 30 天前（按文件名日期）的 `.log` 和 `.jsonl` 文件，跳过非日期格式文件名
- **FR-007**: 系统 MUST 提供 `derive_trace_id(source_file, source_hash="")` 函数，返回文件名 stem；`source_hash` 非空时追加 `-{source_hash[:4]}` 消歧
- **FR-008**: `holmes import` 命令 MUST 在执行任何操作前检查 `config.username`；若为空，写 ERROR 日志、终止、打印 `run: holmes config set username <name>`
- **FR-009**: CLI MUST 新增 `holmes log` 子命令组，包含 `list` 和 `show` 两个子命令
- **FR-010**: `holmes log list` MUST 读取所有 `.jsonl` 文件，按 trace_id 分组，识别三类 trace（import：含 `agent1.*`/`agent2.*`/`lint` span；draft：含 `mcp.draft` span；session：trace_id 以 `session-` 开头），每 trace 输出一行摘要
- **FR-011**: `holmes log show <trace_id>` MUST 聚合所有日志文件中该 trace 的全部 span，按时间顺序输出人类可读 span 树
- **FR-012**: `holmes log show` MUST 支持 `--json` flag（输出原始 JSON Lines）和 `--since YYYY-MM-DD` flag（过滤早于该日期的事件）
- **FR-013**: Logger 接口 MUST 设计为可实例化的普通类（非单例），便于测试时 mock 和各模块独立使用

### Key Entities

- **HolmesLogger**: 日志核心类，属性 `log_dir: Path`、`verbose: bool`；方法 `write_span()`、`rotate()`
- **LogRecord**: 单条日志事件，必填字段 `ts/trace/span/level/msg`，可选任意 extra 字段
- **TraceId**: 字符串标识符，从源文件名 stem 派生；MCP session 使用 `session-{id}` 前缀
- **Span**: 单个操作步骤，隶属于某 trace，携带 `duration_ms`、`tokens` 等性能指标

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 每次 `write_span` 调用后，`.log` 和 `.jsonl` 两个文件均同步写入对应记录，无遗漏
- **SC-002**: `holmes log show` 能在 1 秒内完成对 30 天内所有日志文件的扫描和展示
- **SC-003**: `rotate()` 精确删除超过 30 天的文件，不误删当天文件，不影响非日期格式文件
- **SC-004**: 单元测试覆盖 `write_span` 格式验证（.log/.jsonl 双格式）、`rotate()` 删除逻辑、username 检查拦截，测试通过率 100%
- **SC-005**: Logger 接口被其他模块（M4/M5/M9）调用时，只需传入 `trace_id`、`span`、`level`、`msg` 四个参数，无需关心文件路径或格式细节

## Assumptions

- `~/.holmes/logs/` 目录由 `HolmesLogger.__init__` 自动创建，不需要用户手动创建
- `HOLMES_HOME` 环境变量可覆盖 `~/.holmes/` 路径（沿用现有 `config.py` 的 `_holmes_home()` 约定）
- `write_span` 使用文件追加模式（`a`），不加文件锁；单进程顺序写入不存在并发问题
- `holmes import --verbose` 已有该 flag 参数（当前连接到 `verbose` 变量），M8 负责将其传入 Logger 实例
- `config.username` 字段已由 M1 实现并在 `HolmesConfig` 中存在，M8 直接读取
- 日志时间戳使用 UTC，格式为 ISO 8601（`datetime.now(timezone.utc).isoformat()`）
- M8 不负责在 pipeline 内部实际调用 `write_span`（M2/M4/M5 各自集成），M8 只提供 Logger 接口和 CLI 命令
