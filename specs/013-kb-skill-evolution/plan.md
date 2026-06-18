# Implementation Plan: Holmes KB Autonomous Import Agent

**Branch**: `013-kb-skill-evolution` | **Date**: 2026-06-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/013-kb-skill-evolution/spec.md`

## Summary

Upgrade `holmes import` from a single-shot LLM classification call into a full autonomous agent pipeline built on the Anthropic SDK tool-use loop. The agent self-verifies content correctness, performs semantic deduplication, auto-generates skills, curates skill quality, and guarantees idempotency via `source_hash`. All file writes are atomic (temp + rename); pipeline-level rollback is via `git commit`. Interactive confirmation gates pause on low-confidence decisions; `--no-interactive` suppresses all gates.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `anthropic>=0.27.0` — new; tool-use agent loop (replaces single-shot openai call for agent)
- `openai>=1.30.0` — kept for existing config/model compatibility
- `python-frontmatter>=1.1.0` — YAML frontmatter parse/dump
- `click>=8.1.0` — CLI
- `pydantic>=2.6.0` — data models

**Storage**: Markdown files + YAML frontmatter in `~/.holmes-kb/` (file-based, no DB)

**Testing**: pytest + pytest-asyncio (`asyncio_mode = auto`)

**Target Platform**: Linux CLI

**Project Type**: CLI tool (extension to existing `holmes` CLI)

**Performance Goals**: ≤30s per document ≤10,000 chars (SC-007)

**Constraints**: No vector DB; LLM semantic judgment via Anthropic tool-use; atomic file writes; git as pipeline rollback

**Scale/Scope**: Single-user local KB; single-file imports (≤50,000 chars); batch via `--dir`

## Constitution Check

*GATE: Must pass before Phase 0 research.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 开闭原则 | PASS | Existing `importer.py` extended via composition; `cli.py` import command replaces old cmd cleanly |
| 依赖倒置原则 | PASS | Agent depends on abstract tool functions, not concrete KB internals |
| 单一职责原则 | PASS | Each new module has one job: runner, verifier, dedup, skill_advisor, curator, report |
| 接口隔离原则 | PASS | Tool functions are small; no fat interfaces |
| 迪米特法则 | PASS | Agent calls KB functions via tool layer, not KB internals directly |
| 里氏替换原则 | N/A | No subclassing involved |
| 合成复用原则 | PASS | Agent composes existing `write_pending`, `create_skill`, `link_skill`, etc. |
| 环境配置原则 | PASS | All keys/URLs from `HolmesConfig`; no hardcoded values |
| 代码整洁原则 | PASS | New code lives in `kb/holmes/kb/agent/` package; not crammed into existing files |
| 验证原则 | PASS | All modules will have integration + unit tests |
| 渐进式实现原则 | PASS | No premature abstractions; 6 user stories map directly to modules |
| 可观测性原则 | PASS | ImportReport, --verbose, structured logging in every module |

*Post-design re-check: See bottom of this file.*

## Project Structure

### Documentation (this feature)

```text
specs/013-kb-skill-evolution/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-contracts.md # Phase 1 output
└── tasks.md             # Phase 2 output (by /speckit-tasks)
```

### Source Code (repository root)

```text
kb/
├── holmes/
│   ├── cli.py                          # MODIFIED: import_cmd → agent pipeline; add --dir, --no-interactive
│   └── kb/
│       ├── importer.py                 # MODIFIED: add source_hash helper; keep old function for compat
│       ├── atomic.py                   # NEW: atomic write helpers (temp + os.replace)
│       ├── agent/
│       │   ├── __init__.py             # NEW
│       │   ├── runner.py               # NEW: Anthropic tool-use agent loop, main entry point
│       │   ├── tools.py                # NEW: tool definitions exposed to agent (read, write, hash-check, etc.)
│       │   ├── verifier.py             # NEW: self-verification pass (LLM compares draft vs source)
│       │   ├── dedup.py                # NEW: LLM semantic dedup (same-root-cause detection)
│       │   ├── skill_advisor.py        # NEW: skill generation value assessment (≥3 steps, params)
│       │   ├── curator.py              # NEW: incremental skill curation (merge/oversized/update candidates)
│       │   └── report.py              # NEW: ImportReport builder and formatter
│       └── skill/
│           ├── manager.py              # UNCHANGED
│           └── usage.py               # NEW: SkillUsageRecord sidecar (.skill_usage.json)
└── tests/
    ├── test_integration.py             # MODIFIED: add agent integration tests
    ├── test_agent_runner.py            # NEW: agent loop unit tests
    ├── test_dedup.py                   # NEW: semantic dedup tests
    ├── test_skill_advisor.py           # NEW: skill generation advisor tests
    ├── test_curator.py                 # NEW: curator finding tests
    └── test_skill_usage.py             # NEW: SkillUsageRecord sidecar tests
```

**Structure Decision**: Single project, extending existing `kb/` package. New agent sub-package under `kb/holmes/kb/agent/` keeps agent logic isolated from KB primitives. New `skill/usage.py` is a natural sibling to existing `skill/manager.py`.

## Complexity Tracking

No constitution violations. No complexity justification required.

---

## Post-Design Constitution Re-check

All principles still pass after Phase 1 design. The `agent/` sub-package boundary cleanly separates Anthropic SDK usage from the rest of the KB codebase. Existing tests for KB primitives are unaffected.
