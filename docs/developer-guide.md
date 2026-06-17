# Holmes Developer Guide

## Architecture

Holmes is two Python packages plus an MCP server:

```
holmes/        CLI package (holmes-agent)
    ↕ direct function calls
kb/            KB package (holmes-kb) — store, validator, import pipeline, MCP server
    ↕ filesystem
Knowledge Base (git repo: Markdown + YAML frontmatter)

MCP Server (holmes start — streamable-http on port 8765)
    ↕ Model Context Protocol
Any MCP-compatible AI client (Claude, GPT-4o, etc.)
    ↕ same Knowledge Base
```

Both packages share the `holmes.*` namespace and are installed together:

```bash
cd holmes && pip install -e .   # installs holmes-agent + holmes-kb dependency
```

### CLI Package (`holmes/holmes/`)

Key files:
- `holmes/cli.py` — Click-based CLI entry point (`config`, `import`, `kb`, `session` commands)
- `holmes/config.py` — `HolmesConfig` model + read/write (`~/.holmes/config.json`)
- `holmes/logging_config.py` — structured logging setup
- `holmes/agent/engine.py` — core agentic loop (streaming, tool execution)
- `holmes/agent/session.py` — session model + persistence
- `holmes/agent/context_builder.py` — system prompt assembly
- `holmes/agent/mcp_manager.py` — MCP server integration
- `holmes/agent/tools/kb_confirm.py` — `kb_confirm_entry` tool (explicit evidence recording)
- `holmes/agent/tools/bash.py` — shell command tool (requires confirmation)
- `holmes/agent/tools/file_read.py` — file injection tool

### KB Package (`kb/holmes/kb/`)

Key files:
- `store.py` — `EntryMeta`, `read_entry()`, `list_entries()`, `write_entry()`, `rebuild_index_files()`
- `pending.py` — `get_pending()`, `list_pending()`, `delete_pending()`, `append_log()`
- `validator.py` — `validate_schema()`, `check_duplicate()`, `generate_id()`
- `conflict.py` — `ConflictEntry`, `list_conflicts()`, `resolve_conflict()`, `write_conflict_entry()`
- `merger.py` — git conflict detection + `merge_pending_entry()` (5-scenario logic)
- `linter.py` — `lint() -> LintReport` — KB health check
- `governance.py` — `check_title_duplicate()`, `is_write_protected()`
- `history.py` — `save_snapshot()`, `list_snapshots()` (`.history/` management)
- `decay.py` — `run_decay()`, `archive_orphan()`, `DecayResult`
- `schema.py` — `EvidenceRecord` TypedDict, frontmatter field definitions, `VALID_PITFALL_CATEGORIES`
- `atomic.py` — `atomic_write()` via tempfile + os.replace
- `mcp/tools.py` — 6 MCP tool handlers: `handle_kb_overview`, `handle_kb_list`, `handle_kb_search`, `handle_kb_read`, `handle_kb_confirm`, `handle_kb_submit`
- `mcp/server.py` — `FastMCP("holmes-kb")` server + `run_server(kb_root, port)`, streamable-http transport
- `agent/pipeline.py` — `ThreePhaseImportPipeline`: Reader → Extractor → LLM Writer; Phase 2.5 programmatic dedup pass
- `agent/runner.py` — `ImportAgentRunner`: provider-agnostic tool-use loop orchestrator
- `agent/tools.py` — tool handlers + `TOOL_DEFINITIONS` (Anthropic format; converted to OpenAI format at runtime)
- `agent/provider/factory.py` — `create_provider(cfg)` — infers provider from model name (`claude-*` → Anthropic, else OpenAI)
- `agent/provider/anthropic_provider.py` — Anthropic SDK implementation
- `agent/provider/openai_provider.py` — OpenAI-compatible SDK implementation
- `agent/normalizer.py` — `DraftNormalizer`: deterministic post-Extractor normalization
- `agent/verifier.py` — `ContentVerifier`: two-pass self-verification
- `agent/dedup.py` — `SemanticDeduplicator`: LLM root-cause comparison
- `agent/skill_advisor.py` — `SkillAdvisor`: deterministic skill-gen criteria; slug derived from entry title
- `agent/curator.py` — `SkillCurator`: incremental quality checks
- `agent/phases/extractor.py` — `ExtractorAgent` + `EXTRACTOR_SYSTEM_PROMPT` (type→section mapping)
- `skill/manager.py` — `create_skill()`, `list_skills()`, `read_skill()`

## Local Development

### Prerequisites

```bash
python3 --version  # >= 3.11
```

### Setup

```bash
# Install both packages (holmes-agent + holmes-kb dependency)
cd holmes
pip install -e .

# Install KB package standalone (for kb/ development only)
cd holmes/kb
pip install -e .
```

### Python Code Style

Uses ruff:

```bash
cd holmes
ruff check holmes/    # lint
ruff format holmes/   # format

cd holmes/kb
ruff check holmes/    # lint
ruff format holmes/   # format
```

## MCP Server

`holmes start` runs the KB as an MCP server over streamable-http (`mcp.server.fastmcp.FastMCP`).

### 6 MCP Tools

| Tool | Description |
|------|-------------|
| `kb_overview` | KB structure — types, categories, top tags |
| `kb_list` | Paginated entry listing with 150-char previews |
| `kb_search` | Full-text keyword search across entries, ranked by relevance |
| `kb_read` | Full Markdown for one entry or skill — does NOT write evidence |
| `kb_confirm` | Write one evidence sidecar for an entry (idempotent per session) |
| `kb_submit` | Create a pending entry for human review |

All tool descriptions carry MUST/MUST NOT guidance to steer the calling agent's behavior
(e.g., call `kb_overview` first; only call `kb_confirm` after user confirms resolution).

### Adding a New MCP Tool

1. Add a `handle_<name>()` function to `kb/holmes/mcp/tools.py`
2. Register a `@mcp.tool()` wrapper in `kb/holmes/mcp/server.py`

The `mcp = FastMCP("holmes-kb")` instance is module-level. Port is set via
`mcp.settings.port = port` before `mcp.run(transport="streamable-http")`.

## Adding a New Agent Tool

1. Create `holmes/holmes/agent/tools/your_tool.py`:

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

2. Register it in `holmes/holmes/agent/engine.py`'s tool list.

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

Skills are loaded by the agent at runtime and can be invoked by name.

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
