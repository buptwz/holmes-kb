# Research: M6b — Pending/Approve 树级联

## 决策 1：树遍历策略（BFS vs DFS）

**Decision**: DFS（递归），root 在结果列表最前

**Rationale**: DFS 递归实现简洁，result 列表自然产生 root-first 顺序。approve 时 reversed(result) 即为叶优先（topological 逆序）。BFS 同样可行但代码更复杂。

**Alternatives considered**: BFS（队列）—— 同样防循环，但实现更繁琐；无明显性能优势。

---

## 决策 2：collect_tree 搜索顺序

**Decision**: 先搜 `_pending/`（`_find_pending_entry`），再搜 confirmed（`find_entry`）

**Rationale**: 正常 approve 流程中，整棵树在 `_pending/`；approve 后，整棵树在 confirmed。先搜 pending 可以正确处理 approve-in-progress 和 cancel-pending-tree 场景。

---

## 决策 3：原子性保证策略

**Decision**: 预检查（pre-validate）+ 顺序执行 + 失败时回滚

**Rationale**:
- 预检查阶段：验证所有 tree entries 都在 `_pending/`，如有缺失则提前 fail，不执行任何 approve
- 执行阶段：叶优先（reversed），每次调用 `approve_entry`
- 回滚：已 approved 的 entries 移回 `_pending/`（重建目录，写回 `kb_status=pending`，删除 confirmed 文件）

**Alternatives considered**: 事务文件（写临时文件再 rename）—— 复杂且 file-system 层面不跨目录原子；直接信任文件系统 fsync —— 不可跨目录保证。

---

## 决策 4：老 pending 树检测方式

**Decision**: 用 `type == "pitfall"` 区分树根 vs sub-entry

**Rationale**: `_scan_all_entries` 对新格式 pending entries 缺少 `parent_id` 字段，但 `type` 字段已正确读取。pitfall roots 的 type 一定是 `"pitfall"`；process sub-entries 的 type 是 `"process"`。通过 `type == "pitfall"` 过滤即可找到旧 pending 树根，再 `collect_tree(old_root)` 收集整棵旧树。

**Fix needed**: `_scan_all_entries` 需补充 `parent_id` 字段（从 frontmatter 读取），否则后续功能无法按 `parent_id` 过滤。这是小改动（一行 `parent_id=meta.get("parent_id") or None`）。

---

## 决策 5：holmes kb pending 树形显示策略

**Decision**:
1. 读取所有 `_pending/` entries 的 frontmatter（含 `parent_id`、`child_entry_ids`、`type`）
2. 分组：pitfall roots（type==pitfall，无 parent_id）为树头；其他按树关系归入
3. 通过 `child_entry_ids` 递归收集子节点（只取 pending 空间中存在的）
4. process sub-entries 已显示在树中时，不在平铺列表中重复出现

**Format**:
```
_pending/ (N entries)

[category]
  ├── <pitfall-root-id>         [pitfall root]  YYYY-MM-DD import
  │     <child-id-1>            [process]
  │     <child-id-2>            [process]

  <guideline-id>                [guideline]     YYYY-MM-DD import
```

---

## 决策 6：_scan_all_entries 的 parent_id 修复范围

**Decision**: 仅修复新格式（`_pending/<type>/<category>/` 路径）的 EntryMeta，不修改 legacy 格式

**Rationale**: legacy pending 格式（`contributions/pending/`）不使用树结构，无需 `parent_id`。新格式已有 M5 生成的 `parent_id` 字段，读取即可。
