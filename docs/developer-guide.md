# Holmes Developer Guide

## Architecture

Holmes has three layers plus an optional MCP server:

```
TUI (TypeScript/Bun/React Ink)
    ↕ JSON-RPC 2.0 over Unix domain socket
Agent (Python 3.11+)
    ↕ direct function calls
Knowledge Base (filesystem: Markdown + YAML frontmatter)

MCP Server (holmes start — streamable-http on port 8765)
    ↕ Model Context Protocol
Any MCP-compatible AI client (Claude, GPT-4o, etc.)
    ↕ same Knowledge Base
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
- `agent/tools/kb_confirm.py` — `kb_confirm_entry` tool (explicit evidence recording)
- `agent/tools/bash.py` — shell command tool (requires confirmation)
- `agent/tools/file_read.py` — file injection tool
- `kb/store.py` — KB CRUD, `append_evidence()`, `load_evidence()`, `derive_maturity()`
- `kb/governance.py` — `check_title_duplicate()`, `is_write_protected()`
- `kb/history.py` — `save_snapshot()`, `list_snapshots()` (`.history/` management)
- `kb/decay.py` — `run_decay()`, `archive_orphan()`, `DecayResult`
- `kb/schema.py` — `EvidenceRecord` TypedDict, frontmatter field definitions
- `kb/index_builder.py` — rebuild index.json + _index.md
- `kb/importer.py` — `compute_source_hash()` (SHA-256, 16 hex chars)
- `kb/atomic.py` — `atomic_write()` via tempfile + os.replace
- `kb/pending.py` — pending entry management, `write_pending()`
- `mcp/__init__.py` — MCP server package
- `mcp/tools.py` — 5 MCP tool handlers: `handle_kb_overview`, `handle_kb_list`, `handle_kb_read`, `handle_kb_confirm`, `handle_kb_submit`
- `mcp/server.py` — `FastMCP("holmes-kb")` server + `run_server(kb_root, port)`, streamable-http transport
- `kb/validator.py` — 3-gate confirmation validation
- `kb/merger.py` — 5-scenario merge logic
- `kb/conflict.py` — conflict record management
- `kb/linter.py` — KB health checker
- `kb/agent/__init__.py` — autonomous import agent package
- `kb/agent/pipeline.py` — `ThreePhaseImportPipeline`: Reader → Extractor → LLM Writer 3-phase orchestration; Phase 2.5 programmatic dedup pass
- `kb/agent/runner.py` — `ImportAgentRunner`: provider-agnostic tool-use loop orchestrator
- `kb/agent/tools.py` — 9 tool handlers + `TOOL_DEFINITIONS` (Anthropic input_schema format; converted to OpenAI format at runtime by `OpenAIProvider`)
- `kb/agent/provider/__init__.py` — exports `LLMProvider`, `ToolCall`, `create_provider`
- `kb/agent/provider/base.py` — `LLMProvider` ABC + `ToolCall` dataclass
- `kb/agent/provider/anthropic_provider.py` — Anthropic SDK implementation
- `kb/agent/provider/openai_provider.py` — OpenAI-compatible SDK implementation
- `kb/agent/provider/factory.py` — `create_provider(cfg) -> LLMProvider`
- `kb/agent/report.py` — `ImportReport`, `CuratorFinding`, `DecisionTrace`
- `kb/agent/verifier.py` — `ContentVerifier`: two-pass self-verification
- `kb/agent/dedup.py` — `SemanticDeduplicator`: LLM root-cause comparison
- `kb/agent/skill_advisor.py` — `SkillAdvisor`: deterministic skill-gen criteria
- `kb/agent/curator.py` — `SkillCurator`: incremental quality checks
- `kb/skill/usage.py` — `SkillUsageRecord` sidecar + read/write helpers
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

## MCP Server

`holmes start` runs the KB as an MCP server over streamable-http (`mcp.server.fastmcp.FastMCP`).

### 5 MCP Tools

| Tool | Description |
|------|-------------|
| `kb_overview` | KB structure — types, categories, top tags |
| `kb_list` | Paginated entry listing with 150-char previews |
| `kb_read` | Full Markdown for one entry — does NOT write evidence |
| `kb_confirm` | Write one evidence sidecar for an entry (idempotent per session) |
| `kb_submit` | Create a pending entry for human review |

All tool descriptions carry MUST/MUST NOT guidance to steer the calling agent's behavior
(e.g., call `kb_overview` first; only call `kb_confirm` after user confirms resolution).

### Adding a New MCP Tool

1. Add a `handle_<name>()` function to `kb/holmes/mcp/tools.py`
2. Register a `@mcp.tool()` wrapper in `kb/holmes/mcp/server.py`

The `mcp = FastMCP("holmes-kb")` instance is module-level. Port is set via
`mcp.settings.port = port` before `mcp.run(transport="streamable-http")`.

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

See `specs/003-kb-governance/` for governance and `specs/013-kb-skill-evolution/` for
the autonomous import pipeline design rationale.

Key design decisions:

**Write protection**: There is no `write-entry` command. All Agent writes go through
`write-pending → confirm`. Verified/proven entries can only be changed via the correction
workflow (`write-pending --corrects <id>`), which saves a VersionSnapshot before replacing.

**Evidence-driven maturity**: Maturity (`draft`/`verified`/`proven`) is computed
automatically from the evidence array — it is never set manually. `derive_maturity(evidence)`
applies the rules: 0 records → draft, ≥1 → verified, ≥2 sessions + ≥2 contributors → proven.

**Explicit evidence, never implicit**: Reading a KB entry does NOT record evidence.
Evidence is written only by two explicit actions: (a) the `kb_confirm_entry` agent tool
(Python agent), or (b) the `kb_confirm` MCP tool. Both call `append_evidence()` with a
session-scoped sidecar file. This prevents noisy evidence inflation from exploratory reads.

**Sidecar evidence files (git-friendly)**: Each evidence record is stored as a separate JSON
file at `contributions/evidence/<entry_id>/<session_id>.json`. File additions never conflict
in git, enabling concurrent multi-user `update-refs` calls to merge automatically. `load_evidence()`
aggregates sidecar files with any legacy frontmatter records.

**Auto-decay**: `run_decay()` uses `max(evidence[*].date)` as the staleness reference.
proven entries older than 12 months are demoted to verified; verified older than 6 months
drop to draft. A VersionSnapshot is saved to `.history/` before each demotion.

**VersionSnapshot**: All corrections and decay demotions are preserved in `.history/<id>-<ts>.md`.
This provides traceable history without depending on git history (entries may be renamed).

**Autonomous import pipeline** (`ThreePhaseImportPipeline` + `ImportAgentRunner`): `holmes import`
runs a 3-phase pipeline followed by an LLM tool-use loop (max 20 iterations):

**Pre-loop phases** (deterministic, no LLM):
1. **Reader** — load source document; check `source_hash` idempotency (skip exact duplicates)
2. **Extractor** — LLM-powered structured field extraction into draft KB entries
3. **Phase 2.5: Programmatic dedup** — `pipeline._run_dedup_pass()` calls
   `read_kb_entries_by_category` + `compare_root_cause` programmatically; matching entries
   (same_root_cause=True, confidence ≥ 0.8) are updated directly via `atomic_write` and removed
   from the LLM Writer's workload

**LLM tool-use loop** (remaining drafts only):
4. `verify_content` — self-verification (clears fields without source support)
5. `write_kb_entry` / `update_kb_entry` — persist to pending or merge-update
6. `evaluate_skill` + `create_skill_for_entry` — skill generation advisory
7. `report_item` — structured audit trail in `ImportReport`

After the loop, `ImportAgentRunner._finalize_skill_generation()` also evaluates skill candidates
for entries that were updated (not just created), then `_git_commit()` commits all writes atomically.

**LLM provider abstraction** (`kb/agent/provider/`): `runner.py` calls a stable
`LLMProvider` interface instead of a specific SDK. `create_provider(cfg)` returns the
correct implementation based on `cfg.provider`:

- `AnthropicProvider` — wraps `anthropic.Anthropic`; uses Anthropic tool-call wire format
- `OpenAIProvider` — wraps `openai.OpenAI`; converts `TOOL_DEFINITIONS` from Anthropic
  `input_schema` format to OpenAI `parameters` format at call time; handles OpenAI-style
  tool-result messages (`role: "tool"`) and assistant messages with `tool_calls`

The interface exposes three methods:
- `complete(messages, system, model, max_tokens, tools)` → `(stop, tool_calls, messages)` — one iteration of the tool-use loop
- `simple_complete(messages)` → `str` — single-turn text completion used by `compare_root_cause` and `verify_content`
- `append_tool_results(messages, results)` → `messages` — appends tool results in provider wire format

To add a new provider: implement `LLMProvider` in a new file under `kb/agent/provider/`
and register it in `factory.py`. No changes to `runner.py` or `tools.py` are needed.

**Skill lifecycle sidecar** (`.skill_usage.json`): Each skill directory contains a
JSON sidecar tracking `use_count`, `last_used_at`, `patch_count`, `agent_created` flag,
and `absorbed_into` (tombstone for merged skills). Written atomically by `kb/skill/usage.py`.

**Incremental skill curation** (`SkillCurator`): After every import, the curator scans
agent-created skills and reports three advisory finding types:
- `merge_candidate`: two skills with description Jaccard similarity > 0.6
- `oversized`: SKILL.md body > 3 000 chars
- `update_candidate`: `patch_count=0` and a linked entry was updated after skill creation

All curation findings are advisory — they appear in `ImportReport.suggestions` and
require human or curator-agent action.

- Pure filesystem storage (no database)
- Git-managed for collaboration
- Progressive disclosure: README → _index.md → full entry
- 3-gate confirmation prevents noise entries
- Pending → confirm workflow for safe contribution
