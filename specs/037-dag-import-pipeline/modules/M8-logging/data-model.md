# Data Model: M8 — 可观测性与日志

## 实体定义

### HolmesLogger

```
HolmesLogger
├── log_dir: Path          # ~/.holmes/logs/（或 HOLMES_HOME/logs/）
└── verbose: bool          # True 时 write_span 同时 print 到 stdout
```

**方法**：
- `write_span(trace_id: str, span: str, level: str, msg: str, **extra) -> None`
- `rotate() -> None`

**约束**：
- `log_dir` 在 `__init__` 中自动 `mkdir(parents=True, exist_ok=True)`
- `level` 取值：`"INFO"` / `"WARN"` / `"ERROR"`

---

### LogRecord（写入磁盘的结构）

**JSONL 格式**（每行一个 JSON 对象）：

```json
{
  "ts":    "2026-06-23T14:30:00Z",   // 必填：UTC ISO8601
  "trace": "gpu-troubleshooting",    // 必填：trace_id
  "span":  "agent1.draft",           // 必填：span 名称
  "level": "INFO",                   // 必填：INFO / WARN / ERROR
  "msg":   "write_dag",              // 必填：事件描述
  // 以下为可选附加字段（**extra）：
  "nodes": 8,
  "duration_ms": 42100,
  "tokens": 1240,
  "entry_id": "gpu-init-firmware-001",
  "user": "wangzhi"
}
```

**LOG 格式**（人类可读）：

```
2026-06-23T14:30:00Z [INFO ] gpu-troubleshooting | agent1.draft | write_dag nodes=8 duration_ms=42100
```
格式模板：`{ts} [{level:<5}] {trace} | {span} | {msg} {extra_str}`，extra 为空时 `extra_str` 不留尾随空格。

---

### TraceId

- **import trace**：来自源文件名 stem，如 `gpu-troubleshooting`
- **draft trace**：来自草稿文件名 stem，如 `redis-oom-2026-06-24`
- **session trace**：以 `session-` 开头，如 `session-a3f1`
- **消歧规则**：同名文件时追加 hash 前 4 位，如 `gpu-troubleshooting-a3f1`

**derive_trace_id 函数**：

```python
def derive_trace_id(source_file: str, source_hash: str = "") -> str:
    stem = Path(source_file).stem   # "gpu-troubleshooting"
    if source_hash:
        return f"{stem}-{source_hash[:4]}"
    return stem
```

---

### Span 命名约定

| Span 名 | 触发时机 | 来源模块 |
|---------|---------|---------|
| `agent1.read` | Phase 1 通读完成 | M4 |
| `agent1.draft` | 首次 write_dag | M4 |
| `agent1.review[N]` | 第 N 轮 review | M4 |
| `step25.parse` | DAG 解析完成 | M4 |
| `step25.validate` | 交叉验证完成 | M4 |
| `agent2.node[id]` | 单个节点 entry 生成 | M5 |
| `agent2.root` | pitfall root entry 生成 | M5 |
| `lint` | import 后 lint 完成 | pipeline |
| `kb.approve` | approve 操作 | M6a |
| `kb.delete` | delete 操作 | M7 |
| `mcp.kb_overview` | MCP overview 调用 | M9 |
| `mcp.kb_search` | MCP search 调用 | M9 |
| `mcp.kb_read` | MCP read 调用 | M9 |
| `mcp.kb_confirm` | MCP confirm 调用 | M9 |
| `mcp.draft` | MCP draft 保存 | M9 |

**注**：M8 只提供 Logger 接口；以上 span 由各模块（M4/M5/M6a/M7/M9）各自调用 `write_span()` 写入。

---

## 文件系统布局

```
~/.holmes/logs/
├── 2026-06-23.log      # 人类可读，按行追加
├── 2026-06-23.jsonl    # JSON Lines，按行追加
├── 2026-06-24.log
└── 2026-06-24.jsonl
```

- 文件按 UTC 日期命名
- `rotate()` 删除 30 天前（`date.fromisoformat(stem) < cutoff`）的 `.log` 和 `.jsonl`
- 非日期格式文件名（`ValueError`）跳过不删除
