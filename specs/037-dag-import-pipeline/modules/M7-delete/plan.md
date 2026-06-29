# Implementation Plan: KB Soft Delete (M7 — holmes kb delete)

**Branch**: `dev-M7` | **Date**: 2026-06-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/037-dag-import-pipeline/modules/M7-delete/spec.md`

**Note**: This plan is filled in by the `/speckit-plan` command.

## Summary

Add soft-delete capability to all KB entries by implementing `move_to_trash()` in `store.py` and a `holmes kb delete <id>` CLI command in `cli.py`. Files are moved to `_trash/<type>/<category>/` rather than deleted, preserving git recoverability. Pitfall root nodes with `pitfall_structure: tree` cascade via the existing `collect_tree()` function.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Click (CLI framework), python-frontmatter (YAML parsing), shutil (file move), pathlib (path operations)

**Storage**: Markdown files on filesystem, git-tracked

**Testing**: pytest

**Target Platform**: Linux (Ubuntu), CLI

**Project Type**: CLI tool

**Performance Goals**: N/A — interactive CLI, single-entry or small tree moves

**Constraints**: Must not break existing `find_entry()`, `collect_tree()`, `approve_entry()` interfaces. No atomic write needed for trash moves (source already moved away).

**Scale/Scope**: Single KB repository, typically <1000 entries

## Constitution Check

*GATE: Must pass before Phase 0 research.*

| Principle | Check | Status |
|-----------|-------|--------|
| 单一职责原则 | `move_to_trash()` in store.py; CLI in cli.py | PASS |
| 开闭原则 | New function, no modification to existing store functions | PASS |
| 可观测性原则 | HolmesLogger `kb.delete` span after deletion | PASS |
| 验证原则 | Unit tests required (4+ scenarios) | PASS |
| 渐进式实现原则 | Simple file move; no abstraction layers | PASS |
| 代码整洁原则 | New function appended to existing store.py; CLI command appended to kb group | PASS |
| 安全 | Confirmation prompt prevents accidental deletion; `--force` explicit opt-in | PASS |

All gates pass. No violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M7-delete/
├── brief.md             # Input brief
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
kb/
├── holmes/
│   ├── kb/
│   │   └── store.py        # + move_to_trash() function
│   └── cli.py              # + kb delete command
└── tests/
    └── test_delete.py      # New test file for M7
```
