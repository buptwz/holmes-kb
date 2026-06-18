# Quickstart: 修复 Holmes KB v4 报告问题

## Quick Verification

After implementing all 7 fixes, verify each with these one-liners:

```bash
# US1: merge exit code
holmes kb merge && echo "EXIT OK"

# US3: pending_since in JSON output
holmes kb pending --json | python3 -c "import json,sys; d=json.load(sys.stdin); print('pending_since' in d[0] if d else 'no entries')"

# US5: show with evidence
holmes kb show PT-DB-005 --with-evidence

# US6: history with snapshot view
holmes kb history PT-APP-001 --show $(holmes kb history PT-APP-001 | head -2 | tail -1 | awk '{print $1}')

# US7: dry-run hint
holmes import /tmp/test.md --dry-run 2>&1 | grep "LLM not configured"
```

## Test Scenarios

### US1 — merge exit code
1. Create a conflict in KB (two sessions edit the same entry)
2. Run `holmes kb merge`
3. Check `echo $?` → must be `0`
4. Output must contain `holmes kb resolve`

### US2 — Gate 3 clean preview
1. Run `holmes kb pending --json` to get a pending ID
2. Run `holmes kb confirm <id>` and proceed to Gate 3
3. Preview must not show `pending:`, `source:`, `suggested_type:`, etc.

### US3 — pending_since in JSON
1. Run `holmes kb pending --json`
2. Each item must have `"pending_since"` key with non-empty value

### US4 — detect-commands no false positives
```python
from holmes.kb.skill.manager import detect_commands
text = """---
category: database
type: pitfall
---
WHERE state = 'idle'
FATAL: remaining connection slots are reserved

$ redis-cli info
"""
results = detect_commands(text)
assert not any("WHERE" in c or "FATAL" in c or "category" in c for c in results)
assert any("redis-cli" in c for c in results)
```

### US5 — show --with-evidence
1. Ensure `contributions/evidence/PT-DB-005/` has a JSON sidecar
2. Run `holmes kb show PT-DB-005 --with-evidence`
3. Output contains `Evidence: N sessions`

### US6 — history --show
1. Run `holmes kb history PT-APP-001` to list snapshots
2. Pick a snapshot name (e.g., `20250601T100000.md`)
3. Run `holmes kb history PT-APP-001 --show 20250601T100000.md`
4. Full content displayed

### US7 — dry-run hint
1. Unset API key: `HOLMES_API_KEY="" holmes import /tmp/test.md --dry-run`
2. Output must contain `LLM not configured`
3. With `--type pitfall`: hint must NOT appear
