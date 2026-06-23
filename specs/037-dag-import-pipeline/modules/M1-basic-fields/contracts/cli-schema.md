# CLI Contract: M1 — 基础字段与过滤

**Date**: 2026-06-23

## 命令变更

### `holmes kb list` — 新增 flags

```
holmes kb list [OPTIONS]

新增 options:
  --all           包含 deprecated 条目（不过滤 kb_status）
  --all-types     包含 process sub-entries（不过滤 parent_id）

现有 options（不变）:
  --type TEXT
  --category TEXT
  --query TEXT
  --maturity TEXT
  --limit INT
  --offset INT
  --format [table|json|id-only]
  --json
```

**行为矩阵**:

| Flag | kb_status 过滤 | sub-entry 过滤 |
|------|---------------|---------------|
| (无) | 只显示 active | 过滤 process sub-entries |
| --all | 显示 active + deprecated | 过滤 process sub-entries |
| --all-types | 只显示 active | 不过滤 sub-entries |
| --all --all-types | 显示 active + deprecated | 不过滤 sub-entries |

---

### `holmes kb search` — 新增 flag

```
holmes kb search QUERY [OPTIONS]

新增 options:
  --all    包含 deprecated 条目和 process sub-entries

现有 options（不变）:
  --limit INT
  --json
  --type TEXT
```

---

### `holmes kb show` — sub-entry 标签

当 entry 为 process sub-entry（有 `parent_id` 字段）时，输出前增加一行：

```
[sub-entry of: <parent_id>]
<原始 Markdown 内容>
```

---

### `holmes config set` — 新增 username key

```
holmes config set username <NAME>

示例:
  holmes config set username wangzhi

允许的 key（更新后）:
  kb_path, model, api_key, api_base_url, username
```

**写入位置**: `~/.holmes/config.json` 的 `username` 字段

---

### `holmes config show` — 新增 username 字段

输出 JSON 中新增 `username` 字段：

```json
{
  "kb_path": "/home/user/holmes-kb",
  "model": "gpt-4o",
  "api_base_url": "",
  "username": "wangzhi",
  "config_file": "/home/user/.holmes/config.json",
  "settings_file": "/home/user/.holmes/settings.json"
}
```

---

## 向后兼容保证

- 所有现有命令的输出格式和参数不变
- 新增 flag 均为可选，不传时行为与原始完全一致
- 旧格式 entry 文件不受影响
