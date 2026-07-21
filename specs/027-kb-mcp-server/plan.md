# Implementation Plan: KB MCP Server & System Closure

**Branch**: `027-kb-mcp-server` | **Date**: 2026-06-11 | **Spec**: [spec.md](spec.md)

## Summary

三项并行工作使系统完整闭环：
1. **新增 MCP Server**：`holmes start` 启动 stdio MCP server，暴露 5 个 tool（kb_overview / kb_list / kb_read / kb_confirm / kb_submit），任何 MCP 客户端可连接本地 KB
2. **修复 pending evidence 存储**：`list_entries()` 新增 `include_pending` 参数，使 `append_evidence()` 可对 pending 条目写 evidence sidecar
3. **修复 agent 内部 evidence 逻辑**：移除 engine.py 的 auto-record on read，新增 `kb_confirm_entry` 工具，语义与 MCP 路径一致

## 现有代码摸底（重要）

在动手前已确认的关键现有能力：

| 已有 | 位置 | 说明 |
|------|------|------|
| `holmes kb pending` | `cli.py:666` | 列出 pending 条目 |
| `holmes kb confirm <id>` | `cli.py:884` | 3-gate confirm（schema→dup→preview→promote）|
| `holmes kb reject <id>` | `cli.py:1076` | 拒绝 pending |
| `holmes.kb.pending` | `kb/pending.py` | `write_pending()`, `list_pending()`, `get_pending()`, `delete_pending()` |
| `holmes.kb.validator` | `kb/validator.py` | `validate_schema()`, `generate_id()`, `check_duplicate()` |
| `holmes.kb.governance` | `kb/governance.py` | `check_title_duplicate()`, `is_write_protected()` |
| `KbWriteEntryTool` | `agent/tools/kb_write.py` | agent 写 pending 条目，已有 requires_confirmation |
| Pending ID 格式 | `pending.py:24` | `pending-{YYYYMMDD}-{HHMMSS}-{rand4}` |
| Pending 目录 | `contributions/pending/` | 非 `pending/`，注意路径 |
| `mcp` SDK | pip installed v1.27.1 | stdio transport 可用 |

**结论**：US6（pending approve CLI）已有完整实现（`holmes kb confirm` 就是 approve），无需重新实现。US3 的 `kb_submit` 底层用 `write_pending()` + `append_evidence(include_pending=True)`。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `mcp` v1.27.1（已安装，stdio transport）
- `frontmatter`、`click`（已有）
- `subprocess` / `shlex`（读取 git config）

**Storage**: KB 文件系统（Markdown + YAML frontmatter + JSON sidecar evidence）

**Testing**: pytest，现有 733 tests

**Target Platform**: Linux CLI（streamable-http MCP server，用户手动启动，MCP 客户端通过 HTTP 连接）

**Package Structure**:
```
kb/holmes/
├── mcp/                     ← 新增
│   ├── __init__.py
│   ├── server.py            ← MCP server 入口，注册 5 个 tool
│   └── tools.py             ← 5 个 tool handler 实现
├── kb/
│   ├── store.py             ← list_entries() 加 include_pending 参数
│   └── ...
└── cli.py                   ← 新增 holmes start 命令

agent/holmes/agent/
├── engine.py                ← 移除 auto-record 逻辑
└── tools/
    ├── kb_read.py           ← 现有，不改
    ├── kb_write.py          ← 现有，不改
    └── kb_confirm.py        ← 新增 KbConfirmEntryTool
```

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | ✅ | `list_entries()` 新增可选参数，不破坏现有调用；MCP tools 独立模块 |
| 依赖倒置 | ✅ | MCP server 通过 KB store 接口操作，不直接读文件 |
| 单一职责 | ✅ | `mcp/server.py` 只注册 tools；`mcp/tools.py` 只实现 handler；store 层只做存储 |
| 接口隔离 | ✅ | 5 个 MCP tool 各司其职，不合并职责 |
| 迪米特法则 | ✅ | MCP tools 只调用 KB store 公开函数，不了解文件布局 |
| 验证原则 | ✅ | 每个 US 有独立测试；不写无测试的代码 |
| 可观测性 | ✅ | MCP server 每次 tool 调用 logger.info；evidence 写入记录 session/contributor |
| 渐进式实现 | ✅ | 复用现有 pending/confirm/store 逻辑，不重复实现 |
| 环境配置 | ✅ | `--kb-path` 参数，支持 `HOLMES_KB_PATH` 环境变量 |

## Project Structure

### Documentation

```
specs/027-kb-mcp-server/
├── plan.md           ← 本文件
├── spec.md
├── research.md
└── tasks.md
```

### Source Changes

```
kb/
├── holmes/
│   ├── cli.py                    # 新增 holmes start 命令
│   ├── mcp/                      # 新增
│   │   ├── __init__.py
│   │   ├── server.py             # MCP server 入口
│   │   └── tools.py              # 5 tool handlers
│   └── kb/
│       └── store.py              # list_entries(include_pending=False) 参数
└── tests/
    ├── test_mcp_tools.py         # 新增
    └── test_store.py             # 补充 include_pending 测试

agent/
└── holmes/agent/
    ├── engine.py                 # 移除 auto-record
    └── tools/
        └── kb_confirm.py         # 新增 KbConfirmEntryTool
```

## Implementation Approach

### US4: list_entries include_pending（先做，其他依赖它）

`store.py` 的 `list_entries(kb_root, ..., include_pending=False)`:
- 新增 `include_pending: bool = False` 参数
- 当 `True` 时，额外扫描 `contributions/pending/` 目录下的 `*.md` 文件
- `append_evidence()` 调用 `list_entries` 时传 `include_pending=True`
- 所有现有调用不传此参数，行为不变

### US5: engine.py fix

从 `engine.py` 删除：
- `if tool_name == "kb_read_entry" and not result.is_error:` 块（lines 263-266）
- `_flush_evidence()` 方法（lines 389+）
- `self._flush_evidence()` 调用（line 300）
- `AgentSession.kb_refs` 字段（engine session dataclass）

新增 `agent/holmes/agent/tools/kb_confirm.py`：
- `KbConfirmEntryTool`，调用 `append_evidence(kb_root, entry_id, record)`
- contributor 从 `os.environ.get("HOLMES_CONTRIBUTOR")` 或 fallback "agent"
- requires_confirmation=False（agent 自主调用，无需用户确认）

### US1+US2+US3: MCP Server

**`mcp/server.py`**：
```python
import uuid
from mcp import Server
# streamable-http transport via mcp SDK (verify exact API at implementation time)
# app listens on configurable port (default 8765)

session_id = str(uuid.uuid4())[:8]

app = Server("holmes-kb")
# register 5 tools via @app.call_tool() / @app.list_tools()
# run_server(kb_root, port=8765) called from holmes start
```

**`cli.py` holmes start**：
```bash
holmes start --kb-path ./kb-repo --port 8765
# → starts streamable-http server at http://localhost:8765
# → client config: {"url": "http://localhost:8765"}
```

**`mcp/tools.py`** — 5 个 handler：

`kb_overview(kb_root)`:
- 调用 `list_entries(kb_root)` 聚合统计
- 返回 `{types: {pitfall: N, ...}, categories: [...], top_tags: [...], total: N}`

`kb_list(kb_root, type, category, limit, offset)`:
- 调用 `list_entries(kb_root, kb_type, category)`
- 每条返回 `{id, title, maturity, type, category, brief}`
- brief = 正文前 150 字符

`kb_read(kb_root, entry_id)`:
- 调用 `read_entry(kb_root, entry_id)`
- 返回原始 Markdown 内容
- 不写 evidence

`kb_confirm(kb_root, entry_id, session_id, contributor)`:
- 调用 `append_evidence(kb_root, entry_id, {session_id, contributor, date})`
- 返回 `{ok, maturity, promoted}`
- contributor 从 `git -C kb_root config user.email` 获取，回退 user.name，再回退 hostname

`kb_submit(kb_root, title, type, content, session_id, contributor)`:
- 调用 `write_pending(kb_root, content)`（content 由 server 端组装 frontmatter）
- 调用 `append_evidence(kb_root, pending_id, {session_id, contributor, date})` with include_pending
- 返回 `{id, status: "pending"}`

**`cli.py` 新增 `holmes start`**：
```python
@cli.command("start")
@click.pass_context
def start(ctx):
    """Start the KB MCP server (stdio transport)."""
    kb_root = _require_kb_root(ctx)
    from holmes.mcp.server import run_server
    run_server(kb_root)
```

## research.md

技术决策无需专项研究，均基于现有代码确认：

| 决策 | 结论 | 依据 |
|------|------|------|
| MCP transport | streamable-http | 用户手动启动常驻服务，多客户端共享同一进程；`holmes start --port 8765`；客户端配置 `{"url": "http://localhost:8765"}`；mcp SDK v1.27.1 已安装，需确认 streamable-http 具体 API |
| Session ID | server 启动时 UUID[:8]，贯穿进程生命周期 | 同 session 多次 confirm 被 sidecar 去重 |
| Contributor 获取 | `git -C <kb_path> config user.email` → `user.name` → `socket.gethostname()` | 与 MCP 用途匹配；本地操作 |
| Pending 目录 | `contributions/pending/`（已有） | 与 `pending.py` 一致 |
| kb_submit frontmatter | server 端组装，type/title/maturity=pending 写入 | 与 `write_pending()` 期望格式一致 |
| US6（approve CLI） | 不实现，已有 `holmes kb confirm <id>` | 3-gate confirm = approve；无需重复 |
| kb_confirm agent tool | requires_confirmation=False | 语义是「记录已发生的成功」，不需要用户再确认 |
