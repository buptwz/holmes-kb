# Data Model: 修复 Holmes KB v5 报告问题

## Entities

### SQL 关键字过滤集合

扩展后的完整 `_SQL_KEYWORDS` frozenset（`manager.py`）:

| 类别 | 关键字 |
|------|--------|
| 主句（已有） | select, show, insert, update, delete, drop, create, alter, truncate, replace, describe, explain |
| 从句（新增） | where, from, group, having, order, limit, join, on |

所有匹配均大小写不敏感（`.lower()` 处理）。

### PendingEntry 时间基准优先级链

```
pending_since (frontmatter)
  ↓ 空时
created_at (frontmatter)
  ↓ 空时
path.stat().st_mtime → ISO 格式字符串
```

返回给 `list_pending()` 调用方的 `pending_since` 字段值遵循此优先级。

### SnapshotInternalFields

快照文件中需在 `history --show` 输出前剥离的字段：

| 字段名 | 用途 |
|--------|------|
| `replaced_at` | 快照创建时间（系统内部） |
| `replaced_by` | 替换者 pending ID（系统内部） |
| `snapshot_reason` | 快照原因（correction/decay）（系统内部） |

## State Transitions

### CMD_PATTERN backtick 过滤逻辑（US2）

```
backtick 候选内容
  → cmd_line = m.group(2).strip()
  → if "=" in cmd_line or ":" in cmd_line → 跳过（非命令）
  → else → 进入候选列表
```

### pending batch reject 流程（US4）

```
reject --stale-days N
  → cutoff = now - timedelta(days=N)
  → for entry in list_pending():
      time_ref = entry["pending_since"] or entry["created_at"] or ""
      if time_ref and time_ref < cutoff.isoformat():
          delete_pending(kb_root, entry["id"])
          count += 1
  → echo f"Rejected: {count} stale entries"
```

## Validation Rules

- `--stale-days` 必须为非负整数（负数报错）
- `--stale-days 0`：截止时间 = now，所有有时间基准的条目均被删除
- `search --type` 大小写不敏感后过滤
- backtick 过滤：检查 `=` 或 `:`（字符级检查，不做 regex）
