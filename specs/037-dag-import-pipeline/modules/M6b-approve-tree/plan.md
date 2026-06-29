# Implementation Plan: M6b — Pending/Approve 树级联

**Branch**: `dev-M6b` | **Date**: 2026-06-24 | **Spec**: [spec.md](spec.md)

## Summary

在 M6a（单 entry approve）基础上，新增四个 store 函数实现树级联能力，并改造 `holmes kb approve` 和 `holmes kb pending` 两个 CLI 命令，使 pitfall 类型 entries 的审核流程感知整棵树结构。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Click (CLI), python-frontmatter (Markdown frontmatter), pytest (testing)

**Storage**: 本地文件系统（`_pending/<type>/<category>/` + `<type>/<category>/`）

**Testing**: pytest，单元测试 + CLI 集成测试（click.testing.CliRunner）

**Target Platform**: Linux / macOS CLI

**Project Type**: CLI tool

**Performance Goals**: approve 一棵 10 节点树 < 5s

**Constraints**: 原子性保证（失败回滚）；不依赖外部服务；防循环引用

**Scale/Scope**: 典型树规模 1–15 个 entries

## Constitution Check

| 原则 | 检查 | 状态 |
|------|------|------|
| 单一职责 | 4 个新函数各自职责清晰，无交叉 | PASS |
| 开闭原则 | 在 approve_entry/deprecate_entry 之上封装，不修改原函数 | PASS |
| 验证原则 | 所有新函数和 CLI 路径均有单元测试 | PASS |
| 渐进式实现 | 只实现 spec 所需功能 | PASS |
| 可观测性 | approve 操作保留现有日志 span | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M6b-approve-tree/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
└── tasks.md             # /speckit-tasks output
```

### Source Code (affected files)

```text
kb/holmes/kb/store.py          # 新增 4 个树操作函数，修复 _scan_all_entries
kb/holmes/cli.py               # 改造 kb_approve 和 kb_pending
kb/tests/test_approve_tree.py  # 新增测试文件
```

**Structure Decision**: 单项目结构。所有变更集中在现有 `kb/` 目录下，不新建子包。

## Phase 0: Research

详见 [research.md](research.md)

## Phase 1: Design

详见 [data-model.md](data-model.md)
