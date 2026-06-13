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

The server exposes **six tools**.

### `kb_overview`

Returns KB structure, generates a `session_id` for this session, and hints at next steps.

**Call this first** at the start of any session. Save the returned `session_id` — pass it
to `kb_confirm` and `kb_submit` later in the same session.

```json
// Response
{
  "entries": { "pitfall": 28, "model": 6, "guideline": 5, "process": 3, "decision": 2 },
  "skill_count": 4,
  "categories": ["application", "cache", "database", "network", "system"],
  "top_tags": ["redis", "postgres", "nginx", "timeout", "memory"],
  "session_id": "a3f8c1d2",
  "hint": "Save session_id='a3f8c1d2' — pass it to kb_confirm and kb_submit. Next: call kb_search(query=...) to find entries by keyword, or kb_list(type=...) to browse. Valid type values: pitfall|model|guideline|process|decision|skill."
}
```

### `kb_list`

Lists entries or skills with pagination, filtered by type and/or category.

```json
// Request — entries
{ "type": "pitfall", "category": "database", "limit": 20, "offset": 0 }

// Response
{
  "entries": [
    { "id": "PT-DB-001", "title": "Redis Connection Pool Exhausted", "maturity": "proven", "brief": "..." },
    { "id": "PT-DB-002", "title": "PostgreSQL Autovacuum Blocking Writes", "maturity": "verified", "brief": "..." }
  ],
  "total": 8,
  "offset": 0,
  "limit": 20,
  "hint": "Call kb_read(id=<entry_id>) to read the full content of any entry."
}
```

```json
// Request — skills
{ "type": "skill" }

// Response
{
  "entries": [
    { "id": "redis-oom-recovery", "description": "Steps to recover from Redis OOM eviction" },
    { "id": "nginx-reload", "description": "Safely reload nginx config without downtime" }
  ],
  "total": 4,
  "hint": "Call kb_read(id=<skill_name>) to read the full SKILL.md and linked entries."
}
```

`category` is silently ignored when `type="skill"`.

### `kb_search`

Full-text keyword search across all entries, ranked by relevance. Skills are not included
in the search index — use `kb_list(type="skill")` to browse skills.

```json
// Request
{ "query": "Redis OOM eviction", "limit": 10 }

// Optional: filter by type
{ "query": "connection timeout", "type": "pitfall", "limit": 5 }

// Response — results found
{
  "items": [
    { "id": "PT-DB-001", "title": "Redis OOM Eviction Under Load", "type": "pitfall", "maturity": "proven", "score": 0.87, "brief": "Redis evicts keys when maxmemory is reached..." },
    { "id": "PT-CACHE-003", "title": "Redis Key TTL Expiry Storm", "type": "pitfall", "maturity": "verified", "score": 0.62, "brief": "..." }
  ],
  "total": 2,
  "hint": "Call kb_read(id=<entry_id>) to read the full content of any result. Check skill_refs in the entry response to navigate to related skills."
}

// Response — no results
{
  "items": [],
  "total": 0,
  "hint": "No results found. Try kb_list(type='pitfall'|'model'|'guideline'|'process'|'decision') to browse by type, or broaden your search terms."
}
```

### `kb_read`

Returns the full content of an entry, a skill's SKILL.md, or a skill subfile.
**ID routing is automatic** — no need to specify a type:

| `id` format | `path` | Returns |
|---|---|---|
| Entry ID (`PT-DB-001`) | omitted | Full entry Markdown + `skill_refs` list |
| Skill name (`redis-oom-recovery`) | omitted | SKILL.md body + `linked_entries` + `files` list |
| Skill name | `"scripts/check.sh"` | Text content of that subfile |
| Entry ID | any | Error — `path` is only valid for skills |

```json
// Request — entry
{ "entry_id": "PT-DB-001" }

// Response
{
  "id": "PT-DB-001",
  "type": "pitfall",
  "maturity": "proven",
  "content": "---\nid: PT-DB-001\n...\n---\n\n## Symptoms\n...",
  "skill_refs": ["redis-oom-recovery"],
  "hint": "This entry links to 1 skill(s). Call kb_read(id=<skill_name>) to read any skill's instructions and files."
}
```

```json
// Request — skill
{ "entry_id": "redis-oom-recovery" }

// Response
{
  "id": "redis-oom-recovery",
  "type": "skill",
  "description": "Steps to recover from Redis OOM eviction",
  "content": "## When to Use\n...\n\n## Resolution Steps\n...",
  "linked_entries": ["PT-DB-001"],
  "files": ["scripts/check-memory.sh", "scripts/flush-expired.sh"],
  "hint": "Linked entries: ['PT-DB-001']. Call kb_read(id=<entry_id>) to read them. Skill files available. Call kb_read(id='redis-oom-recovery', path='<file>') to read any file."
}
```

```json
// Request — skill subfile
{ "entry_id": "redis-oom-recovery", "path": "scripts/check-memory.sh" }

// Response
{
  "id": "redis-oom-recovery",
  "path": "scripts/check-memory.sh",
  "content": "#!/bin/bash\nredis-cli INFO memory | grep used_memory_human\n..."
}
```

Only text files are accessible via `path` (`.sh`, `.py`, `.md`, `.yaml`, `.json`, etc.).
Binary files are filtered out of `files` listings and cannot be read.

### `kb_confirm`

Records that an entry successfully helped resolve the current issue. Writes an evidence
sidecar that updates the entry's maturity score.

```json
// Request
{ "entry_id": "PT-DB-001", "session_id": "a3f8c1d2" }

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

// Response — wrong ID type
{
  "ok": false,
  "reason": "not_an_entry",
  "hint": "'redis-oom-recovery' is not a valid entry ID. Pass a valid entry ID (e.g. PT-DB-001), not a skill name."
}
```

**Call `kb_confirm` only when all three conditions are met:**
1. You read the entry during the current session
2. You applied its guidance (executed steps, ran the skill, etc.)
3. The user has explicitly confirmed the issue is resolved

Do not call it if the resolution was partial or the user has not confirmed.
Pass the `session_id` returned by `kb_overview` — this isolates dedup across parallel sessions.

### `kb_submit`

Submits a natural-language problem description for automatic KB entry generation.
The content is processed by the full import pipeline (same as `holmes import`):
classifier → extractor → normalizer → dedup check → reader → skill advisor.

The entry lands in `contributions/pending/` and is published only after a human runs
`holmes kb confirm <id>`. This tool may take 30-120 seconds — configure client timeout ≥ 180s.

```json
// Request
{
  "content": "We had Redis OOM eviction causing cache misses. Symptoms: high memory usage alarm, evicted_keys counter increasing. Root cause: maxmemory set too low for dataset size. Resolution: increased maxmemory to 4gb in redis.conf and restarted. Also ran redis-cli FLUSHDB on stale namespaces to recover headroom.",
  "session_id": "a3f8c1d2"
}

// Response — success
{
  "id": "pending-20240315-143022-a7bk",
  "status": "pending",
  "message": "Submitted 'Redis OOM Eviction Under Load' for review. Publish with: holmes kb confirm pending-20240315-143022-a7bk"
}

// Response — content too short
{
  "error": "Content too short (23 chars). Minimum is 50 characters. Provide a full description of the problem and solution.",
  "status": "rejected"
}

// Response — duplicate detected (pipeline found matching existing entry)
{
  "status": "duplicate",
  "existing_id": "PT-DB-001",
  "existing_title": "Redis OOM Eviction Under Load",
  "hint": "A similar entry already exists. Use kb_confirm(entry_id='PT-DB-001', session_id='a3f8c1d2') to record that it helped you."
}
```

**Call `kb_submit` only when all three conditions are met:**
1. You searched/browsed the KB and found no matching entry for this problem
2. You successfully helped the user resolve the issue
3. The user agrees the solution is worth preserving

After submitting, inform the user: *"Submitted for review. Publish with: `holmes kb confirm <id>`"*

---

## Recommended Tool Call Sequence

```
Session start
    └─► kb_overview          (once per session — save session_id)
            │
            ▼
Problem described
    ├─► kb_search            (keyword search — fastest discovery path)
    │       │
    │       ▼ no results?
    └─► kb_list              (browse by type/category)
            │
            ▼
Scan results / titles
    └─► kb_read <entry_id>   (full entry + skill_refs)
            │
            ▼ skill_refs present?
    └─► kb_read <skill_name> (SKILL.md + files)
            │
            ▼ files present?
    └─► kb_read <skill_name> path=<file>   (subfile content)
            │
            ▼
Apply guidance
            │
      ┌─────┴──────┐
      │            │
   Resolved     No match / new problem
      │            │
      ▼            ▼
   kb_confirm   kb_submit
   (session_id) (content + session_id)
```

---

## What Agents Can and Cannot Do

| Action | Tool | Notes |
|--------|------|-------|
| Read any entry | `kb_read` | No side effects |
| Read any skill and its files | `kb_read` | No side effects |
| Browse the KB | `kb_overview`, `kb_list` | No side effects |
| Search by keyword | `kb_search` | No side effects |
| Record confirmed resolution | `kb_confirm` | Writes evidence sidecar, may promote maturity |
| Submit new knowledge | `kb_submit` | Lands in pending — not visible until human confirms |
| Publish or delete entries | — | Not exposed via MCP — human-only operation |
| Modify existing entries | — | Not exposed via MCP — use `holmes kb write-pending` CLI |

Evidence and submissions are the only write operations agents can perform. All structural
changes to the KB require human review through the CLI pending workflow.

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

            # Step 1: overview — save session_id
            overview = await session.call_tool("kb_overview", {})
            session_id = overview.content[0].text  # parse JSON for session_id

            # Step 2: search by symptom keywords
            results = await session.call_tool("kb_search", {
                "query": problem,
                "limit": 5,
            })

            # Step 3: read the top result
            entry = await session.call_tool("kb_read", {
                "entry_id": "PT-DB-001",
            })

            # Step 4: if entry has skill_refs, read the skill
            skill = await session.call_tool("kb_read", {
                "entry_id": "redis-oom-recovery",
            })

            # Step 5: after confirming resolution with user
            await session.call_tool("kb_confirm", {
                "entry_id": "PT-DB-001",
                "session_id": session_id,
            })

asyncio.run(query_kb("redis out of memory eviction"))
```
