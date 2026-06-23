# M6b — Pending/Approve 树级联

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ Step 4：写入 Pending 与 Approve 流程 > Approve 流程`（级联部分）
  - Step 3 **原子执行**：整棵树（pitfall root + 所有关联 process entries）作为整体一次性处理
  - 不允许部分 approve（中途失败需回滚）

- `§ Step 4 > Approve 时的提示示例`：级联树的完整交互文本格式
  ```
  准备 approve: hardware-init-failure-002（及其 5 个关联 entries）

  [pending 空间] 发现同文档的旧 pending entries：
    - hardware-init-failure-001（2月 import，未审核）及其 4 个关联 entries
    取消旧 pending？[Y/n] → Y

  [confirmed 空间] 发现同文档的 active entries：
    - hardware-init-failure-000（1月 import，已 approve）及其 3 个关联 entries
    标记为 deprecated？[Y/n] → Y

  执行：取消 5 个旧 pending + deprecate 4 个旧 confirmed + approve 6 个新 entries
  确认？[Y/n] → Y
  ```

- `§ Step 0 > 三层并存场景`：confirmed + 旧 pending + 新 pending 三层同时存在，approve 时一次清理两层旧数据；旧 pending 树和旧 confirmed 树的 entry 数量可能不同

- `§ Process Sub-entry 可见性规则`：
  | 命令 | 默认行为 |
  |---|---|
  | `holmes kb list` | 不显示 process sub-entries |
  | `holmes kb search` | 不显示 process sub-entries |
  | `holmes kb show <process-id>` | 正常显示，展示 `[sub-entry of: <parent_id>]` 标签 |
  | `holmes kb list --all-types` | 显示（管理员 review） |
  | `holmes kb pending` | 按树形分组展示（pitfall root 为组标题，sub-entries 缩进） |

- `§ 核心数据模型`：process 节点可出现在树的任意位置，不限于叶子节点；process entry 可以链接到其他 process entries，形成任意深度的嵌套结构

- `§ Frontmatter 新增字段`：`child_entry_ids`（树结构子节点 ID 列表）和 `parent_id`（父 entry ID）字段在树遍历中的使用

- `§ KB Entry 可读性规范 > 3. 关联结构注释`：`child_entry_ids` 每项带标题注释，`parent_id` 带父标题注释，树遍历时可利用注释展示

- `§ 目录结构与文件共置`：同一 pitfall 树的所有 entries（根节点 + process sub-entries）放在同一 `<category>/` 目录；`_pending/<category>/` 下也按 category 分级

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §1 文件系统布局 — 理解 `<category>/` 目录结构（pitfall / process / guideline 等各类型目录）
- §2 Entry Frontmatter 字段 — `child_entry_ids`（树结构）、`parent_id`（父节点）、`kb_status` 字段
- §6 EntryMeta dataclass — `child_entry_ids`（M1 新增）、`parent_id`（M1 新增）字段

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构、Python 包结构、atomic 操作约定。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/store.py           # approve_entry() / deprecate_entry()（M6a 已实现）
                                # find_entries_by_source_file()（M2 已实现）
                                # read_entry()（M1 已改造，返回 child_entry_ids 和 children 字段）
                                # list_entries()（M1 已改造，含 kb_status 过滤和 exclude_sub_entries）
kb/holmes/cli.py                # holmes kb approve / holmes kb pending 子命令（M6a 已实现基础版）
                                # M6b 在此基础上扩展
kb/holmes/kb/atomic.py          # atomic_write()
```

相关测试文件：
```
kb/tests/test_store.py          # M6a 已建立的 approve / deprecate 测试，理解测试模式
```

## 前置依赖

- **M5**（必须先完成）：M5 生成的 entries 带有 `parent_id` / `child_entry_ids` 字段，M6b 依赖这些字段做树遍历
- **M6a**（必须先完成）：M6b 在 M6a 的 `approve_entry()` / `deprecate_entry()` 基础上封装树操作

## 本模块目标

在 M6a（单 entry approve）基础上，新增树级联能力：

1. `holmes kb approve <pitfall-root-id>` 级联处理整棵树（根节点 + 所有关联 process entries）
2. `holmes kb pending` 按树形分组展示（pitfall root 为组标题，process sub-entries 缩进）
3. 旧树（pending 或 confirmed）的级联清理

## 主要改动清单

### store.py
新增函数：

```python
def collect_tree(kb_root: Path, root_id: str) -> list[str]:
    """从 pitfall root 出发，递归遍历 child_entry_ids，收集整棵树的所有 entry ID。

    遍历策略：
    1. 从 root_id 开始，读取 entry frontmatter 中的 child_entry_ids
    2. 递归对每个 child 调用 collect_tree（BFS 或 DFS 均可）
    3. 返回所有 entry ID 的有序列表（root 在最前）
    注意：process sub-entries 可能在 _pending/ 或 confirmed 空间，两处都要搜索
    """

def approve_tree(kb_root: Path, root_id: str) -> list[str]:
    """
    1. collect_tree(root_id) 获取整棵树 ID 列表
    2. 对每个 ID 调用 approve_entry()（M6a）
    3. 整棵树原子操作：任一 entry approve 失败则回滚
    4. 返回已 approve 的文件路径列表
    """

def deprecate_tree(kb_root: Path, root_id: str) -> list[str]:
    """
    1. collect_tree(root_id) 收集整棵树（在 confirmed 空间）
    2. 对每个 ID 调用 deprecate_entry()（M6a）
    3. 返回所有被 deprecated 的 entry ID 列表
    """

def cancel_pending_tree(kb_root: Path, root_id: str) -> list[str]:
    """取消 _pending/ 中整棵 pending 树（直接删除文件，不走 _trash/）。
    返回已取消的文件路径列表。"""
```

### cli.py
**改造 `holmes kb approve <id>`**（在 M6a 基础上扩展）：

当检测到 `<id>` 是 pitfall 根节点（`type == "pitfall"` 且无 `parent_id`）时：

```
Step 1：collect_tree(id) 获取整棵树（同时搜索 _pending/ 和 confirmed 空间）

Step 2：检测同 source_file 的旧 pending 树
  → 若有：collect_tree(旧 root)，列出"旧 pending 树（root + N 个关联 entries）"
  → 询问"取消旧 pending 树？[Y/n]"

Step 3：检测同 source_file 的旧 confirmed 树
  → 若有：collect_tree(旧 root)，列出"旧 confirmed 树（root + N 个关联 entries）"
  → 询问"标记整棵树为 deprecated？[Y/n]"

Step 4：原子执行（展示操作摘要，最终 [Y/n] 确认）
  → cancel_pending_tree（取消旧 pending 树）
  → deprecate_tree（标记旧 confirmed 树为 deprecated）
  → approve_tree（approve 当前 pending 树）

Step 5：更新 category index
```

当 `<id>` 是非根节点（process sub-entry，有 `parent_id`）时：沿用 M6a 的单 entry approve 行为。

**改造 `holmes kb pending`**（在 M6a 基础上扩展）：

按树形分组展示（pitfall 树）+ 平铺展示（非 pitfall 类型）：

```
_pending/ (6 entries)

[hardware]
  ├── hardware-init-failure-002         [pitfall root]  2026-06-23 import
  │     hardware-init-firmware-002      [process]
  │     hardware-init-memory-diag-002   [process]
  │     hardware-init-e01-002           [process]

  ├── gpu-overheat-001                  [pitfall root]  2026-06-22 import
        gpu-overheat-fan-check-001      [process]

[network]
  dns-failure-guideline-001             [guideline]     2026-06-21 import
```

## 关键实现细节

### 树遍历算法
`collect_tree` 需要从 root 出发递归遍历 `child_entry_ids`：
1. 从 `_pending/<category>/` 和 `<category>/` 两个位置搜索每个 ID
2. 读取 frontmatter，获取 `child_entry_ids`
3. 递归收集子节点 ID
4. 防止循环引用（已收集的 ID 跳过）

### 原子性保证
整棵树的 approve 需要原子性：
1. 预检查所有 entry 文件都存在（approve 前）
2. 按拓扑逆序（叶节点先，root 最后）approve 每个 entry
3. 任一步骤失败：记录错误，回滚已 approve 的 entry（移回 `_pending/`）

### 树形展示算法
`holmes kb pending` 树形展示：
1. 扫描 `_pending/` 所有 entry，按 `parent_id` 分组
2. 找出无 `parent_id` 的 pitfall root（树的起点）
3. DFS 递归打印，process sub-entries 缩进
4. 无 pitfall root 的 pending entries（其他类型）单独平铺展示

## 验收条件

- [ ] `holmes kb approve <pitfall-root-id>` 级联 approve 根节点 + 所有关联 process sub-entries
- [ ] 不允许部分 approve（整棵树原子操作，中途失败则回滚）
- [ ] approve 前列出同 source_file 的旧 pending 树（root + 关联 entries），询问是否取消整棵旧树
- [ ] approve 前列出同 source_file 的旧 confirmed 树（root + 关联 entries），询问是否 deprecate 整棵旧树
- [ ] 三层并存（旧 pending 树 + 旧 confirmed 树 + 新 pending 树）：一次 approve 正确清理两层
- [ ] approve 单个 process sub-entry（有 `parent_id` 的非根节点）：沿用 M6a 行为，只 approve 该 entry
- [ ] `holmes kb pending` 以 pitfall root 为组标题，process sub-entries 缩进展示
- [ ] `holmes kb pending` 平铺展示非 pitfall 类型的 pending entries（guideline 等）
- [ ] `collect_tree` 递归遍历有循环引用的异常 DAG 时不陷入死循环（已访问 ID 跳过）
- [ ] 有单元测试：树级联 approve、旧树清理、三层并存场景、树形展示格式

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M6b-approve-tree/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ Step 4 > Approve 流程`（级联部分）和 `§ Step 4 > Approve 时的提示示例`、`§ Step 0 > 三层并存场景`、`§ Process Sub-entry 可见性规则`，再读完 M6a 实现的 `approve_entry()` / `deprecate_entry()` 函数签名和逻辑，再读完 M1 改造的 `read_entry()` 中 `child_entry_ids` / `children` 字段返回方式。
