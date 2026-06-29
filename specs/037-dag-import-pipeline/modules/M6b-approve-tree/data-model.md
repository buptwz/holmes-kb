# Data Model: M6b — Pending/Approve 树级联

## 现有数据模型（不变）

### EntryMeta（`store.py`）
```python
@dataclass
class EntryMeta:
    id: str
    type: str           # "pitfall" | "process" | "guideline" | ...
    title: str
    maturity: str
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    file_path: str
    pending: bool = False
    kb_status: str = "active"
    parent_id: Optional[str] = None   # M1 字段 — 树遍历关键
    source_hash: str = ""
    source_file: str = ""
```

**M6b 变更**：`_scan_all_entries` 中新格式 pending entries 需正确填充 `parent_id`（当前为空）。

## 新增 API（store.py）

### collect_tree
```python
def collect_tree(kb_root: Path, root_id: str) -> list[str]:
    """从 root_id 出发 DFS 遍历 child_entry_ids，收集整棵树 ID 列表。
    root 在列表最前。防止循环引用。搜索顺序：_pending/ → confirmed。
    """
```

### approve_tree
```python
def approve_tree(kb_root: Path, root_id: str) -> list[str]:
    """原子 approve 整棵 pending 树（叶优先，root 最后）。
    失败时回滚已 approved entries。返回 confirmed 文件路径列表。
    Raises: FileNotFoundError（任一 entry 不在 pending）
            RuntimeError（approve 失败，已回滚）
    """
```

### deprecate_tree
```python
def deprecate_tree(kb_root: Path, root_id: str) -> list[str]:
    """Deprecate confirmed 空间整棵树。返回被 deprecated 的 entry ID 列表。"""
```

### cancel_pending_tree
```python
def cancel_pending_tree(kb_root: Path, root_id: str) -> list[str]:
    """删除 _pending/ 中整棵树的文件（不走 _trash/）。
    返回已删除的文件路径列表。
    """
```

## CLI 流程状态机

### kb approve — pitfall root 路径

```
入口：_find_pending_entry(kb_root, entry_id)
│
├─ None → Error（entry not found）
│
├─ 读 frontmatter
│    ├─ type != "pitfall" OR parent_id 存在 → M6a 单 entry 流程
│    │
│    └─ type == "pitfall" AND 无 parent_id → 树级联流程
│         │
│         ├─ Step 1: collect_tree(entry_id) → current_tree_ids
│         │
│         ├─ Step 2: find_entries_by_source_file(source_file)
│         │   → old_pending_roots = [e for e in all_same
│         │       if e.kb_status == "pending"
│         │       and e.type == "pitfall"
│         │       and e.id not in current_tree_ids]
│         │   → 若有：collect_tree(old_root) → old_pending_tree_ids
│         │   → 展示 + prompt [Y/n]
│         │
│         ├─ Step 3: 同上
│         │   → old_confirmed_roots = [e for e in all_same
│         │       if e.kb_status == "active" and e.type == "pitfall"]
│         │   → 若有：collect_tree(old_conf_root) → old_confirmed_tree_ids
│         │   → 展示 + prompt [Y/n]
│         │
│         ├─ Step 4: 展示摘要 + 最终 [Y/n]
│         │   "执行：取消 N 个旧 pending + deprecate M 个旧 confirmed + approve K 个新 entries"
│         │
│         └─ Step 5: 原子执行
│              cancel_pending_tree(old_root)  ← 若用户选 Y
│              deprecate_tree(old_conf_root)  ← 若用户选 Y
│              approve_tree(entry_id)          ← 始终执行
│              rebuild_index_files(kb_root)
```

### kb pending — 树形显示流程

```
扫描 _pending/ 所有 .md 文件
→ 构建 entries_map: {id → {id, type, title, category, created_at, parent_id, child_entry_ids}}
→ 找 pitfall roots: type=="pitfall" AND parent_id 为空
→ 按 category 分组（pitfall roots + 其他 pending entries）
→ 对于每个 category：
     pitfall roots：├── <id>  [pitfall root]  <date>
                    │     <child-id>  [process]  （collect_tree 结果，排除已显示）
     其他类型（不是任何 pitfall root 的子节点）：平铺展示
```

## 文件系统布局（不变）

```
<kb_root>/
  _pending/
    pitfall/
      hardware/
        hw-init-failure-003.md     ← pitfall root（新 pending 树）
    process/
      hardware/
        hw-init-firmware-003.md    ← child（parent_id=hw-init-failure-003）
        hw-init-memory-003.md      ← child
  pitfall/
    hardware/
      hw-init-failure-001.md       ← old confirmed（kb_status=active）
  process/
    hardware/
      hw-init-firmware-001.md      ← child of hw-init-failure-001
```
