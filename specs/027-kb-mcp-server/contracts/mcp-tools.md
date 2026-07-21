# MCP Tool Contracts

Server started with `holmes start --kb-path <path> --port 8765`.
Client config: `{"url": "http://localhost:8765"}`.

---

## kb_overview

**Description**:
Get a structural overview of the knowledge base — available entry types, categories, and frequently used tags.

You MUST call `kb_overview` at the start of any session in which you may need KB knowledge, before deciding which category to browse. This gives you the vocabulary and scope of what's available so you can formulate accurate follow-up calls to `kb_list`. Do NOT skip this call and jump directly to `kb_list` with a guessed category — you may miss relevant entries entirely.

**Input**: None

**Output**:
```json
{
  "total": 45,
  "types": {
    "pitfall": 23,
    "model": 5,
    "guideline": 8,
    "process": 6,
    "decision": 3
  },
  "categories": ["database", "network", "cache", "kubernetes", "application"],
  "top_tags": ["redis", "mysql", "connection-pool", "oom", "timeout"]
}
```

---

## kb_list

**Description**:
List knowledge entries filtered by type and/or category, with brief content previews.

You MUST call `kb_list` after `kb_overview` to browse entries in a relevant category. Scan the returned titles and briefs to identify which entries match the current problem — do NOT read every entry blindly. When the list is long, use `limit` and `offset` to paginate. You MUST call `kb_read` on the specific entry before presenting its guidance to the user.

**Input**:
```json
{
  "type": "pitfall",        // optional: pitfall|model|guideline|process|decision
  "category": "database",   // optional
  "limit": 20,              // optional, default 20, max 100
  "offset": 0               // optional, default 0
}
```

**Output**:
```json
{
  "entries": [
    {
      "id": "PT-DB-001",
      "title": "连接池耗尽导致请求堆积",
      "type": "pitfall",
      "category": "database",
      "maturity": "proven",
      "brief": "## Symptoms\n大量请求超时，日志出现 too many connections..."
    }
  ],
  "total": 23,
  "offset": 0,
  "limit": 20
}
```

---

## kb_read

**Description**:
Read the complete content of a KB entry by ID. Returns the full Markdown including all sections (Symptoms, Root Cause, Resolution for pitfalls; Steps for processes; script code for skills).

You MUST call `kb_read` before using any entry's guidance — never act on just the brief from `kb_list`. For skill entries, the content will contain executable script code: you MUST create the script locally and execute it yourself using your bash capability; do NOT ask the user to run it manually unless the script requires credentials or elevated permissions you cannot access.

This tool does NOT record any evidence. Reading an entry is not a signal of its usefulness. You MUST call `kb_confirm` separately after the entry has demonstrably helped resolve the issue.

**Input**:
```json
{
  "entry_id": "PT-DB-001"
}
```

**Output**:
```json
{
  "id": "PT-DB-001",
  "type": "pitfall",
  "maturity": "proven",
  "content": "---\nid: PT-DB-001\n...\n## Symptoms\n...\n## Resolution\n..."
}
```

**Error**:
```json
{ "error": "Entry not found: PT-DB-001" }
```

---

## kb_confirm

**Description**:
Record that a KB entry successfully helped resolve the current issue. This writes a validated evidence record that improves the entry's maturity score and elevates it in future search results.

You MUST call `kb_confirm` when ALL of the following are true:
1. You called `kb_read` on this entry during the current session
2. You applied the entry's guidance (executed steps, ran the skill script, etc.)
3. The user has explicitly confirmed that the issue is now resolved

You MUST NOT call `kb_confirm` if:
- The user has not yet confirmed the issue is resolved
- You read the entry but decided it was not relevant
- The resolution steps failed or only partially helped

For skill entries: if the skill script executed successfully AND the user confirms the outcome is correct, you MUST call `kb_confirm` immediately without waiting for further prompting.

Duplicate confirms within the same server session are silently ignored — safe to call once per entry per session.

**Input**:
```json
{
  "entry_id": "PT-DB-001"
}
```

**Output** (success):
```json
{
  "ok": true,
  "entry_id": "PT-DB-001",
  "maturity": "verified",
  "promoted": true,
  "contributor": "engineer@example.com"
}
```

**Output** (duplicate):
```json
{
  "ok": false,
  "reason": "duplicate",
  "entry_id": "PT-DB-001"
}
```

---

## kb_submit

**Description**:
Submit a new knowledge entry for human review when you have encountered a problem pattern that is NOT already in the KB.

You MUST call `kb_submit` when ALL of the following are true:
1. You searched or browsed the KB and found no matching entry for the current problem
2. You successfully helped the user resolve the issue
3. The user agrees the solution is worth preserving

You MUST NOT call `kb_submit` if a similar entry already exists — use `kb_confirm` on the existing entry instead. Do NOT submit low-quality, incomplete, or speculative entries. The content MUST include clear Symptoms, Root Cause, and Resolution sections for pitfall entries.

After submitting, inform the user: "I've submitted this knowledge for review. A maintainer can publish it with: `holmes kb confirm <id>`"

**Input**:
```json
{
  "title": "Redis 内存碎片率过高导致 OOM",
  "type": "pitfall",
  "content": "## Symptoms\n...\n## Root Cause\n...\n## Resolution\n...",
  "category": "cache",
  "tags": ["redis", "memory", "oom"]
}
```

**Output**:
```json
{
  "id": "pending-20260611-143022-a3b4",
  "status": "pending",
  "message": "Entry submitted for review. Publish with: holmes kb confirm pending-20260611-143022-a3b4"
}
```
