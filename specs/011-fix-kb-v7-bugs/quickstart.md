# Quickstart & Test Scenarios: 修复 Holmes KB v7 报告问题

## US1 — detect-commands 过滤规则

**Independent Test**: `detect_commands()` on text containing JVM/config-key/method-call/config-block patterns returns no false positives.

```python
from holmes.kb.skill.manager import detect_commands

# JVM args — should be filtered
text = "Set `- Xmx4g -Xms4g` in your startup script"
assert detect_commands(text) == []

# Config key — should be filtered
text = "Configure `session.timeout.ms` to 30000"
assert detect_commands(text) == []

# Method call — should be filtered
text = "Call `emitter.on()` to register listener"
assert detect_commands(text) == []

# Config block — should be filtered
text = "Add `upstream backend {` to nginx.conf"
assert detect_commands(text) == []

# Real command — should NOT be filtered
text = "Run `redis-cli ping` to check"
assert len(detect_commands(text)) == 1
assert detect_commands(text)[0].line == "redis-cli ping"
```

## US2 — amend-pending

**Independent Test**: Write a pending entry with missing maturity (Gate 1 fails), amend it, then confirm succeeds.

```bash
# Write invalid pending (no maturity)
holmes kb write-pending --content "---
title: Test Entry
type: pitfall
category: app
---
Content here."
# → {"pending_id": "pending-20260606-XXXXXX-xxxx"}

# Confirm → Gate 1 fails (maturity missing)
holmes kb confirm pending-... --contributor test
# Gate 1: ✗ Schema errors: Missing required frontmatter field: 'maturity'

# Amend with valid content
holmes kb amend-pending pending-... --content "---
title: Test Entry
type: pitfall
category: app
maturity: draft
---
Content here."
# → ✓ Amended: pending-...

# Confirm → succeeds
holmes kb confirm pending-... --contributor test
# Gate 1: ✓ Schema valid
# → ✓ Entry confirmed: PT-APP-NNN
```

## US3 — write-pending --file

**Independent Test**: `write-pending --file path/to/entry.md` produces same result as `--content "$(cat path/to/entry.md)"`.

```bash
# Create test file
cat > /tmp/test-entry.md << 'EOF'
---
title: File Input Test
type: pitfall
category: app
maturity: draft
---
Testing file input.
EOF

holmes kb write-pending --file /tmp/test-entry.md
# → {"pending_id": "pending-..."}

# Error cases
holmes kb write-pending --file /nonexistent.md
# → Error: Invalid value for '--file': Path '/nonexistent.md' does not exist.

holmes kb write-pending --content "..." --file /tmp/test-entry.md
# → Error: --content and --file are mutually exclusive.

holmes kb write-pending
# → Error: one of --content or --file is required.
```

## US4 — archive-orphans --dry-run

**Independent Test**: `archive-orphans --dry-run` prints IDs without moving files.

```bash
# Count files before
before=$(ls contributions/pending/ | wc -l)

holmes kb archive-orphans --dry-run
# <entry_id_1>
# <entry_id_2>
# Archived 2 orphan draft(s) (dry run)

# Count files after — unchanged
after=$(ls contributions/pending/ | wc -l)
[ "$before" = "$after" ]  # true
```

## US5 — reject single --dry-run

**Independent Test**: `reject <id> --dry-run` prints entry ID without deleting.

```bash
holmes kb reject pending-xxx --dry-run
# pending-xxx
# ✓ Rejected: pending-xxx (dry run)

# File still exists
[ -f contributions/pending/pending-xxx.md ]  # true

# Old error message no longer appears
holmes kb reject pending-xxx --dry-run
# NOT: Error: --dry-run requires --stale-days.
```

## US6 — pending table CREATED column

**Independent Test**: Old-format pending entries show non-empty CREATED in table.

```bash
holmes kb pending
# ID                                       TYPE         TITLE                               CREATED
# pending-20260605-075555-eq8p             pitfall      Old Format Entry                    2026-06-05
# (previously showed blank for old entries)
```
