# CLI Contract: holmes log Commands

## holmes log list

**Command**: `holmes log list`

**Description**: 读取 `~/.holmes/logs/*.jsonl`，按 trace_id 分组，展示所有 trace 的最后事件摘要。

**Output (human-readable)**:

```
TRACE                       TYPE     LAST DATE    SUMMARY
gpu-troubleshooting         import   2026-06-23   created=4 warnings=1
redis-oom-2026-06-24        draft    2026-06-24   pending import
session-a3f1                session  2026-06-24   read=4 confirmed=1 draft=1
```

**Columns**:
- `TRACE`: trace_id
- `TYPE`: `import` / `draft` / `session` / `?`（识别规则见 research.md）
- `LAST DATE`: 该 trace 最后一条事件的 UTC 日期（取自 `ts` 字段前 10 位）
- `SUMMARY`: 按类型自动生成的摘要文本（import：`created=N warnings=N`；draft：`pending import`；session：`read=N confirmed=N draft=N`）

**Exit code**: 0（始终，即使无日志）

---

## holmes log show

**Command**: `holmes log show <trace_id> [--json] [--since YYYY-MM-DD]`

**Arguments**:
- `trace_id` (required): 要展示的 trace ID
- `--json` (flag): 输出原始 JSON Lines（过滤后的行，不格式化）
- `--since YYYY-MM-DD` (option): 只展示该日期（含）之后的事件

**Output (human-readable)**:

```
trace: gpu-troubleshooting  (gpu-troubleshooting.md)

2026-06-23 14:30:00  [import #1]
  agent1.read      42s   turns=4
  agent1.draft     38s   nodes=8
  agent1.review[1] 21s   corrections=3
  agent1.review[2] 18s   corrections=1
  step25.parse      2s   ok
  step25.validate   3s   ok
  agent2.node[N1]   8s   entry=gpu-init-driver-check-001
  agent2.node[N2]   9s   entry=gpu-init-firmware-001
  agent2.root      10s   entry=gpu-init-failure-root-001
  lint              1s   ok  created=4 warnings=1

2026-06-23 15:10:00  [kb.approve]
  kb.approve        0s   entry=gpu-init-failure-root-001  user=wangzhi
```

**Output (--json)**:
```
{"ts":"2026-06-23T14:30:00Z","trace":"gpu-troubleshooting","span":"agent1.read",...}
{"ts":"2026-06-23T14:31:42Z","trace":"gpu-troubleshooting","span":"agent1.draft",...}
...
```

**Error case** (trace not found):
```
No events found for trace: <trace_id>
```
Exit code: 0（不报错，空结果正常）

**--since format error**:
```
Error: --since must be YYYY-MM-DD format
```
Exit code: 1

---

## holmes import (修改)

**New flag**: `--verbose` (已有，接入 Logger)

**Behavior change**: `--verbose` 时，每个 `write_span` 调用同时将人类可读行打印到 stdout。

**username 检查**（新增前置逻辑）：

```
Error: config.username not set
run: holmes config set username <name>
```
Exit code: 1（写 ERROR 日志后终止）

---

## HolmesLogger Python API Contract

```python
from holmes.kb.logger import HolmesLogger, derive_trace_id

# 创建实例
logger = HolmesLogger(log_dir=Path("~/.holmes/logs").expanduser(), verbose=False)

# 写 span
logger.write_span(
    trace_id="gpu-troubleshooting",
    span="agent1.draft",
    level="INFO",
    msg="write_dag",
    nodes=8,
    duration_ms=42100,
)

# 滚动删除旧日志
logger.rotate()

# 派生 trace_id
trace_id = derive_trace_id("gpu-troubleshooting.md")          # → "gpu-troubleshooting"
trace_id = derive_trace_id("gpu-troubleshooting.md", "a3f1b2c3")  # → "gpu-troubleshooting-a3f1"
```

**Invariants**:
- `write_span` 必须对 `.log` 和 `.jsonl` 都完成写入，原子性通过追加模式保证
- `rotate()` 不影响今天的文件
- `derive_trace_id` 无副作用，纯函数
