# Implementation Plan: M6a — Pending/Approve 基础流程

**Branch**: `dev-M6a` | **Date**: 2026-06-24 | **Spec**: [spec.md](./spec.md)

## Summary

在现有 Holmes KB CLI 工具（Python/Click）中，实现 pending → active 的单 entry 生命周期：

1. `store.py` 新增四个函数：`write_pending`（新格式）、`find_entries_by_source_file`、`approve_entry`、`deprecate_entry`
2. `cli.py` 新增 `holmes kb approve` 命令，改造 `holmes kb pending` 命令（按 category 分组 + 兼容旧格式）
3. `tests/test_approve.py` 新增单元测试

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Click（CLI框架）、python-frontmatter（YAML frontmatter 读写）、pytest（测试）

**Storage**: Markdown 文件 + YAML frontmatter，文件系统作为状态存储

**Testing**: pytest，`kb/tests/` 目录

**Target Platform**: Linux/macOS CLI

**Project Type**: CLI tool library

**Performance Goals**: approve 单 entry < 1s（纯文件系统操作）

**Constraints**: 原子写入（atomic_write），approve 失败不留半成品

**Scale/Scope**: 单 KB 仓库，数百至数千个 entries

## Constitution Check

| 原则 | 评估 | 结论 |
|------|------|------|
| 单一职责 | write_pending/approve_entry/deprecate_entry 各自独立、职责单一 | ✓ 通过 |
| 接口隔离 | store.py 函数接口简洁，CLI 与存储逻辑分离 | ✓ 通过 |
| 开闭原则 | 新增函数不修改现有 list_entries/find_entry 逻辑 | ✓ 通过 |
| 验证原则 | 新增 test_approve.py 覆盖四个场景 | ✓ 通过 |
| 可观测性 | approve 后写 HolmesLogger kb.approve span | ✓ 通过 |
| 渐进式实现 | 无抽象层，直接实现函数，不过度设计 | ✓ 通过 |
| 环境配置 | 无硬编码路径，路径由 kb_root 参数传入 | ✓ 通过 |

**Gate Result**: 全部通过，可进入 Phase 1。

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M6a-approve-base/
├── spec.md
├── plan.md              ← 本文件
├── research.md
├── data-model.md
├── contracts/
│   └── cli-interface.md
└── tasks.md             (由 /speckit-tasks 生成)
```

### Source Code (repository root)

```text
kb/holmes/kb/
├── store.py             ← 新增 write_pending / find_entries_by_source_file /
│                           approve_entry / deprecate_entry
├── atomic.py            ← 已有，approve_entry 使用
└── pending.py           ← 已有旧格式，不修改

kb/holmes/
└── cli.py               ← 新增 kb approve 命令；改造 kb pending 命令

kb/tests/
└── test_approve.py      ← 新增，覆盖四个场景
```

## Complexity Tracking

无 Constitution 违规，无需填写。
