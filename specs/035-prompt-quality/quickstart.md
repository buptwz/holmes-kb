# Quickstart: Verifying Prompt Quality Rewrites

**Phase**: 1 | **Date**: 2026-06-18 | **Feature**: 035-prompt-quality

This document describes how to verify each rewritten prompt component before merging.

---

## Prerequisite: Baseline Test Run

Before modifying any prompt, record the current test state:

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/kb
pytest tests/ -q 2>&1 | tail -5
```

All tests must pass. Note the total count (e.g., "284 passed"). Any rewrite that reduces
this count is rejected per SC-005.

---

## Per-Component Verification Workflow

### Step 1: Rewrite the prompt constant

Edit the target file. The new prompt MUST have:
- `## Role` section (one sentence, what the agent is)
- `## Task` section (numbered steps, imperative sentences)
- `## Constraints` section (DO/DON'T list)
- `## Output Format` section (exact schema or example)
- At least one concrete example per KB entry type (Extractor only, per FR-003)

### Step 2: Run regression tests

```bash
pytest tests/ -q
```

If any previously-passing test now fails → **revert and diagnose before proceeding**.

### Step 3: Semantic traceability check

Open the old and new prompt side-by-side. For every instruction in the new version,
annotate with a comment referencing the equivalent instruction in the old version.
If any new instruction lacks an original counterpart → **remove it** (would violate FR-000).

### Step 4: Token count check (SC-003)

Token count proxy (characters / 4):

```python
old_tokens = len(OLD_PROMPT) / 4
new_tokens = len(NEW_PROMPT) / 4
reduction_pct = (old_tokens - new_tokens) / old_tokens * 100
print(f"Token reduction: {reduction_pct:.1f}%")
```

Target: each rewritten prompt should be shorter or equal in length. The aggregate
reduction across all components must reach ≥15%.

---

## Acceptance Scenario Tests (Manual)

### US1 — Section Structure Integrity

Import each of the following document types and check that the pending entry contains
ONLY the sections specified in `TYPE_REQUIRED_SECTIONS`:

| Document Type | Expected Sections | Forbidden Sections |
|---------------|------------------|--------------------|
| pitfall | `## Symptoms`, `## Root Cause`, `## Resolution` | `## Decision`, `## Context`, `## Overview` |
| decision | `## Context`, `## Decision`, `## Rationale` | `## Symptoms`, `## Root Cause`, `## Resolution` |
| process | `## Purpose`, `## Steps`, `## Outcome` | `## Symptoms`, `## Root Cause`, `## Resolution` |
| model | `## Overview`, `## Key Concepts`, `## Usage` | `## Symptoms`, `## Root Cause`, `## Resolution` |
| guideline | `## Context`, `## Guideline`, `## Rationale` | `## Symptoms`, `## Root Cause`, `## Resolution` |

**Pass criterion**: 5/5 entries have correct sections (SC-001).

### US2 — Field Fabrication Prevention

1. Create a short test document that describes symptoms and root cause but provides NO
   resolution steps.
2. Run `holmes import <file>`.
3. Inspect the pending entry. `## Resolution` MUST be empty or absent.

**Pass criterion**: Resolution section not populated with invented steps (SC-002).

### US3 — Classification Accuracy

1. Prepare 10 incident reports with `## Symptoms`, `## Root Cause`, `## Resolution` sections.
2. Run `holmes import --dir <dir>` without `--type`.
3. Inspect all pending entries. At least 9/10 must be type `pitfall`.

**Pass criterion**: ≥9/10 correctly typed (SC-004).

---

## Edge Cases to Exercise

| Edge Case | How to Test |
|-----------|-------------|
| Chinese-language source | Import a Chinese post-mortem; verify entry body is in Chinese |
| Very short document (<200 chars) | Import a one-line file; classifier should return `non_kb` |
| Missing tool call | Temporarily corrupt a tool name; pipeline must report warning, not silently pass |
