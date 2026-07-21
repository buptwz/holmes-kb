# Data Model: Import Pipeline Prompt Quality Optimization

**Phase**: 1 | **Date**: 2026-06-18 | **Feature**: 035-prompt-quality

## Overview

This feature modifies string constants only. There are no new persistent entities,
no schema changes, and no database migrations. This document captures the logical
model of the prompt components being rewritten — useful for task decomposition and
semantic-traceability review.

---

## Entity: PromptComponent

A named string constant used as a system or user prompt in one pipeline stage.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human identifier (e.g. "ExtractorAgent") |
| `constant_name` | string | Python constant (e.g. `EXTRACTOR_SYSTEM_PROMPT`) |
| `file_path` | string | Source file containing the constant |
| `scope` | enum | `system` (LLM role) or `user` (per-call context) |
| `priority` | int | Rewrite order per FR-010 (1 = highest) |
| `approx_tokens` | int | Estimated input token count before rewrite |

### Instances

| name | constant_name | file_path | scope | priority | approx_tokens |
|------|---------------|-----------|-------|----------|--------------|
| ExtractorAgent | `EXTRACTOR_SYSTEM_PROMPT` | `agent/phases/extractor.py` | system | 1 | 350 |
| ImportAgentRunner | `_IMPORT_SYSTEM_PROMPT` | `agent/runner.py` | system | 2 | 180 |
| DocumentClassifier | `_CLASSIFIER_SYSTEM_PROMPT` | `agent/phases/classifier.py` | system | 3 | 200 |
| ReaderAgent | `READER_SYSTEM_PROMPT` | `agent/phases/reader.py` | system | 4 | 150 |
| ReaderCompact | `READER_COMPACT_PROMPT` | `agent/phases/reader.py` | user | 4b | 450 |
| ContentVerifier | *(inline in `verify()`)* | `agent/verifier.py` | system | 5 | 80 |
| SkillAdvisor | *(none — deterministic)* | `agent/skill_advisor.py` | — | 6 (skip) | 0 |

---

## Entity: PromptQualityDimension

One of four measurable axes evaluated before and after each rewrite.

| Dimension | Measurement | Target |
|-----------|-------------|--------|
| Instruction-following rate | % section-structure matches declared type (SC-001) | 100% |
| Hallucination rate | % fabricated fields flagged by verifier (SC-002) | ≥90% detection |
| Token count | Input tokens per standard run (SC-003) | ≥15% reduction |
| Tool-call completeness | All N drafts processed (FR-008 / SC-004) | ≥9/10 correct type |

---

## Validation Rules

- A rewritten `PromptComponent` MUST score no worse than baseline on all four dimensions.
- If any existing passing test fails after a rewrite, the rewrite is rejected (SC-005).
- Every instruction in a rewritten prompt MUST map 1:1 to an instruction in the original (SC-006).
- `READER_COMPACT_PROMPT` rewrite is conditional: only proceed if SC-003 target not met with
  the other five components.
