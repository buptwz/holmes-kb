# Implementation Plan: M1 — 基础字段与过滤

**Branch**: `dev-M1` | **Date**: 2026-06-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/037-dag-import-pipeline/modules/M1-basic-fields/spec.md`

## Summary

为所有 KB entry 的 frontmatter 新增 8 个可选字段（`kb_status`、`source_file`、`source_hash`、`description`、`import_trace_id`、`pitfall_structure`、`child_entry_ids`、`parent_id`），并在 `store.py`、`search.py`、`cli.py`、`config.py` 中实现基于 `kb_status` 的状态过滤、process sub-entry 可见性控制、ID 格式无关化查找、树导航 children 附加字段，以及 `holmes config set username` 命令。所有改动向后兼容旧 entry。

## Technical Context

**Language/Version**: Python 3.10+

**Primary Dependencies**: `click`（CLI）、`python-frontmatter`（YAML frontmatter 解析）、`pathlib.Path`（文件系统扫描）

**Storage**: Markdown 文件（YAML frontmatter + Markdown body），存储于 `~/holmes-kb/` 文件系统目录，由 git 追踪

**Testing**: `pytest`（现有测试套件位于 `kb/tests/`）

**Target Platform**: Linux (Ubuntu)

**Project Type**: Python CLI 工具（`holmes-kb` package）

**Performance Goals**: `list_entries()` 对 ≤1000 条 entry 的 KB 扫描时间 < 500ms；`find_entry()` 对 ≤1000 条 entry < 200ms

**Constraints**: 新增参数必须有默认值，确保现有调用方无需修改；旧 entry（无新字段）行为不变

**Scale/Scope**: KB 规模 ≤1000 条 entries；单 import 会话产生 ≤50 个 entries

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 评估 | 结论 |
|------|------|------|
| 开闭原则 | 新增 `kb_status`/`exclude_sub_entries` 参数有默认值，现有调用方无需修改 | ✅ PASS |
| 单一职责原则 | schema.py 只定义类型，store.py 只做 IO，cli.py 只做 CLI 路由 | ✅ PASS |
| 依赖倒置原则 | store.py 不依赖 CLI 层；search.py 依赖 store 抽象接口 | ✅ PASS |
| 渐进式实现 | 仅在现有函数上新增参数和字段，无新抽象层 | ✅ PASS |
| 自动化验证 | 须为每个新行为编写 pytest 单元测试 | ✅ REQUIRED |
| 环境配置 | `username` 存入 `~/.holmes/config.json`，不硬编码 | ✅ PASS |
| 向后兼容 | 缺省 `kb_status` 字段视为 `active`；新参数有默认值 | ✅ PASS |

**Constitution Check 结论**: 所有门控通过，无复杂性豁免需求。

## Project Structure

### Documentation (this feature)

```text
specs/037-dag-import-pipeline/modules/M1-basic-fields/
├── brief.md             # 模块说明（已存在）
├── spec.md              # 功能规格（/speckit-specify 输出）
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── contracts/           # Phase 1 输出（CLI schema）
└── tasks.md             # Phase 2 输出（/speckit-tasks 命令）
```

### Source Code (repository root)

```text
kb/
├── holmes/
│   ├── kb/
│   │   ├── schema.py        # 新增 KBStatus 类型 + 可选字段注释
│   │   ├── store.py         # EntryMeta 新字段 + list_entries() 过滤 + find_entry() + read_entry() children
│   │   └── search.py        # LinearScanBackend 状态过滤 + sub-entry 过滤
│   ├── mcp/
│   │   └── tools.py         # handle_kb_list 过滤 + _is_entry_id 新格式路由 + _read_entry children
│   ├── cli.py               # kb list/search --all/--all-types; kb show sub-entry 标签; config set username
│   └── config.py            # HolmesConfig.username 字段
└── tests/
    ├── test_m1_schema.py        # 新增：KBStatus 类型 + 字段注释测试
    ├── test_m1_store_filter.py  # 新增：list_entries 过滤测试（kb_status + sub-entry）
    ├── test_m1_find_entry.py    # 新增：find_entry 新旧格式 ID 测试
    ├── test_m1_read_entry.py    # 新增：read_entry children 附加测试
    ├── test_m1_search_filter.py # 新增：search 状态过滤测试
    ├── test_m1_mcp.py           # 新增：mcp tools 过滤 + routing + children 测试
    └── test_m1_config.py        # 新增：username config 测试
```

**Structure Decision**: Single project layout，所有改动都在 `kb/` 目录下，按文件职责分离测试。

## Complexity Tracking

N/A — 无 Constitution Check 违例。
