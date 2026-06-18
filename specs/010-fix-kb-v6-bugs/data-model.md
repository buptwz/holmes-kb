# Data Model: 修复 Holmes KB v6 报告问题

## 变更实体

### PendingEntryRecord (list_pending 返回 dict)

新增字段：

| Field | Type | Values | Description |
|-------|------|--------|-------------|
| `pending_since_source` | string | `"field"` / `"created_at"` / `"mtime"` | `pending_since` 值的来源 |

完整字段集（after fix）：

```python
{
    "id": str,
    "type": str,
    "title": str,
    "created_at": str,
    "pending_since": str,       # ISO datetime, never empty (mtime fallback)
    "pending_since_source": str, # NEW: "field" | "created_at" | "mtime"
    "path": str,
}
```

### ValidKbTypes (runtime computed)

不是持久化实体，每次命令执行时从 `kb_root` 子目录推断：

```python
valid_types = {
    d.name for d in kb_root.iterdir()
    if d.is_dir()
    and not d.name.startswith('.')
    and d.name not in ('contributions', 'skills')
}
```

典型值：`pitfall`, `model`, `runbook`, `reference`, `guideline`, `process`, `decision`

## 不变实体

- **KBEntry**: 无变更
- **SkillDefinition**: run.sh 文件内容变化（注释修正），但 SKILL.md schema 不变
- **EvidenceRecord**: 无变更
- **VersionSnapshot**: 无变更
