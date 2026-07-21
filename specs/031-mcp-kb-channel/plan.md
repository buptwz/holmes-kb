# Implementation Plan: MCP KB 透明通道

**Branch**: `031-mcp-kb-channel` | **Date**: 2026-06-13 | **Spec**: [spec.md](spec.md)

## Summary

在 Feature 027 MCP Server 基础上扩展，实现完整的 KB 透明通道：新增 `kb_search` 工具，扩展 `kb_read` 支持 skill name 统一寻址（含子文件读取），`kb_list` 支持 `type="skill"`，`kb_overview` 补充 `skill_count`，`kb_submit` 改走 `import_document()` pipeline，`kb_confirm` 修复为 per-connection session_id。另生成 `docs/kb-data-model.md` 权威数据模型文档。

---

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `mcp`（FastMCP）、`frontmatter`、`openai`（for `kb_submit` pipeline）

**Storage**: 文件系统，Markdown + YAML frontmatter，JSON sidecar

**Testing**: pytest（现有 `kb/tests/`）

**Target Platform**: Linux（本地运行 MCP Server）

**Project Type**: CLI + MCP Server library

**Performance Goals**: `kb_list` < 1s（500 条目），`kb_read` < 200ms，`kb_search` < 2s

**Constraints**: `kb_submit` 无 server 侧超时；不修改 KB 文件系统布局；不破坏现有测试

**Scale/Scope**: KB ≤ 1000 entries，skills ≤ 50 个

---

## Constitution Check

*Constitution 为项目模板默认状态，无具体规则。以下采用项目惯例：*

- [x] 复用现有模块（`search.py`、`skill/manager.py`、`importer.py`），不重复实现
- [x] 每个工具变更有对应测试覆盖
- [x] 不修改 KB 文件格式（向后兼容）
- [x] 数据模型文档从代码反向提取，非凭空撰写

---

## Project Structure

### Documentation (this feature)

```text
specs/031-mcp-kb-channel/
├── plan.md          ← 本文件
├── spec.md          ← 需求规格
├── research.md      ← 技术调研结论
├── data-model.md    ← MCP 响应数据模型
├── quickstart.md    ← 开发快速入门
├── checklists/
│   └── requirements.md
└── tasks.md         ← 由 /speckit-tasks 生成
```

### Source Code (impacted files)

```text
kb/
├── holmes/
│   ├── mcp/
│   │   ├── server.py        ← 修改：注册 kb_search；per-connection session_id
│   │   └── tools.py         ← 修改：扩展所有 handler；新增 handle_kb_search
│   └── kb/
│       ├── search.py        ← 复用（无修改）
│       ├── skill/
│       │   └── manager.py   ← 复用（无修改）
│       └── importer.py      ← 复用；适配同步调用封装
├── tests/
│   ├── test_mcp_tools.py    ← 修改/新增：扩展所有工具的测试
│   └── test_mcp_server.py   ← 修改：per-connection session_id 测试

docs/
└── kb-data-model.md         ← 新增：KB 数据模型权威文档（FR-010）
```

---

## Implementation Phases

### Phase A：扩展 `kb_overview` 和 `kb_list`（最小改动，独立可测）

**A1** — `handle_kb_overview`：新增 `skill_count`（扫描 `skills/` 目录），新增 `hint` 字段

**A2** — `handle_kb_list`：新增 `type="skill"` 路由，调用 `list_skills(kb_root)`，返回 `{id=name, description}`；`category` 参数对 skill 静默忽略

**测试**：overview 含 skill_count；list(type="skill") 返回正确结构

---

### Phase B：扩展 `kb_read` 统一寻址

**B1** — 路由判断：正则匹配 entry ID 格式（`^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$`）vs skill name

**B2** — Skill SKILL.md 读取：
- 调用 `parse_skill_md()` 获取 description
- 动态计算 `linked_entries`（扫描所有 entry 的 `skill_refs`）
- 扫描 skill 目录，构建 `files` 列表（过滤二进制扩展名）

**B3** — Skill 子文件读取：验证路径安全性（防穿越）+ 文本扩展名 + 读取内容

**B4** — Entry 读取：确保 `skill_refs` 字段出现在响应中

**测试**：路由正确性；skill 读取含 linked_entries + files；子文件读取；路径穿越防护；二进制过滤；entry 传 path 返回 error

---

### Phase C：新增 `kb_search`

**C1** — `handle_kb_search(kb_root, query, type=None, limit=10)`：调用 `search.search()`，可选 type 过滤

**C2** — 注册 `@mcp.tool() def kb_search(...)` 到 `server.py`

**测试**：关键词匹配；type 过滤；无结果空列表；hint 字段存在

---

### Phase D：`kb_submit` 改走 import pipeline

**D1** — `handle_kb_submit` 重构：
- 接收 `content: str`
- 写入临时文件 → `asyncio.run(import_document(...))` → 清理临时文件（finally）
- 捕获 `DuplicatePendingError` → `{status: "duplicate", existing_id, existing_title, hint}`
- 捕获 `ContentTooShortError` → error
- 成功 → `{id, status: "pending", message}`

**测试**：成功提交；重复检测返回 existing_id；内容过短返回 error；LLM 错误（mock）

---

### Phase E：`kb_confirm` per-connection session_id

**E1** — 调研 FastMCP 连接上下文 API，确认 per-connection 状态注入方式

**E2** — 修改 `server.py`：连接建立时生成 UUID，退而使用 `contextvars` 注入（若 FastMCP 不支持原生 lifespan）

**E3** — `handle_kb_confirm` 加入 `session_id: str` 参数，移除全局 `_session_id`

**测试**：同一连接重复 confirm → duplicate；独立调用均写入 evidence

---

### Phase F：`docs/kb-data-model.md`（FR-010）

**F1** — 阅读以下源文件，逐字段提取：
- `schema.py` → 所有 frontmatter 字段、有效值、section 规则
- `store.py` → EntryMeta 结构、maturity 阈值、evidence sidecar 路径规则
- `skill/manager.py` → SkillDefinition、SkillSummary、skill name 格式
- `skill/template.py` → SKILL.md 模板格式
- `pending.py` → pending ID 格式、pending 特有字段

**F2** — 生成 `docs/kb-data-model.md`，章节：
1. 文件系统布局
2. Entry frontmatter 字段（必填/可选、类型、有效值、来源代码行）
3. 各 Entry 类型必需 body sections
4. Skill SKILL.md 结构
5. ID 格式规则
6. Maturity 升级规则（含代码依据）
7. Evidence sidecar 格式
8. Pending entry 格式

**约束**：每条规则注明对应源文件路径，不写无代码依据的内容

---

## Key Risks

| 风险 | 可能性 | 缓解方案 |
|------|--------|---------|
| FastMCP 不支持 per-connection 上下文 | 中 | 退而使用 `contextvars.ContextVar` 注入 session_id |
| `import_document()` 需要文件路径而非字符串 | 已知 | 临时文件方案（D1）已规划，finally 保证清理 |
| `kb_submit` LLM 调用在 MCP 上下文超时 | 低 | 文档说明客户端配置 ≥180s，Server 不限制 |
