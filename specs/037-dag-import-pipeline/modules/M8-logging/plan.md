# Implementation Plan: M8 — 可观测性与日志

**Branch**: `dev-M8` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/037-dag-import-pipeline/modules/M8-logging/spec.md`

## Summary

为 Holmes KB CLI 新增 `HolmesLogger` 类，实现双格式日志写入（`.log` 人类可读 + `.jsonl` JSON Lines），并在 CLI 中添加 `holmes log list/show` 子命令，同时在 `holmes import` 命令中接入 Logger（username 检查 + `--verbose` 实时打印）。

技术方案：纯 Python 标准库实现（`json`、`pathlib`、`datetime`），不引入第三方日志框架；Logger 作为普通类实例传递，便于测试 mock。

## Technical Context

**Language/Version**: Python 3.11（沿用现有代码库）

**Primary Dependencies**: `click`（CLI 框架，已有），Python 标准库 `json`、`pathlib`、`datetime`

**Storage**: `~/.holmes/logs/YYYY-MM-DD.log` + `~/.holmes/logs/YYYY-MM-DD.jsonl`（文件追加模式）

**Testing**: pytest（沿用现有 `kb/tests/` 测试结构）

**Target Platform**: Linux（Ubuntu 机器）

**Project Type**: CLI 工具

**Performance Goals**: `holmes log show` 在 1 秒内完成 30 天日志扫描

**Constraints**: 无第三方日志框架依赖；不引入单例模式；文件追加 `a` 模式不加锁（单进程场景）

**Scale/Scope**: 单用户本地工具，日志文件数量上限 30 个（滚动删除）

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | PASS | `write_span(**extra)` 支持任意附加字段，无需修改现有接口即可扩展 |
| 单一职责 | PASS | `HolmesLogger` 只负责写日志；`holmes log` CLI 只负责读展示；两者独立 |
| 渐进式实现 | PASS | 无抽象基类、无插件系统；直接实现最小可用接口 |
| 依赖倒置 | PASS | `ImportAgentRunner` 通过构造参数接收 logger 实例，不硬依赖路径 |
| 可观测性原则 | PASS | 本模块即可观测性实现 |
| 验证原则 | PASS | 必须有单元测试（write_span 格式、rotate 逻辑、username 检查） |
| 代码整洁 | PASS | `logger.py` 独立新文件，不污染现有模块 |
| 环境配置 | PASS | `log_dir` 从 `_holmes_home()` 派生，支持 `HOLMES_HOME` 覆盖 |

**所有 gate 通过，无 violation。**

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M8-logging/
├── spec.md
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── cli-log-commands.md   # Phase 1 output
└── tasks.md             # Phase 2 output (by /speckit-tasks)
```

### Source Code (repository root)

```text
kb/holmes/
├── kb/
│   └── logger.py           # NEW: HolmesLogger 类
└── cli.py                  # MODIFIED: 新增 holmes log group + import 接入 Logger

kb/tests/
└── test_logger.py          # NEW: HolmesLogger 单元测试
```

**Structure Decision**: 单文件新增（`logger.py`），CLI 改动集中于 `cli.py` 末尾新增 log 子命令组，最小化侵入范围。

## Complexity Tracking

无 Constitution Check violation，本表留空。
