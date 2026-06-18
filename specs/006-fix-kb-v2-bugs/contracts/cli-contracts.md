# CLI Contracts: 修复 Holmes KB v2 报告缺陷

**Feature**: 006-fix-kb-v2-bugs | **Date**: 2026-06-06

---

## Contract 1: `holmes kb confirm <pending-id>` — 纠错路径输出

### 修复前行为（BUG）

```yaml
# 确认纠错 pending 条目后，holmes kb show 显示：
pending: true
pending_since: '2026-06-05T11:41:27+00:00'
source: auto
source_session: '2026-06-05T11:41:27+00:00'
suggested_category: database
suggested_type: pitfall
```

### 修复后行为（CORRECT）

```yaml
# 以上字段均不出现在正式条目的 frontmatter 中
id: PT-DB-003
type: pitfall
title: ...
maturity: verified
category: database
tags: [...]
evidence: [...]
contributors: [...]
created_at: ...
updated_at: ...
```

**Contract**: 纠错路径 confirm 后，`{pending, pending_since, source, source_session, suggested_type, suggested_category}` 中任何一个字段不出现在正式条目 frontmatter 中。

---

## Contract 2: `holmes kb lint` — conflict_count 准确性

### 修复前行为（BUG）

```
Entries: 7  Pending: 20  Conflicts: 4   # 含已解决冲突
```

### 修复后行为（CORRECT）

```
Entries: 7  Pending: 20  Conflicts: 1   # 仅 pending_review 状态
```

`holmes kb lint --report` JSON 输出：

```json
{
  "total_entries": 7,
  "pending_count": 20,
  "conflict_count": 1,    // ← 只含 pending_review 状态
  ...
}
```

**Contract**: `conflict_count` == 实际 `status: pending_review` 的冲突文件数量。

---

## Contract 3: `holmes kb skill run <name> --json` — 退出码

### 修复前行为（BUG）

```bash
holmes kb skill run failing-skill --json
echo $?   # 0  ← 始终 0，即使 skill 脚本退出 1
```

### 修复后行为（CORRECT）

```bash
holmes kb skill run failing-skill --json
# stdout: {"skill": "failing-skill", "exit_code": 1, ...}
echo $?   # 1  ← 与 JSON 中 exit_code 一致

holmes kb skill run succeeding-skill --json
# stdout: {"skill": "succeeding-skill", "exit_code": 0, ...}
echo $?   # 0
```

**Contract**: `holmes kb skill run --json` 的 CLI 退出码 == JSON 输出中的 `exit_code` 字段值。

---

## Contract 4: `holmes kb skill detect-commands` — SQL 过滤

### 修复前行为（BUG）

```bash
holmes kb skill detect-commands --json --content "
\`\`\`sql
SHOW SLAVE STATUS\G
SELECT * FROM users;
\`\`\`
\`\`\`bash
mysqladmin stop-slave
\`\`\`
"
# 输出包含 SQL 语句（错误）
[
  {"line": "SHOW SLAVE STATUS\\G", ...},
  {"line": "SELECT * FROM users;", ...},
  {"line": "mysqladmin stop-slave", ...}
]
```

### 修复后行为（CORRECT）

```json
[
  {"line": "mysqladmin stop-slave", "suggested_name": "mysqladmin-stop-slave"}
]
```

**Contract**: `detect_commands()` 不返回以 SQL 关键字（大小写不敏感）开头的命令行。SQL 关键字集合：`select, show, insert, update, delete, drop, create, alter, truncate, replace, describe, explain`。
