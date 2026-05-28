# Holmes KB — Developer Guide

## Architecture

Holmes KB has two layers:

```
holmes-agent (AI agent, any OpenAI-compatible backend)
    ↕ subprocess calls via TypeScript KB tools
holmes-kb (Python package — filesystem operations)
    ↕ direct file I/O
Knowledge Base (git repo — Markdown + YAML frontmatter)
```

### Python Package (`holmes/`)

| File | Responsibility |
|------|---------------|
| `cli.py` | Click CLI entry point (`holmes` command) |
| `config.py` | Config model + read/write (`~/.holmes/config.json`) |
| `agent_server.py` | JSON-RPC 2.0 server (Unix socket) for agent ↔ KB communication |
| `kb/store.py` | Entry CRUD, index listing, reference tracking, maturity promotion |
| `kb/validator.py` | Schema validation + Jaccard deduplication |
| `kb/pending.py` | Write/list pending entries with PendingEntry frontmatter fields |
| `kb/importer.py` | LLM-powered document classification and structuring |
| `kb/merger.py` | 5-scenario git conflict detection and auto-resolution |
| `kb/conflict.py` | Content contradiction isolation and resolution |
| `kb/linter.py` | KB health checks: orphans, stale pending, maturity decay, duplicates |
| `kb/index_builder.py` | Rebuild `_index.md` and `index.json` |
| `agent/engine.py` | Core agentic loop (streaming, tool dispatch) |
| `agent/ipc_server.py` | JSON-RPC server over Unix domain socket |
| `agent/session.py` | Session model and persistence |
| `agent/context_builder.py` | System prompt assembly (loads HOLMES.md) |
| `agent/skill_manager.py` | Skill file discovery and execution |
| `agent/tools/kb_read.py` | KB read tools (KbReadOverview, KbSearch, KbReadEntry, …) |
| `agent/tools/kb_write.py` | KB write tools (KbWriteEntry, KbExtractAndSave) |

### TypeScript KB Tools (`src/tools/kb/`)

Seven native tools loaded into the holmes-agent (claude-code fork) at startup.
They call the `holmes` CLI via subprocess — no MCP overhead.

| Tool | Access | CLI call |
|------|--------|----------|
| `KbReadOverview` | read | `holmes kb overview --json` |
| `KbReadCategoryIndex` | read | `holmes kb read-category <type> --json` |
| `KbReadEntry` | read | `holmes kb show <id>` |
| `KbSearch` | read | `holmes kb list --query <q> --json` |
| `KbListPending` | read | `holmes kb pending --json` |
| `KbWriteEntry` | write | `holmes kb write-pending` |
| `KbExtractAndSave` | write | `holmes kb write-pending` (with LLM extraction) |

Write tools set `isReadOnly: false`, triggering the agent's native permission
confirmation flow before executing.

See [FORK_CHANGES.md](../FORK_CHANGES.md) for how to register these tools in a
claude-code fork.

## Local Development

### Setup

```bash
git clone https://github.com/buptwz/holmes-kb.git
cd holmes-kb
pip install -e .
```

### Run the CLI

```bash
holmes --help
holmes setup --kb-path ./kb-template --model gpt-4o --api-key <key>
holmes kb list
```

### Linting

```bash
pip install ruff
ruff check holmes/
ruff format holmes/
```

### Tests

```bash
pip install pytest pytest-asyncio
# Set env vars for your LLM provider first:
export HOLMES_MODEL=gpt-4o
export HOLMES_API_BASE=https://api.openai.com/v1
export HOLMES_API_KEY=sk-xxx

pytest tests/
```

## KB Entry Format

```markdown
---
id: PT-DB-001
type: pitfall
title: Redis Connection Pool Exhausted
maturity: proven
category: database
tags: [redis, connection-pool, timeout]
created_at: 2026-03-15T08:00:00Z
updated_at: 2026-05-20T14:30:00Z
reference_count: 7
last_referenced: 2026-05-20T14:30:00Z
---

## Symptoms

## Root Cause

## Resolution
```

### Entry Types

| Type | Required sections |
|------|-------------------|
| `pitfall` | Symptoms, Root Cause, Resolution |
| `model` | Definition |
| `guideline` | Rule |
| `process` | Steps |
| `decision` | Context, Decision |

### Maturity Model

| Level | Promoted when | Decays when |
|-------|--------------|-------------|
| `draft` | — | — |
| `verified` | reference_count >= 1 | last_referenced > 180 days ago |
| `proven` | reference_count >= 3 | last_referenced > 365 days ago |

## Adding a New KB Tool

1. Create `holmes/agent/tools/your_tool.py`:

```python
from holmes.agent.tools.base import BaseTool, ToolResult

class YourTool(BaseTool):
    name = "your_tool"
    description = "What this tool does."
    input_schema = {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "..."}
        },
        "required": ["param"],
    }
    requires_confirmation = False

    async def execute(self, param: str, **kwargs) -> ToolResult:
        result = do_something(param)
        return ToolResult(result)
```

2. Register it in `agent_server.py`'s `build_tools()`.

## IPC Protocol

JSON-RPC 2.0 over Unix domain socket, newline-delimited JSON.

### Key Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `session.create` | TUI→Agent | Create a new session |
| `chat.send` | TUI→Agent | Send a user message |
| `session.resolve` | TUI→Agent | End session and extract knowledge |
| `tool.approve` | TUI→Agent | Approve a pending tool call |
| `tool.deny` | TUI→Agent | Deny a pending tool call |
| `agent/token` | Agent→TUI | Streaming token delta |
| `agent/tool_confirm` | Agent→TUI | Request user confirmation |
| `agent/done` | Agent→TUI | Turn complete |
| `agent/error` | Agent→TUI | Error occurred |
