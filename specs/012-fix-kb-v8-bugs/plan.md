# Implementation Plan: 修复 Holmes KB v8 报告问题

**Branch**: `012-fix-kb-v8-bugs` | **Date**: 2026-06-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-fix-kb-v8-bugs/spec.md`

## Summary

修复 Holmes KB v8 使用报告中发现的 7 个问题：amend-pending 缺少 updated_at 注入、detect-commands 非 shell 代码块误报、write-pending 无 frontmatter 校验、Gate 3 长条目盲确认、resolve 后 index 不更新、list 缺 --maturity 过滤、history exit 码不一致。

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: click 8.x, python-frontmatter, pytest

**Storage**: File-based (Markdown + YAML frontmatter)

**Testing**: pytest (`kb/tests/test_integration.py`, `kb/tests/test_pending.py`, `kb/tests/test_skill_manager.py`)

**Target Platform**: Linux/macOS CLI

**Project Type**: CLI tool

**Performance Goals**: N/A

**Constraints**: Preserve all 387 existing tests; surgical fixes only

**Scale/Scope**: 7 bug fixes across 3 source files

## Constitution Check

- No new abstractions — surgical fixes only
- No new dependencies
- Tests added for each fix
- All 387 existing tests must pass

## Project Structure

### Documentation (this feature)

```text
specs/012-fix-kb-v8-bugs/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (repository root)

```text
kb/
├── holmes/
│   ├── cli.py                        # kb_amend_pending, kb_write_pending, kb_confirm, kb_resolve_conflict, kb_list, kb_history
│   └── kb/
│       └── skill/
│           └── manager.py            # _CODE_BLOCK_RE, _extract_code_block_lines()
└── tests/
    ├── test_integration.py
    └── test_skill_manager.py
```

## Fix Locations

| US  | File | Function/Constant | Line | Change |
|-----|------|-------------------|------|--------|
| US1 | `kb/holmes/cli.py` | `kb_amend_pending()` | ~565 | inject `updated_at`; preserve `created_at` |
| US2 | `kb/holmes/kb/skill/manager.py` | `_CODE_BLOCK_RE`, `_extract_code_block_lines()` | ~34, ~45 | capture lang tag; whitelist shell langs |
| US3 | `kb/holmes/cli.py` | `kb_write_pending()` | ~530 | reject content without `---` frontmatter |
| US4 | `kb/holmes/cli.py` | `kb_confirm()` Gate 3 | ~700 | long content: require `yes` prompt |
| US5 | `kb/holmes/cli.py` | `kb_resolve_conflict()` | ~1027 | call `rebuild_index_files()` after resolve |
| US6 | `kb/holmes/cli.py` | `kb_list()` decorator + body | ~1087 | add `--maturity` option + filter |
| US7 | `kb/holmes/cli.py` | `kb_history()` | ~1184, ~1213 | exit 1 on not-found |
