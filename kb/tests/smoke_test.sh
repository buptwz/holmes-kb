#!/usr/bin/env bash
# smoke_test.sh — End-to-end smoke tests for KB Skill Mounting
#
# Covers quickstart.md scenarios 1, 4 (CLI-observable flows):
#   1. skill create → link → show → list → run → unlink
#   4. list with multiple skills, detect-commands
#
# Usage:
#   bash smoke_test.sh
#
# Exit code: 0 if all checks pass, 1 if any fail.

set -euo pipefail

PASS=0
FAIL=0
SKIP=0

# ---------------------------------------------------------------------------
# Setup: temporary KB directory
# ---------------------------------------------------------------------------

KB_DIR=$(mktemp -d /tmp/holmes-smoke-XXXXXX)
trap 'rm -rf "$KB_DIR"' EXIT

HOLMES="holmes"

# Check holmes CLI is available
if ! command -v "$HOLMES" &>/dev/null; then
  echo "[SKIP] 'holmes' not found on PATH — skipping smoke tests" >&2
  exit 0
fi

BASE_CMD=("$HOLMES" "--kb-path" "$KB_DIR")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

pass() { echo "[PASS] $1"; ((PASS++)); }
fail() { echo "[FAIL] $1"; ((FAIL++)); }
section() { echo ""; echo "=== $1 ==="; }

check_exit() {
  local desc="$1"; shift
  if "$@" &>/dev/null; then
    pass "$desc"
  else
    fail "$desc (exit code $?)"
  fi
}

check_output_contains() {
  local desc="$1"; local pattern="$2"; shift 2
  local out
  out=$("$@" 2>&1) || true
  if echo "$out" | grep -q "$pattern"; then
    pass "$desc"
  else
    fail "$desc (expected '$pattern' in output; got: $out)"
  fi
}

check_output_not_contains() {
  local desc="$1"; local pattern="$2"; shift 2
  local out
  out=$("$@" 2>&1) || true
  if echo "$out" | grep -q "$pattern"; then
    fail "$desc (unexpected '$pattern' in output)"
  else
    pass "$desc"
  fi
}

check_exit_nonzero() {
  local desc="$1"; shift
  if "$@" &>/dev/null 2>&1; then
    fail "$desc (expected non-zero exit, got 0)"
  else
    pass "$desc"
  fi
}

# ---------------------------------------------------------------------------
# Scenario 1: skill create → link → show → run → unlink
# ---------------------------------------------------------------------------

section "Scenario 1: skill create / link / show / list / run / unlink"

# 1a: create skill
check_output_contains \
  "skill create produces success message" \
  "Skill created" \
  "${BASE_CMD[@]}" kb skill create check-redis --desc "Check Redis connections"

# 1b: SKILL.md created
if [ -f "$KB_DIR/skills/check-redis/SKILL.md" ]; then
  pass "SKILL.md file exists"
else
  fail "SKILL.md file missing"
fi

# 1c: run.sh created
if [ -f "$KB_DIR/skills/check-redis/scripts/run.sh" ]; then
  pass "scripts/run.sh file exists"
else
  fail "scripts/run.sh file missing"
fi

# 1d: run.sh is executable
if [ -x "$KB_DIR/skills/check-redis/scripts/run.sh" ]; then
  pass "run.sh is executable"
else
  fail "run.sh is not executable"
fi

# 1e: Write a simple run.sh
cat > "$KB_DIR/skills/check-redis/scripts/run.sh" << 'RUNSH'
#!/usr/bin/env bash
echo "smoke-ok host=${SKILL_PARAM_HOST:-default}"
RUNSH
chmod +x "$KB_DIR/skills/check-redis/scripts/run.sh"

# 1f: Create a KB entry to link to
mkdir -p "$KB_DIR/pitfall/database"
cat > "$KB_DIR/pitfall/database/PT-DB-001.md" << 'ENTRY'
---
id: PT-DB-001
type: pitfall
title: Redis Connection Timeout
maturity: draft
category: database
tags: [redis]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Redis connections time out under load.

## Root Cause
Connection pool is too small.

## Resolution
Increase maxclients in redis.conf.
ENTRY

# 1g: link skill to entry
check_output_contains \
  "skill link produces success message" \
  "Linked skill" \
  "${BASE_CMD[@]}" kb skill link PT-DB-001 check-redis

# 1h: kb show has skills section
check_output_contains \
  "kb show PT-DB-001 shows Skills section" \
  "Skills" \
  "${BASE_CMD[@]}" kb show PT-DB-001

# 1i: kb show has skill name
check_output_contains \
  "kb show PT-DB-001 shows check-redis" \
  "check-redis" \
  "${BASE_CMD[@]}" kb show PT-DB-001

# 1j: skill list shows the skill
check_output_contains \
  "skill list shows check-redis" \
  "check-redis" \
  "${BASE_CMD[@]}" kb skill list

# 1k: skill run
check_output_contains \
  "skill run produces smoke-ok output" \
  "smoke-ok" \
  "${BASE_CMD[@]}" kb skill run check-redis

# 1l: skill run with param
check_output_contains \
  "skill run --param host=10.0.0.1 passes param" \
  "host=10.0.0.1" \
  "${BASE_CMD[@]}" kb skill run check-redis --param host=10.0.0.1

# 1m: skill run nonexistent → non-zero exit
check_exit_nonzero \
  "skill run nonexistent skill fails" \
  "${BASE_CMD[@]}" kb skill run nonexistent-skill-xyz

# 1n: skill unlink
check_output_contains \
  "skill unlink produces success message" \
  "Unlinked" \
  "${BASE_CMD[@]}" kb skill unlink PT-DB-001 check-redis

# 1o: after unlink, kb show no longer has Skills section
check_output_not_contains \
  "kb show after unlink has no Skills section" \
  "── Skills ──" \
  "${BASE_CMD[@]}" kb show PT-DB-001

# ---------------------------------------------------------------------------
# Scenario 4: detect-commands
# ---------------------------------------------------------------------------

section "Scenario 4: detect-commands"

RESOLUTION_TEXT="Run \$ redis-cli ping to check connectivity. Also try \`nginx -t\` to validate config."

# Create a skill for detection test
detect_out=$("${BASE_CMD[@]}" kb skill detect-commands --content "$RESOLUTION_TEXT" --json 2>&1) || true
if echo "$detect_out" | python3 -c "import sys, json; data=json.load(sys.stdin); sys.exit(0 if isinstance(data, list) else 1)" 2>/dev/null; then
  pass "detect-commands returns a JSON list"
else
  fail "detect-commands output is not a JSON list: $detect_out"
fi

# ---------------------------------------------------------------------------
# Scenario: old entry (no skill_refs) shows no skills section
# ---------------------------------------------------------------------------

section "Backward Compatibility: old entry without skill_refs"

mkdir -p "$KB_DIR/pitfall/network"
cat > "$KB_DIR/pitfall/network/PT-NET-001.md" << 'OLDENTRY'
---
id: PT-NET-001
type: pitfall
title: DNS Failure
maturity: draft
category: network
tags: [dns]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
DNS queries fail.

## Root Cause
Misconfigured resolver.

## Resolution
Check /etc/resolv.conf.
OLDENTRY

check_output_not_contains \
  "kb show old entry has no Skills section" \
  "── Skills ──" \
  "${BASE_CMD[@]}" kb show PT-NET-001

check_exit \
  "kb show old entry exits 0" \
  "${BASE_CMD[@]}" kb show PT-NET-001

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "============================================"
echo "Smoke Test Results: PASS=$PASS  FAIL=$FAIL  SKIP=$SKIP"
echo "============================================"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
