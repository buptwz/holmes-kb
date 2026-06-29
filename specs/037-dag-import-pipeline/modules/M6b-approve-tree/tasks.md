# Tasks: M6b — Pending/Approve 树级联

**Input**: Design documents from `specs/037-dag-import-pipeline/modules/M6b-approve-tree/`

**Branch**: `dev-M6b`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: 确认依赖关系，无需新建包或配置文件

- [X] T001 验证 M6a 中 `approve_entry`/`deprecate_entry`/`write_pending`/`_find_pending_entry` 已正确实现（阅读 `kb/holmes/kb/store.py`）

---

## Phase 2: Foundational — store.py 树操作函数

**Purpose**: 新增 4 个树操作函数 + 修复 `_scan_all_entries`，所有 US 均依赖这些基础函数

**⚠️ CRITICAL**: CLI 改造必须在本阶段完成后进行

- [X] T002 在 `kb/holmes/kb/store.py` 的 `_scan_all_entries` 函数中，为新格式（`_pending/<type>/<category>/`）的 EntryMeta 补充 `parent_id=meta.get("parent_id") or None` 字段

- [X] T003 在 `kb/holmes/kb/store.py` 末尾新增 `collect_tree(kb_root: Path, root_id: str) -> list[str]` 函数：
  - DFS 递归遍历 `child_entry_ids`
  - 先搜 `_find_pending_entry`，再搜 `find_entry`
  - `visited: set[str]` 防循环引用（key 用 `entry_id.lower()`）
  - root 在列表最前，children 深度优先追加

- [X] T004 在 `kb/holmes/kb/store.py` 新增 `approve_tree(kb_root: Path, root_id: str) -> list[str]` 函数：
  - 调用 `collect_tree` 获取 tree_ids
  - 预检查：所有 entry 必须在 `_pending/` 中（否则 FileNotFoundError）
  - 按 `reversed(tree_ids)` 顺序（叶优先）逐一调用 `approve_entry`
  - 失败时回滚：已 approved 的 entries 写回 `_pending/`（`kb_status=pending`），删除 confirmed 文件
  - 返回 confirmed 文件路径列表（str）

- [X] T005 在 `kb/holmes/kb/store.py` 新增 `deprecate_tree(kb_root: Path, root_id: str) -> list[str]` 函数：
  - 调用 `collect_tree` 获取 tree_ids（在 confirmed 空间）
  - 对每个 ID 调用 `deprecate_entry`
  - 返回被 deprecated 的 entry ID 列表

- [X] T006 在 `kb/holmes/kb/store.py` 新增 `cancel_pending_tree(kb_root: Path, root_id: str) -> list[str]` 函数：
  - 调用 `collect_tree` 获取 tree_ids（在 `_pending/` 空间）
  - 对每个 ID 用 `_find_pending_entry` 定位文件路径
  - `os.unlink(path)` 直接删除，不走 `_trash/`
  - 返回已删除的文件路径列表（str）

**Checkpoint**: store.py 基础函数完成，CLI 改造可并行进行

---

## Phase 3: User Story 1 — Approve Pitfall Tree Cascade (P1) 🎯 MVP

**Goal**: `holmes kb approve <pitfall-root-id>` 级联 approve 整棵树（原子性，失败回滚）

**Independent Test**: 创建 1 pitfall root + 2 process sub-entries pending 树，运行 approve，验证 3 个文件全部移入 confirmed 空间且 `kb_status=active`

- [X] T007 [US1] 修改 `kb/holmes/cli.py` 的 `kb_approve` 命令：在读取 pending entry frontmatter 后，检测是否为 pitfall root（`type=="pitfall"` 且 `parent_id` 为空），若是则进入树级联分支，否则沿用现有 M6a 单 entry 流程

- [X] T008 [US1] 在 `kb_approve` 的树级联分支中实现 Step 1 和 Step 4：
  - Step 1: `collect_tree(kb_root, entry_id)` 收集整棵 pending 树；显示 `"\n准备 approve: {entry_id}（及其 {len(tree)-1} 个关联 entries）"`
  - Step 4: 显示摘要 `"执行：取消 N 个旧 pending + deprecate M 个旧 confirmed + approve K 个新 entries"`，若非 `--no-interactive` 则 prompt `"确认？[Y/n]"`

- [X] T009 [US1] 在 `kb_approve` 树级联分支中实现 Step 5（执行阶段）：
  - `approve_tree(kb_root, entry_id)`（始终执行）
  - `cancel_pending_tree(kb_root, old_root_id)`（若用户选 Y）
  - `deprecate_tree(kb_root, old_conf_root_id)`（若用户选 Y）
  - 完成后调用 `rebuild_index_files(kb_root)`（若 _index.md 存在）

- [X] T010 [P] [US1] 创建 `kb/tests/test_approve_tree.py`，实现以下测试：
  - `test_collect_tree_single_entry`：单节点树，返回 `[root_id]`
  - `test_collect_tree_with_children`：root + 2 children，返回 3 个 ID
  - `test_collect_tree_cycle_safe`：制造循环引用（child_entry_ids 含 root），验证不死循环
  - `test_collect_tree_searches_pending_and_confirmed`：root 在 pending，child 在 confirmed，两者都能找到
  - `test_approve_tree_approves_all`：root + 2 children，全部 approved 后在 confirmed 空间
  - `test_approve_tree_rollback_on_failure`：mocked `approve_entry` 在第 2 次失败，验证第 1 个已 approved entry 回滚到 `_pending/`
  - `test_approve_tree_raises_if_entry_missing_from_pending`：child 不在 pending，预期 FileNotFoundError

---

## Phase 4: User Story 2 — Old Tree Cleanup on Approve (P1)

**Goal**: approve 时检测并清理旧 pending/confirmed 树，支持三层并存场景

**Independent Test**: 三层并存（confirmed hw-001 + 旧 pending hw-002 + 新 pending hw-003），approve hw-003 后验证：hw-002 tree 被取消，hw-001 tree 被 deprecated，hw-003 tree active

- [X] T011 [US2] 在 `kb_approve` 树级联分支中实现 Step 2（旧 pending 检测）：
  - `find_entries_by_source_file(kb_root, source_file)` 获取所有同源条目
  - 过滤 `old_pending_roots`：`kb_status=="pending" AND type=="pitfall" AND id not in current_tree_ids`
  - 对每个 old root 调用 `collect_tree(old_root)` 获取旧 pending 树 IDs
  - 显示 `"\n[pending 空间] 发现同文档的旧 pending entries：\n  - {old_root}（{date}，未审核）及其 {len(old_tree)-1} 个关联 entries"`
  - prompt `"  取消旧 pending 树？[Y/n]"`（`--no-interactive` 自动 Y）

- [X] T012 [US2] 在 `kb_approve` 树级联分支中实现 Step 3（旧 confirmed 检测）：
  - 过滤 `old_confirmed_roots`：`kb_status=="active" AND type=="pitfall"`
  - 对每个 old root 调用 `collect_tree(old_root)` 获取旧 confirmed 树 IDs
  - 显示 `"\n[confirmed 空间] 发现同文档的 active entries：\n  - {old_root}（{date}，已 approve）及其 {len(old_tree)-1} 个关联 entries"`
  - prompt `"  标记为 deprecated？[Y/n]"`（`--no-interactive` 自动 Y）

- [X] T013 [P] [US2] 在 `test_approve_tree.py` 中新增：
  - `test_three_layer_scenario`：构造 3 层并存（confirmed 树 + 旧 pending 树 + 新 pending 树），通过 CLI `CliRunner` invoke `approve --no-interactive <new-root>`，验证旧 pending tree 文件删除、旧 confirmed tree `kb_status=deprecated`、新 tree `kb_status=active`
  - `test_approve_tree_sub_entry_uses_m6a_path`：entry 有 `parent_id` 时，CLI 走 M6a 单 entry 路径（不调用 collect_tree）
  - `test_cancel_pending_tree`：root + 2 children 在 pending，cancel 后 3 个文件均消失
  - `test_deprecate_tree`：root + 2 children 在 confirmed，deprecate 后 3 个 `kb_status=deprecated`

---

## Phase 5: User Story 3 — Tree-Grouped Pending Display (P2)

**Goal**: `holmes kb pending` 以 pitfall root 为组标题，process sub-entries 缩进显示

**Independent Test**: 写入 1 pitfall root + 2 process sub-entries + 1 guideline，运行 `holmes kb pending`，输出包含 `[pitfall root]` 标签和缩进 sub-entries

- [X] T014 [US3] 修改 `kb/holmes/cli.py` 的 `kb_pending` 命令，在收集 new_entries 时同时读取 `parent_id` 和 `child_entry_ids` 字段：
  ```python
  new_entries.append({
      ...existing fields...,
      "parent_id": str(meta.get("parent_id", "") or ""),
      "child_entry_ids": list(meta.get("child_entry_ids") or []),
  })
  ```

- [X] T015 [US3] 在 `kb_pending` 的非 JSON 显示路径中，替换现有扁平显示逻辑为树形显示逻辑：
  1. 构建 `entries_map: {id → entry_dict}` 和 `pending_ids: set`
  2. 找出 pitfall roots：`type=="pitfall"` 且 `parent_id` 为空
  3. 按 category 分组（pitfall roots + 非树 entries）
  4. 计算 `tree_child_ids: set`：所有 pitfall root 的子树 IDs（防止 sub-entries 在平铺列表中重复出现）
  5. 对每个 category 输出：
     - `"\n[{cat}]"`
     - 各 pitfall root：`"  ├── {id:<40} [pitfall root]  {date[:10]} import"`
     - 其 sub-entries（从 child_entry_ids 递归收集，仅取 pending_ids 中存在的）：`"  │     {child_id:<38} [process]"`
     - 非 pitfall 类型且不是任何树 sub-entry 的 entries：`"  {id:<42} [{type}]     {date[:10]} import"`
  6. 显示总 entry 数：`"_pending/ ({total} entries)"`

- [X] T016 [P] [US3] 在 `test_approve_tree.py` 中新增：
  - `test_pending_display_tree_grouped`：1 pitfall root + 2 process children + 1 guideline，验证输出含 `[pitfall root]`、缩进 child_ids、`[guideline]` 平铺
  - `test_pending_display_no_sub_entry_duplication`：process sub-entry 已显示在树中，不在平铺列表中重复出现
  - `test_pending_display_no_entries`：`_pending/` 为空，显示 "No pending entries."

---

## Phase 6: Polish

- [X] T017 运行完整测试套件 `cd kb && python -m pytest tests/ -x -q`，确保所有 M6b 测试通过且无回归

- [X] T018 [P] 验证验收条件覆盖：
  - `holmes kb approve <pitfall-root-id>` 级联 approve
  - 不允许部分 approve（中途失败回滚）
  - 旧 pending 树级联取消
  - 旧 confirmed 树级联 deprecated
  - 三层并存清理
  - process sub-entry 沿用 M6a
  - `holmes kb pending` 树形分组
  - `collect_tree` 循环引用安全

---

## Dependencies

```
T001 → T002 → T003 → T004 → T005 → T006 (基础函数，顺序构建)
T006 → T007 → T008 → T009 (CLI US1 树级联)
T006 → T011 → T012 (CLI US2 旧树检测)
T003-T006 → T010 (US1 测试，可并行写测试骨架)
T009-T012 → T013 (US2 测试)
T015 → T016 (US3 测试)
T009 + T012 + T015 → T017 (全套测试验证)
```

## Parallel Execution

以下任务可并行执行（不同文件，无依赖）：
- T010（测试文件）可与 T007-T009（CLI 实现）并行
- T014-T015（US3 pending 显示）可与 T011-T012（US2 旧树检测）并行，前提是 T002-T006 已完成

## Implementation Strategy

**MVP**: Phase 1 + Phase 2 + Phase 3（T001-T010）= 树级联 approve 核心功能可用

**Increment 2**: Phase 4（T011-T013）= 旧树清理功能完整

**Full**: Phase 5 + Phase 6（T014-T018）= pending 树形展示 + 验收完整

---

**Total tasks**: 18
**Tasks per user story**:
- US1 (Approve Tree Cascade): T007, T008, T009, T010 → 4 tasks
- US2 (Old Tree Cleanup): T011, T012, T013 → 3 tasks
- US3 (Tree-Grouped Pending): T014, T015, T016 → 3 tasks
- Foundational: T001-T006 → 6 tasks
- Polish: T017-T018 → 2 tasks
