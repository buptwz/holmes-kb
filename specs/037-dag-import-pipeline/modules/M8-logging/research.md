# Research: M8 — 可观测性与日志

## 决策记录

### 决策 1：不使用 Python 标准库 `logging` 模块

**Decision**: 不使用 `logging.Logger`，直接写文件

**Rationale**:
- `logging` 模块的 Handler/Formatter 体系对"同时写两种格式（`.log` + `.jsonl`）"需要两个 Handler，配置复杂
- Holmes 日志的核心 schema 包含自定义字段（`trace`、`span`、`extra`），不适合 `logging.LogRecord` 的固定字段
- Holmes 是单进程工具，不需要 `logging` 的线程安全机制
- 直接写文件：30 行代码即可实现完整需求，符合渐进式实现原则

**Alternatives considered**:
- `logging` + 两个 FileHandler：配置复杂（约 50 行），且 `extra` 字段在 JSONL Handler 中需要特殊处理
- `structlog`：第三方库，引入新依赖，不值得

---

### 决策 2：Logger 实例传递，非单例

**Decision**: `HolmesLogger` 作为普通类实例，在 CLI 入口处创建，通过构造参数传入各子系统

**Rationale**:
- 单例模式导致测试时无法 mock（需要 monkeypatch 模块级变量）
- 普通实例：测试时直接 `logger = HolmesLogger(tmp_path)` 隔离文件系统
- 各 CLI 命令在入口处创建 logger，生命周期与命令调用一致

**Alternatives considered**:
- 模块级单例 `_logger = HolmesLogger(...)`：测试隔离困难，违反单一职责
- 依赖注入框架：过度工程，违反渐进式实现原则

---

### 决策 3：derive_trace_id 作为独立函数

**Decision**: `derive_trace_id(source_file, source_hash="")` 作为模块级函数，不绑定到 Logger 实例

**Rationale**:
- trace_id 派生逻辑（取文件名 stem）在 import 命令早于 Logger 创建时就需要使用
- 函数比方法更易于在 M4/M5 等模块直接 import 使用，无需先有 Logger 实例

---

### 决策 4：日志文件追加模式，不加锁

**Decision**: 使用 `open(path, "a", encoding="utf-8")` 每次写入后关闭，不维护持久文件句柄

**Rationale**:
- Holmes 是单进程工具，不存在多进程并发写同一日志文件的场景
- 每次写入后关闭：避免文件句柄泄漏，实现简单
- 跨天自动切换到新文件名：每次 `write_span` 重新计算 `today`，天然支持按日滚动

---

### 决策 5：`holmes log show` 聚合所有 .jsonl 文件

**Decision**: `log show` 读取 `~/.holmes/logs/*.jsonl` 所有文件，过滤 trace_id，按 ts 排序输出

**Rationale**:
- trace 可能跨多天（第一天 import，第二天 approve），必须聚合所有文件
- 文件数量上限 30 个，全读性能可接受（SC-002 要求 1 秒内）
- 先过滤再排序：内存效率 O(events_of_trace)，不是 O(all_events)

---

### 决策 6：log list 的 trace 类型识别规则

| 类型 | 识别规则 |
|------|---------|
| import | 该 trace 含有任意 span 以 `agent1.`、`agent2.` 开头，或 span == `lint` |
| draft | 该 trace 含有 span == `mcp.draft` |
| session | trace_id 以 `session-` 开头 |
| unknown | 以上都不匹配（兜底，展示为 `?`） |

识别为 import 的优先级高于 draft（理论上不重叠，但作为防御性设计）。
