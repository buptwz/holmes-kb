# Data Model: M4 — Agent 1 DAG Extraction Harness

**Created**: 2026-06-24

## Entities

### DAGNode

Single node in the troubleshooting tree.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | str | YES | Node identifier (e.g., "N1", "N7") |
| `description` | str | YES | One-sentence description of the node |
| `node_type` | NodeType enum | YES | `human_observation` / `api_call` / `decision` / `action` |
| `complexity` | Complexity enum | YES | `simple` / `process` |
| `section_heading` | Optional[str] | NO | Source document heading (e.g., `"### 固件修复步骤"`) |
| `is_end` | bool | NO | True if this node is a terminal END node |
| `children` | list[DAGEdge] | YES | Outgoing edges (empty list for END nodes) |

**Validation rules**:
- `process` nodes: must have `section_heading` OR non-empty `description`
- `is_end=True` nodes: `children` must be empty
- `is_end=False` nodes: `children` must be non-empty

---

### DAGEdge

Directed edge from a parent node to a target node.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `condition` | str | YES | Trigger condition text (e.g., "红色闪烁") |
| `target` | str | YES | Target node ID |
| `is_back_edge` | bool | NO | True for back-edges (cycle-breaking markers) |

**Validation rules**:
- `target` must reference an existing `DAGNode.id` in the parent `DAGGraph`
- `is_back_edge=True` edges are excluded from cycle detection

---

### DAGGraph

The complete troubleshooting tree extracted from one source document.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `nodes` | list[DAGNode] | YES | All nodes in the graph |
| `title` | str | YES | Human-readable tree title |
| `source_file` | str | YES | Relative path of the source document |
| `generated` | str | YES | ISO date string (YYYY-MM-DD) |

**Validation rules** (enforced by `output_dag`):
1. At least one root node (node not referenced as any edge's `target`)
2. All edge targets exist in `nodes`
3. No cycles (excluding `is_back_edge=True` edges)
4. All `process` nodes have `section_heading` or non-empty `description`
5. All non-END nodes have at least one outgoing edge (`is_end=False` → `children` non-empty)

**Multi-root**: Multiple root nodes are allowed (`multi_incident` documents). Each root must be able to reach at least one END node.

---

### Agent1Session

Crash recovery snapshot written every 20 turns.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_hash` | str | YES | 16-char SHA-256 prefix of the source document |
| `source_file` | str | NO | Relative path of the source document (for display) |
| `turn_count` | int | YES | Number of LLM turns completed at snapshot time |
| `messages` | list[Any] | YES | Complete message history (provider-compatible format) |

**Storage**: `_import-state/<source_hash>.session.json`

---

## State Transitions

### `.dag.md` lifecycle

```
[not exists]
    → write_dag() called (Phase 2 draft)
[.dag.md exists, in-progress]
    → write_dag() called again (Phase 3 review updates)
[.dag.md exists, validated]
    → output_dag() succeeds → .dag.json written
[.dag.md + .dag.json exist]
    → menu shown → user chooses [1/2/3]
[user edits via [1]]
    → .dag.md modified externally
[user resumes via --resume]
    → Step 2.5 parses .dag.md
```

### `session.json` lifecycle

```
[not exists]
    → loop starts fresh
[session.json exists, turn_count < 300]
    → --resume: load messages, continue from turn_count
[session.json exists, output_dag validated]
    → session.json kept for audit; not used for resume
```

---

## File System Layout

```
<kb_root>/
  _import-state/
    <source_hash>.dag.md       # Human-readable DAG (Agent 1 output, user-editable)
    <source_hash>.dag.json     # Machine-readable DAGGraph (output_dag output)
    <source_hash>.session.json # Crash recovery snapshot (every 20 turns)
```

All three files are tracked by git (state persists across sessions and is shareable).

---

## Enumerations

### NodeType

```python
class NodeType(str, Enum):
    human_observation = "human_observation"
    api_call = "api_call"
    decision = "decision"
    action = "action"
```

### Complexity

```python
class Complexity(str, Enum):
    simple = "simple"
    process = "process"
```
