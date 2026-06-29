# Feature Specification: M6a — Pending/Approve 基础流程

**Feature Branch**: `dev-M6a`

**Created**: 2026-06-23

**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 写入 Pending 并 Approve 新 Entry (Priority: P1)

工程师完成文档 import 后，生成的 entries 以 `kb_status: pending` 写入 `_pending/<category>/`。审核通过后，运行 `holmes kb approve <id>` 将 entry 移入正式 `<category>/`，`kb_status` 变为 `active`，立即可被 `holmes kb list` 和 agent 检索。

**Why this priority**: approve 是 pending → active 流程的核心，无此功能 import pipeline 无法落地。

**Independent Test**: 可通过"写入一个 pending entry → 运行 approve → 验证 list 可见"独立验证。

**Acceptance Scenarios**:

1. **Given** `_pending/hardware/hw-init-001.md` 存在且 `kb_status: pending`，**When** 运行 `holmes kb approve hw-init-001`，**Then** 文件出现在 `hardware/hw-init-001.md`，`kb_status` 为 `active`，`_pending/hardware/hw-init-001.md` 被删除。
2. **Given** approve 完成，**When** 运行 `holmes kb list`，**Then** `hw-init-001` 出现在列表中。
3. **Given** `_pending/network/` 目录不存在，**When** 调用 `write_pending(kb_root, "dns-001", content, "network")`，**Then** 目录自动创建，`_pending/network/dns-001.md` 被写入。

---

### User Story 2 — Approve 前冲突检测与 Deprecate (Priority: P2)

审核员运行 approve 前，系统自动检测同 `source_file` 的旧 pending entries 和 active confirmed entries，分别询问是否取消/deprecate，再原子执行所有操作。

**Why this priority**: 冲突处理是避免知识重复、保持 KB 一致性的关键。

**Independent Test**: 可在三层并存场景（confirmed 旧版 + pending 旧版 + pending 新版）中独立测试。

**Acceptance Scenarios**:

1. **Given** `hw-init-001`（confirmed active）和 `hw-init-002`（pending）来自同一 `source_file`，**When** approve `hw-init-002`，**Then** 系统展示旧 pending 列表，询问"取消旧 pending？[Y/n]"。
2. **Given** 用户回答 Y，**When** 系统继续，**Then** 展示旧 confirmed 列表，询问"标记为 deprecated？[Y/n]"。
3. **Given** 用户两步均确认 Y，**When** 执行，**Then** `hw-init-001` 的 `kb_status` 改为 `deprecated`（文件不移动），`hw-init-002` 变为 `active`。
4. **Given** 三层并存（`hw-001` confirmed + `hw-002` pending 旧版 + `hw-003` pending 新版），**When** approve `hw-003`，**Then** `hw-002` 被删除，`hw-001` 被 deprecate，`hw-003` 变为 active。

---

### User Story 3 — holmes kb pending 按 Category 分组展示 (Priority: P3)

`holmes kb pending` 同时扫描新格式 `_pending/<category>/` 和旧格式 `contributions/pending/`，按 category 分组展示所有待审核 entries。

**Why this priority**: 可见性是 pending 流程的基础，审核员需要知道有哪些 entries 等待 approve。

**Independent Test**: 创建若干不同 category 的 pending entries，运行命令验证分组展示。

**Acceptance Scenarios**:

1. **Given** `_pending/hardware/hw-001.md` 和 `_pending/network/net-001.md` 存在，**When** 运行 `holmes kb pending`，**Then** 输出按 `[hardware]` 和 `[network]` 分组，每组列出该组的 entries。
2. **Given** 旧格式 `contributions/pending/pending-xxx.md` 存在，**When** 运行 `holmes kb pending`，**Then** 旧格式 entries 也出现在输出中（可在独立 legacy 区块或 category 分组末尾）。
3. **Given** `_pending/` 和 `contributions/pending/` 均为空，**When** 运行 `holmes kb pending`，**Then** 输出 "No pending entries."。

---

### Edge Cases

- approve 不存在的 entry_id → 打印错误信息，退出非零。
- `_pending/<category>/` 内 entry 的 `category` frontmatter 字段与目录名不一致 → 以目录名为准确定目标目录。
- approved entry 没有 `source_file` 字段 → 跳过冲突检测步骤，直接 approve。
- `<category>/` 目标目录不存在 → approve 时自动创建。
- `deprecate_entry` 对不存在的 entry_id → 返回 False / 打印警告，不抛异常。
- `_index.md` 不存在的 category → approve 后跳过 index 更新（不报错）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `write_pending(kb_root, entry_id, content, category)` 必须将 entry 原子写入 `_pending/<category>/<entry_id>.md`，目录不存在时自动创建。
- **FR-002**: `find_entries_by_source_file(kb_root, source_file)` 必须扫描 `_pending/` 和所有 confirmed 类型目录，返回 `source_file` 字段匹配的 `EntryMeta` 列表。
- **FR-003**: `approve_entry(kb_root, entry_id)` 必须将 pending entry 从 `_pending/<category>/` 移入 `<category>/`，并将 `kb_status` 更新为 `active`。
- **FR-004**: `deprecate_entry(kb_root, entry_id)` 必须 in-place 将 confirmed entry 的 `kb_status` 改为 `deprecated`，不移动文件。
- **FR-005**: `holmes kb approve <id>` 必须执行四步流程：旧 pending 检测 → 旧 confirmed 检测 → 原子执行 → index 更新。
- **FR-006**: approve 的原子执行必须遵循"先写新文件，再删旧文件"顺序，任一步骤失败时记录日志，避免留下半成品。
- **FR-007**: `holmes kb pending` 必须扫描 `_pending/<category>/` 新格式，按 category 分组展示，并兼容扫描旧格式 `contributions/pending/`。
- **FR-008**: `holmes kb list` 默认只显示 `kb_status: active` 的 entries（既有行为，approve 后立即可见）。
- **FR-009**: approve 后若 `<category>/_index.md` 存在，必须触发该文件的更新（调用 `rebuild_index_files` 或等价逻辑）。
- **FR-010**: `holmes kb approve` 每步确认支持 `[Y/n]`，默认 Y；用户输入 n 时该步骤跳过（不中止整体流程）。

### Key Entities

- **PendingEntry (新格式)**: 存储在 `_pending/<category>/<entry_id>.md`，frontmatter 含 `kb_status: pending`、`source_file`、`category`。
- **ConfirmedEntry**: 存储在 `<category>/<entry_id>.md`，`kb_status: active` 或 `deprecated`。
- **EntryMeta**: 现有 dataclass，含 `id`、`kb_status`、`source_file`（新增）、`category`、`file_path` 字段。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: approve 单个 entry 的完整流程（含冲突检测）在 1 秒内完成（不含 LLM 调用）。
- **SC-002**: 三层并存场景下，一次 approve 操作正确处理所有层（100% 正确率，无遗漏）。
- **SC-003**: `holmes kb pending` 能正确分组展示所有新旧格式 pending entries，分组准确率 100%。
- **SC-004**: approve 操作失败时，不留下半成品状态（文件系统一致性 100%）。
- **SC-005**: 所有新增函数有单元测试覆盖，覆盖 approve 基本流程、旧 pending 清理、旧 confirmed deprecate、三层并存四个场景。

## Assumptions

- M1 已完成：`kb_status`、`source_file`、`source_hash` 字段已在 EntryMeta 和 list_entries 中支持。
- M8 已完成：HolmesLogger 接口可用；approve 后写 `kb.approve` span（含 entry_id、user、duration_ms）。
- `find_entries_by_source_file` 作为 M2 前置依赖，在本模块一并实现，不等待 M2 分支。
- `_pending/` 目录与 `contributions/pending/` 目录并存，现有旧 pending 逻辑不变（向后兼容）。
- approve 时 `category` 由 pending 文件的目录名确定（优先），frontmatter `category` 字段作为备用。
- `deprecate_entry` 的搜索范围：所有 confirmed 类型目录（pitfall/model/guideline/process/decision），不扫 `_pending/`。
- category index 更新使用现有 `rebuild_index_files()` 函数（store.py 已有），而非增量更新。
- 本模块处理单个 entry 的 approve；M6b 负责 pitfall 树的级联 approve（依赖本模块）。
