# Tasks: M8 — 可观测性与日志

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M8-logging/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-log-commands.md

**Tests**: 验收条件明确要求单元测试（write_span 格式验证 + rotate() 逻辑），测试任务包含在内。

**Organization**: 按用户故事分 Phase，每个 Phase 可独立测试交付。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件，无未完成依赖）
- **[Story]**: 所属用户故事（US1–US5）
- 每个任务包含精确文件路径

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 无需创建新项目结构，仅确认现有目录存在

- [x] T001 确认 `kb/holmes/kb/` 目录存在（logger.py 将新建于此），`kb/tests/` 目录存在（test_logger.py 将新建于此）

---

## Phase 2: Foundational（阻塞前提，所有 US 依赖）

**Purpose**: 创建 `HolmesLogger` 核心类和 `derive_trace_id` 函数 — 所有用户故事的基础

**⚠️ CRITICAL**: 此 Phase 完成前所有用户故事均不能开始

- [x] T002 新建 `kb/holmes/kb/logger.py`，实现 `HolmesLogger.__init__(log_dir, verbose=False)`：调用 `log_dir.mkdir(parents=True, exist_ok=True)`
- [x] T003 在 `kb/holmes/kb/logger.py` 实现 `HolmesLogger.write_span(trace_id, span, level, msg, **extra)` 方法：
  - 构建 `record = {"ts": ..., "trace": trace_id, "span": span, "level": level, "msg": msg}` 并 `update(extra)`
  - 写 `~/.holmes/logs/{today}.jsonl`（追加模式，`json.dumps(record) + "\n"`）
  - 写 `~/.holmes/logs/{today}.log`（追加模式，格式 `{ts} [{level:<5}] {trace} | {span} | {msg} {extra_str}`，extra 为空时不留尾随空格）
  - 若 `self.verbose`：同时 `print(log_line)` 到 stdout
- [x] T004 在 `kb/holmes/kb/logger.py` 实现模块级函数 `derive_trace_id(source_file: str, source_hash: str = "") -> str`：
  - `stem = Path(source_file).stem`
  - `source_hash` 非空时返回 `f"{stem}-{source_hash[:4]}"`，否则返回 `stem`

**Checkpoint**: `HolmesLogger` 和 `derive_trace_id` 可 import，`write_span` 写入磁盘可验证

---

## Phase 3: User Story 1 — 文档导入全链路追踪（Priority: P1）🎯 MVP

**Goal**: `holmes import` 执行后，`~/.holmes/logs/<today>.jsonl` 和 `.log` 有对应 trace 记录

**Independent Test**: 运行 `holmes import <file>`，检查两个日志文件均有 trace 记录，运行 `holmes log show <trace_id>` 输出 span 树

### Tests for User Story 1

- [x] T005 [P] [US1] 新建 `kb/tests/test_logger.py`，编写测试 `test_write_span_writes_jsonl`：
  - 用 `tmp_path` 创建 `HolmesLogger(tmp_path)`
  - 调用 `write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8, duration_ms=42100)`
  - 断言 `(tmp_path / f"{today}.jsonl")` 存在，读取内容 `json.loads(line)`，验证必填字段 `ts/trace/span/level/msg` 全部存在，`nodes=8`、`duration_ms=42100` 正确
- [x] T006 [P] [US1] 在 `kb/tests/test_logger.py` 添加测试 `test_write_span_writes_log`：
  - 调用 `write_span("t1", "agent1.draft", "INFO", "write_dag", nodes=8)`
  - 读取 `.log` 文件，断言行格式符合 `{ts} [INFO ] t1 | agent1.draft | write_dag nodes=8`
- [x] T007 [P] [US1] 在 `kb/tests/test_logger.py` 添加测试 `test_write_span_no_trailing_space_when_no_extra`：
  - 调用 `write_span("t1", "lint", "INFO", "ok")`（无 extra）
  - 读取 `.log` 行，断言不以空格结尾

### Implementation for User Story 1

- [x] T008 [US1] 在 `kb/holmes/cli.py` 的 `import_cmd` 函数入口处（在 `cfg = load_config()` 之后），新增：
  - 从 `holmes.config._holmes_home` 获取 `log_dir = _holmes_home() / "logs"`
  - 创建 `logger = HolmesLogger(log_dir, verbose=verbose)`
  - 调用 `logger.rotate()`（清理 30 天前旧日志）
  - 派生 `trace_id = derive_trace_id(str(file))` 并写一条 `span="import.start"` 的 INFO span
  - 注意：`HolmesLogger` 和 `derive_trace_id` 从 `holmes.kb.logger` 导入

**Checkpoint**: US1 完成 — `holmes import` 执行后两种格式日志文件均有记录

---

## Phase 4: User Story 2 — 缺少 username 时阻断导入（Priority: P2）

**Goal**: `config.username` 为空时，写 ERROR 日志并终止 import，打印修复指引

**Independent Test**: 清空 username 后运行 `holmes import <file>`，终端显示提示信息，命令以非零退出码结束，日志有 ERROR 记录

### Tests for User Story 2

- [x] T009 [US2] 在 `kb/tests/test_logger.py` 添加测试 `test_write_span_error_level`：
  - 调用 `write_span("t1", "import.start", "ERROR", "config.username not set")`
  - 读取 `.jsonl` 行，断言 `level == "ERROR"`

### Implementation for User Story 2

- [x] T010 [US2] 在 `kb/holmes/cli.py` 的 `import_cmd` 函数中，在 `logger.rotate()` 之后，添加 username 检查：
  ```python
  if not cfg.username:
      logger.write_span(
          trace_id,
          "import.start",
          "ERROR",
          "config.username not set, run: holmes config set username <name>",
      )
      click.echo("Error: config.username not set", err=True)
      click.echo("run: holmes config set username <name>", err=True)
      sys.exit(1)
  ```

**Checkpoint**: US2 完成 — username 未配置时日志写 ERROR，命令退出码 1

---

## Phase 5: User Story 3 — 日志查询（Priority: P2）

**Goal**: `holmes log list` 列出三类 trace 摘要；`holmes log show` 展示完整 span 树，支持 `--json` 和 `--since`

**Independent Test**: 在已有日志文件的环境中运行 `holmes log list`，确认 import/draft/session 三类均正确分类；运行 `holmes log show <id>` 输出 span 树；`--json` 输出原始 JSON Lines；`--since` 过滤生效

### Tests for User Story 3

- [x] T011 [P] [US3] 在 `kb/tests/test_logger.py` 添加测试 `test_log_list_trace_classification`：
  - 用 `tmp_path` 写入多条 jsonl 记录（含 `agent1.draft` span、`mcp.draft` span、`trace: session-abc`）
  - 调用 CLI `holmes log list`（通过 `click.testing.CliRunner`），验证输出含 `import`、`draft`、`session` 三类标签

### Implementation for User Story 3

- [x] T012 [US3] 在 `kb/holmes/cli.py` 末尾新增 `holmes log` 子命令组：
  ```python
  @cli.group("log")
  def log_group() -> None:
      """View Holmes operation logs."""
  ```
- [x] T013 [US3] 在 `log_group` 下实现 `holmes log list` 命令：
  - 读取 `_holmes_home() / "logs" / "*.jsonl"` 所有文件
  - 按 `trace` 字段分组；识别类型（import/draft/session/`?`）：
    - import：含 span 前缀 `agent1.`、`agent2.` 或 span == `lint`
    - draft：含 span == `mcp.draft`
    - session：trace_id 以 `session-` 开头
  - 提取每 trace 最后事件的 UTC 日期（`ts` 前 10 位）
  - 按表格格式输出：`{trace_id:<30} {type:<10} {last_date:<12} {summary}`
  - 无日志文件时输出 `No log entries found.`
- [x] T014 [US3] 在 `log_group` 下实现 `holmes log show <trace_id> [--json] [--since YYYY-MM-DD]` 命令：
  - 读取所有 `.jsonl` 文件，过滤 `trace == trace_id` 的行，按 `ts` 升序排列
  - `--since` 非空时，验证日期格式（`date.fromisoformat`，格式错误则打印错误并 `sys.exit(1)`），过滤早于该日期的事件
  - `--json` flag：直接输出过滤后的 JSON Lines（每行 `json.dumps(record)`）
  - 默认输出：
    - 首行 `trace: {trace_id}`
    - 按 span 树格式输出，每行 `  {span:<20} {duration_s}s   {extra_summary}`
  - trace 无事件时输出 `No events found for trace: {trace_id}`，退出码 0

**Checkpoint**: US3 完成 — log list/show 命令均可正常工作

---

## Phase 6: User Story 4 — 实时 verbose 输出（Priority: P3）

**Goal**: `holmes import --verbose` 时，每个 span 完成后实时打印到终端

**Independent Test**: 运行 `holmes import <file> --verbose`，终端实时出现 span 日志行

### Tests for User Story 4

- [x] T015 [US4] 在 `kb/tests/test_logger.py` 添加测试 `test_verbose_prints_to_stdout`：
  - 创建 `HolmesLogger(tmp_path, verbose=True)`
  - 调用 `write_span(...)` 并用 `capsys` 捕获 stdout
  - 断言 stdout 包含人类可读日志行

### Implementation for User Story 4

- [x] T016 [US4] 确认 `kb/holmes/cli.py` 的 `import_cmd` 已将 `verbose` 参数传入 `HolmesLogger(log_dir, verbose=verbose)`（T008 中已完成），在此 task 中验证端到端行为：添加 import.start span 的打印是否实时可见

**Checkpoint**: US4 完成 — `--verbose` 实时打印到 terminal

---

## Phase 7: User Story 5 — 日志滚动与清理（Priority: P3）

**Goal**: `rotate()` 删除 30 天前的 `.log` 和 `.jsonl` 文件，保留最近文件

**Independent Test**: 在 `~/.holmes/logs/` 中手动创建 31 天前的文件，调用 `rotate()`，验证旧文件删除、新文件保留

### Tests for User Story 5

- [x] T017 [P] [US5] 在 `kb/tests/test_logger.py` 添加测试 `test_rotate_deletes_old_files`：
  - 在 `tmp_path` 下创建 31 天前的 `.log` 和 `.jsonl` 文件（文件名为 31 天前的日期字符串）
  - 同时创建今天的 `.log` 和 `.jsonl` 文件
  - 调用 `HolmesLogger(tmp_path).rotate()`
  - 断言旧文件不存在，今天的文件存在
- [x] T018 [P] [US5] 在 `kb/tests/test_logger.py` 添加测试 `test_rotate_skips_non_date_files`：
  - 在 `tmp_path` 下创建 `README.txt`（非日期格式）
  - 调用 `rotate()`
  - 断言 `README.txt` 仍然存在

### Implementation for User Story 5

- [x] T019 [US5] 在 `kb/holmes/kb/logger.py` 实现 `HolmesLogger.rotate()` 方法：
  ```python
  from datetime import date, timedelta
  cutoff = date.today() - timedelta(days=30)
  for ext in ("*.log", "*.jsonl"):
      for f in self.log_dir.glob(ext):
          try:
              file_date = date.fromisoformat(f.stem)
              if file_date < cutoff:
                  f.unlink()
          except ValueError:
              pass  # 跳过非日期格式文件名
  ```

**Checkpoint**: US5 完成 — rotate() 精确删除超期文件

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 最终验证、边界处理完善

- [x] T020 [P] 在 `kb/tests/test_logger.py` 添加测试 `test_logger_creates_log_dir_if_missing`：创建路径不存在的 `HolmesLogger`，验证目录自动创建
- [x] T021 [P] 在 `kb/holmes/cli.py` 的 `holmes log show` 中，完善 `--since` 日期格式错误处理：格式不合法（`ValueError`）时打印 `Error: --since must be YYYY-MM-DD format` 并 `sys.exit(1)`
- [x] T022 在 `kb/holmes/kb/logger.py` 确保 `derive_trace_id` 已通过 `__all__` 或直接 import 可从 `holmes.kb.logger` 导入（无需额外 export 声明，但确认 module 顶层可访问）
- [x] T023 运行 `pytest kb/tests/test_logger.py -v` 验证所有测试通过，补充任何遗漏的边界场景

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (Foundational)**: 依赖 Phase 1 — **阻塞所有用户故事**
- **Phase 3 (US1)**: 依赖 Phase 2 完成
- **Phase 4 (US2)**: 依赖 Phase 2 完成（可与 US1 并行）
- **Phase 5 (US3)**: 依赖 Phase 2 完成（可与 US1/US2 并行，但实际需要日志文件已写入，建议在 Phase 3 后进行）
- **Phase 6 (US4)**: 依赖 Phase 3（verbose=True 需要 import.start span 存在）
- **Phase 7 (US5)**: 依赖 Phase 2（rotate 方法在 Foundational 完成后即可实现）
- **Phase 8 (Polish)**: 依赖所有 US 完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 完成后即可开始
- **US2 (P2)**: Phase 2 完成后即可开始，可与 US1 并行
- **US3 (P2)**: Phase 2 完成后即可开始，建议在 US1 后（需要已有日志可供查询测试）
- **US4 (P3)**: 依赖 US1（verbose 接入 import 命令）
- **US5 (P3)**: 依赖 Phase 2（rotate 方法），可与 US1/US2/US3 并行

### Parallel Opportunities

- T005、T006、T007（US1 测试）可并行
- T011（US3 测试）可与 US1 测试并行
- T017、T018（US5 测试）可并行
- T020、T021（Polish）可并行

---

## Parallel Example: Phase 2 (Foundational)

```bash
# T002, T003, T004 顺序执行（同一文件 logger.py，顺序追加实现）
Task: "新建 logger.py 并实现 __init__"     # T002
Task: "实现 write_span 方法"               # T003
Task: "实现 derive_trace_id 函数"          # T004
```

## Parallel Example: Phase 3 (US1 Tests)

```bash
# T005, T006, T007 可同时启动（不同测试函数）
Task: "test_write_span_writes_jsonl"        # T005
Task: "test_write_span_writes_log"          # T006
Task: "test_write_span_no_trailing_space"   # T007
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1: Setup
2. 完成 Phase 2: Foundational（T002–T004，新建 `logger.py`）
3. 完成 Phase 3: US1（T005–T008，测试+接入 import 命令）
4. **STOP & VALIDATE**: `holmes import <file>` 后检查 `.jsonl` 和 `.log` 均有记录
5. 继续 US2 → US3 → US4 → US5

### Incremental Delivery

1. Phase 2 完成 → logger.py 可 import，write_span 工作
2. Phase 3 (US1) → import 写日志
3. Phase 4 (US2) → username 检查阻断
4. Phase 5 (US3) → log list/show 可查询
5. Phase 6 (US4) → verbose 实时打印
6. Phase 7 (US5) → rotate 自动清理
7. Phase 8 → 全量测试通过

---

## Notes

- `[P]` 任务在不同文件/不同测试函数，可并行执行
- `[Story]` 标签追踪每个任务归属
- 每个 Phase Checkpoint 后可独立验证，无需等待后续 Phase
- `logger.py` 是全新文件，不改动现有模块（除 `cli.py`）
- `cli.py` 改动：仅在 `import_cmd` 入口处添加 logger 创建和检查，末尾添加 `log_group` 子命令
- 测试先写（T005–T007）再实现（T008），遵循 TDD 精神
