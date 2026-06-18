# Quickstart: KB Access Control & Governance

**Feature**: 003-kb-governance
**Date**: 2026-06-01

Integration scenarios for testing all 4 user stories independently.

---

## Setup

```bash
# Ensure KB is initialized with at least one verified entry
export HOLMES_KB_PATH=/home/wangzhi/holmes-kb

# Seed test data (maintainer places file directly — no write-entry command exists)
mkdir -p $HOLMES_KB_PATH/pitfall/database
cat > $HOLMES_KB_PATH/pitfall/database/PT-DB-001.md << 'EOF'
---
id: PT-DB-001
type: pitfall
title: Redis connection timeout under load
category: database
tags: [redis, timeout, connection-pool]
maturity: verified
evidence:
  - session_id: "seed-session-001"
    contributor: "maintainer"
    date: "2025-01-01T00:00:00+00:00"
    context: "initial seed"
contributors: [maintainer]
created_at: 2025-01-01T00:00:00+00:00
updated_at: 2025-01-01T00:00:00+00:00
---

## Symptoms
Connection pool exhaustion under high load.

## Root Cause
Default pool size too small.

## Resolution
Increase max_connections in redis config.
EOF
```

---

## US1: Read-Only Protection

**Test**: There is no write-entry command — all writes go through pending. Duplicate title is rejected.

```bash
# Test 1: write-entry does not exist — attempt returns command not found
holmes --kb-path $HOLMES_KB_PATH kb write-entry 2>&1 || true
# Expected: "No such command 'write-entry'."

# Test 2: Read → should succeed
holmes --kb-path $HOLMES_KB_PATH kb show PT-DB-001
# Expected exit code: 0

# Test 3: Duplicate title attempt → should be rejected
holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --content "$(cat << 'EOF'
---
type: pitfall
title: Redis connection timeout under load
category: database
tags: [redis]
maturity: draft
created_at: 2026-06-01T00:00:00+00:00
updated_at: 2026-06-01T00:00:00+00:00
---

## Symptoms
Same title as PT-DB-001.

## Root Cause
Test.

## Resolution
Test.
EOF
)"
# Expected exit code: 1
# Expected output: {"error": "Duplicate title: 'Redis connection timeout under load' matches PT-DB-001..."}

# Test 4: Use --corrects to submit correction (correct flow for modifying verified entry)
holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --corrects PT-DB-001 \
  --content "$(cat $HOLMES_KB_PATH/pitfall/database/PT-DB-001.md)"
# Expected exit code: 0, returns {"pending_id": "pending-..."}
```

---

## US2: Agent Deposits to Pending

**Test**: Agent writes new knowledge → appears in pending, confirm moves it to public.

```bash
# Agent writes to pending
PENDING_ID=$(holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --content "$(cat << 'EOF'
---
type: pitfall
title: MySQL deadlock on concurrent inserts
category: database
tags: [mysql, deadlock, transaction]
maturity: draft
---

## Symptoms
App hangs intermittently under high write concurrency.

## Root Cause
Two transactions acquiring row locks in different order.

## Resolution
Use SELECT ... FOR UPDATE in consistent order; or use single writer queue.
EOF
)" )

echo "Pending ID: $PENDING_ID"

# Verify it appears in pending list
holmes --kb-path $HOLMES_KB_PATH kb pending --json | jq '.[] | select(.id == "'$PENDING_ID'")'
# Expected: entry with id=$PENDING_ID, maturity=draft

# Verify public area unchanged
holmes --kb-path $HOLMES_KB_PATH kb list --type pitfall --json | \
  jq '.[] | select(.title | contains("MySQL deadlock"))'
# Expected: empty (not yet in public)

# Maintainer confirms
holmes --kb-path $HOLMES_KB_PATH kb confirm $PENDING_ID
# Expected: "✓ Entry confirmed: PT-DB-002" (or next sequential ID)

# Verify no longer in pending
holmes --kb-path $HOLMES_KB_PATH kb pending --json | jq '.[] | select(.id == "'$PENDING_ID'")'
# Expected: empty

# Test reject flow
PENDING_ID2=$(holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --content "$(cat /tmp/draft-entry.md)")
holmes --kb-path $HOLMES_KB_PATH kb reject $PENDING_ID2 --reason "test rejection"
# Expected: "✓ Rejected: pending-..."
```

---

## US3: Correction Workflow

**Test**: Submit correction for PT-DB-001, confirm replaces original with snapshot preserved.

```bash
# Submit correction proposal
CORRECTION_ID=$(holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --corrects PT-DB-001 \
  --content "$(cat << 'EOF'
---
type: pitfall
title: Redis connection timeout under load
category: database
tags: [redis, timeout, connection-pool, keepalive]
maturity: draft
---

## Symptoms
Connection pool exhaustion under high load; also occurs with long-idle connections.

## Root Cause
Default pool size too small; TCP keepalive not configured.

## Resolution
Increase max_connections AND enable tcp_keepalive in redis config.
EOF
)" )

echo "Correction Pending ID: $CORRECTION_ID"

# Verify pending has corrects field
holmes --kb-path $HOLMES_KB_PATH kb pending --show $CORRECTION_ID | \
  grep "corrects:"
# Expected: "corrects: PT-DB-001"

# Verify original unchanged
holmes --kb-path $HOLMES_KB_PATH kb show PT-DB-001 | grep "Resolution"
# Expected: original resolution text

# Maintainer confirms correction
holmes --kb-path $HOLMES_KB_PATH kb confirm $CORRECTION_ID
# Expected: "✓ Correction applied: PT-DB-001 (snapshot: .history/PT-DB-001-....md)"

# Verify original content replaced
holmes --kb-path $HOLMES_KB_PATH kb show PT-DB-001 | grep "keepalive"
# Expected: new content with "keepalive"

# Verify snapshot exists
ls $HOLMES_KB_PATH/.history/PT-DB-001-*.md
# Expected: at least one snapshot file

# Test reject correction
CORRECTION_ID2=$(holmes --kb-path $HOLMES_KB_PATH kb write-pending \
  --corrects PT-DB-001 \
  --content "$(cat /tmp/test-entry.md)")
holmes --kb-path $HOLMES_KB_PATH kb reject $CORRECTION_ID2
# Verify PT-DB-001 unchanged after rejection
```

---

## US4: Maturity Decay

**Test**: Seed an entry with old evidence date, run decay, verify maturity drops.

```bash
# Seed a proven entry with old evidence date (13 months ago)
mkdir -p $HOLMES_KB_PATH/model
cat > $HOLMES_KB_PATH/model/MOD-001.md << 'EOF'
---
id: MOD-001
type: model
title: Circuit Breaker Pattern
category: null
tags: [resilience, circuit-breaker]
maturity: proven
evidence:
  - session_id: "old-session-001"
    contributor: "alice"
    date: "2025-01-01T00:00:00+00:00"
    context: "initial validation"
contributors: [alice]
created_at: 2024-01-01T00:00:00+00:00
updated_at: 2024-01-01T00:00:00+00:00
---

## Definition
A circuit breaker prevents cascading failures by stopping requests to failing services.
EOF

# Dry-run decay check
holmes --kb-path $HOLMES_KB_PATH kb decay --dry-run --json
# Expected: MOD-001 in changes list (proven → verified, 13+ months)

# Run actual decay
holmes --kb-path $HOLMES_KB_PATH kb decay --json
# Expected: {"scanned": N, "decayed": 1, "changes": [{"id": "MOD-001", ...}]}

# Verify maturity changed
holmes --kb-path $HOLMES_KB_PATH kb show MOD-001 | grep "maturity:"
# Expected: "maturity: verified"

# Verify decay logged
tail -5 $HOLMES_KB_PATH/contributions/log.md | grep "decay"
# Expected: log entry with "decay: unreferenced N months"

# Test update-refs (session-end evidence append)
holmes --kb-path $HOLMES_KB_PATH kb update-refs \
  --ids PT-DB-001 \
  --session-id "session-test-$(date +%s)" \
  --contributor "alice" \
  --context "US4 test"
# Expected: {"updated": ["PT-DB-001"], "skipped_duplicate": [], "not_found": [], "maturity_promoted": [...]}
```
