# Implementation Plan: 修复 Holmes KB v7 报告问题

**Branch**: `011-fix-kb-v7-bugs` | **Date**: 2026-06-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-fix-kb-v7-bugs/spec.md`

## Summary

修复 Holmes KB v7 使用报告中发现的 6 个问题：(1) detect-commands backtick 路径补充 4 条过滤规则消除 JVM/Node.js/Nginx 误报；(2) 新增 amend-pending 命令支持修复 Gate 1 失败的 pending 条目；(3) write-pending 新增 --file 选项；(4) archive-orphans 新增 --dry-run；(5) 单条 reject 支持 --dry-run；(6) pending 表格 CREATED 列使用 pending_since 兜底值。

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: click 8.x, python-frontmatter, pytest

**Storage**: File-based (Markdown + YAML frontmatter in `contributions/pending/` and KB entry directories)

**Testing**: pytest (`kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`)

**Target Platform**: Linux/macOS CLI

**Project Type**: CLI tool

**Performance Goals**: N/A (local file operations)

**Constraints**: Preserve all 367 existing tests; surgical fixes only, no refactoring

**Scale/Scope**: 6 bug fixes across 3 source files

## Constitution Check

- No new abstractions or layers introduced — surgical bug fixes only
- No new dependencies
- Tests added for each fix
- All 367 existing tests must continue to pass

## Project Structure

### Documentation (this feature)

```text
specs/011-fix-kb-v7-bugs/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
kb/
├── holmes/
│   ├── cli.py                        # kb_write_pending, kb_reject, kb_archive_orphans, pending table
│   └── kb/
│       ├── pending.py                # write_pending, list_pending
│       └── skill/
│           └── manager.py            # detect_commands() CMD_PATTERN loop
└── tests/
    ├── test_integration.py           # CLI integration tests
    ├── test_pending.py               # pending.py unit tests
    └── test_skill_manager.py         # skill manager unit tests
```

**Structure Decision**: Single project, existing structure. All changes are surgical — no new files in source tree.

## Fix Locations

| US  | File | Function | Line Range | Change |
|-----|------|----------|-----------|--------|
| US1 | `kb/holmes/kb/skill/manager.py` | `detect_commands()` | ~462-473 | Add 4 backtick filters after existing `=`/`:` filter |
| US2 | `kb/holmes/cli.py` | new `kb_amend_pending()` | after write-pending (~544) | New `@kb.command("amend-pending")` |
| US3 | `kb/holmes/cli.py` | `kb_write_pending()` | ~526 | Add `--file` option, make `--content` optional |
| US4 | `kb/holmes/cli.py` | `kb_archive_orphans()` | ~1213 | Add `--dry-run` option |
| US5 | `kb/holmes/cli.py` | `kb_reject()` | ~828-830 | Remove single-mode dry-run restriction |
| US6 | `kb/holmes/cli.py` | `kb_pending()` table | ~521 | Use `pending_since` not `created_at` for CREATED column |
