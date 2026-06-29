# Feature Specification: M4 — Agent 1 DAG Extraction Harness

**Feature Branch**: `dev-M4`

**Created**: 2026-06-24

**Status**: Draft

**Input**: Agent 1 complete harness for DAG extraction from pitfall documents.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single-Document DAG Extraction (Priority: P1)

An engineer runs `holmes import doc.md` on a pitfall troubleshooting document. The system automatically runs Agent 1, which reads the document in three phases (study → draft → review), produces a `.dag.md` file with a human-readable troubleshooting tree, then presents an interactive menu asking whether to edit, skip, or defer.

**Why this priority**: Core Agent 1 functionality. All other stories depend on it.

**Independent Test**: Run `holmes import hardware-failure.md` on a sample pitfall doc; verify `_import-state/<hash>.dag.md` is created with all three sections (文档摘要, 排查树概览, 节点详情) and the interactive menu appears.

**Acceptance Scenarios**:

1. **Given** a pitfall document, **When** `holmes import doc.md` is run, **Then** Agent 1 produces `_import-state/<hash>.dag.md` with three sections and an interaction menu is shown.
2. **Given** Agent 1 completes, **When** user selects `[1]`, **Then** editor opens on the `.dag.md` file.
3. **Given** Agent 1 completes, **When** user selects `[2]`, **Then** pipeline proceeds to Step 2.5 without editing.
4. **Given** Agent 1 completes, **When** user selects `[3]`, **Then** process exits with state preserved in `_import-state/`.

---

### User Story 2 - Tool Whitelist Enforcement (Priority: P1)

Agent 1 is constrained to exactly five tools: `Read`, `Grep`, `write_dag`, `read_dag`, `output_dag`. Any attempt to call any other tool (e.g., `write_kb_entry`) is immediately rejected with an error message returned to the agent, without halting the loop.

**Why this priority**: Security constraint — Agent 1 must be physically unable to write KB entries or modify files outside `_import-state/`.

**Independent Test**: Inject a tool call to `write_kb_entry` during a test run; verify the harness returns `{"error": "tool not allowed"}` and the loop continues.

**Acceptance Scenarios**:

1. **Given** Agent 1 is running, **When** it calls a non-whitelisted tool, **Then** the harness returns `{"error": "tool not allowed"}` without executing the tool.
2. **Given** Agent 1 is running, **When** it calls any of the 5 whitelisted tools, **Then** the call executes normally.

---

### User Story 3 - output_dag Validation (Priority: P1)

When Agent 1 calls `output_dag()`, the harness validates the current `.dag.md` against 5 structural rules. If any rule fails, `output_dag` returns a descriptive error and Agent 1 must fix the issue and retry. Only when all 5 rules pass does the harness generate `.dag.json`, terminate the loop, and show the interactive menu.

**Why this priority**: Guarantees structural correctness before proceeding to Step 2.5/Agent 2.

**Independent Test**: Create a `.dag.md` missing a root node; call `output_dag`; verify error returned and loop does not terminate.

**Acceptance Scenarios**:

1. **Given** a DAG with no root node, **When** `output_dag` is called, **Then** error returned: "至少存在一个根节点".
2. **Given** a DAG with a dangling edge (target node doesn't exist), **When** `output_dag` is called, **Then** error returned describing the missing node.
3. **Given** a DAG with a cycle (N3→N8→N3), **When** `output_dag` is called, **Then** error returned with the cycle path.
4. **Given** a process node with empty description and no section_heading, **When** `output_dag` is called, **Then** error returned.
5. **Given** a node with no outgoing edges and not marked END, **When** `output_dag` is called, **Then** error returned.
6. **Given** a valid DAG passing all 5 rules, **When** `output_dag` is called, **Then** `.dag.json` is written and loop terminates.

---

### User Story 4 - Crash Recovery (Priority: P2)

Every 20 turns, the harness serializes the complete message history to `_import-state/<hash>.session.json`. If `holmes import --resume` is run after an interrupted session, the harness loads that snapshot and continues the loop from where it left off, without starting over.

**Why this priority**: Critical for long documents (maxTurns=300) where crashes may occur mid-way.

**Independent Test**: Run Agent 1 for 25 turns, kill the process, then run `--resume`; verify the loop resumes from turn 25 without re-reading the document from scratch.

**Acceptance Scenarios**:

1. **Given** Agent 1 is at turn 20, **Then** `_import-state/<hash>.session.json` is written with all messages.
2. **Given** Agent 1 is at turn 40, **Then** `session.json` is overwritten with the latest 40 messages.
3. **Given** a `session.json` exists, **When** `holmes import --resume` is run, **Then** the loop resumes from the snapshot; agent does not restart from turn 1.
4. **Given** Agent 1 exceeds maxTurns=300, **Then** the harness raises an error and exits without producing output.

---

### User Story 5 - --no-interactive Mode (Priority: P2)

When `--no-interactive` is passed (explicitly or implicitly via `--dir`), Agent 1 completes normally but skips the interactive menu, automatically selecting option `[2]` (proceed to Step 2.5 without editing).

**Why this priority**: Required for batch import workflows where no human is waiting.

**Independent Test**: Run `holmes import doc.md --no-interactive`; verify no menu prompt appears and pipeline continues to Step 2.5.

**Acceptance Scenarios**:

1. **Given** `--no-interactive` flag, **When** Agent 1 completes, **Then** option `[2]` is selected automatically; no prompt shown.
2. **Given** `--dir ./docs/`, **When** multiple docs are processed, **Then** all run without interaction.
3. **Given** `--no-interactive`, **When** Agent 1 completes, **Then** ImportReport records "DAG 未经用户确认".

---

### User Story 6 - --resume with --skip-edit (Priority: P3)

Running `holmes import --resume --skip-edit` skips the user editing menu entirely and goes directly to Step 2.5 (parse and normalize the existing `.dag.md`).

**Why this priority**: Convenience for automated pipelines or users who know they don't want to edit.

**Independent Test**: With a completed `.dag.md` present, run `--resume --skip-edit`; verify Step 2.5 proceeds directly without any prompt.

**Acceptance Scenarios**:

1. **Given** a completed `.dag.md` with valid content, **When** `--resume --skip-edit` is run, **Then** no menu is shown and Step 2.5 starts immediately.

---

### Edge Cases

- What happens if the document has no headings (prose-only)? Agent 1 must still extract a DAG using Grep for keywords and Read for context.
- How does the system handle multi-root documents (multi_incident)? `output_dag` must accept multiple root nodes (each root can reach at least one END).
- What if a cycle is detected? `output_dag` returns an error with the cycle path; system prompt instructs agent to mark one edge as `back_edge` in description and remove it from structure.
- What if `session.json` is corrupted on `--resume`? Report an error and offer to restart from scratch.
- What if Agent 1 never calls `output_dag` and reaches maxTurns=300? Harness raises `MaxTurnsExceededError` and exits with a clear error.
- What if `write_dag` is called in Phase 1 (study phase)? System prompt forbids it; if called anyway, the harness executes it (it's whitelisted) but the prompt instructs the agent not to.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST create `kb/holmes/kb/agent/dag/` package with `__init__.py`, `schema.py`, `tools1.py`, `harness1.py`, `prompt1.py`, `formatter.py`.
- **FR-002**: `schema.py` MUST define `DAGNode`, `DAGEdge`, `DAGGraph` dataclasses with fields: `id`, `description`, `node_type` (human_observation/api_call/decision/action), `complexity` (simple/process), `section_heading` (optional), `children` (list of condition+target edges).
- **FR-003**: `tools1.py` MUST implement `write_dag(content: str)` writing to `_import-state/<hash>.dag.md` via `atomic_write`.
- **FR-004**: `tools1.py` MUST implement `read_dag()` returning current `.dag.md` content as a string.
- **FR-005**: `tools1.py` MUST implement `output_dag()` that validates the DAG against 5 rules; on pass writes `.dag.json` and signals loop termination; on fail returns descriptive error.
- **FR-006**: `output_dag` validation MUST enforce: (1) at least one root node, (2) no dangling edges, (3) no cycles, (4) all process nodes have section_heading or non-empty description, (5) every non-END node has at least one outgoing edge.
- **FR-007**: `harness1.py` MUST implement `Agent1Harness` with a tool whitelist of exactly: `Read`, `Grep`, `write_dag`, `read_dag`, `output_dag`. Non-whitelisted calls return `{"error": "tool not allowed"}`.
- **FR-008**: `harness1.py` MUST enforce `maxTurns=300`; exceeding raises `MaxTurnsExceededError`.
- **FR-009**: `harness1.py` MUST write crash recovery snapshot to `_import-state/<hash>.session.json` every 20 turns (overwrite).
- **FR-010**: `harness1.py` MUST support `--resume` by loading `session.json` and continuing the loop from the snapshot.
- **FR-011**: `prompt1.py` MUST contain the complete three-phase system prompt: Phase 1 (study, no write_dag), Phase 2 (first write_dag draft), Phase 3 (read_dag → review → write_dag → output_dag), plus tool descriptions, forbidden items, and termination checklist.
- **FR-012**: `formatter.py` MUST implement `.dag.md` ↔ `.dag.json` conversion: `dag_to_markdown(graph, title, source_file)` and `markdown_to_dag(text)`.
- **FR-013**: After `output_dag` succeeds, the pipeline MUST display `[1] 编辑 / [2] 跳过 / [3] 稍后` menu.
- **FR-014**: `--no-interactive` MUST auto-select `[2]`; ImportReport MUST record "DAG 未经用户确认".
- **FR-015**: `--resume --skip-edit` MUST skip the editing menu and proceed to Step 2.5.
- **FR-016**: `pipeline.py._run_dag_pipeline()` MUST be updated to call `Agent1Harness` (remove the `NotImplementedError`).
- **FR-017**: HolmesLogger spans MUST be recorded: `agent1.read` (Phase 1), `agent1.draft` (first write_dag), `agent1.review[N]` (each subsequent review turn), each with `duration_ms`, `llm_calls`, `tokens`.

### Key Entities

- **DAGNode**: A single node in the troubleshooting tree. Attributes: id, description, node_type, complexity, section_heading (optional), is_end flag.
- **DAGEdge**: A directed edge between nodes. Attributes: condition (trigger text), target (node id), is_back_edge (for cycle marking).
- **DAGGraph**: The complete DAG. Attributes: nodes (list of DAGNode), title, source_file, generated_date, multi_root allowed.
- **Agent1Session**: Crash recovery snapshot. Attributes: messages (list), source_hash, turn_count, source_file.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Agent 1 completes extraction for a 2000-line pitfall document without hitting maxTurns=300 in normal cases.
- **SC-002**: Tool whitelist enforcement: 100% of non-whitelisted tool calls are rejected (0 bypasses).
- **SC-003**: `output_dag` rejects 100% of structurally invalid DAGs across all 5 validation rules.
- **SC-004**: Crash recovery: after `--resume`, loop continues from within 20 turns of the interruption point (no full restart).
- **SC-005**: All 5 new files are importable with no runtime errors; existing test suite (684 tests) continues to pass.
- **SC-006**: `_run_dag_pipeline()` no longer raises `NotImplementedError` for pitfall documents; pipeline completes end-to-end.

## Assumptions

- M3 (`037-dag-import-pipeline` branch) is merged and `_run_dag_pipeline()` stub exists in `pipeline.py`.
- M8 (`HolmesLogger`) is merged and the `HolmesLogger` interface is available for span recording.
- `atomic_write()` from `kb/atomic.py` is available for file writes.
- `compute_source_hash()` from `kb/importer.py` is available to derive the state file prefix.
- The `Read` and `Grep` tool definitions used by Agent 1 are the same doc-access tools already defined in `agent/doc_access.py`.
- `--resume` without a source file path uses the most recent `session.json` in `_import-state/`; if multiple exist, presents a selection menu.
- Step 2.5 (parse + normalize) is NOT implemented in M4; M4 only calls Agent 1 and presents the [1/2/3] menu. Step 2.5 remains a stub (or the existing pipeline continues).
- `_import-state/` directory is created inside `kb_root` (the KB repository root), committed to git.
