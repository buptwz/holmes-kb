# Feature Specification: KB 包整合与 Bug 修复

**Feature**: 034-kb-consolidation-bugfix
**Date**: 2026-06-17
**Status**: Draft

---

## Overview

Holmes 项目中存在两套并行的 `holmes.kb` 实现（`holmes/holmes/kb/` 旧版与 `kb/holmes/kb/` 新版），且一批 IPC 通信相关代码在切换至 MCP 模式后已成为死代码。本 feature 完成以下工作：

1. **包整合**：将旧版 `holmes/holmes/kb/` 的 CLI 调用方切换至新版 `kb/holmes/kb/` API，消除双包并存问题，统一安装入口
2. **死代码清理**：删除已无人调用的 IPC 路径（`agent_server.py`、`ipc_server.py`、`agent/tools/kb_*.py`）
3. **Bug-4 修复**：skill 自动生成时名称来自 pending ID 时间戳，改为从条目 `title` 字段派生可读 kebab-case slug
4. **Bug-5 修复**：Extractor LLM 在选择 entry `type` 后，body section 结构与该 type 的 schema 要求不一致，需在 prompt 中强化 type-section 联动约束

---

## Problem Statement

### 双包并存（根因：Bug-2）

`holmes/cli.py` 同时从两个不同的 `holmes.kb` 实现中导入：
- KB 管理命令（list、pending、confirm 等）使用旧版 `holmes/holmes/kb/`
- `holmes import` 命令尝试使用新版 `kb/holmes/kb/agent/runner`，但旧版安装后不含该路径，导致 `ImportError`

工程师运行 `holmes import` 时必须手动设置 `PYTHONPATH` 才能工作，体验差且易出错。

### IPC 死代码

系统已从 IPC 通信模式切换为 MCP 模式，但旧 IPC 相关代码仍留在代码库中：
- `holmes/agent_server.py`、`holmes/agent/ipc_server.py`
- `holmes/agent/tools/kb_read.py`、`holmes/agent/tools/kb_write.py`

这些文件引用旧版 `holmes.kb` API，增加维护负担，也是双包并存的原因之一。

### Bug-4：Skill 名称不可读

自动生成的 skill 名称形如 `skill-pending20260617040251g0ww`——当条目 ID 是 pending ID 时，`_make_slug()` 仅去除连字符后取前 20 字符，结果是时间戳字符串。工程师和 agent 无法通过名称判断 skill 的用途。

### Bug-5：type 与 section 结构不匹配

Extractor 在判断 `type: decision` 的同时，body 仍使用 `## Symptoms / ## Root Cause / ## Resolution` 结构（pitfall 格式），与 schema 要求的 `## Context / ## Decision` 不符，导致写入的 KB 条目校验失败或内容语义错误。根因是 Extractor prompt 模板只展示 pitfall 结构，未明确其他 type 对应的 section 格式。

---

## User Stories

### US1 — 工程师可以用一条命令安装并运行 holmes import

**As** 一名运维工程师，
**I want** 运行 `pip install -e .` 后直接执行 `holmes import <file>` 不报错，
**So that** 不需要额外设置 `PYTHONPATH` 或安装额外包。

**Acceptance Criteria**:
- 主包安装后，`holmes import` 完整走 ImportAgentRunner pipeline，输出阶段日志
- 不需要手动执行 `pip install -e kb/`
- 已有的 `holmes kb list/pending/confirm` 等命令行为不变

### US2 — 死代码从代码库中移除

**As** 一名开发者，
**I want** 代码库中不包含无人调用的 IPC 相关模块，
**So that** 减少维护负担，新人不会被误导去理解死代码。

**Acceptance Criteria**:
- `holmes/agent_server.py`、`holmes/agent/ipc_server.py`、`holmes/agent/tools/kb_read.py`、`holmes/agent/tools/kb_write.py` 被删除
- 删除后所有现有测试仍通过
- `holmes tui` / `holmes agent start` 命令若无其他有效实现，相应 CLI 入口一并移除或给出明确错误

### US3 — Skill 名称从条目标题派生，清晰可读

**As** 一名使用 KB 的工程师或 agent，
**I want** 自动生成的 skill 名称能反映该 skill 的实际用途，
**So that** 在 `kb_list(type=skill)` 或 `skill_refs` 中能通过名称理解 skill 内容。

**Acceptance Criteria**:
- Skill slug 从条目 `title` 字段派生：转小写、非字母数字字符替换为连字符、去首尾连字符、截取合理长度
- 当 title 生成的 slug 已存在时，末尾追加序号（`-2`、`-3`）去重
- 仅在 title 为空时回退到 entry_id 派生（现有兜底逻辑）
- 生成的 slug 符合现有 skill name 格式约束（3-64 字符，kebab-case）

### US4 — Extractor 生成的 KB 条目 type 与 section 结构一致

**As** 一名使用 `holmes import` 的工程师，
**I want** 导入后生成的 KB 条目 type 和 body sections 始终匹配 schema 要求，
**So that** 不会因格式不合法导致条目校验失败或内容语义错误。

**Acceptance Criteria**:
- Extractor prompt 明确列出每种 type 对应的必需 sections
- 生成的条目选择 `decision` type 时，body 使用 `## Context / ## Decision`，不出现 `## Resolution`
- Verifier 阶段对 type-section 不一致的条目发出 warning 或自动修正
- 回归：pitfall 条目 `## Symptoms / ## Root Cause / ## Resolution` 结构不受影响

---

## Functional Requirements

### 包整合（US1）

- **FR-1**: 主 `pyproject.toml` 增加对 `kb/` 子包的本地依赖，使 `holmes-kb` 随主包一同安装
- **FR-2**: `holmes/holmes/kb/` 与 `kb/holmes/kb/` 之间同名模块（`store.py`、`pending.py` 等）的调用方统一切换至新版 API；旧版文件在迁移验证后删除
- **FR-3**: `holmes/cli.py` 中所有 `holmes.kb.*` 的顶层 import 改为从新版包路径导入，消除运行时双包歧义

### 死代码清理（US2）

- **FR-4**: 删除 `holmes/agent_server.py`、`holmes/agent/ipc_server.py`、`holmes/agent/tools/kb_read.py`、`holmes/agent/tools/kb_write.py`
- **FR-5**: 相应地删除或更新 `holmes/cli.py` 中对上述模块的引用（`holmes agent start`、`holmes tui` 相关命令）

### Bug-4 修复（US3）

- **FR-6**: `SkillAdvisor._make_slug()` 接受可选 `title` 参数；当 `title` 非空时，优先从 `title` 派生 slug；`title` 为空时保持现有 entry_id 回退逻辑
- **FR-7**: `SkillAdvisor.advise()` 将 `description`（即 title）参数传入 `_make_slug()`
- **FR-8**: slug 生成规则：小写化 → 非字母数字替换为 `-` → 合并连续 `-` → 去首尾 `-` → 截取前 40 字符 → 若与现有 skill 重名则追加 `-2`/`-3` 去重

### Bug-5 修复（US4）

- **FR-9**: `EXTRACTOR_SYSTEM_PROMPT` 中为每种 entry type 明确列出对应的必需 sections，格式为对照表（type → required sections）
- **FR-10**: Verifier 阶段（或 Normalizer）检查 `type` 与 body sections 的一致性，不一致时记录 warning 并尝试自动修正（优先修正 sections，保留 type）

---

## Out of Scope

- `holmes tui` TUI 功能本身的改动（TUI 通过 MCP 与 KB 交互，不受本次改动影响）
- `kb/holmes/kb/` 新包内部逻辑的修改（本 feature 只做调用方迁移，不改实现）
- `holmes agent start` 替代实现（若移除后无替代，该命令直接移除）
- CFG-1（分阶段模型配置）留待后续 feature

---

## Assumptions

- `kb/holmes/kb/` 的新版 `store.py`、`pending.py`、`linter.py`、`merger.py`、`conflict.py`、`validator.py` 提供的功能覆盖旧版所有被 CLI 使用的函数（已通过代码对比验证）
- API 差异（如 `get_entry` → `read_entry`，`KnowledgeEntry` → `EntryMeta`）通过更新 CLI 调用方解决，不需要在新包中增加兼容层
- 旧版 `holmes/holmes/kb/index_builder.py` 的 `rebuild_index` 功能在新版 `store.py` 的 `rebuild_index_files()` 中有对应实现
- 现有测试套件（`kb/tests/`）覆盖新版 API，迁移后回归测试基线不下降

---

## Success Criteria

1. `pip install -e .`（仅主包）后，`holmes import <file>` 无需额外环境变量即可完整运行
2. 所有现有 `holmes kb *` CLI 命令行为与迁移前完全一致，测试通过数不低于迁移前基线（733）
3. 自动生成的 skill 名称中不再出现 `pending` 前缀或纯数字时间戳片段
4. 使用 20 步多分支测试文档导入后，所有生成的 KB 条目通过 schema 校验（无 type-section 不匹配错误）
5. 代码库中不再存在 `ipc_server.py`、`agent_server.py`、`agent/tools/kb_read.py`、`agent/tools/kb_write.py`
