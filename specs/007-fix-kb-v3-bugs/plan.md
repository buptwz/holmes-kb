# Implementation Plan: 修复 Holmes KB v3 报告缺陷

**Branch**: `007-fix-kb-v3-bugs` | **Date**: 2026-06-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-fix-kb-v3-bugs/spec.md`

## Summary

修复 Holmes KB v3 使用报告中发现的 7 个缺陷（1 个 P0 崩溃、4 个 P1 数据完整性、2 个 P2 UX 改善）。所有修复均为外科手术式的小范围代码变更，不新增模块或依赖。

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: click, python-frontmatter, openai（均已在项目中）

**Storage**: Markdown 文件 + YAML frontmatter（KB 条目），无数据库

**Testing**: pytest（现有 293 个测试；新增覆盖 7 个缺陷场景）

**Target Platform**: Linux CLI（holmes kb 命令）

**Project Type**: CLI 工具（Python package）

**Performance Goals**: 无特殊性能要求（CLI 交互式工具）

**Constraints**: 所有修复不破坏现有 293 个测试；每个修复独立可回滚

**Scale/Scope**: 影响 3 个核心文件（`store.py`, `cli.py`, `importer.py`）

## Constitution Check

| 原则 | 评估 | 状态 |
|------|------|------|
| 开闭原则 | 修复现有函数行为，不新增抽象层 | ✅ PASS |
| 单一职责 | 每个修复仅修改对应职责的函数 | ✅ PASS |
| 验证原则 | 所有修复均配套自动化测试 | ✅ PASS |
| 渐进式实现 | 最小化修改，无超前抽象 | ✅ PASS |
| 代码规范 | 保持 Google style，行宽 ≤ 100 | ✅ PASS |
| 质量标准 | 修复用户报告的真实缺陷，提升可用性 | ✅ PASS |

**Constitution Gates**: ALL PASS — 可进入 Phase 0

## Project Structure

### Documentation (this feature)

```text
specs/007-fix-kb-v3-bugs/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (affected files)

```text
kb/
├── holmes/
│   ├── cli.py                    # US3/US4/US5/US6/US7 修复
│   └── kb/
│       ├── store.py              # US1 修复（数字 tag 崩溃）
│       └── importer.py           # US2 修复（dry-run 跳过 LLM）
└── tests/
    ├── test_store.py             # US1 新增测试
    ├── test_integration.py       # US3/US4/US5/US6/US7 新增测试
    └── test_importer.py          # US2 新增测试（新文件或现有文件追加）
```

## Bug → File → Fix 映射

| Bug | 优先级 | 文件 | 修复位置 | 修复方式 |
|-----|--------|------|----------|----------|
| US1: 数字 tag 崩溃 | P0 | `kb/holmes/kb/store.py` | `list_entries()` 搜索逻辑 | `str(t).lower()` |
| US2: dry-run 调 LLM | P1 | `kb/holmes/kb/importer.py` | `import_document()` LLM 调用前 | dry-run 时跳过 LLM，直接用原文 |
| US3: created_at 丢失 | P1 | `kb/holmes/cli.py` | `kb_confirm()` 纠错路径 | 从 orig_post 继承 created_at |
| US4: contributor 未追加 | P1 | `kb/holmes/cli.py` | `kb_confirm()` 纠错路径 | 追加 contributor 到列表（去重） |
| US5: Gate 3 截断 | P1 | `kb/holmes/cli.py` | `kb_confirm()` Gate 3 | 替换截断为 `--show` 提示命令 |
| US6: 空 ID 显示 | P2 | `kb/holmes/cli.py` | `kb_pending()` 列表输出 | 空 id 时显示 path.stem |
| US7: maturity 降级无警告 | P2 | `kb/holmes/cli.py` | `kb_confirm()` 纠错路径 | 输出 maturity 变更信息 |
