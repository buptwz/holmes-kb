# CLI Contracts: 修复 Holmes KB v4 报告问题

## US1: holmes kb merge

**Contract**: exit code after conflict isolation

```
holmes kb merge
  → conflicts isolated to contributions/conflicts/
  → exit code: 0  (was: 1 — BUG FIXED)
  → stdout includes: "Run 'holmes kb resolve <id> --keep [A|B]' to resolve."
```

**Before fix**: `sys.exit(1)` at `cli.py:808`
**After fix**: `click.echo("Run 'holmes kb resolve <id> --keep [A|B]' to resolve.")`

---

## US2: holmes kb confirm <id> (Gate 3 preview)

**Contract**: Gate 3 preview must not contain internal fields

```
Gate 3 preview content MUST NOT contain:
  - pending: true/false
  - pending_since: <any value>
  - source: <any value>
  - source_session: <any value>
  - suggested_type: <any value>
  - suggested_category: <any value>
```

**Implementation**: `fm.loads(raw)` → pop internal fields → `fm.dumps(post)` → display

---

## US3: holmes kb pending --json

**Contract**: each record includes `pending_since`

```json
[
  {
    "id": "PT-DB-001",
    "type": "pitfall",
    "title": "...",
    "created_at": "...",
    "pending_since": "2025-06-01T10:00:00",
    "path": "contributions/pending/PT-DB-001.md"
  }
]
```

**Graceful degradation**: old entries without `pending_since` → `"pending_since": ""`

---

## US4: detect_commands(text)

**Contract**: filtered output

```
Input: text with YAML frontmatter + SQL fragments + real shell commands
Output: only real shell commands (no SQL, no frontmatter values)

Filtering rules:
1. Strip leading YAML block: if text starts with "---\n", remove content between first --- and second ---
2. CMD_PATTERN candidates: apply _SQL_KEYWORDS filter to each match
```

---

## US5: holmes kb show <id> --with-evidence

**Contract**: evidence summary line appended to output

```
# PT-DB-005 — Title
...normal show output...
Evidence: 3 sessions (alice, bob) — last: 2025-06-01
```

**No sidecar**: `Evidence: none`
**Without flag**: behavior unchanged (backward compatible)

---

## US6: holmes kb history <id> --show <snapshot-name>

**Contract**: snapshot content output

```
holmes kb history PT-APP-001 --show 20250601T100000.md
→ stdout: full Markdown content of .history/PT-APP-001/20250601T100000.md
```

**Security**: reject if `Path(name).name != name` (path traversal attempt)
**Not found**: error message, exit 0

**Without flag**: list snapshots (original behavior)

---

## US7: holmes import <file> --dry-run

**Contract**: hint when no LLM + no classification params

```
Condition: api_key is empty AND all of (kb_type, category, title, tags) are None
→ append: "Tip: LLM not configured. Use --type/--category/--title/--tags to preview with manual classification."
```

**No hint when**: api_key present OR any classification param provided
