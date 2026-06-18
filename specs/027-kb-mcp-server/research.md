# Research: KB MCP Server & System Closure

## MCP Server Pattern (stdio)

**Decision**: Use `mcp` Python SDK with stdio transport.

**Rationale**: `mcp` v1.27.1 already installed. stdio transport is the standard for local MCP servers launched as subprocess by clients (Claude Desktop, Cursor). No additional network setup required.

**Pattern**:
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
import asyncio

app = Server("holmes-kb")

@app.list_tools()
async def list_tools():
    return [Tool(name="kb_overview", ...)]

@app.call_tool()
async def call_tool(name, arguments):
    ...

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

asyncio.run(main())
```

## Contributor Identity Resolution

**Decision**: `git -C <kb_path> config user.email` → `user.name` → `socket.gethostname()`

**Rationale**: KB is git-managed; git config is the natural identity source. Hostname fallback ensures contributor is never empty, enabling evidence writes in all environments (CI, containers).

## list_entries include_pending

**Decision**: Add `include_pending: bool = False` to `list_entries()`.

**Rationale**: `append_evidence()` uses `list_entries()` to find entry paths. Pending entries live in `contributions/pending/`, outside the current scan paths. Adding a flag preserves backwards compatibility (all existing callers unaffected) while enabling evidence writes for pending entries.

**Implementation**: When `include_pending=True`, additionally scan `kb_root / "contributions" / "pending"` for `*.md` files, returning them alongside official entries.

## engine.py auto-record removal

**Decision**: Remove `kb_read_entry` → `session.kb_refs` auto-tracking entirely.

**Rationale**: Read ≠ useful. Auto-recording on read pollutes evidence signal. Only explicit `kb_confirm_entry` call should write evidence. This aligns internal agent behavior with MCP path semantics.

**Impact**: `AgentSession.kb_refs` field, `_flush_evidence()` method, and `_InternalStopEvent` flush call all removed. No regression risk — no active feature depends on evidence being written at session end.

## kb_submit frontmatter assembly

**Decision**: MCP server assembles complete frontmatter from structured inputs before calling `write_pending()`.

**Rationale**: `write_pending()` expects valid Markdown with YAML frontmatter. MCP `kb_submit` receives title/type/content from agent and must produce a well-formed entry. Server-side assembly ensures required fields (id will be assigned by `write_pending`), maturity=pending, created_at are always present.

## US6 (pending approve) — already exists

**Decision**: `holmes kb confirm <id>` IS the approve command. Not reimplementing.

**Rationale**: Existing 3-gate confirm (schema → duplicate → preview → promote) does exactly what `pending approve` would do, plus adds duplicate detection and schema validation. Reusing it avoids duplicated logic.
