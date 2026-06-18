# Quickstart & Integration Scenarios (018)

## Setup

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/kb
python -m pytest tests/ -q   # baseline: all 582 tests pass
```

---

## Scenario 1: Chinese-Header Document (Root A Normalizer)

**Input**: Incident doc with `## 症状`, `## 根因`, `## 解决方案` headers produced by deepseek-v4-flash.

**Expected output after fix**:
```
✓ 1 created | skill: 1 generated
  [Kubernetes OOMKilled 事故] type: pitfall, category: kubernetes
  tags: [kubernetes, oomkilled, memory, limit, pod]
  Normalizer: header "## 症状" → "## Symptoms"; header "## 根因" → "## Root Cause"; header "## 解决方案" → "## Resolution"
  Normalizer: category "kubernetes" accepted (expanded schema)
```

**Verify**:
```bash
cat ~/.holmes-kb/contributions/pending/pending-*.md | grep "^##"
# Must show: ## Symptoms, ## Root Cause, ## Resolution (English)
```

---

## Scenario 2: Category kubernetes Now Valid (Root B)

**Input**: Any Kubernetes incident document.

**Expected output**:
```
✓ 1 created | category: kubernetes
```

**Verify**:
```bash
holmes --kb-path ~/.holmes-kb kb pending
# Shows category: kubernetes in entry
python -m pytest tests/test_schema.py -q -k "kubernetes"
# Passes
```

---

## Scenario 3: Skill Generation Is Model-Agnostic (Root C)

**Input**: Incident with `kubectl delete pod {POD_NAME} -n {NAMESPACE}` in Resolution.

**With gpt-4o** → `run.sh` contains exact command.
**With deepseek-v4-flash** → `run.sh` contains same exact command.

**Verify**:
```bash
# gpt-4o run:
cat ~/.holmes-kb/skills/skill-*/scripts/run.sh | grep "kubectl delete pod"
# deepseek run (same input):
cat ~/.holmes-kb/skills/skill-*/scripts/run.sh | grep "kubectl delete pod"
# Both must be identical
bash -n ~/.holmes-kb/skills/skill-*/scripts/run.sh   # syntax check passes

cat ~/.holmes-kb/skills/skill-*/SKILL.md | grep -A5 "params:"
# Must show: POD_NAME, NAMESPACE
```

---

## Scenario 4: Meeting Notes Rejected (Root D)

**Input**: Q2 tech team meeting notes.

**Expected output**:
```
✓ 0 created | 0 skill
  Warning: non-kb document classified as "meeting notes" — skipped
```

**Verify**:
```bash
holmes import meeting-notes.md --no-interactive 2>&1 | grep "non-kb"
# Returns: "Warning: non-kb document..."
# Check pending count unchanged
```

---

## Scenario 5: Runbook Not Over-Split (Root D)

**Input**: CrashLoopBackOff 5-step runbook.

**Expected output**:
```
✓ 1 created | skill: 1 generated
  Reader: 1 knowledge point identified (runbook guidance applied)
  [CrashLoopBackOff 应急排查与恢复流程] type: process
```

**Verify**:
```bash
holmes import crashloop-runbook.md --no-interactive --verbose 2>&1 | grep "knowledge points"
# Must show: 1 knowledge points identified (not 4-7)
```

---

## Scenario 6: Pitfall Resolution Verbatim Restored (Root E)

**Input**: Incident where Extractor rewrote commands; Verifier CLEARed them.

**Expected output**:
```
✓ 1 created | skill: 1 generated
  [Nginx 502] type: pitfall
  Warning: resolution auto-recovered from source for kp-1
  Resolution contains: [auto-recovered from source] kubectl rollout restart ...
```

**Verify**:
```bash
cat ~/.holmes-kb/contributions/pending/pending-*.md | grep "auto-recovered"
# Should show the recovered command
```

---

## Scenario 7: API Key Error User-Friendly (E-5)

```bash
holmes config set api_key INVALID_KEY
holmes import some-doc.md 2>&1
# Must show: "Error: Authentication failed — API key rejected..."
# Must NOT show raw JSON
```

---

## Scenario 8: Dry-Run Preview (E-4)

```bash
holmes import runbook.md --dry-run 2>&1
# Must show: "[DRY RUN] Would process: runbook.md (~1 knowledge points estimated)"
# For non-kb doc:
holmes import meeting-notes.md --dry-run 2>&1
# Must show: "[DRY RUN] Would reject: meeting-notes.md — non-kb document"
```

---

## Regression Validation

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/kb
python -m pytest tests/ -q
# All 582+ tests pass (new tests add to total)
python -m pytest tests/test_normalizer.py tests/test_classifier.py -v
# New test files all pass
```
