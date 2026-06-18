# Quickstart: 修复 Holmes KB v5 报告问题

## Quick Verification

```bash
# US1+US2: detect-commands no false positives
python3 -c "
from holmes.kb.skill.manager import detect_commands
text = '''---
type: pitfall
category: database
---
WHERE state = 'idle'
FROM pg_stat_activity
\`FATAL: remaining connection slots are reserved\`
\`max_connections = 300\`

\`\`\`bash
redis-cli info
\`\`\`
'''
results = detect_commands(text)
lines = [c.line for c in results]
assert not any('WHERE' in l or 'FROM' in l or 'FATAL' in l or '=' in l for l in lines), f'False positives: {lines}'
assert any('redis-cli' in l for l in lines), f'Missing real command: {lines}'
print('US1+US2 OK:', lines)
"

# US3: run.sh contains SKILL_PARAM comment
holmes kb skill auto-create --name test-skill-v5 --cmd 'psql -h $HOST' --desc 'test'
grep "SKILL_PARAM" $(holmes --kb-path $HOLMES_KB_PATH kb show test-skill-v5 2>/dev/null || echo /dev/null) || \
  grep -r "SKILL_PARAM" ~/.holmes-kb/skills/test-skill-v5/scripts/

# US4: batch reject
holmes kb reject --stale-days 9999   # reject nothing
holmes kb reject --stale-days 0      # reject all with timestamps

# US5: pending mtime fallback
holmes kb pending --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
empty = [e for e in data if not e.get('pending_since')]
print('Entries still missing pending_since:', len(empty))
"

# US6: search --type
holmes kb search timeout --type pitfall --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
bad = [e for e in data if e.get('type') != 'pitfall']
assert not bad, f'Type filter failed: {bad}'
print('US6 OK, results:', len(data))
"

# US9: --version
holmes --version
```

## Test Scenarios

### US1 — SQL 从句过滤
Input: multiline SQL with `WHERE`/`FROM`/`GROUP BY`/`HAVING`/`ORDER BY`/`LIMIT`/`JOIN`/`ON`
Expected: none of those lines in `detect_commands()` output

### US2 — backtick 误报
Input: `` `FATAL: remaining connection slots` ``, `` `max_connections = 300` ``
Expected: not in output; `` `redis-cli info` `` still in output

### US3 — SKILL_PARAM 注释
Run `auto_create_skill(kb_root, "test", "psql -h $HOST", "desc")`
Check: `run.sh` contains `SKILL_PARAM_` in a comment line

### US4 — 批量 reject
Seed 3 old entries, run `reject --stale-days 1` → all 3 deleted

### US5 — mtime 兜底
Seed pending entry without `pending_since`/`created_at`
Run `list_pending()` → `pending_since` is non-empty ISO string

### US6 — search --type
Seed pitfall + model entries matching same query
`search(kb_root, "query", kb_type="pitfall")` → only pitfall returned

### US7 — evidence 位置
`show --with-evidence` output: Evidence line before first `##` heading

### US8 — snapshot 字段剥离
`history --show <snap>` output: no `replaced_at/replaced_by/snapshot_reason`

### US9 — --version
`holmes --version` exits 0 and prints `0.1.0`
