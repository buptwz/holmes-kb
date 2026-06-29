# Research: M4 — Agent 1 DAG Extraction Harness

**Created**: 2026-06-24

## R-01: Agent Loop Architecture (claude-code reference)

**Decision**: Python `Agent1Harness._run_loop()` mirrors the TypeScript `query.ts` pattern from claude-code:
- Single `messages: list[Any]` array threaded through every turn
- Each turn: `provider.complete()` → parse tool_use blocks → execute tools → `provider.append_tool_results()` → check stop
- Turn counter incremented every iteration; `maxTurns` checked before `provider.complete()`

**Rationale**: The existing `ThreePhaseImportPipeline._run_extraction_loop()` already uses this pattern. Agent 1 reuses it with two differences: (a) 5-tool whitelist check before dispatch, (b) crash recovery snapshot every 20 turns.

**Alternatives considered**: Async loop — rejected because the CLI is synchronous and `LLMProvider` is synchronous.

---

## R-02: Tool Whitelist Implementation

**Decision**: `harness1.py` defines `_ALLOWED_TOOLS = {"Read", "Grep", "write_dag", "read_dag", "output_dag"}`. In `_execute_tool(name, input_)`, if `name not in _ALLOWED_TOOLS`, return `{"error": "tool not allowed: {name}"}` immediately without calling any handler.

**Rationale**: Simple `set` lookup is O(1) and physically prevents capability leakage. Matches `tools.ts` CORE_TOOLS pattern from claude-code.

**Alternatives considered**: Role-based permissions — overcomplicated for a single-agent harness.

---

## R-03: output_dag Validation — Cycle Detection

**Decision**: After parsing the `.dag.md` into a `DAGGraph`, run DFS cycle detection on the edge graph. If a cycle is found, include the cycle path (e.g., "N3 → N8 → N3") in the error message. The system prompt instructs the agent to mark one back-edge in the description and remove it from the structure.

**Rationale**: Topological sort (Kahn's algorithm) already produces cycle detection as a side effect. Simple and well-understood.

**Alternatives considered**: Floyd-Warshall — unnecessarily expensive for small DAGs (≤100 nodes).

---

## R-04: Crash Recovery Format

**Decision**: `session.json` stores:
```json
{
  "source_hash": "<16-char hash>",
  "source_file": "<relative path>",
  "turn_count": <int>,
  "messages": [...]
}
```
Written via `atomic_write()` every 20 turns (overwrite). On `--resume`, the harness reads this file, restores `messages`, and resumes the loop from `turn_count`.

**Rationale**: Full message serialization is the simplest correct approach for resumption. The 20-turn cadence limits crash loss to at most 20 turns of LLM cost.

**Alternatives considered**: Delta-log approach — more complex, no benefit for typical document sizes.

---

## R-05: .dag.md Format Parsing

**Decision**: `formatter.py` uses regex-based section parsing:
1. Split on `## 节点详情` to separate the overview sections from node detail blocks.
2. Each node block starts with `### N\d+ —` (or any ID pattern); parse `complexity:`, `node_type:`, `section_heading:` as key-value lines.
3. Edge lines match pattern `- <condition> → **<target>**` (with optional 🔧).
4. `markdown_to_dag()` is lenient on whitespace/formatting (user-edited files may have variations).

**Rationale**: LLM output and user edits may not be perfectly formatted. A lenient regex parser is more robust than strict YAML/JSON parsing.

**Alternatives considered**: Require strict YAML frontmatter for node definitions — rejected because it defeats the "user-editable" design goal.

---

## R-06: Read and Grep Tool Integration

**Decision**: Agent 1 uses the existing `DOC_ACCESS_TOOL_DEFINITIONS` and `DOC_ACCESS_TOOL_HANDLERS` from `agent/doc_access.py` for `Read` and `Grep`. The harness passes `source_file` and `source_text` in `ctx` so these tools can serve document content.

**Rationale**: Reuse the existing doc-access tools rather than re-implement. The same tools work for Agent 2 as well.

**Alternatives considered**: Pass source_text directly in messages — impractical for large documents (>8000 chars) and prevents targeted re-reading.

---

## R-07: HolmesLogger Span Recording

**Decision**: The harness detects phase transitions by tracking whether `write_dag` has been called yet (Phase 1 → Phase 2 boundary) and counting subsequent `read_dag` calls (Phase 3 review rounds). Each phase boundary closes the current span and opens a new one.

**Rationale**: Matches M8 HolmesLogger interface. If M8 is not yet merged, spans are no-ops (guard with `try/except ImportError`).

**Alternatives considered**: Instrument via LLM response parsing — fragile and overly complex.

---

## R-08: Interactive Menu Implementation

**Decision**: After `output_dag` succeeds and `.dag.json` is written, display:
```
DAG 已提取（X 个节点，Y 个 process 节点）。
已保存到 _import-state/<hash>.dag.md

选择：
  [1] 现在编辑（打开编辑器，完成后按 Enter 继续）
  [2] 不需要编辑，直接生成
  [3] 稍后处理（退出后运行 holmes import --resume）
```
Implementation: `click.prompt()` for input; `click.edit()` for option [1]. `--no-interactive` skips to [2]. `--skip-edit` also skips to [2].

**Rationale**: Follows the blueprint spec exactly. `click` is already a dependency.

---

## R-09: --resume Multi-State Selection

**Decision**: `holmes import --resume` without a `--source` path scans `_import-state/*.session.json`, presents a numbered list if multiple exist, and lets the user pick. Parses the `source_file` from each JSON to show a human-readable label.

**Rationale**: Engineers may have multiple in-flight imports; selection UI prevents accidental resumption of wrong state.

---

## R-10: _run_dag_pipeline() Integration

**Decision**: Replace `raise NotImplementedError("DAG pipeline (M4)")` with:
```python
from holmes.kb.agent.dag import run_agent1
return run_agent1(
    source_text=source_text,
    file_path=file_path,
    kb_root=self.kb_root,
    cfg=self.cfg,
    provider=self._provider,
    no_interactive=self.no_interactive,
    dry_run=self.dry_run,
)
```
`run_agent1()` is the top-level entry point exported from `dag/__init__.py`.

**Rationale**: Clean single-function interface keeps `pipeline.py` changes minimal and respects the open/closed principle.
