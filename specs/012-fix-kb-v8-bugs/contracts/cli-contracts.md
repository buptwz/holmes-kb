# CLI Contracts: 修复 Holmes KB v8 报告问题

## Changed Commands

### amend-pending (US1)

Output after fix: same `✓ Amended: <id>`.
The written file now always contains `updated_at` (current UTC) and `created_at` (preserved or empty).

### write-pending (US3)

**New validation** (before existing duplicate check):
- Content without `---` frontmatter → `Error: content must include YAML frontmatter (starting with "---").` + exit 1
- Applies to both `--content` and `--file` paths

### confirm (US4)

**Gate 3 — long content (>800 chars)**:

Before:
```
Content exceeds 800 chars. To review full content:
  holmes kb pending --show <id>

Confirm this entry? [Y/n]:
```

After:
```
Content exceeds 800 chars. To review full content:
  holmes kb pending --show <id>

Type 'yes' to confirm this entry:
```
- Input `yes` (case-insensitive) → confirm proceeds
- Any other input → `Aborted.` + exit 0
- ≤800 chars: behavior unchanged (`[Y/n]` with default Y)

### resolve (US5)

**Added after successful resolution**:
```
✓ Conflict <id> resolved (kept side A)
✓ Index rebuilt.
```
Both `--keep` and `--manual` paths trigger index rebuild.

### list (US6)

**New option**:
```
holmes kb list [--maturity <draft|verified|proven>] [--type ...] [--category ...] ...
```

Behavior:
- Valid maturity: filter entries, return only matching
- Invalid maturity: stderr warning + empty result + exit 0
- Combinable with `--type`, `--category`, `--query`

### history (US7)

**Changed exit codes**:

| Scenario | Before | After |
|----------|--------|-------|
| `history NONEXISTENT` | exit 0 | exit 1 |
| `history <id> --show NONEXISTENT.md` | exit 0 | exit 1 |
| `history <id>` (snapshots found) | exit 0 | exit 0 (unchanged) |
| `history <id> --show VALID.md` | exit 0 | exit 0 (unchanged) |
