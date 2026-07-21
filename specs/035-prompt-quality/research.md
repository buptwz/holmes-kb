# Research: Import Pipeline Prompt Quality Optimization

**Phase**: 0 | **Date**: 2026-06-18 | **Feature**: 035-prompt-quality

## Inventory: Current Prompt Components

All 6 prompt components have been located and audited.

| # | Component | File | Constant Name | Current Token Estimate | Priority |
|---|-----------|------|---------------|----------------------|----------|
| 1 | ExtractorAgent | `kb/holmes/kb/agent/phases/extractor.py` | `EXTRACTOR_SYSTEM_PROMPT` | ~350 tokens | P1 |
| 2 | ImportAgentRunner | `kb/holmes/kb/agent/runner.py` | `_IMPORT_SYSTEM_PROMPT` | ~180 tokens | P2 |
| 3 | DocumentClassifier | `kb/holmes/kb/agent/phases/classifier.py` | `_CLASSIFIER_SYSTEM_PROMPT` | ~200 tokens | P3 |
| 4 | ReaderAgent | `kb/holmes/kb/agent/phases/reader.py` | `READER_SYSTEM_PROMPT` | ~150 tokens | P4 |
| 4b | ReaderAgent compact | `kb/holmes/kb/agent/phases/reader.py` | `READER_COMPACT_PROMPT` | ~450 tokens | P4b |
| 5 | ContentVerifier | `kb/holmes/kb/agent/verifier.py` | inline in `verify()` | ~80 tokens | P5 |
| 6 | SkillAdvisor | `kb/holmes/kb/agent/skill_advisor.py` | *none* | 0 | P6 (see Finding 1) |

## Key Findings

### Finding 1 — SkillAdvisor Has No LLM Prompt (FR-009 is Moot)

**Decision**: SkillAdvisor is purely deterministic Python code. It does NOT call the LLM.
Recommendations (RECOMMENDED / LINK / SKIP) are derived from rule-based logic:
- Has existing `skill_refs` → LINK
- Similar skill found by Jaccard similarity → LINK
- Resolution section empty → SKIP
- Skill markers present → RECOMMENDED (Form B)
- Resolution non-empty → RECOMMENDED (Form A)

FR-009 ("SkillAdvisor prompt MUST provide explicit thresholds") is therefore implemented in
code, not prompts. The thresholds are already explicit constants in the module. No prompt
rewrite is needed for SkillAdvisor.

**Rationale**: Changing a deterministic evaluator to an LLM-based one would violate FR-000
(semantic equivalence) and constitute a new behaviour, which is explicitly out of scope.

**Action**: Skip SkillAdvisor prompt rewrite. Priority 6 is effectively a no-op.
The runner system prompt (Priority 2) will be improved to give clear guidance on when to
call `evaluate_skill` and `create_skill_for_entry` — this addresses the spirit of FR-009.

---

### Finding 2 — Root Causes of Current Prompt Quality Issues

**Section cross-contamination (P1 / US1)**:
- Extractor prompt mentions pitfall sections first in its structure example, then TYPE-SECTION
  MAPPING in a separate rule block. The LLM must mentally reconcile two representations.
- Decision: provide one authoritative TYPE-SECTION table, remove the redundant pitfall example
  from the structural template, and add a concrete example for each type.

**Field fabrication (P2 / US2)**:
- ContentVerifier system prompt is inline (not a named constant), lacks a strict output schema,
  and doesn't explicitly instruct the model to return an empty `verified_fields` list when
  source support is absent.
- Decision: extract to a named constant, add schema specification, add explicit "return empty
  list if unsupported" instruction.

**Misclassification (P3 / US3)**:
- Classifier prompt uses paragraph-style examples. `guideline` vs `process` vs `decision`
  distinction is implicit and relies on the model inferring from vague examples.
- Decision: add a distinguishing-characteristics table, restructure examples as concise
  bullet pairs (source content → classification label).

**Token waste (P4 / US4)**:
- Extractor repeats "CRITICAL FOR ## Resolution" twice with overlapping content.
- Reader compact prompt is 450 tokens but necessary for semantic continuity — minimal
  optimization possible; focus reduction on Extractor and Classifier.
- Decision: merge duplicate CRITICAL blocks into a single rule set; trim narrative preamble.

---

### Finding 3 — Claude Code Prompt Style (Reference)

The spec references Claude Code's system prompt style. Key structural patterns:

1. **Labeled sections**: `## Role`, `## Task`, `## Constraints`, `## Output Format`
2. **Explicit DO/DON'T lists**: each rule on its own line, starting with DO/DON'T
3. **Few-shot examples**: inline, concrete, per-category examples
4. **Concise imperatives**: short action sentences, no narrative padding

Applied to this project: each rewritten prompt will follow the 4-section structure.
DO/DON'T lists replace current "IMPORTANT RULES" paragraphs. Per-type examples replace
the single structural template.

---

### Finding 4 — Semantic Equivalence Strategy

FR-000 mandates that every rewrite is semantically equivalent. Verification approach:

1. **Primary gate**: SC-005 — all existing passing tests must still pass. Run `pytest kb/tests/`
   before and after each component rewrite. Any new failure blocks the rewrite.
2. **Secondary gate**: SC-006 — reviewer maps every instruction in the new version to a
   corresponding instruction in the original. Maintained as inline comments during review.
3. **Token measurement**: For SC-003, compare token counts using the Anthropic tokenizer or
   character count proxy (1 token ≈ 4 chars) on the 5 reference import documents.

---

### Finding 5 — READER_COMPACT_PROMPT Scope

The `READER_COMPACT_PROMPT` (~450 tokens) is Chinese-language text used for semantic history
compaction. It is large by design — it serves as a structured template for the LLM to fill in.
Token reduction here risks losing compaction quality. Recommendation: treat this as low-priority
and defer token optimization unless the other 5 components already meet SC-003's 15% target.

## Decisions

| Decision | What Was Chosen | Rationale | Alternatives Rejected |
|----------|----------------|-----------|----------------------|
| D-1: SkillAdvisor | Skip prompt rewrite | Code is deterministic, no LLM calls | Converting to LLM-based violates FR-000 |
| D-2: Extractor structure | Replace dual representation with one TYPE-SECTION table + per-type examples | Reduces ambiguity for the model | Keeping dual representation — root cause of P1 failures |
| D-3: Verifier | Extract inline string to named constant + strict schema | Enables testing and PR review | Keep inline — blocks unit testing of prompt content |
| D-4: READER_COMPACT_PROMPT | Defer optimization unless 15% target missed without it | Large but necessary for compaction quality | Aggressive reduction — risks compaction failures |
| D-5: Semantic equivalence | pytest test suite as primary gate | Automated, objective, already exists | Manual review only — too slow and subjective |
