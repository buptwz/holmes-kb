# M2 — Step 0：去重与更新检测

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ Step 0：去重与更新检测`（全节）
  - **检测逻辑**：三步串行判断（hash 匹配 → 完全重复；source_file 匹配 + hash 不同 → 文档更新；均未匹配 → 全新）
  - **更新流程**：每次 import 全量重新生成，新旧物理隔离
  - **Pending 空间清理**（import 时触发）：检测同 source_file 的旧 pending entries，询问 [Y/n] 取消旧版或并存
  - **Confirmed 空间替换**（approve 时触发）：approve 新 entries 时检测同 source_file 的 active confirmed，询问 deprecate
  - **三层并存场景**：confirmed + 旧 pending + 新 pending 三层同时存在，approve 时一次清理两层旧数据
  - **Entry 状态字段**：`kb_status` 三态（pending/active/deprecated）及其与 `decay_status` 的正交性

- `§ 状态存储（git 追踪）`：`_import-state/<hash>.dag.md / .dag.json / .session.json` 三文件职责

- `§ CLI 兼容性`
  - `holmes import --force`：跳过去重检测
  - `source_file` 存储为相对于 KB root 的路径（如 `docs/hardware/gpu.md`）
  - `source_hash`：SHA-256 前 16 位 hex 字符串

- `§ Frontmatter 新增字段`：`source_file`（字符串，相对路径）、`source_hash`（字符串）字段定义

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

了解 §1 文件系统布局（`contributions/pending/` 与 confirmed 目录结构）、§2 Entry Frontmatter 字段（了解现有字段，确保不冲突）、§6 EntryMeta dataclass。

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构（Python 包结构、CLI 入口、测试约定）。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/importer.py        # 现有 import pipeline 入口
                                # 重点：run() 方法结构、compute_source_hash() 实现（SHA-256 前 16 位）
kb/holmes/kb/store.py           # list_entries()、find_entry()；M1 完成后新增 kb_status 过滤
                                # 理解现有 pending 目录扫描逻辑（include_pending=True）
kb/holmes/cli.py                # holmes import 子命令参数定义（--force / --dry-run 等）
kb/holmes/config.py             # HolmesConfig dataclass
```

相关测试文件（理解现有测试覆盖范围）：
```
kb/tests/test_importer.py       # 现有 import 测试（若存在）
kb/tests/test_store.py          # list_entries / find_entry 测试，了解测试模式
```

## 前置依赖

- **M1**（必须先完成）：M1 在 entry frontmatter 新增了 `source_file` 和 `source_hash` 字段，M2 依赖这两个字段做检测；M1 改造的 `store.py` 的 `list_entries` 已支持扫描所有状态的 entry

## 本模块目标

在 `holmes import <file>` 入口处新增 Step 0：计算源文档 hash，与已有 pending 和 confirmed entries 对比，识别三种情况：

1. **完全重复**（hash 匹配，任意空间）→ 跳过，打印提示
2. **文档更新**（相同 source_file 路径但 hash 不同）→ 提示用户，检测旧 pending 是否需要清理，继续走 import 流程
3. **全新文档** → 正常走 import 流程

同时支持 `--force` 跳过去重，和导入前 "pending 空间清理" 询问。

## 主要改动清单

### store.py
新增两个查询函数（搜索范围：pending 空间 `_pending/<type>/<category>/` + confirmed 空间 `<category>/`）：

```python
def find_entries_by_source_hash(kb_root: Path, source_hash: str) -> list[EntryMeta]:
    """搜索 pending + confirmed 空间中 source_hash 匹配的 entries。"""

def find_entries_by_source_file(kb_root: Path, source_file: str) -> list[EntryMeta]:
    """搜索 pending + confirmed 空间中 source_file 路径匹配的 entries。"""
```

实现方式：遍历 `kb_root` 下所有 `.md` 文件（含 `_pending/<type>/<category>/` 子目录），读取 frontmatter，比对字段值。`source_file` 比对时使用规范化后的相对路径。

### importer.py（或 pipeline.py）
在 `run(source_text, file_path)` 开头插入 Step 0：

```python
source_hash = compute_source_hash(source_text)     # SHA-256 前 16 位（已有函数）
source_file = str(file_path.relative_to(kb_root))  # 相对于 KB root 的路径

if not force:
    # 1. hash 匹配 → 完全重复，跳过
    hash_matches = find_entries_by_source_hash(kb_root, source_hash)
    if hash_matches:
        print("已存在完全相同的文档，跳过导入")
        return

    # 2. source_file 匹配且 hash 不同 → 文档更新
    file_matches = find_entries_by_source_file(kb_root, source_file)
    if file_matches:
        print(f"文档有更新（上次导入：{...}）")
        # 检查 pending 空间中是否有旧版本 entries
        old_pending = [m for m in file_matches if m.kb_status == "pending"]
        if old_pending:
            # 展示旧 pending 列表，询问 [Y/n] 取消旧版
            ...
```

### cli.py
- `holmes import` 新增 `--force` flag：跳过 Step 0 去重检测，强制重新生成

## 关键实现细节（来自蓝图）

### source_hash 格式
```python
import hashlib
source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]
```
`compute_source_hash()` 在 `importer.py` 中已有，直接复用。

### source_file 格式
相对于 KB root 的路径：`str(file_path.relative_to(kb_root))`，例如 `docs/hardware/gpu.md`。

### 两个搜索空间
```
confirmed 空间：<category>/*.md（pitfall / model / guideline / process / decision）
pending 空间：_pending/<type>/<category>/*.md
```
两个空间都要搜索，任意空间有 hash 匹配即为"完全重复"。

### Pending 空间清理提示（import 时）
```
检测到同文档的旧 pending entries（2024-03-01 导入，未审核）：
  - hardware-init-failure-001 (pending)
  - hardware-init-memory-diag-001 (pending)
是否取消旧 pending，用本次新 import 替换？[Y/n]
```
Y → 从 `_pending/` 移除旧 entries（未审核草稿，直接删除，不走 `_trash/`）。
n → 新旧 pending 并存，reviewer 在 approve 时自行选择。

## 验收条件

- [ ] 导入完全相同内容的文档（source_hash 一致）：打印"已存在，跳过"，不启动 pipeline
- [ ] 导入内容有变化的同名文档（source_file 匹配但 hash 不同）：打印"文档有更新"提示，继续导入
- [ ] 文档更新时，若 pending 空间有旧版本：展示列表，询问用户选择
- [ ] `--force` 完全跳过去重，直接进 pipeline
- [ ] 同时搜索 `_pending/<type>/<category>/` 和 confirmed `<category>/` 两个空间
- [ ] source_hash 使用 SHA-256 前 16 位 hex 字符串（`compute_source_hash()` 函数）
- [ ] source_file 存储为相对于 KB root 的路径（如 `docs/hardware/gpu.md`）
- [ ] 旧 entry（无 source_hash 字段）不被误判为 hash 匹配（空字段不等于新文档 hash）
- [ ] 有单元测试：三种情况（重复/更新/全新）+ `--force` 行为 + pending 空间清理

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M2-dedup/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ Step 0` 全节（含三层并存场景和 Confirmed 空间替换逻辑），理解 `source_file` 路径规范化要求，再读完 `importer.py` 中的 `compute_source_hash()` 实现。
