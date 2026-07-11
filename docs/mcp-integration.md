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

The server exposes **four tools**.

### `kb_browse`

Directory-style browsing with pagination. Call with no params first to see the full
index (type → category → entries with briefs). Then use type/category filters to narrow.

**Call this first** at the start of any session. Save the returned `session_id` — pass it
to `kb_confirm` and `kb_draft` later in the same session.

```json
// Request — full index
{}

// Response
{
  "index": {
    "pitfall": {
      "database": [
        { "id": "PT-DB-001", "title": "Redis Connection Pool Exhausted", "maturity": "proven", "brief": "Redis maxclients too low causes connection timeout under load" }
      ],
      "network": [...]
    },
    "model": {...},
    "guideline": {...}
  },
  "total_entries": 44,
  "session_id": "a3f8c1d2",
  "hint": "Save session_id='a3f8c1d2'. Scan titles and briefs to find relevant entries. Call kb_read(entry_id=...) to read any entry."
}

// Request — filter by type and category
{ "type": "pitfall", "category": "database", "page": 1 }
```

Pagination: 50 entries per page. Entries are sorted by maturity (proven first).

### `kb_read`

Progressive disclosure: returns a structured summary by default. Drill into full
content, specific sections, or individual resolution branches on demand.

**Detail levels** (mutually exclusive):

| `detail` | Returns |
|-----------|---------|
| `"summary"` (default) | Structured summary: brief, key facts, Contents (table of sections) |
| `"navigate"` | Contents section only — the structural roadmap |
| `"full"` | Complete document body with all sections |

**Section/branch navigation:**

| Parameter | Purpose |
|-----------|---------|
| `section` | Read a specific `## section` by name (e.g. `"Root Cause"`, `"Steps"`) |
| `branch` | Read a specific `### resolution branch` by label (e.g. `"电源子系统"`) |

```json
// Request — summary (default)
{ "entry_id": "PT-DB-001" }

// Response
{
  "id": "PT-DB-001",
  "type": "pitfall",
  "maturity": "proven",
  "brief": "Redis maxclients too low causes connection timeout under load",
  "summary": "## Symptoms\nUsers report Redis operations timing out...\n\n## Contents\n- Symptoms\n- Root Cause\n- Resolution",
  "hint": "Use kb_read(entry_id='PT-DB-001', section='Resolution') to read a specific section, or kb_read(entry_id='PT-DB-001', detail='full') for the complete entry."
}

// Request — specific section
{ "entry_id": "PT-DB-001", "section": "Resolution" }

// Request — specific branch (pitfall with multiple resolution branches)
{ "entry_id": "PT-HW-003", "branch": "电源子系统" }

// Request — full content (also records a lightweight reference for decay timer)
{ "entry_id": "PT-DB-001", "detail": "full", "session_id": "a3f8c1d2" }
```

**Behavior tags** in resolution steps tell the agent how to handle each step:

| Tag | Meaning |
|-----|---------|
| `[api:read]` | Read-only command, safe to auto-execute |
| `[api:write]` | State-changing command, inform user first |
| `[api:danger]` | Irreversible command (firmware flash, disk format) — MUST get user confirmation |
| `[physical]` | Ask user to perform physical action (check LED, reseat module) |
| `[remote]` | Execute on a remote system (BMC, switch, management plane) |
| `[decide]` | Ask user which condition they observe, then branch accordingly |
| `[verify]` | Check the previous step's result — confirms diagnosis or loops back |

**Evidence lifecycle**: calling `kb_read` with `detail="full"` records a lightweight
`referenced` evidence sidecar that resets the entry's decay timer. Only an explicit
`kb_confirm(outcome="solved")` promotes maturity.

### `kb_confirm`

Records the outcome after using a KB entry. Only `"solved"` promotes maturity;
`"not_solved"` is neutral feedback.

```json
// Request
{ "entry_id": "PT-DB-001", "session_id": "a3f8c1d2", "outcome": "solved" }

// Response — success
{
  "ok": true,
  "entry_id": "PT-DB-001",
  "maturity": "proven",
  "promoted": true,
  "contributor": "user@example.com"
}

// Response — duplicate (same session already confirmed this entry)
{ "ok": false, "reason": "duplicate", "entry_id": "PT-DB-001" }
```

**Call `kb_confirm` only when all three conditions are met:**
1. You read the entry during the current session
2. You applied its guidance (executed steps, etc.)
3. The user has explicitly confirmed the issue is resolved

Pass the `session_id` returned by `kb_browse`.

### `kb_draft`

Saves a raw draft document for later import — **no LLM processing**. The draft is
saved as-is to `_drafts/`; a human engineer runs `holmes import _drafts/<file>` to
structure it into a KB entry.

```json
// Request
{
  "content": "We had Redis OOM eviction causing cache misses. Symptoms: high memory usage alarm, evicted_keys counter increasing. Root cause: maxmemory set too low for dataset size. Resolution: increased maxmemory to 4gb in redis.conf and restarted.",
  "title": "redis-oom-2026-06-23",
  "session_id": "a3f8c1d2"
}

// Response
{
  "ok": true,
  "path": "_drafts/redis-oom-2026-06-23.md",
  "hint": "Draft saved. Run 'holmes import _drafts/redis-oom-2026-06-23.md' to structure it into a KB entry."
}
```

**Call `kb_draft` only when all three conditions are met:**
1. You browsed the KB and found no matching entry for this problem
2. You successfully helped the user resolve the issue
3. The user agrees the solution is worth preserving

---

## Recommended Tool Call Sequence

```
Session start
    └─► kb_browse              (once per session — save session_id)
            │
            ▼
Scan titles and briefs
    └─► kb_read <entry_id>     (summary — identify relevant sections)
            │
            ▼ need more detail?
    └─► kb_read section=...    (read specific section)
    └─► kb_read branch=...     (read specific resolution branch)
    └─► kb_read detail=full    (full content — also records reference)
            │
            ▼
Apply guidance
            │
      ┌─────┴──────┐
      │            │
   Resolved     No match / new problem
      │            │
      ▼            ▼
   kb_confirm   kb_draft
   (solved)     (content for later import)
```

---

## What Agents Can and Cannot Do

| Action | Tool | Notes |
|--------|------|-------|
| Browse the KB (directory-style) | `kb_browse` | No side effects; returns index with briefs |
| Read entry summary | `kb_read` | No side effects |
| Read full entry content | `kb_read(detail=full)` | Records lightweight reference (resets decay timer) |
| Read specific section/branch | `kb_read(section=...)` | No side effects |
| Record confirmed resolution | `kb_confirm(solved)` | Writes evidence sidecar, may promote maturity |
| Record unsuccessful attempt | `kb_confirm(not_solved)` | Neutral — recorded but does not affect maturity |
| Save a draft for later import | `kb_draft` | Saved to `_drafts/` — not visible until `holmes import` |
| Publish or delete entries | — | Not exposed via MCP — human-only (`holmes approve` / `holmes delete`) |
| Modify existing entries | — | Not exposed via MCP |

Evidence sidecars and drafts are the only write operations agents can perform. All structural
changes to the KB require human review through the CLI.

---

## Integration Example

Minimal Python snippet connecting to the Holmes MCP server:

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def query_kb(problem: str):
    async with streamablehttp_client("http://localhost:8765") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Step 1: browse — save session_id
            browse = await session.call_tool("kb_browse", {})
            session_id = browse.content[0].text  # parse JSON for session_id

            # Step 2: read summary of a matching entry
            summary = await session.call_tool("kb_read", {
                "entry_id": "PT-DB-001",
            })

            # Step 3: drill into the resolution section
            resolution = await session.call_tool("kb_read", {
                "entry_id": "PT-DB-001",
                "section": "Resolution",
            })

            # Step 4: after confirming resolution with user
            await session.call_tool("kb_confirm", {
                "entry_id": "PT-DB-001",
                "session_id": session_id,
                "outcome": "solved",
            })

asyncio.run(query_kb("redis out of memory eviction"))
```
