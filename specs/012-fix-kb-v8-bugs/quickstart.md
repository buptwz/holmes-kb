# Quickstart & Test Scenarios: 修复 Holmes KB v8 报告问题

## US1 — amend-pending updated_at

```bash
# Amend and confirm should now succeed
holmes kb amend-pending pending-xxx --file /tmp/fixed.md
holmes kb confirm pending-xxx --contributor test
# Gate 1: ✓ Schema valid  (no more "Missing required field: 'updated_at'")
```

## US2 — detect-commands code block language filter

```python
from holmes.kb.skill.manager import detect_commands

# nginx block — should be empty
nginx_text = """
```nginx
upstream backend {
    server 127.0.0.1:8080;
    keepalive 32;
}
```
"""
assert detect_commands(nginx_text) == []

# bash block — should detect commands
bash_text = """
```bash
redis-cli ping
```
"""
result = detect_commands(bash_text)
assert any("redis-cli" in c.line for c in result)
```

## US3 — write-pending frontmatter validation

```bash
holmes kb write-pending --content "no frontmatter at all"
# Error: content must include YAML frontmatter (starting with "---").
# exit 1

holmes kb write-pending --content ""
# Error: content must include YAML frontmatter (starting with "---").
# exit 1
```

## US4 — Gate 3 long content yes confirm

```bash
# With content > 800 chars, Gate 3 shows:
# Type 'yes' to confirm this entry:
# Pressing Enter or typing 'y' → Aborted.
# Typing 'yes' → ✓ Entry confirmed
```

## US5 — resolve auto-rebuild index

```bash
holmes kb resolve conflict-xxx --keep A
# ✓ Conflict conflict-xxx resolved (kept side A)
# ✓ Index rebuilt.

holmes kb list  # entry immediately visible
```

## US6 — list --maturity filter

```bash
holmes kb list --maturity draft
# Only draft entries shown

holmes kb list --maturity proven --type pitfall
# Only proven pitfall entries

holmes kb list --maturity invalid_xyz
# Warning: unknown maturity 'invalid_xyz'. Valid values: draft, proven, verified
# (empty output, exit 0)
```

## US7 — history exit codes

```bash
holmes kb history NONEXISTENT
# No snapshots found for NONEXISTENT.
# echo $?  → 1

holmes kb history NONEXISTENT --show bad.md
# Snapshot not found: bad.md
# echo $?  → 1
```
