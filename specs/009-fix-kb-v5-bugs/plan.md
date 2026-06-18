# Implementation Plan: 修复 Holmes KB v5 报告问题

**Branch**: `009-fix-kb-v5-bugs` | **Date**: 2026-06-06 | **Spec**: [spec.md](spec.md)

## Summary

修复 Holmes KB v5 使用报告中发现的 9 个问题（3 个 P1 bug、2 个 P2 功能改进、4 个 P3 UX 改善）。所有修复均为外科手术式变更，影响 3 个核心文件。

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: click, python-frontmatter, pathlib, re（均已在项目中）

**Testing**: pytest（现有 328 个测试）

**Target Platform**: Linux CLI

**Constraints**: 所有修复向后兼容；不破坏现有 328 个测试

**Scale/Scope**: 影响 3 个文件（`cli.py`, `pending.py`, `skill/manager.py`）

## Constitution Check

| 原则 | 评估 | 状态 |
|------|------|------|
| 开闭原则 | 新选项不改变现有行为；SKILL_PARAM 注释不改变生成逻辑 | ✅ PASS |
| 单一职责 | 每个修复对应独立函数/行为 | ✅ PASS |
| 验证原则 | 所有修复配套自动化测试 | ✅ PASS |
| 渐进式实现 | 最小化修改，无超前抽象 | ✅ PASS |
| 质量标准 | 修复真实用户报告，消除误报和操作困难 | ✅ PASS |

**Constitution Gates**: ALL PASS

## Project Structure

### Documentation (this feature)

```text
specs/009-fix-kb-v5-bugs/
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
│   ├── cli.py                         # US4/US6/US7/US8/US9
│   └── kb/
│       ├── pending.py                 # US5
│       └── skill/
│           └── manager.py             # US1/US2/US3
└── tests/
    ├── test_integration.py            # US4/US6/US7/US8/US9 测试
    ├── test_pending.py                # US5 测试
    └── test_skill_manager.py          # US1/US2/US3 测试
```

## Bug → File → Fix 映射

| Bug | 优先级 | 文件 | 修复位置 | 修复方式 |
|-----|--------|------|----------|----------|
| US1: SQL 从句补全 | P1 | `skill/manager.py` | `_SQL_KEYWORDS` frozenset | 追加 `where/from/group/having/order/limit/join/on` |
| US2: backtick 误报 | P1 | `skill/manager.py` | `detect_commands()` CMD_PATTERN loop | 检查候选含 `=` 或 `:` → 跳过 |
| US3: SKILL_PARAM 注释 | P1 | `skill/manager.py` | `auto_create_skill()` run.sh 模板 | 在 run.sh 头部添加 SKILL_PARAM 注释块 |
| US4: pending 批量 reject | P2 | `cli.py` | `kb_reject()` + decorator | 新增 `--stale-days N` 选项 |
| US5: pending mtime 兜底 | P2 | `pending.py` | `list_pending()` | 两日期字段均空时用文件 mtime |
| US6: search --type | P3 | `cli.py` | `kb_search()` + decorator | 新增 `--type` 选项过滤 `list_entries` |
| US7: evidence 位置调整 | P3 | `cli.py` | `kb_show()` | 移动 Evidence 行至正文前 |
| US8: snapshot 内部字段 | P3 | `cli.py` | `kb_history()` `--show` 路径 | pop `replaced_at/replaced_by/snapshot_reason` |
| US9: --version | P3 | `cli.py` | `@cli` group decorator | 添加 `click.version_option` |
