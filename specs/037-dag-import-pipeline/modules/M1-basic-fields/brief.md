# M1 — 基础字段与过滤

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，用 Click 框架实现，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 安装包：`kb/` 目录，`pip install -e .` 安装
- KB 数据：`~/holmes-kb/`（git 追踪的 Markdown + YAML frontmatter 文件）
- 配置文件：`~/.holmes/config.json`

## 必读参考文档（实现前全部通读）

### 1. 知乎 KB 数据模型（权威字段参考）
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §1 文件系统布局 — 现有目录结构（pitfall/model/guideline/process/decision/contributions/）
- §2 Entry Frontmatter 字段 — 所有现有必填/可选字段及来源文件行号
- §3 Maturity 生命周期 — draft → verified → proven 升级路径
- §4 Evidence sidecar — contributions/evidence/ 结构
- §6 EntryMeta dataclass — store.py 的轻量 meta 结构

### 2. 施工蓝图
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

重点章节：
- `§ Entry 状态字段` — kb_status 三态（pending/active/deprecated），向后兼容规则
- `§ Frontmatter 新增字段` — 完整字段表格（kb_status/source_file/source_hash/description/import_trace_id/pitfall_structure/child_entry_ids/parent_id）及与知乎模型字段的关系
- `§ Process Sub-entry 可见性规则` — 各 CLI 命令默认行为表格
- `§ Store 层适配（对 MCP 透明）` — 5 项 store 改动说明（ID 无关化/kb_status 过滤/sub-entry 可见性/children 字段/contributor 来源）
- `§ KB Entry 可读性规范 > 2. 必填元信息字段` — description/source_file/contributors 字段规范及示例
- `§ KB Entry 可读性规范 > 3. 关联结构注释` — child_entry_ids 和 parent_id 标题注释格式
- `§ CLI 兼容性` — holmes kb list --all/--all-types；holmes config set username

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构和开发约定。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/kb/schema.py          # KBType Literal、REQUIRED_FRONTMATTER_FIELDS、validate_entry()
kb/holmes/kb/store.py           # EntryMeta dataclass、list_entries()、read_entry()、find_entry()
kb/holmes/kb/search.py          # search_entries()
kb/holmes/kb/linter.py          # category index 更新逻辑
kb/holmes/cli.py                # holmes kb list/search/show 子命令；holmes config set 子命令
kb/holmes/config.py             # HolmesConfig dataclass，load_config/save_config
kb/holmes/mcp/tools.py          # handle_kb_list/handle_kb_search/handle_kb_read（需同步更新）
```

相关测试文件（理解现有测试覆盖范围）：
```
kb/tests/test_store.py
kb/tests/test_schema.py
kb/tests/test_search.py
kb/tests/test_mcp_tools.py
```

## 本模块目标

为所有 KB entry 新增 5 个 frontmatter 字段，更新 store/search/CLI/MCP 过滤逻辑，实现：

1. 只有 `kb_status: active` 的 entry 出现在默认列表和搜索结果中
2. `type: process` 且有 `parent_id` 的 sub-entries 默认隐藏
3. store 层 ID 查找改为文件系统扫描，兼容新旧两种 ID 格式
4. `read_entry` 返回有 `child_entry_ids` 的 pitfall entry 时附加结构化 `children` 字段
5. `holmes config set username <name>` 写入 `~/.holmes/config.json`

## 前置依赖

无。本模块是所有其他模块的地基，优先完成。

## 主要改动

### schema.py
- 新增 `KBStatus = Literal["pending", "active", "deprecated"]`
- `REQUIRED_FRONTMATTER_FIELDS` 不变（新字段均为可选，向后兼容）
- 新增可选字段文档注释

### store.py
- `EntryMeta` 新增可选字段：`kb_status / source_file / source_hash / description / import_trace_id / pitfall_structure / child_entry_ids / parent_id`
- `list_entries()` 新增参数：`kb_status: str = "active"`（过滤）、`exclude_sub_entries: bool = True`（过滤有 parent_id 的 process entries）；旧 entry 无 kb_status 字段时视为 active
- `find_entry(id)` 改为文件系统扫描（`rglob("*.md")` 匹配文件名 stem），不再依赖正则匹配旧 ID 格式 `PT-DB-001`
- 新增 `read_entry()` 扩展：返回有 `child_entry_ids` 的 entry 时，附加 `children: [{id, title}]` 字段

### search.py
- `search_entries()` 默认只搜索 `kb_status: active` 的非 sub-entry

### cli.py
- `holmes kb list` 新增 `--all` flag（含 deprecated）、`--all-types` flag（含 sub-entries）
- `holmes kb search` 新增 `--all` flag
- `holmes kb show <id>` 展示新字段；process sub-entry 显示 `[sub-entry of: <parent_id>]` 标签
- `holmes config set username <name>` 子命令

### config.py
- `HolmesConfig` 新增 `username: str = ""` 字段

### mcp/tools.py
- `handle_kb_list` / `handle_kb_search` 调用更新后的 `list_entries(kb_status="active", exclude_sub_entries=True)`
- `handle_kb_read` 返回值包含 `children` 字段（当 entry 有 `child_entry_ids` 时）

## 验收条件

- [ ] `holmes kb list` 不显示 `kb_status: pending/deprecated` 的 entry
- [ ] `holmes kb list` 不显示 `type: process` 且有 `parent_id` 的 entry
- [ ] `holmes kb list --all` 包含 deprecated；`--all-types` 包含 sub-entries
- [ ] `holmes kb search <q>` 只返回 active 非 sub-entry 结果
- [ ] `holmes kb show <process-sub-id>` 正常展示，显示 `[sub-entry of: <parent_id>]`
- [ ] `holmes config set username wangzhi` 成功写入并可读取
- [ ] `find_entry("PT-DB-001")` 和 `find_entry("gpu-init-failure-root-001")` 均可正确查找
- [ ] `read_entry` 对有 `child_entry_ids` 的 entry 返回 `children` 字段
- [ ] 旧 entry（无 kb_status 字段）被视为 active，不被过滤
- [ ] 新增字段单元测试：happy path + 向后兼容旧 entry

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M1-basic-fields/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```
