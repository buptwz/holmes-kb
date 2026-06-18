# Quickstart: Import Pipeline v3 Bug Fixes

## Test Scenario 1 — English document has language:en and tags

```bash
holmes import /tmp/holmes-v3-docs/TC-L02-english.md --no-interactive

# Expected:
# ✓ 1 created, 0 updated, 0 skipped
# No "YAML parse error" in output

# Inspect pending entry
grep "^language:" ~/.holmes-kb/contributions/pending/pending-*.md | tail -1
# Expected: language: en

grep "^tags:" ~/.holmes-kb/contributions/pending/pending-*.md | tail -1
# Expected: tags: (with at least one item on next line)
```

## Test Scenario 2 — English document produces zero YAML errors

```bash
holmes import /tmp/holmes-v3-docs/TC-L02-english.md --no-interactive 2>&1
# Expected: No line containing "YAML parse error" or "draft format error"
```

## Test Scenario 3 — Chinese document unchanged (no regression)

```bash
holmes import /tmp/holmes-v3-docs/TC-Q01-standard-incident.md --no-interactive

grep "^language:" ~/.holmes-kb/contributions/pending/pending-*.md | tail -1
# Expected: language: zh
```

## Test Scenario 4 — Re-import is a complete no-op (document-level)

```bash
# First import
holmes import /tmp/holmes-v3-docs/TC-M01-single-kp.md --no-interactive
# Expected: ✓ 1 created, 0 updated, 0 skipped

# Second import (same document)
holmes import /tmp/holmes-v3-docs/TC-M01-single-kp.md --no-interactive
# Expected: ✓ 0 created, 0 updated, 1 skipped
# No new pending files created

ls ~/.holmes-kb/contributions/pending/ | grep -c pending-
# Count should be same before and after second import
```

## Test Scenario 5 — --force bypasses document-level dedup

```bash
holmes import /tmp/holmes-v3-docs/TC-M01-single-kp.md --no-interactive  # first
holmes import /tmp/holmes-v3-docs/TC-M01-single-kp.md --no-interactive --force  # second with force
# Expected second run: ✓ 1 created (force bypasses dedup)
```

## Test Scenario 6 — Multi-KP document: all KPs skipped on re-import

```bash
holmes import /tmp/holmes-v3-docs/TC-M03-multi-knowledge.md --no-interactive
# Expected first run: ✓ 3 created

holmes import /tmp/holmes-v3-docs/TC-M03-multi-knowledge.md --no-interactive
# Expected second run: ✓ 0 created, 0 updated, 3 skipped
```
