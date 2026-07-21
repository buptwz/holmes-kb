# Quickstart Test Scenarios: Import Pipeline — Pending Dedup & Type Override

**Branch**: `017-fix-pending-dedup-type` | **Date**: 2026-06-09

---

## T-01: Duplicate Import Skipped (D-5, US1)

**Setup**: Single-incident document (~500 chars). KB is clean.

**Step 1 — First import**:
```bash
holmes import /tmp/nginx-502.md --no-interactive
```
**Expected**: `✓ 1 created, 0 updated, 0 skipped`
One new file in `contributions/pending/`.

**Step 2 — Second import (same file)**:
```bash
holmes import /tmp/nginx-502.md --no-interactive
```
**Expected**: `✓ 0 created, 0 updated, 1 skipped`
No new file in `contributions/pending/`. Pending count unchanged.

---

## T-02: Dedup After Approval (D-5, US1)

**Setup**: Same document as T-01, but pending entry has been approved (`holmes kb confirm`).

**Action**: Run `holmes import /tmp/nginx-502.md --no-interactive` again.

**Expected**: `✓ 0 created, 0 updated, 1 skipped`
Match found in approved KB entries (existing behavior). Confirms approved-KB dedup still works after the change.

---

## T-03: Force Type Override — Pitfall on Guideline Doc (E-2, US2)

**Setup**: `redis-policy.md` — a Redis key expiry policy document that would naturally be classified as `guideline`.

**Action**:
```bash
holmes import /tmp/redis-policy.md --type pitfall --no-interactive
```

**Expected**:
- `✓ 1 created`
- Pending file frontmatter contains `type: pitfall`
- Verbose trace shows `type ← "pitfall"` (not `guideline`)

---

## T-04: Force Type in Dry-Run (E-2, US2)

**Setup**: Same document as T-03.

**Action**:
```bash
holmes import /tmp/redis-policy.md --type process --dry-run
```

**Expected**:
```
[DRY RUN] Planned actions:
  Would create: <title> (type: process)
```
No files written.

---

## T-05: No `--type` — Auto-Classification Unchanged (E-2, US2)

**Setup**: Any document with clear `pitfall` content.

**Action**:
```bash
holmes import /tmp/redis-oom.md --no-interactive
```

**Expected**: LLM classifies type freely. No regression from this change.

---

## T-06: Invalid `--type` Value (edge case)

**Action**:
```bash
holmes import /tmp/doc.md --type unknown_type
```

**Expected**: Immediate error before any LLM call:
```
Error: Invalid type 'unknown_type'. Valid values: pitfall, model, guideline, process, decision.
```

---

## T-07: Dedup with Corrupt Pending File (edge case)

**Setup**: Manually place a malformed `.md` file (no frontmatter) in `contributions/pending/`.

**Action**: Import any document.

**Expected**: Import completes normally. Corrupt pending file is silently skipped during hash scan. No crash.

---

## T-08: Multi-KP Document with Force Type (E-2, US2)

**Setup**: Three-incident document that produces 3 KPs.

**Action**:
```bash
holmes import /tmp/three-incidents.md --type pitfall --no-interactive
```

**Expected**: All 3 created pending entries have `type: pitfall`.
