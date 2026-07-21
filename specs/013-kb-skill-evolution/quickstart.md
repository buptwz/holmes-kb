# Quickstart: Holmes KB Autonomous Import Agent

**Feature**: `013-kb-skill-evolution` | **Date**: 2026-06-07

---

## Scenario 1: Import a single incident report (US1)

```bash
# Write a test incident document
cat > /tmp/test-incident.md << 'EOF'
PostgreSQL OOM Crash — 2026-05-15

Service became unresponsive. DB logs showed:
  FATAL: out of memory
  ERROR: could not resize shared memory segment

Root cause: shared_buffers was set to 4GB on a server with only 6GB RAM.
PostgreSQL OOM-killed by kernel when cache pressure peaked.

Resolution:
1. Reduce shared_buffers to 1.5GB: ALTER SYSTEM SET shared_buffers = '1536MB';
2. Reload config: SELECT pg_reload_conf();
3. Monitor memory: watch -n5 'free -h'
EOF

# Import it
holmes --kb-path ~/.holmes-kb import /tmp/test-incident.md
```

**Expected output**:
```
Analyzing source...
✓ Knowledge point 1: pitfall/database — "PostgreSQL OOM Crash"
  Dedup check: no match found
  Skill assessment: Recommended (3 steps, parameters present)
  Confirm create skill: pg-oom-recovery? [Y/n]: Y
  Writing entry... done (pending-20260607-103001-ab12)
  Skill created: pg-oom-recovery (agent_created: true)

Summary: 1 created, 0 updated, 0 skipped | skill: 1 generated, 0 merged | 0 suggestions
```

---

## Scenario 2: Idempotency — reimport same document (US3)

```bash
# Run import a second time on the same file
holmes --kb-path ~/.holmes-kb import /tmp/test-incident.md
```

**Expected output**:
```
Analyzing source...
✓ skipped (already imported, source_hash: a1b2c3d4e5f60123)

Summary: 0 created, 0 updated, 1 skipped | skill: 0 generated | 0 suggestions
```

---

## Scenario 3: Dry-run preview (US6)

```bash
holmes --kb-path ~/.holmes-kb import --dry-run /tmp/test-incident.md
```

**Expected output**:
```
[DRY RUN] Analyzing source...
  Would create: pitfall/database — "PostgreSQL OOM Crash"
  Would generate skill: pg-oom-recovery
  No files written.
```

Verify no files changed:
```bash
cd ~/.holmes-kb && git diff  # empty
```

---

## Scenario 4: Batch import a directory (US1 + US3)

```bash
holmes --kb-path ~/.holmes-kb import --dir ./runbooks/ --no-interactive
```

**Expected output**:
```
Processing 5 files from ./runbooks/...
[1/5] db-backup.md — ✓ created (pending-20260607-103001-ab12)
[2/5] network-debug.md — ✓ created (pending-20260607-103002-cd34)
[3/5] redis-flush.md — ⚠ skipped (already imported)
[4/5] broken.txt — ✗ error: content too short (12 chars, minimum 50)
[5/5] deploy-process.md — ✓ created (pending-20260607-103003-ef56)

Batch summary: 3 created, 0 updated, 1 skipped | skill: 2 generated | 1 error
```

---

## Scenario 5: Low-confidence interactive gate (US4)

```bash
holmes --kb-path ~/.holmes-kb import /tmp/ambiguous-note.md
```

**Expected prompt**:
```
Analyzing source...
  I think this is: guideline/networking (confidence: 0.58)
  Correct? [Y/n/other type]: model
  Confirmed: type=model
  Writing entry... done
Summary: 1 created | 0 suggestions
```

---

## Scenario 6: Semantic dedup — merge update (US3)

Given an existing KB entry `PT-DB-001` about "PostgreSQL OOM" already in the KB:

```bash
# New document with same root cause, additional resolution step
holmes --kb-path ~/.holmes-kb import /tmp/pg-oom-followup.md
```

**Expected prompt**:
```
Analyzing source...
  Similar entry found: PT-DB-001 "PostgreSQL OOM Crash"
  Update it or create new? [u=update/n=new]: u
  Merging new content into PT-DB-001...
  Updated PT-DB-001 (updated_at refreshed)
Summary: 0 created, 1 updated, 0 skipped
```

---

## Scenario 7: Self-verification catches hallucinated content (US2)

Given a minimal input with no commands:
```bash
echo "The database ran out of memory. Restarting it fixed the problem." | holmes --kb-path ~/.holmes-kb import -
```

**Expected output**:
```
Analyzing source...
  Self-verification: Resolution field cleared (no source support for commands)
  ⚠ Warning: Root Cause field has low confidence (0.42) — marked as draft
  Writing entry... done (pending-20260607-103004-gh78, maturity: draft)
Summary: 1 created | 1 warning: root_cause requires manual review
```

---

## Scenario 8: Skill curation suggestions (US5)

```bash
holmes --kb-path ~/.holmes-kb import /tmp/pg-monitoring.md --verbose
```

**Expected curator output** (at end):
```
  Curator (same category: database):
    merge_candidate: "check-pg-connections" and "pg-connection-monitor" (Jaccard: 0.71; LLM: same intent)
    update_candidate: "pg-oom-recovery" (patch_count=0; PT-DB-001 updated 2026-06-01)

  2 suggestions added to report.
```
