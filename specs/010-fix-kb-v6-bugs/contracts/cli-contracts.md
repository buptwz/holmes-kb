# CLI Contracts: 修复 Holmes KB v6 报告问题

## US1: auto-create run.sh 注释

```
生成的 run.sh 文件中：
- 不含 {{placeholder}} 双花括号
- 注释示例使用 {placeholder} 单花括号
- SKILL_PARAM_* 注释块保持正确

无参数命令时 fallback 行：
  # No parameters defined via {placeholder} syntax  ← 单花括号
```

---

## US2: reject --stale-days --dry-run

```
holmes kb reject --stale-days <N> --dry-run
  → 打印待删条目 ID 列表（每行一个），不执行删除
  → 末行输出: "Rejected: N stale entries (dry run)"
  → pending 目录文件数不变
  → exit code: 0

holmes kb reject --stale-days <N>
  → 原有行为不变（实际删除）

holmes kb reject --dry-run（无 --stale-days）
  → Error: --dry-run requires --stale-days
  → exit code: 1
```

---

## US3: CLAUDE.md detect-commands 约束

```
CLAUDE.md 包含以下约束（或等价表述）：
  detect-commands / holmes kb skill detect-commands 只应接收
  KB 条目的 ## Resolution 段落内容，而非完整条目文本。
  传入完整条目会导致表名、参数名等单词标识符被误识别为命令。
```

---

## US4: --type 无效值警告

```
holmes kb search <query> --type <invalid>
  stdout: []  (合法 JSON，--json 模式)
  stdout: "No results found."  (非 JSON 模式)
  stderr: "Warning: unknown type '<invalid>'. Valid types: decision, guideline, model, pitfall, ..."
  exit code: 0

holmes kb list --type <invalid>
  同上 stderr warning 行为

holmes kb search <query> --type <valid>
  无 warning，正常返回结果

holmes kb search <query>（无 --type）
  无 warning，正常返回结果
```

---

## US5: list_pending() pending_since_source

```python
# 有真实 pending_since 字段
entry["pending_since_source"] == "field"

# 无 pending_since，有 created_at
entry["pending_since_source"] == "created_at"

# 两者均无，用 mtime
entry["pending_since_source"] == "mtime"

# 完整 dict 字段集
{
    "id": "pending-20260606-...",
    "type": "pitfall",
    "title": "...",
    "created_at": "...",
    "pending_since": "2026-06-06T...",
    "pending_since_source": "field",   # ← NEW
    "path": "/path/to/pending/..."
}
```
