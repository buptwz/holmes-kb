# M6a — Pending/Approve 基础流程

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ Step 4：写入 Pending 与 Approve 流程`（全节）
  - **写入 Pending**：所有生成的 entries 写入 `_pending/<type>/<category>/`，等待 approve
  - **Approve 流程**（4 步）：
    - Step 1：检测同 `source_file` 的旧 pending entries，询问取消旧版
    - Step 2：检测同 `source_file` 的 active confirmed entries，询问 deprecate
    - Step 3：**原子执行**（取消旧 pending + deprecate 旧 confirmed + approve 当前 pending）
    - Step 4：更新 KB 目录索引（category index）
  - **Approve 时的提示示例**：完整的交互文本格式（含旧 pending 列表、旧 confirmed 列表、最终确认）

- `§ Step 0 > Pending 空间清理`（import 时触发的清理逻辑，approve 基础流程需要理解）

- `§ Step 0 > Confirmed 空间替换（approve 时触发）`：approve 新 entries 时，检测同 source_file 的 active entries，询问 deprecate

- `§ Step 0 > 三层并存场景`：confirmed + 旧 pending + 新 pending 三层同时存在，一次 approve 清理两层旧数据

- `§ Step 0 > Entry 状态字段`：`kb_status` 三态（pending/active/deprecated）及状态转换

- `§ 目录结构与文件共置`（全节）：`_pending/<type>/<category>/`、`_trash/<type>/<category>/`、`<type>/<category>/` 三层镜像结构；pitfall root 在 `pitfall/<category>/`，process sub-entries 在 `process/<category>/`；approve 是从 `_pending/<type>/<category>/` 移入 `<type>/<category>/`

- `§ KB Entry 可读性规范 > 2. 必填元信息字段`：`contributors` / `source_file` / `import_trace_id` 字段规范，approve 后 entry 内容不变，只修改 `kb_status`

- `§ Process Sub-entry 可见性规则`：`holmes kb pending` 按树形分组展示（M6b 负责树形，M6a 先做平铺）；`holmes kb list` 默认不显示 process sub-entries

- `§ CLI 兼容性`：`holmes kb approve <id>`（兼容，新增冲突提示）；`holmes kb pending`（兼容，按 category 分组）

- `§ 多人协作流程的普适性`：pending → approve → git PR 的协作模型适用于所有知识类型

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §1 文件系统布局 — 现有目录结构（pitfall / model / guideline / process / decision / contributions/）；理解 `contributions/pending/`（现有旧格式）与新格式 `_pending/<type>/<category>/` 的区别
- §2 Entry Frontmatter 字段 — `kb_status` 字段（M1 新增）、`source_file`（M1 新增）与现有字段的关系
- §3 Maturity 生命周期 — approve 后 maturity 不自动变化（仍为 draft）；证据积累才驱动升级

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构、Python 包结构、CLI Click 子命令注册模式、atomic_write 使用约定。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/store.py           # list_entries()（M1 已改造，含 kb_status 过滤）
                                # find_entry()（M1 已改造，文件系统扫描）
                                # write_entry() / read_entry()
                                # EntryMeta dataclass（M1 新增 kb_status / source_file / source_hash 字段）
kb/holmes/kb/atomic.py          # atomic_write() — 原子文件写入（approve 时移动文件用）
kb/holmes/kb/linter.py          # 了解 category index 更新逻辑（approve 后需要更新索引）
kb/holmes/kb/pending.py         # 现有 pending 实现（contributions/pending/）
                                # 了解现有写入和读取模式，M6a 建立新格式 _pending/<type>/<category>/
kb/holmes/cli.py                # 现有子命令结构；holmes kb approve / kb pending（若已有则改造）
```

相关测试文件（理解现有测试覆盖范围）：
```
kb/tests/test_store.py          # list_entries / find_entry 测试
kb/tests/test_schema.py         # schema 验证测试
```

## 前置依赖

- **M1**（必须先完成）：`kb_status` 字段、`source_file`/`source_hash` 字段定义；`list_entries()` 新增 `kb_status` 过滤；`find_entry()` 改为文件系统扫描
- **M2**（必须先完成）：`find_entries_by_source_file()` 函数（approve 前冲突检测用）

## 本模块目标

实现所有类型 entry 的 pending → active 生命周期（**单 entry 粒度**）：

1. **写入 pending**：新增 `write_pending()` 函数，将 entry 写入 `_pending/<type>/<category>/`
2. **approve**：将 pending entry 从 `_pending/<type>/<category>/` 移入 `<type>/<category>/`，`kb_status` 改为 `active`
3. **冲突处理**：approve 前检测同 `source_file` 的旧 pending 和 confirmed entries，提示用户处理
4. **deprecate**：将 confirmed entry 的 `kb_status` 改为 `deprecated`（in-place 修改，不移动文件）
5. **category index 更新**：approve 后更新 `<category>/index.md`（若存在）

注意：本模块处理**单个 entry** 的 approve。M6b 负责 pitfall 树的级联 approve（依赖本模块完成后）。

## 主要改动清单

### store.py
新增函数：

```python
def write_pending(kb_root: Path, entry_id: str, content: str, entry_type: str, category: str) -> Path:
    """将 entry 内容原子写入 _pending/<entry_type>/<category>/<entry_id>.md，返回文件路径。"""
    pending_dir = kb_root / "_pending" / entry_type / category
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{entry_id}.md"
    atomic_write(path, content)
    return path

def approve_entry(kb_root: Path, entry_id: str) -> Path:
    """将 _pending/<type>/<category>/<entry_id>.md 移入 <type>/<category>/，更新 kb_status: active，返回新路径。"""
    # 1. 找到 pending 文件（在 _pending/<type>/<category>/ 下扫描）
    # 2. 读取 frontmatter，修改 kb_status = "active"
    # 3. 确定目标目录（<type>/<category>/，从 frontmatter 读取 type 和 category）
    # 4. atomic_write 到目标路径
    # 5. 删除原 pending 文件
    # 返回新文件路径

def deprecate_entry(kb_root: Path, entry_id: str) -> None:
    """将 confirmed entry 的 kb_status 改为 deprecated（in-place 修改 frontmatter）。"""
    # 找到 entry 文件（在 confirmed 空间 <category>/ 下扫描）
    # 读取 frontmatter，修改 kb_status = "deprecated"
    # in-place 写回（atomic_write 到同一路径）
```

### cli.py
**`holmes kb approve <id>`** 子命令（新增或改造）：

```
Step 1：检测同 source_file 的旧 pending entries（find_entries_by_source_file，pending 空间）
  → 若有：展示列表，询问"取消旧 pending？[Y/n]"

Step 2：检测同 source_file 的 active confirmed entries（find_entries_by_source_file，confirmed 空间）
  → 若有：展示列表，询问"标记为 deprecated？[Y/n]"

Step 3：原子执行（展示操作摘要，最终 [Y/n] 确认）
  → 取消旧 pending（从 _pending/<type>/<category>/ 直接删除文件）
  → deprecate 旧 confirmed（调用 deprecate_entry）
  → approve 当前 pending（调用 approve_entry）

Step 4：更新 category index（若 <category>/index.md 或 _index.md 存在）
```

提示示例（来自蓝图）：
```
准备 approve: hardware-init-failure-002

[pending 空间] 发现同文档的旧 pending entries：
  - hardware-init-failure-001（2月 import，未审核）
  取消旧 pending？[Y/n] → Y

[confirmed 空间] 发现同文档的 active entries：
  - hardware-init-failure-000（1月 import，已 approve）
  标记为 deprecated？[Y/n] → Y

执行：取消 1 个旧 pending + deprecate 1 个旧 confirmed + approve 1 个新 entry
确认？[Y/n] → Y
```

**`holmes kb pending`** 子命令（新增或改造）：
- 扫描 `_pending/` 下所有 entry（`_pending/<type>/<category>/<id>.md`）
- 按 type → category 分组展示（平铺版，M6b 在此基础上改为树形展示）
- 展示格式：category 为组标题，每 entry 一行（entry_id、type、title、import 时间）

## 关键实现细节

### _pending/ 目录结构（新格式）
```
_pending/
  pitfall/
    hardware/
      hardware-init-failure-002.md     ← pitfall 根节点
    network/
      dns-failure-001.md               ← pitfall 根节点
  process/
    hardware/
      hardware-init-firmware-002.md    ← process 子节点
```

结构与确认空间（`<type>/<category>/`）完全镜像。approve 操作就是从 `_pending/<type>/<category>/` 移到 `<type>/<category>/`，路径对称，逻辑清晰。

与现有 `contributions/pending/`（旧格式，平铺）不同，新格式按 type/category 两级分组。两种格式并存，`holmes kb pending` 先扫新格式 `_pending/`，再兼容扫旧格式 `contributions/pending/`。

### kb_status 状态转换
```
pending（写入 _pending/<type>/<category>/）→ active（approve 后移入 <type>/<category>/）
active → deprecated（新版本 approve 时，旧版本被标记）
```
`deprecate_entry` 只修改 `kb_status` 字段，不移动文件，方便 git 追踪历史。

### approve 原子性
approve 操作涉及多个文件操作，需要尽量保证原子性：先写新文件，再删旧文件，任一步骤失败时日志记录，不留半成品状态。

## 验收条件

- [ ] `write_pending` 将 entry 写入 `_pending/<type>/<category>/<id>.md`（目录不存在则自动创建）；函数签名含 `entry_type` 参数
- [ ] `holmes kb approve <id>` 将文件从 `_pending/<type>/<category>/` 移入 `<type>/<category>/`，frontmatter `kb_status` 改为 `active`
- [ ] approve 前列出同 `source_file` 的旧 pending，询问是否取消
- [ ] approve 前列出同 `source_file` 的 active confirmed，询问是否 deprecate
- [ ] deprecate 操作只修改 `kb_status` 字段，不移动或删除文件
- [ ] approve 后 `holmes kb list` 立即可见新 entry（`kb_status: active`）
- [ ] approve 后 deprecated entries 不出现在 `holmes kb list` 默认视图
- [ ] `holmes kb pending` 列出 `_pending/` 下所有 entry，按 category 分组
- [ ] 三层并存场景（旧 pending + 旧 confirmed + 新 pending）一次 approve 正确清理两层
- [ ] approve 后触发 category index 更新（若 `_index.md` 存在）
- [ ] approve 完成后通过 HolmesLogger 写入 `kb.approve` span（含 `entry_id`、`user`、`duration_ms`）；依赖 M8 `HolmesLogger` 接口
- [ ] 有单元测试：approve 基本流程、旧 pending 清理、旧 confirmed deprecate、三层并存场景

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M6a-approve-base/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ Step 4` 全节（含 Approve 流程四步、提示示例）、`§ Step 0 > Confirmed 空间替换`、`§ Step 0 > 三层并存场景`、`§ 目录结构与文件共置`，再读完 `pending.py` 理解现有 pending 模式，读完 `store.py` 中 `list_entries` 和 `find_entry` 的 M1 改造版本。
