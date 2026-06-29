# M7 — `holmes kb delete`（垃圾箱）

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。知识库以 Markdown 文件存储，存放在 `~/holmes-kb/` 目录下，由 git 追踪。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ CLI 兼容性 > holmes kb delete <id>` 行为描述：
  - 所有 entry（pending 或 confirmed）→ 移入 `_trash/<type>/<category>/`，不硬删除
  - pitfall 根节点 → 默认级联整棵树（根节点 + 全部 process sub-entries）一起移入 `_trash/`；加 `--no-cascade` 可只删根节点本身
  - 非根 entry（单个 process sub-entry）→ 只移自身，不影响其他节点
  - `_trash/` 随 git 追踪，可随时恢复；定期清理由管理员手动执行

- `§ CLI 兼容性` 注释：**无需新增 `holmes kb deprecate` 命令**（旧版本 entries 在 approve 流程中自动 deprecate）

- `§ 目录结构与文件共置`（全节）：
  ```
  kb/
    <category>/             ← confirmed entries
    _pending/
      <category>/           ← pending entries
    _trash/
      <category>/           ← 已删除，可恢复，随 git 追踪
    _drafts/                ← MCP 草稿
    _import-state/          ← DAG 提取状态
  ```
  规则：已删除的 entries 移入 `_trash/<type>/<category>/`（不硬删除），保留 git 可追溯性

- `§ Frontmatter 新增字段`：`parent_id`（判断是否为根节点）、`child_entry_ids`（级联收集子节点）、`kb_status`（pending 和 confirmed 均可删除）、`type`（判断是否为 pitfall 类型）

- `§ 核心数据模型`：process 节点可出现在树的任意位置，process entry 可以链接到其他 process entries 形成任意深度的嵌套；`collect_tree` 递归遍历时需要处理这种任意深度

- `§ 多人协作流程的普适性`：`holmes kb delete → 删除错误或过时的条目`（适用于所有知识类型）

- `§ 知乎知识库建模兼容性 > pitfall_structure 字段`：旧 pitfall entries（`pitfall_structure: flat` 或缺省）不级联（无 `child_entry_ids` 字段）；新 pitfall entries（`pitfall_structure: tree`）才有子节点需要级联

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §1 文件系统布局 — 现有目录结构（pitfall / model / guideline / process / decision）；理解 `contributions/pending/` 位置（旧格式）与新 `_pending/<type>/<category>/` 的区别
- §2 Entry Frontmatter 字段 — `type` 字段（判断是否为 pitfall）、`parent_id`（M1 新增，判断是否为根节点）、`child_entry_ids`（M1 新增，级联收集）

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构、Python 包结构、Click 子命令注册模式、文件移动操作约定。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/store.py           # find_entry()（M1 已改造，文件系统扫描）
                                # list_entries()（M1 已改造）
                                # EntryMeta dataclass（M1 新增 parent_id / child_entry_ids / kb_status）
                                # collect_tree()（M6b 已实现，M7 可复用此函数收集级联节点）
kb/holmes/cli.py                # 现有子命令结构，了解如何注册新子命令
kb/holmes/kb/atomic.py          # atomic_write()
```

相关测试文件：
```
kb/tests/test_store.py          # 了解 find_entry / list_entries 测试模式
```

## 前置依赖

**无**。本模块独立，可与 M1/M8/M9 并行开发。

注意：
- M7 实现时若 M1 已完成，可利用 `parent_id` / `child_entry_ids` / `kb_status` 字段判断根节点和收集子树
- 若 M6b 已完成，可复用 `collect_tree()` 函数；否则在 M7 内部自行实现树遍历逻辑
- 若 M1/M6b 未完成，通过直接读取 frontmatter `parent_id` 字段是否存在来判断是否为根节点

## 本模块目标

为所有 KB entry 提供**软删除**能力：将文件移入 `_trash/<type>/<category>/` 而非硬删除，保留 git 可恢复性。对 pitfall 根节点支持级联删除整棵树。

## 主要改动清单

### store.py
新增函数：

```python
def move_to_trash(
    kb_root: Path,
    entry_id: str,
    cascade: bool = True
) -> list[str]:
    """软删除 entry：将文件移入 _trash/<type>/<category>/，保留 git 追踪。

    Args:
        kb_root: KB 根目录
        entry_id: 要删除的 entry ID
        cascade: 若为 pitfall 根节点，是否级联删除整棵树。默认 True。

    Returns:
        所有被移动的文件路径列表

    实现逻辑：
    1. find_entry(entry_id) 找到文件路径
    2. 读取 frontmatter，获取 type / parent_id / child_entry_ids
    3. 判断是否为 pitfall 根节点（type == "pitfall" 且无 parent_id）
       且 cascade == True：收集整棵树所有 entry ID（collect_tree 或本地递归）
       否则：只处理自身
    4. 对每个 entry：
       - 确定目标 category（从 frontmatter 读取）
       - _trash/<type>/<category>/ 不存在则创建
       - shutil.move(src, dst) 移动文件
    5. 返回所有被移动的文件路径列表
    """
```

### cli.py
新增 `holmes kb delete <id>` 子命令：

```
1. 调用 move_to_trash(kb_root, id, cascade=True)（预演模式：不实际移动，只收集文件列表）
2. 展示"以下文件将被移入 _trash/："+ 文件列表
3. 询问"确认删除？[Y/n]"
4. 确认后执行实际移动
5. 打印"已删除 N 个文件，可通过 git checkout 恢复"
```

参数：
- `--no-cascade`：只删根节点自身，不级联（覆盖默认的 cascade=True）
- `--force`：跳过确认直接执行

## 关键实现细节

### _trash/ 目录结构
```
_trash/
  pitfall/
    hardware/
      old-gpu-issue.md           # 已删除的 pitfall 根节点
  process/
    hardware/
      old-gpu-firmware-001.md    # 已删除的 process sub-entry
```

与 `_pending/<type>/<category>/` 结构完全镜像：`_trash/<type>/<category>/`。移动时保留原文件名，不添加时间戳后缀（通过 git log 可追溯删除时间）。

### 同时处理 pending 和 confirmed
entry 可能在 `_pending/<type>/<category>/` 或 `<type>/<category>/` 中：
- `find_entry()` 已支持扫描两个位置
- 移动到 `_trash/` 时，保留原空间的 type 层：从 `pitfall/<category>/` 来的移入 `_trash/pitfall/<category>/`；从 `_pending/pitfall/<category>/` 来的同样移入 `_trash/pitfall/<category>/`

### 旧 pitfall entries（pitfall_structure: flat）
旧 entries 没有 `child_entry_ids` 字段，不做级联。判断逻辑：
```python
if frontmatter.get("pitfall_structure") == "tree" and frontmatter.get("child_entry_ids"):
    # 新式树形 pitfall，级联
else:
    # 旧式 flat pitfall 或其他类型，只删自身
```

### 错误处理
- 若某个子 entry 文件不存在（数据不一致）：跳过该 entry，继续处理其他，但在输出中标注警告
- `_trash/` 中已存在同名文件：追加 `-<timestamp>` 后缀避免冲突

## 验收条件

- [ ] `holmes kb delete <process-sub-entry-id>` 只移自身到 `_trash/<type>/<category>/`，不影响其他节点
- [ ] `holmes kb delete <pitfall-root-id>` 默认将根节点 + 全部关联 process entries 一起移入 `_trash/`
- [ ] `holmes kb delete <pitfall-root-id> --no-cascade` 只移根节点自身
- [ ] 移入 `_trash/` 的文件保留原始内容，`git status` 可见（不被 `.gitignore` 忽略）
- [ ] pending 和 confirmed entry 均可删除（从各自目录移入 `_trash/`）
- [ ] 删除前展示"将移动 N 个文件到 _trash/"，用户确认后执行
- [ ] `--force` 跳过确认直接执行
- [ ] `_trash/<type>/<category>/` 目录不存在时自动创建
- [ ] 删除旧式 flat pitfall（无 `child_entry_ids`）时不报错，只删自身
- [ ] 删除完成后通过 HolmesLogger 写入 `kb.delete` span（含 `entry_id`、`user`、`cascade`、`duration_ms`）；依赖 M8 `HolmesLogger` 接口
- [ ] 有单元测试：删单个 non-root entry、删 pitfall 根节点（级联）、`--no-cascade`、pending entry 删除

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M7-delete/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：读完蓝图 `§ CLI 兼容性 > holmes kb delete 行为`（四条规则）、`§ 目录结构与文件共置`（`_trash/<type>/<category>/` 目录规则），再读完 `store.py` 中 `find_entry()` 实现（理解如何同时搜索 `_pending/` 和 confirmed 空间），再读完 M6b 的 `collect_tree()` 实现（用于收集级联子节点）。
