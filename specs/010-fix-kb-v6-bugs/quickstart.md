# Quickstart: 修复 Holmes KB v6 报告问题

## Quick Verification

```bash
# US1: run.sh 注释无双花括号
holmes kb skill auto-create --name test-v6 --cmd 'echo hello' --desc 'test'
grep "{{" $(find ~/.holmes-kb/skills/test-v6 -name run.sh) && echo "FAIL: double braces found" || echo "US1 OK"

# US2: dry-run 不删除
# (先创建一条旧 pending)
holmes kb reject --stale-days 0 --dry-run
# 应输出条目列表 + "(dry run)"，实际文件未删除

# US3: CLAUDE.md 包含约束
grep -i "Resolution\|resolution" CLAUDE.md | grep -i "detect" && echo "US3 OK" || echo "US3 MISSING"

# US4: 无效 type 警告
holmes kb search "test" --type invalid_type_xyz 2>&1 | grep "Warning"
# 应输出: Warning: unknown type 'invalid_type_xyz'. Valid types: ...

# US5: pending_since_source 字段
holmes kb pending --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
missing = [e for e in data if 'pending_since_source' not in e]
print('Missing pending_since_source:', len(missing))
valid = {'field', 'created_at', 'mtime'}
invalid = [e for e in data if e.get('pending_since_source') not in valid]
print('Invalid source values:', [e['id'] for e in invalid])
"
```

## Test Scenarios

### US1 — 注释单花括号
`auto_create_skill(kb_root, "test", "echo hi", "desc")` → run.sh 不含 `{{placeholder}}`

### US2 — dry-run 预览
3 条超期 pending + `reject --stale-days 1 --dry-run` → 打印 3 个 ID，文件数不变，输出含 `(dry run)`

### US3 — CLAUDE.md 约束
`CLAUDE.md` 包含 detect-commands 只传 Resolution 段落的说明

### US4 — 无效 type 警告
`kb_search(kb_root, "timeout")` with `--type invalid` → stderr warning + valid types list + empty results

### US5 — pending_since_source
- 有 `pending_since` 字段 → `source == "field"`
- 只有 `created_at` → `source == "created_at"`
- 两者均无 → `source == "mtime"`
