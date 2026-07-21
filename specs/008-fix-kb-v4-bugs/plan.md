# Implementation Plan: 修复 Holmes KB v4 报告问题

**Branch**: `008-fix-kb-v4-bugs` | **Date**: 2026-06-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-fix-kb-v4-bugs/spec.md`

## Summary

修复 Holmes KB v4 使用报告中发现的 7 个问题（4 个 P1 bug、3 个 P2 功能改进）。所有修复均为外科手术式变更，不引入新模块，影响 4 个核心文件。

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: click, python-frontmatter, pathlib（均已在项目中）

**Storage**: Markdown + YAML frontmatter，sidecar JSON（evidence），`.history/` 快照文件

**Testing**: pytest（现有 307 个测试）

**Target Platform**: Linux CLI

**Project Type**: CLI 工具（Python package）

**Performance Goals**: 无特殊要求

**Constraints**: 所有修复向后兼容；不破坏现有 307 个测试

**Scale/Scope**: 影响 4 个文件（`cli.py`, `pending.py`, `skill/manager.py`）

## Constitution Check

| 原则 | 评估 | 状态 |
|------|------|------|
| 开闭原则 | 新选项（`--with-evidence`, `--show`）不改变现有行为 | ✅ PASS |
| 单一职责 | 每个修复对应独立函数 | ✅ PASS |
| 验证原则 | 所有修复配套自动化测试 | ✅ PASS |
| 渐进式实现 | 最小化修改，无超前抽象 | ✅ PASS |
| 质量标准 | 修复真实用户报告，消除困惑和误导 | ✅ PASS |

**Constitution Gates**: ALL PASS

## Project Structure

### Documentation (this feature)

```text
specs/008-fix-kb-v4-bugs/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
└── tasks.md
```

### Source Code (affected files)

```text
kb/
├── holmes/
│   ├── cli.py                         # US1/US2/US5/US6/US7
│   └── kb/
│       ├── pending.py                 # US3
│       └── skill/
│           └── manager.py             # US4
└── tests/
    ├── test_integration.py            # US1/US2/US5/US6/US7 测试
    ├── test_pending.py                # US3 测试
    └── test_skill_manager.py          # US4 测试
```

## Bug → File → Fix 映射

| Bug | 优先级 | 文件 | 修复位置 | 修复方式 |
|-----|--------|------|----------|----------|
| US1: merge exit 1 | P1 | `cli.py` | `kb_merge()` line 808 | 移除 `sys.exit(1)`，改为输出 next-step |
| US2: Gate 3 内部字段 | P1 | `cli.py` | `kb_confirm()` Gate 3 | 展示前用 `fm.loads` 剥离内部字段 |
| US3: pending_since 缺失 | P1 | `pending.py` | `list_pending()` | 追加 `pending_since` 字段 |
| US4: CMD_PATTERN 误报 | P1 | `skill/manager.py` | `detect_commands()` | 剥离 YAML frontmatter + fallback SQL 过滤 |
| US5: show --with-evidence | P2 | `cli.py` | `kb_show()` + decorator | 新增选项，读取 `load_evidence()` |
| US6: history --show | P2 | `cli.py` | `kb_history()` + decorator | 新增选项，读取 `.history/<id>/<name>` |
| US7: dry-run 无参数提示 | P2 | `cli.py` | `import_cmd()` | 检测无参数无 api_key 时输出提示 |
