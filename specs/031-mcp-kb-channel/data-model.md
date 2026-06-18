# Data Model: MCP KB Channel (Feature 031)

**Date**: 2026-06-13

---

## MCP 工具 ID 路由模型

### 统一寻址规则（`kb_read`）

| ID 类型 | 格式 | 示例 | 路由目标 |
|---------|------|------|---------|
| Entry ID | `^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$` | `PT-DB-001` | `<type>/<category>/<id>.md` |
| Skill Name | `^[a-z0-9][a-z0-9-]*[a-z0-9]$` | `redis-oom-recovery` | `skills/<name>/SKILL.md` |

两者格式互斥，server 侧正则判断路由，无需 agent 声明类型。

### `kb_list` type 参数有效值

| `type` 值 | 数据来源 | 返回格式 |
|-----------|---------|---------|
| `pitfall` | `pitfall/*.md` | `{id, title, type, category, maturity, brief}` |
| `model` | `model/*.md` | 同上 |
| `guideline` | `guideline/*.md` | 同上 |
| `process` | `process/*.md` | 同上 |
| `decision` | `decision/*.md` | 同上 |
| `skill` | `skills/*/SKILL.md` | `{id (=name), description}` |

---

## MCP 响应结构

### `kb_overview` 响应

```json
{
  "entries": {"pitfall": 42, "model": 8, "guideline": 5, "process": 3, "decision": 2},
  "skill_count": 7,
  "categories": ["application", "database", "network", "system"],
  "top_tags": ["redis", "kubernetes", "postgres"],
  "hint": "string"
}
```

### `kb_read` Entry 响应

```json
{
  "id": "PT-DB-001",
  "type": "pitfall",
  "maturity": "validated",
  "content": "<完整 Markdown 含 frontmatter>",
  "skill_refs": ["redis-oom-recovery"],
  "hint": "string"
}
```

`skill_refs` 直接可用作下一个 `kb_read(id=)` 的参数。

### `kb_read` Skill 响应

```json
{
  "id": "redis-oom-recovery",
  "type": "skill",
  "description": "string",
  "content": "<SKILL.md body（去除 frontmatter）>",
  "linked_entries": ["PT-DB-001"],
  "files": ["scripts/check-memory.sh", "references/runbook.md"],
  "hint": "string"
}
```

`linked_entries`：动态反查（扫描所有 entry `skill_refs`），不存储在 SKILL.md。
`files`：递归扫描 skill 目录，过滤二进制文件后的路径列表。

### `kb_read` Skill 子文件响应

```json
{
  "id": "redis-oom-recovery",
  "path": "scripts/check-memory.sh",
  "content": "string"
}
```

### `kb_search` 响应

```json
{
  "items": [
    {
      "id": "PT-DB-001",
      "title": "string",
      "type": "pitfall",
      "maturity": "string",
      "score": 0.87,
      "brief": "string"
    }
  ],
  "total": 3,
  "hint": "string"
}
```

### `kb_submit` 响应（成功）

```json
{"id": "pending-20260613-123456-a1b2", "status": "pending", "message": "string"}
```

### `kb_submit` 响应（重复）

```json
{
  "status": "duplicate",
  "existing_id": "PT-DB-001",
  "existing_title": "string",
  "hint": "Use kb_confirm(entry_id='PT-DB-001') to record that it helped you."
}
```

### `kb_confirm` 响应（成功）

```json
{"ok": true, "entry_id": "PT-DB-001", "maturity": "verified", "promoted": true, "contributor": "user@company.com"}
```

### `kb_confirm` 响应（重复）

```json
{"ok": false, "reason": "duplicate", "entry_id": "PT-DB-001"}
```

---

## 二进制文件过滤规则

Skill 子目录中，`files` 列表仅包含以下扩展名的文件：

```
.sh .bash .py .rb .js .ts .go .rs .java
.md .txt .yaml .yml .json .toml .ini .conf .env
.sql .xml .html .css
```

其他扩展名（`.png`、`.jpg`、`.pdf`、`.zip` 等）不出现在 `files` 列表中，调用 `kb_read(path=...)` 读取时返回 error。
