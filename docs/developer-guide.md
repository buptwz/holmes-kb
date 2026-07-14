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

### CLI Package (`kb/holmes/`)

Key files:
- `cli.py` — Click-based CLI entry point (top-level commands: `overview`, `import`, `approve`, `search`, etc.)
- `config.py` — `HolmesConfig` model + read/write (`~/.holmes/config.json`)

### KB Package (`kb/holmes/kb/`)

Key files:
- `store.py` — `EntryMeta`, `read_entry()`, `list_entries()`, `write_entry()`, `rebuild_index_files()`, `update_entry_content()`
- `pending.py` — `get_pending()`, `list_pending()`, `delete_pending()`, `append_log()`
- `schema.py` — `EvidenceRecord` TypedDict, frontmatter field definitions, `DecisionMapEntry`, `validate_entry()`
- `conflict.py` — `ConflictEntry`, `list_conflicts()`, `resolve_conflict()`, `write_conflict_entry()`
- `merger.py` — git conflict detection + `merge_pending_entry()`
- `linter.py` — `lint() -> LintReport` — KB health check
- `governance.py` — `check_title_duplicate()`, `is_write_protected()`
- `history.py` — `save_snapshot()`, `list_snapshots()` (`.history/` management)
- `decay.py` — `run_decay()`, `archive_orphan()`, `DecayResult` (proven→verified→draft→archived lifecycle)
- `doctor.py` — `run_doctor()` — lifecycle lint (stale drafts, decay candidates, orphans)
- `atomic.py` — `atomic_write()` via tempfile + os.replace
- `mcp/tools.py` — 4 MCP tool handlers: `handle_kb_browse`, `handle_kb_read`, `handle_kb_confirm`, `handle_kb_draft`
- `mcp/server.py` — `FastMCP("holmes-kb")` server + `run_server(kb_root, port)`, streamable-http transport
- `agent/pipeline.py` — `ImportPipeline`: Classifier → Summarizer → Generator; `_fallback_extract()` regex fallback
- `agent/phases/classifier.py` — `DocumentClassifier`: type detection, language detection, multi-topic check
- `agent/phases/summarizer.py` — `SummarizerAgent`: structured extraction (key_facts, commands, symptoms, resolution_branches); direct mode for <8K docs
- `agent/phases/generator.py` — `GeneratorAgent`: formats summary into KB Markdown with YAML frontmatter
- `agent/normalizer.py` — `DraftNormalizer`: deterministic post-generation normalization (header mapping, KP cleanup)
- `agent/fidelity.py` — `verify_summary_fidelity_042()`: validate extracted summary against source
- `agent/interactive_review.py` — `review_summary()` + `review_draft()`: interactive confirmation gates
- `agent/compact.py` — `CompactAdapter`: tool-loop context compaction when approaching context limits
- `agent/dedup.py` — `SemanticDeduplicator`: LLM root-cause comparison
- `agent/skill_advisor.py` — `SkillAdvisor`: deterministic skill-gen criteria (≥3 commands)
- `agent/provider/factory.py` — `create_provider(cfg)` — infers provider from model name
- `agent/provider/openai_provider.py` — OpenAI-compatible SDK implementation (`temperature=0`)
- `agent/observability.py` — Langfuse integration (optional plugin, disabled by default)
- `skill/manager.py` — `create_skill()`, `list_skills()`, `read_skill()`, `validate_skill_md()`

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

### 4 MCP Tools

| Tool | Description |
|------|-------------|
| `kb_browse` | Directory-style browsing: type → category → entries with briefs, pagination |
| `kb_read` | Progressive disclosure: summary (default), full, section, branch navigation |
| `kb_confirm` | Record outcome (`solved`/`not_solved`) — `solved` promotes maturity |
| `kb_draft` | Save a raw draft document for later import (no LLM processing) |

All tool descriptions carry guidance to steer the calling agent's behavior
(e.g., call `kb_browse` first; only call `kb_confirm` after user confirms resolution).

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

Create a skill directory in the KB:

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

Key design decisions:

**One document = one entry**: `holmes import` converts each source document into a single
structured KB entry. Multi-branch diagnostics are represented as `### Branch` subsections
within a single entry's `## Resolution` section (not as separate tree entries).

**Write protection**: There is no `write-entry` command. All Agent writes go through
`write-pending → approve`. Verified/proven entries can only be changed via the correction
workflow (`write-pending --corrects <id>`), which saves a VersionSnapshot before replacing.

**Evidence-driven maturity**: Maturity (`draft`/`verified`/`proven`) is computed
automatically from the evidence array — it is never set manually. `derive_maturity(evidence)`
applies the rules: 0 solved → draft, ≥1 → verified, ≥2 sessions + ≥2 contributors → proven.

**Reference tracking**: Reading an entry with `kb_read(detail="full")` records a lightweight
`referenced` evidence sidecar that resets the entry's decay timer. Only an explicit
`kb_confirm(outcome="solved")` promotes maturity. This creates a closed lifecycle loop:
import → draft → verified → proven → decay → archive.

**Sidecar evidence files (git-friendly)**: Each evidence record is stored as a separate JSON
file at `contributions/evidence/<entry_id>/<session_id>.json`. File additions never conflict
in git, enabling concurrent multi-user confirmations to merge automatically.

**Auto-decay**: `run_decay()` uses `max(evidence[*].date)` as the staleness reference.
proven entries older than 12 months are demoted to verified; verified older than 6 months
drop to draft; draft entries older than 30 days + 3 months stale are archived.
A VersionSnapshot is saved to `.history/` before each demotion.

**LLM reliability**: All LLM calls use `temperature=0`. Every LLM output goes through
validate → feedback → retry (max 2 retries). If the Summarizer LLM fails completely,
a regex-based fallback ensures the pipeline never crashes.

**Import pipeline** (three-phase):

```
Source doc → Classifier (type + language detection)
                │
                ▼
          Summarizer (structured extraction: key_facts, commands, symptoms, branches)
                │
                ▼
          Generator (format summary into KB Markdown with YAML frontmatter)
                │
                ▼
          Normalizer + Fidelity Check (validate → feedback → retry)
                │
                ▼
          _pending/ (awaiting human review)
```

Documents under 8K chars use Summarizer direct mode (full text embedded in prompt,
single LLM call instead of 3-7 tool-use round trips).

**LLM provider abstraction** (`kb/agent/provider/`): `pipeline.py` calls a stable
`LLMProvider` interface instead of a specific SDK. `create_provider(cfg)` returns the
correct implementation based on `cfg.provider`:

- `OpenAIProvider` — wraps `openai.OpenAI`; handles OpenAI-style tool-result messages

The interface exposes:
- `complete(messages, system, model, max_tokens, tools)` → `(stop, tool_calls, messages, usage)` — one iteration of the tool-use loop
- `simple_complete(messages)` → `str` — single-turn text completion

To add a new provider: implement `LLMProvider` in a new file under `kb/agent/provider/`
and register it in `factory.py`.

**Observability (Langfuse plugin)**: Optional, disabled by default. When enabled,
every import run produces a full trace in Langfuse with nested spans:

```
import_pipeline → classifier → summarizer → generator
```

Each LLM call records prompt, response, tokens, and latency. Implementation:

- `agent/observability.py` — conditional loader: only imports langfuse when
  `cfg.langfuse_enabled` is `true`. Otherwise all decorators are no-ops.
- OpenAI path: `langfuse.openai.OpenAI` SDK wrapper auto-captures generations.
- Anthropic path: `@observe(as_type="generation")` on `complete()` / `simple_complete()`.
- Pipeline/Classifier/Summarizer/Generator: `@observe(name="...")` for span hierarchy.
- CLI (`cli.py`): calls `init_langfuse_from_config(cfg)` **before** importing pipeline
  modules, so decorators bind to the real langfuse implementation at import time.

To enable: `holmes config set langfuse_enabled true` (plus key/host config).
Install dependency: `pip install -e ".[observability]"`.

- Pure filesystem storage (no database)
- Git-managed for collaboration
- Progressive disclosure: kb_browse → kb_read(summary) → kb_read(section) → kb_read(full)
- Pending → approve workflow for safe contribution
