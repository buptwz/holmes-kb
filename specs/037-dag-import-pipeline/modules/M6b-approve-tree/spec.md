# Feature Specification: M6b — Pending/Approve 树级联

**Feature Branch**: `dev-M6b`

**Created**: 2026-06-24

**Status**: Draft

## User Scenarios & Testing

### User Story 1 - Approve Pitfall Tree Cascade (Priority: P1)

工程师运行 `holmes kb approve <pitfall-root-id>`，系统自动级联处理整棵排查树（root + 所有 process sub-entries），而非只处理单个 entry。approve 操作原子执行：要么全部成功，要么全部回滚。

**Why this priority**: 树形结构的 pitfall entries 若只 approve root 不 approve sub-entries，会导致 agent 导航链接断裂，知识库功能不完整。

**Independent Test**: 创建一棵 3 节点 pending 树（1 pitfall root + 2 process sub-entries），运行 `holmes kb approve <root-id>`，验证三个文件全部从 `_pending/` 移入 confirmed 空间且 `kb_status=active`。

**Acceptance Scenarios**:

1. **Given** `_pending/` 中有 pitfall root + 2 个 process sub-entries（通过 `child_entry_ids` 链接），**When** `holmes kb approve <root-id>`，**Then** 3 个 entries 全部 approved，root 和 sub-entries 均出现在 confirmed 空间
2. **Given** approve 中途某个 sub-entry 失败，**When** approve 操作继续，**Then** 已 approved 的 entries 回滚回 `_pending/`，KB 恢复到 approve 前的状态
3. **Given** entry 有 `parent_id`（process sub-entry），**When** `holmes kb approve <sub-entry-id>`，**Then** 只 approve 该单个 entry（M6a 行为）

---

### User Story 2 - Old Tree Cleanup on Approve (Priority: P1)

approve 新 pending 树时，系统检测同 `source_file` 的旧 pending 树和旧 confirmed 树，逐步提示用户取消/deprecate，最终一次执行清理两层旧数据。

**Why this priority**: 没有级联清理会导致同一文档存在多套 entries（新旧并存），破坏知识库的 source_file 一致性约束。

**Independent Test**: 构造三层并存场景（1 confirmed 树 + 1 旧 pending 树 + 1 新 pending 树），approve 新树后验证旧 pending 被取消、旧 confirmed 被 deprecated、新树变为 active。

**Acceptance Scenarios**:

1. **Given** 同 `source_file` 存在旧 pending pitfall 树 hw-001 和新 pending 树 hw-002，**When** approve hw-002，**Then** 显示"发现旧 pending entries：hw-001 及其 N 个关联 entries，取消旧 pending 树？[Y/n]"
2. **Given** 同 `source_file` 存在 confirmed active pitfall 树 hw-000，**When** approve hw-002，**Then** 显示"发现 active entries：hw-000 及其 K 个关联 entries，标记为 deprecated？[Y/n]"
3. **Given** 三层并存（confirmed hw-000 + 旧 pending hw-001 + 新 pending hw-002），**When** approve hw-002 并确认，**Then** hw-001 树被取消，hw-000 树被 deprecated，hw-002 树变为 active
4. **Given** `--no-interactive` 模式，**When** approve pitfall root，**Then** 自动接受旧 pending 取消和旧 confirmed deprecate

---

### User Story 3 - Tree-Grouped Pending Display (Priority: P2)

`holmes kb pending` 以 pitfall root 为组标题，process sub-entries 缩进显示，非 pitfall 类型（guideline 等）平铺展示。

**Why this priority**: 当 pending 空间有树形结构时，扁平列表无法反映 entries 之间的关联关系，reviewer 难以判断哪些 entries 属于同一批 import。

**Independent Test**: 写入 1 个 pitfall root + 2 个 process sub-entries + 1 个 guideline 到 `_pending/`，运行 `holmes kb pending`，验证输出中 pitfall root 显示 `[pitfall root]` 标签，sub-entries 缩进显示在 root 下方，guideline 平铺显示。

**Acceptance Scenarios**:

1. **Given** `_pending/hardware/` 有 pitfall root + 3 个 process sub-entries，**When** `holmes kb pending`，**Then** 输出格式为：`├── <root-id> [pitfall root] <date>` + 缩进的 sub-entries
2. **Given** `_pending/network/` 有 guideline 类型 entry，**When** `holmes kb pending`，**Then** guideline 单独平铺显示（非树形），带 `[guideline]` 标签
3. **Given** `_pending/` 为空，**When** `holmes kb pending`，**Then** 显示 "No pending entries."

---

## Functional Requirements

### FR1 — collect_tree 函数
- 从 `root_id` 出发，递归读取 `child_entry_ids`，收集整棵树所有 entry ID
- 同时搜索 `_pending/` 和 confirmed 空间（先搜 pending，再搜 confirmed）
- 防止循环引用：已访问过的 ID 跳过
- 返回有序列表，root 在最前

### FR2 — approve_tree 函数
- 调用 `collect_tree` 获取树 IDs
- 预检查所有 entries 在 `_pending/` 中存在
- 按拓扑逆序（叶节点先，root 最后）逐一调用 `approve_entry`
- 任一步骤失败：回滚已 approved entries（移回 `_pending/`）
- 返回已 approved 文件路径列表

### FR3 — deprecate_tree 函数
- 调用 `collect_tree` 收集 confirmed 空间的树
- 对每个 ID 调用 `deprecate_entry`
- 返回被 deprecated 的 entry ID 列表

### FR4 — cancel_pending_tree 函数
- 调用 `collect_tree` 收集 `_pending/` 空间的树
- 直接删除文件（不走 `_trash/`）
- 返回已取消的文件路径列表

### FR5 — holmes kb approve 树级联流程
- 读取 pending entry frontmatter，检测是否为 pitfall root（`type=="pitfall"` 且无 `parent_id`）
- **是 pitfall root**：执行树级联流程
  - Step 1: `collect_tree(entry_id)` 获取当前 pending 树（包含 root + 所有 sub-entries）
  - Step 2: 检测旧 pending 树（同 `source_file`，`type=="pitfall"`，不在当前树中），展示并询问取消
  - Step 3: 检测旧 confirmed 树（同 `source_file`，`type=="pitfall"`，`kb_status=="active"`），展示并询问 deprecate
  - Step 4: 展示摘要（"取消 N 个旧 pending + deprecate M 个旧 confirmed + approve K 个新 entries"），最终 [Y/n] 确认
  - Step 5: 执行 `cancel_pending_tree` + `deprecate_tree` + `approve_tree`
  - Step 6: 重建 category index
- **是 process sub-entry**（有 `parent_id`）：沿用 M6a 单 entry approve 行为

### FR6 — holmes kb pending 树形分组展示
- 扫描 `_pending/` 所有 entries，读取 `parent_id` 和 `child_entry_ids`
- 找出 pitfall roots（`type=="pitfall"` 且无 `parent_id`）
- 按 category 分组，每组内：
  - pitfall roots 显示 `├── <id>  [pitfall root]  <date>`
  - 各 root 的子树 entries 缩进显示（`│     <child-id>  [process]`）
- 非 pitfall 类型 entries 平铺显示在各自 category 下
- process sub-entries（有 `parent_id`）不在平铺列表中重复出现

---

## Success Criteria

- `holmes kb approve <pitfall-root-id>` 成功级联 approve 包含根节点和至少 3 个 process sub-entries 的树，整个操作在 5 秒内完成
- 三层并存场景（confirmed + 旧 pending + 新 pending）下，一次 approve 操作清理两层旧数据，approved 后 `holmes kb list` 只显示 1 套 active entries
- approve 操作失败后，KB 状态与 approve 前完全一致（原子性保证）
- `holmes kb pending` 树形展示与扁平展示混合输出，reviewer 能直观看出哪些 entries 属于同一棵树
- `collect_tree` 遇到循环引用 DAG 不陷入死循环

---

## Dependencies and Assumptions

- **M5 依赖**：M5 生成的 entries 包含 `parent_id` / `child_entry_ids` frontmatter 字段（M6b 依赖这些字段做树遍历）
- **M6a 依赖**：M6b 在 M6a 已实现的 `approve_entry()` / `deprecate_entry()` / `write_pending()` 基础上封装树操作
- **假设**：`child_entry_ids` 中的注释（`# <title>`）格式可选，不影响功能
- **假设**：一次 import 只生成一棵树（单 pitfall root）；multi-incident 场景有多棵树但每棵树独立 approve
- **假设**：`_scan_all_entries` 需补充 `parent_id` 字段以支持新格式 pending entries 的类型检测

---

## Scope Boundaries

**In scope**:
- `store.py`：新增 `collect_tree`、`approve_tree`、`deprecate_tree`、`cancel_pending_tree`
- `cli.py`：改造 `holmes kb approve`（树级联）和 `holmes kb pending`（树形展示）
- 单元测试覆盖所有新函数和 CLI 变更

**Out of scope**:
- `holmes kb delete` 的树级联（另一个 spec）
- 多 pitfall root 树的批量 approve
- `_trash/` 机制的集成（cancel 直接删除，不走 trash）
