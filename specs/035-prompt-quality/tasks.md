# Tasks: Import Pipeline Prompt Quality Optimization

**Feature**: 035-prompt-quality | **Branch**: `035-prompt-quality`

## Phase 1: Setup

- [X] T001 Verify baseline test suite passes (`pytest kb/tests/ -q`) and record count

## Phase 2: US1 — Section Structure Integrity (P1) — Extractor Rewrite

- [X] T002 [US1] Rewrite `EXTRACTOR_SYSTEM_PROMPT` in `kb/holmes/kb/agent/phases/extractor.py`
  - Structured sections: ## Role / ## Task / ## Constraints / ## Output Format
  - Single authoritative TYPE-SECTION table (remove duplicate pitfall-only template)
  - One complete example per KB entry type (pitfall/model/guideline/process/decision)
  - Merge two overlapping "CRITICAL FOR ## Resolution" blocks into one DO/DON'T list
  - All original rules preserved; token count must be ≤ original
- [X] T003 [US1] Run `pytest kb/tests/ -q` — all tests must still pass

## Phase 3: US2 — Runner System Prompt (P2)

- [X] T004 [US2] Rewrite `_IMPORT_SYSTEM_PROMPT` in `kb/holmes/kb/agent/runner.py`
  - Structured sections: ## Role / ## Task / ## Constraints / ## Output Format
  - Add explicit "Process ALL N drafts before finishing" directive (FR-008)
  - Clarify evaluate_skill / create_skill_for_entry call criteria
  - All 7 original steps preserved
- [X] T005 [US2] Run `pytest kb/tests/ -q` — all tests must still pass

## Phase 4: US3 — Classification Consistency (P3) — Classifier Rewrite

- [X] T006 [US3] Rewrite `_CLASSIFIER_SYSTEM_PROMPT` in `kb/holmes/kb/agent/phases/classifier.py`
  - Structured sections: ## Role / ## Task / ## Constraints / ## Output Format
  - Add distinguishing-characteristics table for guideline vs process vs decision
  - Convert paragraph examples to compact table (source feature → label)
  - All original 5 type labels and non_kb definition preserved
- [X] T007 [US3] Run `pytest kb/tests/ -q` — all tests must still pass

## Phase 5: Reader Rewrite (P4)

- [X] T008 Rewrite `READER_SYSTEM_PROMPT` in `kb/holmes/kb/agent/phases/reader.py`
  - Structured sections: ## Role / ## Task / ## Constraints
  - All original rules preserved (coverage threshold, KP scoping, tool usage)
  - READER_COMPACT_PROMPT: leave unchanged (defer unless 15% token target not met)
- [X] T009 Run `pytest kb/tests/ -q` — all tests must still pass

## Phase 6: US2 — Field Fabrication Prevention (P2) — Verifier Rewrite

- [X] T010 [US2] Rewrite ContentVerifier system prompt in `kb/holmes/kb/agent/verifier.py`
  - Extract inline string to named constant `_VERIFIER_SYSTEM_PROMPT`
  - Add explicit rule: return empty `verified_fields` list when source support absent
  - Add strict output schema specification
  - Original fields-to-check (title, root_cause, resolution) preserved
- [X] T011 [US2] Run `pytest kb/tests/ -q` — all tests must still pass

## Phase 7: Polish & Validation

- [X] T012 Token count check: verify aggregate reduction ≥ 15% across all rewritten prompts
- [X] T013 Final `pytest kb/tests/ -q` — confirm all tests pass (SC-005 gate)

## Dependencies

T002 → T003 → T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011 → T012 → T013

All tasks are sequential (each rewrite validated before next begins).

## Implementation Strategy

Each prompt rewrite is independently shippable (FR-010). Complete and validate one before
starting the next. If any test fails after a rewrite, revert that component and diagnose
before proceeding.
