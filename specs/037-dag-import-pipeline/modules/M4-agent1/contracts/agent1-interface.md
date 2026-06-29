# Contract: Agent 1 Public Interface

**Created**: 2026-06-24

## Entry Point

```python
# kb/holmes/kb/agent/dag/__init__.py

def run_agent1(
    source_text: str,
    file_path: Optional[Path],
    kb_root: Path,
    cfg: HolmesConfig,
    provider: LLMProvider,
    no_interactive: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    skip_edit: bool = False,
) -> ImportReport:
    """Run Agent 1 DAG extraction for a pitfall document.

    Args:
        source_text: Full, untruncated source document text.
        file_path: Optional source file path.
        kb_root: KB repository root.
        cfg: HolmesConfig (api_key, model, etc.).
        provider: Pre-created LLMProvider instance.
        no_interactive: If True, skip all user prompts (auto-select [2]).
        dry_run: If True, skip file writes.
        resume: If True, load session.json and continue loop.
        skip_edit: If True, skip [1/2/3] menu after completion.

    Returns:
        ImportReport with:
          - phase_traces: ["Agent1: X nodes, Y process nodes extracted"]
          - warnings: any issues encountered
          - errors: any fatal errors (e.g., MaxTurnsExceeded)
          - auto_decisions: "DAG 未经用户确认" when no_interactive=True
    """
```

## Tool Definitions (exposed to LLM)

### write_dag

```json
{
  "name": "write_dag",
  "description": "Write or overwrite the entire .dag.md file. Call this once with the complete three-section content.",
  "input_schema": {
    "type": "object",
    "properties": {
      "content": {
        "type": "string",
        "description": "Complete .dag.md content (all three sections)"
      }
    },
    "required": ["content"]
  }
}
```

**Returns**: `{"success": true, "path": "<hash>.dag.md"}` or `{"error": "<message>"}`

### read_dag

```json
{
  "name": "read_dag",
  "description": "Read the current .dag.md content for self-review.",
  "input_schema": {
    "type": "object",
    "properties": {}
  }
}
```

**Returns**: `{"content": "<dag_md_text>"}` or `{"error": "no DAG written yet"}`

### output_dag

```json
{
  "name": "output_dag",
  "description": "Validate the current .dag.md, generate .dag.json, and terminate the loop. Only call this when the self-check checklist is complete.",
  "input_schema": {
    "type": "object",
    "properties": {}
  }
}
```

**Returns on success**: Loop terminates — no return value seen by agent.

**Returns on validation failure**:
```json
{"error": "DAG validation failed: <specific rule failure description>"}
```

Possible error messages:
- `"至少存在一个根节点（无 parent 的节点）"`
- `"悬空边：节点 N5 引用了不存在的目标 N99"`
- `"循环引用：N3 → N8 → N3"`
- `"Process 节点 N7 既无 section_heading 也无有效 description"`
- `"节点 N4 无出边且未标记为 END"`

## Error Types

```python
class MaxTurnsExceededError(RuntimeError):
    """Raised when Agent 1 exceeds maxTurns=300."""

class DAGValidationError(ValueError):
    """Raised internally by output_dag on validation failure (returned as tool error)."""

class SessionLoadError(IOError):
    """Raised when session.json cannot be loaded on --resume."""
```

## ImportReport Fields Populated by Agent 1

| Field | Value |
|-------|-------|
| `phase_traces` | `"Agent1: {n} nodes, {p} process nodes extracted"` |
| `auto_decisions` | `"DAG 未经用户确认"` (when `no_interactive=True`) |
| `warnings` | Any `output_dag` retry errors, session load issues |
| `errors` | `MaxTurnsExceededError` message |
