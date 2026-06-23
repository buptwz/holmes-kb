# M9 — MCP 接口

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，同时提供 MCP（Model Context Protocol）服务，让 AI agent 通过 MCP 工具访问知识库。MCP 服务使用 `fastmcp` 库，通过 `streamable-http` 传输。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ MCP 接口`（全节）
  - **定位**：MCP 是 agent 访问知识库的**读通道**；知识质量由人工审阅保障，因此知识的结构化、审阅、approve 全在 CLI 侧完成，**MCP 内部不运行任何 LLM**
  - **架构分工**：
    ```
    agent (via MCP)
      ├── 读知识库      → kb_overview / kb_list / kb_search / kb_read
      ├── 记录证据      → kb_confirm（写使用记录，不生成知识）
      └── 保存草稿      → kb_draft（捕获现场文档，等待人工 import）

    人工 CLI
      └── holmes import _drafts/<file>   → DAG pipeline → approve → 知识上线
    ```
  - **工具清单**（6 个工具）：
    | 工具 | 类型 | 说明 |
    |---|---|---|
    | `kb_overview` | 读 | KB 结构概览：各类型数量、分类、高频 tag |
    | `kb_list` | 读 | 按 type/category 浏览 entry 列表（默认只返回 active，不含 sub-entries） |
    | `kb_search` | 读 | 关键词搜索（默认只返回 active pitfall roots） |
    | `kb_read` | 读 | 按 ID 读取 entry 完整内容；pitfall entry 额外返回 `children` 树导航字段 |
    | `kb_confirm` | 写（证据） | 记录"此 entry 帮助解决了当前问题"；写证据记录，触发 maturity 升级 |
    | `kb_draft` | 写（草稿） | 将现场文档保存到 `_drafts/`；不运行 LLM，不生成结构化 entry |
  - **`kb_submit` 已删除**：原有的 MCP 内联 import pipeline 与"质量由人工保障"原则冲突，改为 `kb_draft` + 人工 `holmes import`
  - **kb_read 树形导航**：读取有 `child_entry_ids` 的 pitfall entry 时，返回结构化 `children` 字段：
    ```json
    {
      "id": "gpu-init-failure-root-001",
      "type": "pitfall",
      "content": "...",
      "children": [
        {"id": "gpu-init-driver-check-001",    "title": "驱动版本检查流程"},
        {"id": "gpu-init-firmware-update-001", "title": "固件升级流程"}
      ]
    }
    ```
    agent 沿 `children` 递归调用 `kb_read` 即可完成树形导航，不需要理解 entry ID 格式或 frontmatter 结构
  - **kb_draft 草稿保存**：
    - 调用前检查 `config.username`，未配置则返回 `{"error": "config.username not set, run: holmes config set username <name>"}`
    - 文件保存到 `_drafts/<title>.md`（若 `title` 参数未提供，用时间戳 `<YYYY-MM-DD-HHMMSS>.md`）
    - frontmatter 写入：`author: config.username`、`saved_at: <ISO timestamp>`、`source: mcp.draft`
    - 不做任何 LLM 处理
    - 写一条日志事件：`trace_id = 文件名 stem`，`span = mcp.draft`
    - 返回给 agent：`{"saved": "_drafts/<filename>.md", "next_step": "holmes import _drafts/<filename>.md"}`
  - **Draft 生命周期**：草稿保存在 `_drafts/`；`holmes import _drafts/<file>` 处理后移入 `_drafts/_imported/`
  - **MCP 日志记录**（调用 M8 的 `HolmesLogger.write_span`）：
    - `kb_overview` → `write_span(session_id, "mcp.kb_overview", "INFO", ...)`
    - `kb_search` → `write_span(session_id, "mcp.kb_search", "INFO", query=..., results=...)`
    - `kb_read` → `write_span(session_id, "mcp.kb_read", "INFO", entry_id=...)`
    - `kb_confirm` → `write_span(session_id, "mcp.kb_confirm", "INFO", entry_id=..., promoted=...)`
    - `kb_draft` → `write_span(filename_stem, "mcp.draft", "INFO", ...)` （trace_id = 文件名 stem）
    - session_id：从 `kb_overview` 生成（已有逻辑），前缀 `session-`，传递给同 session 的后续调用
  - **Store 层适配**（M1 已完成，M9 只需确保 MCP 工具调用 M1 新接口）：
    - ID 无关化：`find_entry()` 改为文件系统扫描（M1 已实现）
    - `kb_status` 过滤：`list_entries(kb_status="active")`（M1 已实现）
    - sub-entry 可见性：`list_entries(exclude_sub_entries=True)`（M1 已实现）
    - `children` 树导航字段：`read_entry()` 对有 `child_entry_ids` 的 entry 返回 `children`（M1 已实现）

- `§ Step 0 > Entry 状态字段`：`kb_status: active` entries 才参与 agent 检索

- `§ Process Sub-entry 可见性规则`：
  - `kb_list`：默认不显示 process sub-entries（`exclude_sub_entries=True`）
  - `kb_search`：搜索范围限于 pitfall roots
  - `kb_read <process-id>`：正常显示（明确指定 ID 时可查看）

- `§ 目录结构与文件共置`：
  - `_drafts/<title>.md`：MCP `kb_draft` 保存的草稿
  - `_drafts/_imported/`：`holmes import` 处理后的草稿归档
  - `_drafts/` 随 git 追踪

- `§ CLI 兼容性`：
  - `holmes kb drafts`（新增）：列出 `_drafts/` 下待 import 的草稿文件，含保存时间和来源

- `§ 知乎知识库建模兼容性 > pitfall_structure 字段`：旧 pitfall entries（`pitfall_structure: flat`）直接读 Resolution；新 tree entries 按 `child_entry_ids` 递归导航；`kb_read` 返回的 `children` 字段让 agent 无需解析 frontmatter 即可导航

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §1 文件系统布局 — 理解现有目录结构；`_drafts/` 是新增目录
- §2 Entry Frontmatter 字段 — `kb_status`（M1 新增，MCP 过滤依据）、`child_entry_ids`（M1 新增，tree 导航）、`parent_id`（M1 新增，sub-entry 判断）
- §4 Evidence sidecar — `kb_confirm` 写入的证据记录结构（`contributions/evidence/`）

### 3. MCP 集成文档
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/mcp-integration.md`

全文阅读。了解：
- `fastmcp` 库的工具注册方式（`@mcp.tool()` 装饰器）
- MCP server 启动方式和 `streamable-http` 传输
- 现有工具的返回格式约定
- session_id 生成和传递机制（`kb_overview` 已有实现）
- `kb_confirm` 工具的现有实现（证据写入逻辑）

### 4. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构、Python 包结构、MCP 模块位置（`kb/holmes/mcp/`）。

## 涉及的现有代码（实现前全部通读）

```
kb/holmes/mcp/server.py         # MCP server，工具注册
                                # 重点：了解 kb_submit 的注册方式（@mcp.tool()）
                                # 删除 kb_submit，新增 kb_draft 的注册位置
kb/holmes/mcp/tools.py          # 所有 tool handler 函数
                                # 重点：handle_kb_submit（删除）
                                # handle_kb_list / handle_kb_search / handle_kb_read（更新调用 M1 接口）
                                # handle_kb_overview（同步更新）
                                # handle_kb_confirm（了解证据写入，无需大改）
kb/holmes/kb/store.py           # 经 M1 改造后的接口：
                                # list_entries(kb_status="active", exclude_sub_entries=True)
                                # find_entry()（文件系统扫描）
                                # read_entry()（返回 children 字段）
kb/holmes/kb/logger.py          # 经 M8 实现的 HolmesLogger（写日志）
kb/holmes/config.py             # HolmesConfig（username / model / api_key）
kb/holmes/cli.py                # 了解子命令注册方式
```

相关测试文件：
```
kb/tests/test_mcp_tools.py      # 现有 MCP 工具测试，理解测试模式
                                # M9 完成后需更新：移除 kb_submit 测试，新增 kb_draft 测试
```

## 前置依赖

- **M1**（必须先完成）：store 层适配（ID 无关化、kb_status 过滤、sub-entry 可见性、children 字段）
- **M8**（必须先完成）：`HolmesLogger` 接口（MCP 日志记录调用 `HolmesLogger.write_span`）

## 本模块目标

1. **删除 `kb_submit` 工具**：从 `server.py` 和 `tools.py` 中完全移除
2. **新增 `kb_draft` 工具**：保存草稿到 `_drafts/`，不运行 LLM
3. **新增 `holmes kb drafts` 命令**：列出待 import 的草稿
4. **更新现有 MCP 工具**：确保 `kb_list` / `kb_search` / `kb_read` 调用 M1 新接口（`kb_status` 过滤、sub-entry 可见性、`children` 字段）
5. **MCP 日志记录**：所有工具调用写入日志（调用 M8 的 `HolmesLogger`）
6. **Import pipeline 联动**：`holmes import _drafts/<file>` 完成后将草稿移入 `_drafts/_imported/`

## 主要改动清单

### mcp/server.py
- 删除 `kb_submit` 工具注册（`@mcp.tool()` 装饰的函数）
- 新增 `kb_draft` 工具注册

### mcp/tools.py

**删除**：
- `handle_kb_submit` 函数完全移除

**新增** `handle_kb_draft(kb_root, content, title, config) -> dict`：
```python
def handle_kb_draft(kb_root: Path, content: str, title: str | None, config: HolmesConfig) -> dict:
    # 1. 检查 config.username，未配置则返回 error
    if not config.username:
        return {"error": "config.username not set, run: holmes config set username <name>"}

    # 2. 生成文件名（title 参数提供则用之，否则用时间戳）
    filename = f"{title}.md" if title else f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}.md"

    # 3. 写入 _drafts/<filename>.md，frontmatter 包含 author / saved_at / source
    draft_dir = kb_root / "_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_content = f"""---
author: {config.username}
saved_at: {datetime.now(timezone.utc).isoformat()}
source: mcp.draft
---

{content}
"""
    atomic_write(draft_dir / filename, draft_content)

    # 4. 写日志事件（trace_id = 文件名 stem）
    logger.write_span(
        trace_id=Path(filename).stem,
        span="mcp.draft",
        level="INFO",
        msg="draft saved",
        author=config.username
    )

    # 5. 返回
    return {
        "saved": f"_drafts/{filename}",
        "next_step": f"holmes import _drafts/{filename}"
    }
```

**更新** `handle_kb_list`、`handle_kb_search`：
- 调用 `list_entries(kb_status="active", exclude_sub_entries=True)`（M1 新接口）
- 追加日志：`write_span(session_id, "mcp.kb_search", "INFO", query=..., results=len(...))`

**更新** `handle_kb_read`：
- 调用 `read_entry()` 返回值中包含 `children` 字段（M1 已实现）
- 将 `children` 原样包含在返回的 JSON 中
- 追加日志：`write_span(session_id, "mcp.kb_read", "INFO", entry_id=...)`

**更新** `handle_kb_overview`：
- 调用 M1 的新 `list_entries`（`kb_status="active"`）
- 追加日志：`write_span(session_id, "mcp.kb_overview", "INFO", ...)`

### cli.py
新增 `holmes kb drafts` 子命令：
- 列出 `_drafts/` 下（不含 `_drafts/_imported/`）的所有 `.md` 文件
- 展示格式：文件名、保存时间（读 frontmatter `saved_at`）、来源（读 frontmatter `source`）
- 若 `_drafts/` 不存在或为空：打印"暂无待 import 的草稿"

### importer.py（或 pipeline.py）
Import pipeline 联动：当 import 的源文件路径在 `_drafts/` 下时，import 完成后：
```python
if source_path.parent.name == "_drafts" or "_drafts" in str(source_path):
    imported_dir = kb_root / "_drafts" / "_imported"
    imported_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(imported_dir / source_path.name))
```

## 关键实现细节

### kb_submit 完全删除
- `mcp/server.py`：删除 `kb_submit` 的 `@mcp.tool()` 注册行
- `mcp/tools.py`：删除 `handle_kb_submit` 函数（包含函数定义和任何调用）
- 如有测试 `test_mcp_tools.py`：删除对应测试用例
- **不做向后兼容**：调用 `kb_submit` 的 agent 会收到工具不存在的错误，这是预期行为

### session_id 传递
现有 `kb_overview` 生成 session_id（前缀 `session-`），传递给同 session 内的后续工具调用。M9 在 `write_span` 中使用该 session_id 作为 trace_id（MCP 操作的 trace 与 import trace 不同，前者以 `session-` 区分）。

### kb_read children 字段
M1 已在 `read_entry()` 中实现 `children` 字段返回（对有 `child_entry_ids` 的 entry 返回结构化 children 列表）。`handle_kb_read` 只需将 `read_entry()` 的返回值原样透传给 agent：
```python
result = read_entry(kb_root, entry_id)
# result 已包含 children 字段（M1 实现）
return result  # 直接返回
```

## 验收条件

- [ ] MCP 服务不再暴露 `kb_submit` 工具（调用返回工具不存在错误）
- [ ] `kb_draft(content="...", title="redis-oom-2026-06-23")` 在 `_drafts/` 下创建文件，frontmatter 含 `author / saved_at / source: mcp.draft`
- [ ] `kb_draft` 未配置 username 时返回明确错误信息
- [ ] `kb_draft` 不运行任何 LLM（纯文件写入）
- [ ] `holmes kb drafts` 列出 `_drafts/` 下待 import 的草稿，不含 `_imported/` 中的文件
- [ ] `holmes import _drafts/redis-oom.md` 完成后文件移入 `_drafts/_imported/`
- [ ] `kb_list`、`kb_search` 默认只返回 `kb_status: active` 的非 sub-entry 条目（利用 M1 store 接口）
- [ ] `kb_read` 返回 pitfall entry 时附带 `children` 字段（利用 M1 store 接口）
- [ ] 所有 MCP 读操作写入 session trace 日志（依赖 M8 `HolmesLogger`）
- [ ] `kb_draft` 写入文档 trace 日志（trace_id = 文件名 stem，span = mcp.draft）
- [ ] `test_mcp_tools.py` 更新：移除 kb_submit 测试，新增 kb_draft 测试（含 username 未配置场景）

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M9-mcp/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ MCP 接口` 全节（含工具清单、kb_read 树形导航示例、kb_draft 草稿保存流程、Draft 生命周期、MCP 日志记录）、`§ 目录结构与文件共置`（`_drafts/` 和 `_drafts/_imported/` 目录规则），再读完 `mcp/server.py` 和 `mcp/tools.py` 中现有工具实现（特别是 `handle_kb_submit` 的删除范围和 `handle_kb_read` 的现有返回格式），再读完 `docs/mcp-integration.md` 理解 fastmcp 工具注册方式，再读完 M8 的 `HolmesLogger.write_span` 接口签名。
