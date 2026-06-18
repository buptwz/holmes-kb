# Implementation Plan: Import Pipeline v2 Report Bug Fixes

**Branch**: `019-fix-v2-report-bugs` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/019-fix-v2-report-bugs/spec.md`

## Summary

Fix five bugs identified in the v2 verification report, all rooted in Feature 018's `runner.py` and `tools.py`. The critical blocker is a `CommandCandidate` TypeError that crashes every import involving skill generation. The remaining fixes close gaps where deterministic enforcement was missing (dedup, force_type, skill gate bypass, LINK description). Also cleans up three pre-existing corrupted KB data files.

**No new abstractions** — all changes are targeted one-line or small-block fixes within existing functions.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: `python-frontmatter`, `re` (stdlib), `openai` SDK, `click`

**Storage**: Filesystem (holmes-kb directory tree, pending/ subdirectory)

**Testing**: pytest (existing suite in `kb/tests/`)

**Target Platform**: Linux (Ubuntu)

**Project Type**: CLI tool / library

**Performance Goals**: N/A (correctness fixes only)

**Constraints**: All existing 634 tests must continue to pass; no new dependencies

**Scale/Scope**: 5 code files changed, 3 KB data files patched/deleted

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| 单一职责 | ✅ Pass | Each fix touches only the responsible module |
| 验证原则 | ✅ Pass | ≥10 new tests covering all fixed behaviors |
| 可观测性 | ✅ Pass | Skipped-duplicate entries logged in report summary |
| 渐进式实现 | ✅ Pass | Minimal targeted fixes; no new abstractions |
| 代码整洁 | ✅ Pass | Changes are confined to existing functions |

## Project Structure

### Documentation (this feature)

```text
specs/019-fix-v2-report-bugs/
├── plan.md              # This file
├── research.md          # Root cause analysis (Phase 0)
├── data-model.md        # Entity contract changes (Phase 1)
├── quickstart.md        # Test scenarios (Phase 1)
└── tasks.md             # Task list (/speckit-tasks)
```

### Source Code (files changed)

```text
kb/holmes/kb/agent/
├── runner.py            # CommandCandidate fix (4 sites), E-12 tracking, E-11 description
├── tools.py             # D-5 dedup enforcement, E-2 force_type in write_kb_entry
└── pipeline.py          # Add force_type to shared ctx

kb/tests/
├── test_agent_runner.py # New tests: CommandCandidate, E-12 bypass, E-11 LINK
├── test_pipeline.py     # New test: force_type end-to-end
└── test_tools.py        # New tests: D-5 dedup enforcement

holmes-kb/pitfall/database/
├── PT-DB-002.md         # Remove duplicate section headers
└── PT-DB-005.md         # Remove body_additions frontmatter field

holmes-kb/pitfall/database/PT-DB-TEST2.md   # Delete
holmes-kb/pitfall/network/PT-NET-TEST.md    # Delete
```

## Complexity Tracking

No constitution violations.
