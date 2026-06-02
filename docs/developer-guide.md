# Holmes Developer Guide

## Architecture

Holmes has three layers:

```
TUI (TypeScript/Bun/React Ink)
    ↕ JSON-RPC 2.0 over Unix domain socket
Agent (Python 3.11+)
    ↕ direct function calls
Knowledge Base (filesystem: Markdown + YAML frontmatter)
```

### TUI Layer (`tui/`)

Adapted from claude-code's React/Ink TUI framework.

Key files:
- `src/main.tsx` — entry point, spawns agent subprocess, renders App
- `src/screens/REPL.tsx` — main chat screen
- `src/screens/SessionList.tsx` — session history browser
- `src/screens/KnowledgeBrowser.tsx` — KB entry browser
- `src/ipc/HolmesIPCClient.ts` — JSON-RPC client
- `src/ipc/types.ts` — all IPC message type definitions
- `src/components/ToolCallCard.tsx` — tool execution card
- `src/components/ConfirmDialog.tsx` — confirmation dialog
- `src/components/TokenUsageBar.tsx` — token usage display
- `src/components/StatusBar.tsx` — bottom status bar

### Agent Layer (`agent/holmes/`)

Modeled after claude-code's QueryEngine pattern.

Key files:
- `agent_server.py` — starts the IPC server as a subprocess
- `config.py` — configuration model + read/write
- `logging_config.py` — structured logging setup
- `agent/engine.py` — core agentic loop (streaming, tool execution)
- `agent/ipc_server.py` — JSON-RPC server over Unix socket
- `agent/session.py` — session model + persistence
- `agent/context_builder.py` — system prompt assembly
- `agent/memory.py` — persistent memory loading
- `agent/context_manager.py` — token usage tracking
- `agent/mcp_manager.py` — MCP server integration
- `agent/skill_manager.py` — skill file loading
- `agent/tools/base.py` — BaseTool abstract class
- `agent/tools/kb_read.py` — KB discovery tools
- `agent/tools/kb_write.py` — KB write (requires confirmation)
- `agent/tools/bash.py` — shell command tool (requires confirmation)
- `agent/tools/file_read.py` — file injection tool
- `kb/store.py` — KB CRUD, `append_evidence()`, `load_evidence()`, `derive_maturity()`
- `kb/governance.py` — `check_title_duplicate()`, `is_write_protected()`
- `kb/history.py` — `save_snapshot()`, `list_snapshots()` (`.history/` management)
- `kb/decay.py` — `run_decay()`, `archive_orphan()`, `DecayResult`
- `kb/schema.py` — `EvidenceRecord` TypedDict, frontmatter field definitions
- `kb/index_builder.py` — rebuild index.json + _index.md
- `kb/importer.py` — LLM-powered import classification
- `kb/pending.py` — pending entry management, `write_pending()`
- `kb/validator.py` — 3-gate confirmation validation
- `kb/merger.py` — 5-scenario merge logic
- `kb/conflict.py` — conflict record management
- `kb/linter.py` — KB health checker
- `cli.py` — Click-based CLI entry point

## Local Development

### Prerequisites

```bash
python3 --version  # >= 3.11
bun --version      # >= 1.3
```

### Setup

```bash
# Python
cd agent
pip install -e ".[dev]"  # or: pip install -e .

# TypeScript
cd tui
bun install
```

### Running in Development

```bash
# Terminal 1: Start agent server
cd agent
python -m holmes.agent_server --socket /tmp/holmes-dev.sock

# Terminal 2: Start TUI
cd tui
bun run src/main.tsx --socket=/tmp/holmes-dev.sock
```

### Python Code Style

Uses ruff with Google style rules:

```bash
cd agent
ruff check holmes/    # lint
ruff format holmes/   # format
```

### TypeScript Code Style

Uses ESLint + Prettier with Google style:

```bash
cd tui
bun run lint          # ESLint check
bun run format:check  # Prettier check
bun run lint:fix      # Auto-fix ESLint
bun run format        # Auto-format
```

## IPC Protocol

JSON-RPC 2.0 over Unix domain socket. Messages are newline-delimited JSON.

### Request Flow

```
TUI → Agent: {"jsonrpc":"2.0","id":1,"method":"chat.send","params":{...}}
Agent → TUI: {"jsonrpc":"2.0","method":"agent/token","params":{...}}  (notifications)
Agent → TUI: {"jsonrpc":"2.0","id":1,"result":null}  (response)
```

### Notification Methods

| Method | Direction | Description |
|--------|-----------|-------------|
| `agent/token` | Agent→TUI | Streaming token delta |
| `agent/tool_start` | Agent→TUI | Tool execution started |
| `agent/tool_end` | Agent→TUI | Tool execution completed |
| `agent/tool_confirm` | Agent→TUI | Confirmation required |
| `agent/done` | Agent→TUI | Turn complete with token stats |
| `agent/error` | Agent→TUI | Error occurred |
| `context/update` | Agent→TUI | Token usage updated |
| `mcp/status` | Agent→TUI | MCP server connection status |

### Request Methods

| Method | Description |
|--------|-------------|
| `session.create` | Create a new session |
| `session.list` | List sessions |
| `session.get` | Get session details |
| `session.resolve` | Resolve session and extract knowledge |
| `chat.send` | Send a message |
| `kb.list` | List KB entries |
| `kb.get` | Get KB entry |
| `tool.approve` | Approve a tool confirmation |
| `tool.deny` | Deny a tool confirmation |
| `skill.invoke` | Execute a skill |
| `context.compact` | Compact context |
| `/remember` | Save to memory |

## Adding a New Tool

1. Create `agent/holmes/agent/tools/your_tool.py`:

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
    requires_confirmation = False  # or True for write/exec tools

    async def execute(self, param: str, **kwargs) -> ToolResult:
        result = do_something(param)
        return ToolResult(result)
```

2. Register it in `agent/holmes/agent_server.py`'s `build_tools()`.

3. Add IPC type definitions in `tui/src/ipc/types.ts` if needed.

## Adding a Skill

Create `~/.holmes/skills/my-skill.md`:

```markdown
---
name: check-disk
description: Check disk usage across all mount points
---

Check disk usage on this system:
1. Run `df -h` to see disk usage
2. Identify mount points above 80% usage
3. Find large directories with `du -sh /path/*`
4. Report findings with recommended cleanup actions
```

Then use in TUI: `/check-disk`

## Knowledge Base Design

See `specs/003-kb-governance/` for the full data model and design rationale.

Key design decisions:

**Write protection**: There is no `write-entry` command. All Agent writes go through
`write-pending → confirm`. Verified/proven entries can only be changed via the correction
workflow (`write-pending --corrects <id>`), which saves a VersionSnapshot before replacing.

**Evidence-driven maturity**: Maturity (`draft`/`verified`/`proven`) is computed
automatically from the evidence array — it is never set manually. `derive_maturity(evidence)`
applies the rules: 0 records → draft, ≥1 → verified, ≥2 sessions + ≥2 contributors → proven.

**Sidecar evidence files (git-friendly)**: Each evidence record is stored as a separate JSON
file at `contributions/evidence/<entry_id>/<session_id>.json`. File additions never conflict
in git, enabling concurrent multi-user `update-refs` calls to merge automatically. `load_evidence()`
aggregates sidecar files with any legacy frontmatter records.

**Auto-decay**: `run_decay()` uses `max(evidence[*].date)` as the staleness reference.
proven entries older than 12 months are demoted to verified; verified older than 6 months
drop to draft. A VersionSnapshot is saved to `.history/` before each demotion.

**VersionSnapshot**: All corrections and decay demotions are preserved in `.history/<id>-<ts>.md`.
This provides traceable history without depending on git history (entries may be renamed).

- Pure filesystem storage (no database)
- Git-managed for collaboration
- Progressive disclosure: README → _index.md → full entry
- 3-gate confirmation prevents noise entries
- Pending → confirm workflow for safe contribution
