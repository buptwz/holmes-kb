# Quickstart: Import Pipeline v2 Report Bug Fixes

## Test Scenario 1 — CommandCandidate crash is gone

```bash
# Document with shell commands in Resolution
holmes import /tmp/holmes-v15-docs/TC-M01-single-kp.md --no-interactive

# Expected:
# ✓ 1 created, 0 updated, 0 skipped | skill: N generated, 0 linked
# Exit code: 0
# No "expected string or bytes-like object" error
```

## Test Scenario 2 — {PARAM} extracted into SKILL.md

```bash
holmes import /tmp/holmes-v15-docs/TC-T03-process-runbook.md --no-interactive
cat ~/.holmes-kb/skills/k8s-pod-crashloopbackoff-*/SKILL.md | grep -A5 "params:"
# Expected: params: block with NAMESPACE, DEPLOYMENT_NAME etc.
cat ~/.holmes-kb/skills/k8s-pod-crashloopbackoff-*/scripts/run.sh
# Expected: $NAMESPACE, $DEPLOYMENT_NAME variables (not raw {NAMESPACE})
```

## Test Scenario 3 — --type override is respected

```bash
holmes import /tmp/holmes-v15-docs/TC-M01-single-kp.md --type guideline --no-interactive
grep "^type:" ~/.holmes-kb/contributions/pending/pending-$(date +%Y%m%d)*.md | head -1
# Expected: type: guideline
```

## Test Scenario 4 — Re-import is a no-op

```bash
holmes import /tmp/holmes-v15-docs/TC-M01-single-kp.md --no-interactive  # first import
holmes import /tmp/holmes-v15-docs/TC-M01-single-kp.md --no-interactive  # second import
# Expected second run: ✓ 0 created, 0 updated, 1 skipped
```

## Test Scenario 5 — Skill creation gate is respected (interactive)

```bash
printf "n\n" | holmes import /tmp/holmes-v15-docs/TC-S02-optional-skill.md
# Expected: Prompt appears, user answers "n", NO skill directory created
ls ~/.holmes-kb/skills/ | grep spring-boot-set-log-level
# Expected: no output (skill not created)
```

## Test Scenario 6 — KB data is clean

```bash
grep "^## " ~/.holmes-kb/pitfall/database/PT-DB-002.md
# Expected: ## Symptoms, ## Root Cause, ## Resolution (each exactly once)

grep "body_additions" ~/.holmes-kb/pitfall/database/PT-DB-005.md
# Expected: no output

ls ~/.holmes-kb/pitfall/database/PT-DB-TEST2.md 2>&1
# Expected: No such file or directory

ls ~/.holmes-kb/pitfall/network/PT-NET-TEST.md 2>&1
# Expected: No such file or directory
```
