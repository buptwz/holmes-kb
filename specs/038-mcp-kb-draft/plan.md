# Implementation Plan: M9 — MCP 接口重构（kb_draft + 日志集成）

**Branch**: `dev-M9` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)

## Summary

删除 MCP 内联 LLM pipeline（`kb_submit`），新增纯文件写入的 `kb_draft` 工具；新增 `holmes kb drafts` CLI 命令；`holmes import` 完成后自动归档 `_drafts/` 草稿；更新所有 MCP 读工具使用 M1 store 接口并写入 HolmesLogger 日志。无新抽象层，复用现有 store/logger 接口。

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: fastmcp, click, python-frontmatter, holmes.kb.store (M1), holmes.kb.logger (M8)

**Storage**: 文件系统（`_drafts/`、`~/.holmes/logs/`），无数据库

**Testing**: pytest

**Target Platform**: Linux（ubuntu）

**Project Type**: CLI + MCP server

**Performance Goals**: `kb_draft` 纯文件写入 < 1s；`holmes kb drafts` < 1s（扫描 `_drafts/` 目录）

**Constraints**: `kb_draft` 禁止调用任何 LLM；所有写操作使用 atomic_write

**Scale/Scope**: 单用户本地工具，`_drafts/` 预期 < 100 文件

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 单一职责 | PASS | kb_draft 只写文件，不调 LLM；CLI 只读 _drafts/ |
| 渐进式实现 | PASS | 无新抽象层，直接调用 M1/M8 现有接口 |
| 可观测性 | PASS | 所有 MCP 操作写入 HolmesLogger（span 命名规范） |
| 自动化验证 | PASS | test_mcp_tools.py 新增 TestKbDraft，移除 TestKbSubmitPipeline |
| 环境配置 | PASS | username 从 config 读取，不硬编码 |
| 安全 | PASS | title 参数需防路径穿越（sanitize 或拒绝含 `/` 的 title） |

*无 Constitution 违规，无需 Complexity Tracking。*

## Project Structure

### Documentation (this feature)

```text
specs/038-mcp-kb-draft/
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── contracts/           # Phase 1 输出（CLI 命令 + MCP 工具接口）
└── tasks.md             # /speckit-tasks 输出
```

### Source Code 修改范围

```text
kb/holmes/mcp/
├── server.py            # 删除 kb_submit 注册；新增 kb_draft 注册
└── tools.py             # 删除 handle_kb_submit；新增 handle_kb_draft；更新日志调用

kb/holmes/
└── cli.py               # 新增 @kb.command("drafts")；import_cmd 新增草稿移动逻辑

kb/tests/
└── test_mcp_tools.py    # 移除 TestKbSubmitPipeline；新增 TestKbDraft
```

---

## Phase 0: Research

见 [research.md](./research.md)

---

## Phase 1: Design

见 [data-model.md](./data-model.md) 和 [contracts/](./contracts/)
