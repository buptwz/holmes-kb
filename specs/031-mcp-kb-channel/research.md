# Research: MCP KB Channel (Feature 031)

**Date**: 2026-06-13

---

## 1. 现有 MCP Server 实现（Feature 027）

**Decision**: 在 `kb/holmes/mcp/server.py` + `kb/holmes/mcp/tools.py` 的基础上直接扩展，不重写。

**当前 5 个工具**：`kb_overview`、`kb_list`、`kb_read`、`kb_confirm`、`kb_submit`

**需修改**：
- `handle_kb_overview` → 加 `skill_count`
- `handle_kb_list` → 加 `type="skill"` 路由
- `handle_kb_read` → 加 skill name 路由 + `path` 参数支持
- `handle_kb_confirm` → session_id 改为 per-connection
- 新增 `handle_kb_search`
- `handle_kb_submit` → 改为调用 `import_document()`

---

## 2. 知识搜索能力

**Decision**: 使用 `kb/holmes/kb/search.py` 的 `LinearScanBackend`。

**实现细节**：
- 全文线性扫描，匹配 title + tags + body
- O(n) 时间，≤1000 条目下 < 200ms（设计文档已验证）
- 返回 `SearchResult`（含 `entry_id`、`title`、`kb_type`、`snippet`、`score`）
- **不搜索 skills**（skills 不在扫描目录内）— 已知限制，spec 中接受

**Rationale**: 无需引入向量数据库或外部索引，当前规模下足够用。

---

## 3. Skill 读取实现

**Decision**: 使用 `kb/holmes/kb/skill/manager.py` 中的 `list_skills()` 和 `parse_skill_md()`。

**`list_skills(kb_root)` 行为**：
- 扫描 `skills/` 目录
- 反向扫描所有 entry 的 `skill_refs` 字段，构建 `linked_entries` 映射
- 返回 `SkillSummary(name, description, version, linked_entries)` 列表

**`parse_skill_md(path)` 行为**：
- 解析 SKILL.md frontmatter，返回 `SkillDefinition`
- 当前字段：`name`、`description`、`version`、`platforms`、`timeout`、`params`、`prerequisites`、`content`

**注意**：031 分支基于 main，尚未合并 030 的 Anthropic Agent Skills 格式变更（030 中 `SkillDefinition` 简化为 `name`+`description`+`content`）。本 Feature 实现时以当前 main 分支代码为准，兼容现有 SKILL.md 格式。

**Skill 子文件读取**：需在 `handle_kb_read` 中新增逻辑，直接读取 `skills/<name>/<path>` 文件，过滤二进制扩展名。

---

## 4. `kb_submit` → Import Pipeline

**Decision**: 调用 `kb/holmes/kb/importer.py` 中的 `import_document()`（已有实现），而非 `ImportAgentRunner`（030 分支特有，当前 main 没有）。

**`import_document()` 签名**（async）：
```python
async def import_document(
    kb_root: Path,
    source_path: Path,   # 实际为文件路径，需要临时写入内容
    model: str,
    api_base_url: str,
    api_key: str,
    kb_type: Optional[str] = None,
    ...
) -> ImportResult
```

**适配方案**：`handle_kb_submit` 将 `content` 字符串写入临时文件，调用 `import_document()`，读取结果后删除临时文件。用 `asyncio.run()` 同步封装。

**重复检测**：`importer.py` 内有 `DuplicatePendingError`（含 `existing_id`）— 捕获后返回 `{status: "duplicate", existing_id}` 响应。

---

## 5. `kb_confirm` per-connection Session ID

**Decision**: 在 `server.py` 的 MCP 工具注册层生成 per-connection UUID，传递给 `handle_kb_confirm()`。

**FastMCP 连接模型**：每次 MCP 客户端连接触发新的工具调用上下文。通过在 `@mcp.tool()` 装饰器函数外层绑定 connection-scoped session_id 实现隔离。

**实现方案**：利用 FastMCP 的 lifespan 或 context 机制；若不支持，退而使用线程本地存储（threading.local）在每个请求中注入 UUID。

**Rationale**: 修复当前全局 session_id 导致的跨客户端去重冲突。

---

## 6. ID 路由规则（`kb_read` 统一寻址）

**Entry ID pattern**: `^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$`（如 `PT-DB-001`、`MD-SVC-003`）
**Skill name pattern**: `^[a-z0-9][a-z0-9-]*[a-z0-9]$`（如 `redis-oom-recovery`）

两者格式天然互斥，server 侧正则判断即可路由，无歧义。

---

## 7. 数据模型文档 (FR-010)

**Decision**: 实现阶段首先阅读 `schema.py`、`store.py`、`skill/manager.py`、`skill/template.py`、`pending.py` 等源文件，然后生成 `docs/kb-data-model.md`。

**约束**：文档内容 100% 从代码反向提取，每个字段/规则必须可以在代码中找到对应实现。
