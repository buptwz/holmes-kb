# CLI Contracts: 修复 Holmes KB v5 报告问题

## US1: detect_commands() SQL 从句过滤

```
Input: text containing "WHERE state = 'idle'" or "FROM pg_stat_activity"
Output: those lines NOT in results

_SQL_KEYWORDS (after fix):
  select, show, insert, update, delete, drop, create, alter, truncate,
  replace, describe, explain,
  where, from, group, having, order, limit, join, on
```

---

## US2: detect_commands() backtick 过滤

```
backtick content with "=" or ":" → filtered out
  - `max_connections = 300`  → filtered (contains =)
  - `FATAL: remaining...`    → filtered (contains :)
  - `pg_stat_activity`       → filtered (no = or :, but no CLI match)
  - `redis-cli info`         → kept (valid command)
```

---

## US3: skill auto-create run.sh

```bash
#!/usr/bin/env bash
# Auto-generated skill: {name}
# {description}

set -euo pipefail

# To accept parameters via --param KEY=VALUE, use SKILL_PARAM_* variables:
# Example: HOST="${SKILL_PARAM_HOST:-localhost}"
#          PORT="${SKILL_PARAM_PORT:-5432}"
# Then use $HOST, $PORT in your command below.

{param_assignments or "# No parameters defined via {placeholder} syntax"}

{shell_cmd}
```

---

## US4: holmes kb reject --stale-days

```
holmes kb reject --stale-days <N>
  N >= 0 → delete pending entries older than N days
  N < 0  → error: "Error: --stale-days must be non-negative"
  N = 0  → delete all entries that have any time reference

Output: "Rejected: N stale entries"
        "Rejected: 0 stale entries" (when nothing matches)

Backward compat: holmes kb reject <pending_id> → unchanged
```

---

## US5: list_pending() mtime fallback

```json
// Old entry with no dates:
{
  "id": "old-entry",
  "pending_since": "2024-03-15T10:22:33+00:00",  // ← file mtime (was "")
  ...
}

// New entry with pending_since:
{
  "id": "pending-20260606-123456-abcd",
  "pending_since": "2026-06-06T12:34:56+00:00",  // ← original value preserved
  ...
}
```

---

## US6: holmes kb search --type

```
holmes kb search "timeout" --type pitfall
  → results filtered to kb_type == "pitfall" (case-insensitive)
  → empty result if no match (no error)

holmes kb search "timeout"
  → all types returned (backward compat)
```

---

## US7: show --with-evidence output order

```
# BEFORE (v4):
<full entry content>
── Skills ──
  ...
Evidence: 3 sessions (alice, bob) — last: 2026-06-01   ← at bottom

# AFTER (v5):
Evidence: 3 sessions (alice, bob) — last: 2026-06-01   ← before content
<full entry content>
── Skills ──
  ...
```

---

## US8: history --show output

```
holmes kb history PT-DB-001 --show PT-DB-001-20260101-120000.md
→ Outputs snapshot WITHOUT:
    replaced_at: ...
    replaced_by: ...
    snapshot_reason: ...
→ Outputs snapshot WITH all knowledge fields intact
```

---

## US9: holmes --version

```
holmes --version
→ holmes, version 0.1.0

holmes -v
→ holmes, version 0.1.0
```
