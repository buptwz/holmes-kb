# Agent 2 Tool Interface Contract

**Module**: `kb/holmes/kb/agent/dag/tools2.py`

All tool handlers follow the same calling convention as tools1.py:
```python
handler(ctx: dict, tool_input: dict) -> dict
```

---

## read_dag()

**Input**: `{}` (no parameters)

**Returns (success)**:
```json
{
  "title": "排查树标题",
  "nodes": [...],
  "entry_ids": {"N1": "slug-N1-001", "root": "slug-root-001"},
  "import_seq": "001"
}
```

**Returns (error)**:
```json
{"error": "read_dag: .dag.json not found"}
```

---

## write_entry(entry_id, content)

**Input**:
```json
{
  "entry_id": "hardware-init-failure-N3-001",
  "content": "---\ntitle: ...\n---\n\n## Steps\n..."
}
```

**Built-in validation** (before write):
1. Required frontmatter fields present and non-empty
2. Required sections present (Symptoms/Root Cause/Resolution for pitfall; Steps for process)
3. All `child_entry_ids` items exist in `entry_ids` table
4. `parent_id` (if set) exists in `entry_ids` table

**Returns (success)**:
```json
{"success": true, "path": "_pending/process/hardware/hardware-init-failure-N3-001.md"}
```

**Returns (validation error)**:
```json
{"error": "write_entry: missing required field 'description'"}
```

**Returns (content_source warning)** — written to pending but with warning:
```json
{"success": true, "warning": "content_source: description_match_failed", "path": "..."}
```

---

## read_entry(entry_id)

**Input**:
```json
{"entry_id": "hardware-init-failure-N3-001"}
```

**Returns (success)**:
```json
{
  "title": "固件修复流程",
  "content": "---\n...\n---\n\n## Steps\n...",
  "frontmatter": {"title": "...", "type": "process", ...}
}
```

**Returns (error)**:
```json
{"error": "read_entry: entry not found: hardware-init-failure-N3-001"}
```

---

## finalize()

**Input**: `{}` (no parameters)

**Side effects**:
1. Run 7 lint rules against all written entries
2. Set `ctx["_terminate"] = True` to signal harness loop exit
3. Populate `ctx["lint_results"]` with list of LintResult

**Returns (success)**:
```json
{
  "_terminate": true,
  "success": true,
  "lint_passed": 6,
  "lint_failed": 1,
  "lint_errors": ["tree_completeness: DAG node N9 has no corresponding entry"]
}
```

---

## Read(path, offset, limit)

Reuses `tools1.tool_read` — same interface as Agent 1.

---

## Grep(pattern, path, context_lines)

Reuses `tools1.tool_grep` — same interface as Agent 1.

---

## Whitelist

Only these 6 tool names are allowed. All others return:
```json
{"error": "tool not allowed: <name>"}
```
