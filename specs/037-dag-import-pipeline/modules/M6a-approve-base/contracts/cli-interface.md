# CLI Interface Contract: M6a

## holmes kb approve <id>

```
Usage: holmes kb approve [OPTIONS] ENTRY_ID

  Approve a pending entry: move from _pending/ to confirmed space.

Arguments:
  ENTRY_ID  The entry ID to approve (must exist in _pending/<category>/)

Options:
  --no-interactive  Skip all confirmation prompts (auto-accept Y)
  --help            Show this message and exit.
```

### Interaction Flow

```
准备 approve: <entry_id>

[pending 空间] 发现同文档的旧 pending entries:
  - <old_id_1> (import 时间: YYYY-MM-DD)
  - <old_id_2> (import 时间: YYYY-MM-DD)
  取消旧 pending？[Y/n]

[confirmed 空间] 发现同文档的 active entries:
  - <confirmed_id_1> (approve 时间: YYYY-MM-DD)
  标记为 deprecated？[Y/n]

执行: 取消 N 个旧 pending + deprecate M 个旧 confirmed + approve 1 个新 entry
确认？[Y/n]

✓ Approved: <entry_id> → <category>/<entry_id>.md
```

### Exit Codes

| 情况 | 退出码 |
|------|--------|
| 成功 | 0 |
| entry_id 不在 _pending/ 中 | 1 |
| 用户在最终确认时输入 n | 0（无操作，打印提示） |
| 文件系统错误 | 2 |

---

## holmes kb pending (改造)

```
Usage: holmes kb pending [OPTIONS]

  List pending entries grouped by category.

Options:
  --json        Output as JSON array
  --show TEXT   Show full content of a specific pending entry ID
  --help        Show this message and exit.
```

### 输出格式（按 category 分组）

```
=== hardware (2 entries) ===
  hw-init-002        pitfall   硬件初始化失败 — 固件修复流程   2026-06-24
  hw-init-memory-002 process   内存诊断工具运行步骤             2026-06-24

=== network (1 entry) ===
  dns-001            pitfall   DNS 解析失败排查                 2026-06-23

--- legacy (1 entry) ---
  pending-20260101-120000-ab12  pitfall  旧格式条目  2026-01-01
```

### JSON 输出格式

```json
[
  {
    "id": "hw-init-002",
    "type": "pitfall",
    "title": "硬件初始化失败 — 固件修复流程",
    "category": "hardware",
    "created_at": "2026-06-24T00:00:00Z",
    "path": "_pending/hardware/hw-init-002.md",
    "format": "new"
  }
]
```
