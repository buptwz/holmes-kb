# MCP Integration Guide

Holmes exposes its knowledge base as a standard MCP server. Any MCP-compatible AI agent —
Claude, GPT-4o, or a custom agent — can query and contribute to the KB without custom
integration code.

---

## Starting the MCP Server

```bash
holmes start                    # Port 8765, KB path from config
holmes start --port 9000        # Custom port
holmes start --kb-path ~/my-kb  # Override KB path
```

The server uses the **streamable-http** MCP transport.

### MCP Client Configuration

```json
{ "url": "http://localhost:8765" }
```

For Claude Desktop or any MCP-compatible client, add the above as a server entry.
No authentication is required by default.

---

## Available Tools

The server exposes five tools.

### `kb_overview`

Returns the structure of the KB: entry type counts, available categories, and top tags.

**Call this first**, at the start of any session where the agent may need KB knowledge.
It gives the vocabulary needed to formulate accurate follow-up calls to `kb_list`.
Skipping this and guessing a category directly risks missing relevant entries entirely.

```json
{
  "total": 42,
  "types": { "pitfall": 28, "process": 8, "guideline": 6 },
  "categories": ["application", "database", "network", "system"],
  "top_tags": ["redis", "postgres", "nginx", "timeout", "memory"]
}
```

### `kb_list`

Lists entries filtered by type and/or category, with brief content previews.

```json
// Request
{ "type": "pitfall", "category": "database", "limit": 20, "offset": 0 }

// Response
{
  "entries": [
    { "id": "PT-DB-001", "title": "Redis Connection Pool Exhausted", "brief": "..." },
    { "id": "PT-DB-002", "title": "PostgreSQL Autovacuum Blocking Writes", "brief": "..." }
  ],
  "total": 8,
  "offset": 0,
  "limit": 20
}
```

Scan the titles and briefs to identify relevant entries. Do not read every entry blindly.
Use `limit`/`offset` to paginate when the list is long.

### `kb_read`

Returns the full Markdown content of one entry, including all sections.

```json
// Request
{ "entry_id": "PT-DB-001" }

// Response
{
  "id": "PT-DB-001",
  "content": "---\ntype: pitfall\n...\n---\n\n## Symptoms\n..."
}
```

**Always call `kb_read` before acting on an entry.** The brief from `kb_list` is a
summary only. For skill entries, the content includes executable script code — run it
directly rather than asking the user to copy-paste it.

### `kb_confirm`

Records that an entry successfully helped resolve the current issue. This writes an
evidence sidecar that improves the entry's maturity score.

```json
// Request
{ "entry_id": "PT-DB-001" }

// Response
{ "status": "ok", "message": "Evidence recorded for PT-DB-001" }
```

**Call `kb_confirm` only when all three conditions are met:**
1. You read the entry during the current session
2. You applied its guidance (executed steps, ran the script, etc.)
3. The user has explicitly confirmed the issue is resolved

Do not call it if the resolution only partially helped, or if the user has not yet
confirmed success. Duplicate confirms within the same session are silently ignored —
safe to call once per entry.

### `kb_submit`

Submits a new knowledge entry for human review. The entry lands in `contributions/pending/`
and is published only after a human runs `holmes kb confirm <id>`.

```json
// Request
{
  "title": "Redis NOAUTH Error After Password Change",
  "type": "pitfall",
  "content": "## Symptoms\nAll Redis commands fail with NOAUTH...\n\n## Root Cause\n...\n\n## Resolution\n...",
  "category": "database",
  "tags": ["redis", "auth", "configuration"]
}

// Response
{
  "id": "pending-abc123",
  "status": "pending",
  "message": "Entry submitted for review. Publish with: holmes kb confirm pending-abc123"
}
```

**Call `kb_submit` only when all three conditions are met:**
1. You searched the KB and found no matching entry for the current problem
2. You successfully helped the user resolve the issue
3. The user agrees the solution is worth preserving

The `content` parameter is the entry body (Markdown sections only, without frontmatter).
Pass `title`, `type`, `category`, and `tags` as separate parameters — the server assembles
the frontmatter. After submitting, inform the user:

> "I've submitted this knowledge for review. A maintainer can publish it with:
> `holmes kb confirm <id>`"

---

## Recommended Tool Call Sequence

```
Session start
    └─► kb_overview          (once per session, learn KB vocabulary)
            │
            ▼
Problem described
    └─► kb_list              (filter by relevant type + category)
            │
            ▼
Scan titles and briefs
    └─► kb_read <id>         (one or more matching entries)
            │
            ▼
Apply guidance
            │
      ┌─────┴──────┐
      │            │
   Resolved     No match / new problem
      │            │
      ▼            ▼
   kb_confirm   (resolve first, then)
                kb_submit
```

---

## What Agents Can and Cannot Do

| Action | Tool | Notes |
|--------|------|-------|
| Read any entry | `kb_read` | No side effects |
| Browse the KB | `kb_overview`, `kb_list` | No side effects |
| Record confirmed resolution | `kb_confirm` | Writes an evidence sidecar file |
| Submit new knowledge | `kb_submit` | Lands in pending — not visible until human confirms |
| Publish or delete entries | — | Not exposed via MCP — human-only operation |
| Modify existing entries | — | Not exposed via MCP — use `holmes kb write-pending` CLI |

Evidence and submissions are the only write operations agents can perform. All structural
changes to the KB require human review through the CLI pending workflow.

---

## Integration Example

Below is a minimal Python snippet connecting to the Holmes MCP server and querying the KB.

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def query_kb(problem: str):
    async with streamablehttp_client("http://localhost:8765") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Step 1: overview
            overview = await session.call_tool("kb_overview", {})

            # Step 2: list relevant entries
            entries = await session.call_tool("kb_list", {
                "type": "pitfall",
                "category": "database",
            })

            # Step 3: read a specific entry
            entry = await session.call_tool("kb_read", {
                "entry_id": "PT-DB-001",
            })

            return entry

asyncio.run(query_kb("redis timeout"))
```
