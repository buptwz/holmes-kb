# Implementation Plan: Import Pipeline Prompt Quality Optimization

**Branch**: `035-prompt-quality` | **Date**: 2026-06-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/035-prompt-quality/spec.md`

## Summary

Systematically rewrite all LLM prompt string constants in the Holmes KB import pipeline
using structured sections (## Role / ## Task / ## Constraints / ## Output Format), explicit
DO/DON'T rule lists, and per-type examples. Goal: reduce section cross-contamination (P1),
prevent field fabrication (P2), improve classification accuracy (P3), and lower token
consumption (P4). All rewrites are semantically equivalent — no pipeline behaviour changes.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: python-frontmatter, anthropic, openai (OpenAI-compatible mode), pytest

**Storage**: N/A — feature modifies string constants only; no data model or persistence layer changes

**Testing**: pytest (`kb/tests/`)

**Target Platform**: Linux server

**Project Type**: CLI / library

**Performance Goals**: ≥15% input-token reduction per standard import run (SC-003)

**Constraints**:
- Semantic equivalence is mandatory (FR-000): all rewrites preserve original intent and tool-call behaviour
- All existing passing tests must continue to pass (SC-005)
- No pipeline control-flow, tool definition, or data model changes permitted

**Scale/Scope**: 6 prompt components across 5 source files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 开闭原则 | ✅ Pass | Modifying string constants inside existing functions; no new extension points added |
| 依赖倒置 | ✅ Pass | No new abstractions or interfaces |
| 单一职责 | ✅ Pass | Each prompt stays in its owner file; no consolidation across modules |
| 接口隔离 | ✅ Pass | No interface changes |
| 渐进式实现 | ✅ Pass | FR-010 mandates independent shippability per component; Extractor first |
| 验证原则 | ✅ Pass | SC-005 mandates existing test suite as regression gate |
| 代码整洁 | ✅ Pass | No new files; string rewrites within existing modules |
| 可观测性 | ✅ Pass | No new logging requirements |
| 环境配置 | ✅ Pass | No new configuration required |

**No constitution violations. Gate passed.**

## Project Structure

### Documentation (this feature)

```text
specs/035-prompt-quality/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (Prompt Component entity)
├── quickstart.md        # Phase 1 output (test scenarios and token measurement)
└── tasks.md             # Phase 2 output (/speckit-tasks command)
```

### Source Code (repository root — string changes only, no new files)

```text
kb/holmes/kb/agent/phases/extractor.py     # EXTRACTOR_SYSTEM_PROMPT  (Priority 1)
kb/holmes/kb/agent/runner.py               # _IMPORT_SYSTEM_PROMPT    (Priority 2)
kb/holmes/kb/agent/phases/classifier.py    # _CLASSIFIER_SYSTEM_PROMPT (Priority 3)
kb/holmes/kb/agent/phases/reader.py        # READER_SYSTEM_PROMPT      (Priority 4)
                                           # READER_COMPACT_PROMPT     (Priority 4b)
kb/holmes/kb/agent/verifier.py             # inline system_prompt str  (Priority 5)
kb/holmes/kb/agent/skill_advisor.py        # deterministic — no LLM prompt (see research.md)

kb/tests/                                  # existing tests — must all stay green
```

**Structure Decision**: Single-project, in-place string rewrites. No new directories,
no new test files (unless unit tests for specific prompt properties are needed per spec
Assumptions). All changes land in the 6 source files listed above.
