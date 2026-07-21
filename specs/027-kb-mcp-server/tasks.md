# Tasks: KB MCP Server & System Closure

**Input**: Design documents from `specs/027-kb-mcp-server/`

**Prerequisites**: plan.md, spec.md, research.md, contracts/mcp-tools.md

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Verify baseline and confirm MCP SDK API before coding.

- [X] T001 Verify MCP SDK transport: run `python -c "from mcp.server.fastmcp import FastMCP; f=FastMCP('test'); print('ok')"` and confirm FastMCP supports `streamable-http` transport (already confirmed: `f.run(transport='streamable-http')`)
- [X] T002 Run existing test suite baseline: `cd kb && python -m pytest -q 2>&1 | tail -3` — record count (expect 733)
- [X] T003 Run agent test suite baseline: `cd agent && python -m pytest -q 2>&1 | tail -3` — record count

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Fix `list_entries()` include_pending support — required by US3 (kb_submit evidence) and US4.

- [X] T004 In `kb/holmes/kb/store.py` `list_entries()` function signature: add parameter `include_pending: bool = False` after existing parameters; when `True`, additionally scan `kb_root / "contributions" / "pending"` for `*.md` files using the same frontmatter parsing and `EntryMeta` construction logic as the official type directories; skip files starting with `_`; handle exceptions silently
- [X] T005 In `kb/holmes/kb/store.py` `append_evidence()` function: change the internal `list_entries(kb_root)` call to `list_entries(kb_root, include_pending=True)` so pending entries can receive evidence writes
- [X] T006 Add test in `kb/tests/test_store.py`: `test_append_evidence_to_pending_entry` — create a pending entry file at `tmp_path / "contributions" / "pending" / "pending-test.md"` with valid frontmatter; call `append_evidence(tmp_path, "pending-test", {...})`; assert returns True and sidecar JSON file written
- [X] T007 Run `cd kb && python -m pytest tests/test_store.py -q` — confirm T006 passes and no regressions

**Checkpoint**: `append_evidence()` can now write evidence for pending entries.

---

## Phase 3: User Story 5 — Fix engine.py auto-record (Priority: P1)

**Goal**: 移除 engine.py 中 `kb_read_entry` 成功后自动写 evidence 的逻辑，新增显式 `kb_confirm_entry` 工具替代。

**Independent Test**: agent 调用 `kb_read_entry` 后 `contributions/evidence/` 无新文件；调用 `kb_confirm_entry` 后 evidence 文件立即写入。

- [X] T008 [US5] In `agent/holmes/agent/engine.py`: remove the block `if tool_name == "kb_read_entry" and not result.is_error:` and its body (the entry_id append to `self._session.kb_refs`) — approximately lines 263–266; do not change any surrounding logic
- [X] T009 [US5] In `agent/holmes/agent/engine.py`: remove `self._flush_evidence()` call in the `_InternalStopEvent` handler (approximately line 300)
- [X] T010 [US5] In `agent/holmes/agent/engine.py`: remove the `_flush_evidence(self) -> None` method entirely (approximately lines 389–410)
- [X] T011 [US5] In `agent/holmes/agent/engine.py` `AgentSession` dataclass: remove the `kb_refs: list[str] = field(default_factory=list)` field (approximately line 88); remove any `field` import if no longer used
- [X] T012 [US5] Create new file `agent/holmes/agent/tools/kb_confirm.py`: implement `KbConfirmEntryTool` class extending `BaseTool`; name = `"kb_confirm_entry"`; description = "Record that a KB entry successfully helped resolve the current issue. MUST be called only after the user explicitly confirms the problem is resolved. MUST NOT be called if the resolution failed or the entry was not used. For skill entries, call this immediately after successful script execution and user confirmation."; input_schema requires `entry_id: str`; requires_confirmation = False; execute() calls `append_evidence(self._kb_root, entry_id, {"session_id": self._session_id, "contributor": os.environ.get("HOLMES_CONTRIBUTOR", "agent"), "date": date.today().isoformat()})`; returns ToolResult with ok/maturity/promoted info
- [X] T013 [US5] In `agent/holmes/agent/engine.py` or tool registration: register `KbConfirmEntryTool` alongside existing KB tools so it is available in agent sessions; import it from `holmes.agent.tools.kb_confirm`
- [X] T014 [US5] Run `cd agent && python -m pytest -q 2>&1 | tail -3` — confirm no regressions

**Checkpoint**: US5 complete — agent no longer auto-records evidence on read; explicit confirm tool available.

---

## Phase 4: User Story 1+2 — MCP Browse & Read + Confirm (Priority: P1)

**Goal**: 实现 MCP server 核心，支持 `kb_overview`、`kb_list`、`kb_read`、`kb_confirm` 四个 tool。

**Independent Test**: 启动 `holmes start --kb-path <test_kb>`；用 MCP 客户端或 curl 调用四个 tool；验证返回内容与直接读文件一致；`kb_read` 不产生 evidence 文件；`kb_confirm` 写入 sidecar JSON。

### MCP Package Setup

- [X] T015 [US1] Create directory `kb/holmes/mcp/` with empty `__init__.py`
- [X] T016 [US1] Create `kb/holmes/mcp/tools.py` with module docstring; import at top: `from pathlib import Path`, `import json`, `import socket`, `import subprocess`, `from datetime import date`, `from uuid import uuid4`; import from store: `from holmes.kb.store import list_entries, read_entry, append_evidence`; import from pending: `from holmes.kb.pending import write_pending`; define module-level helper `_get_contributor(kb_root: Path) -> str` that runs `subprocess.run(["git", "-C", str(kb_root), "config", "user.email"], ...)`, falls back to `user.name`, falls back to `socket.gethostname()`

### kb_overview handler

- [X] T017 [US1] In `kb/holmes/mcp/tools.py`: implement `handle_kb_overview(kb_root: Path) -> dict` — call `list_entries(kb_root)`; aggregate counts by type into `{types: {pitfall: N, ...}}`; collect unique categories from all entries; collect all tags and return top 10 by frequency as `top_tags`; return `{total, types, categories, top_tags}`

### kb_list handler

- [X] T018 [US1] In `kb/holmes/mcp/tools.py`: implement `handle_kb_list(kb_root: Path, type: str|None, category: str|None, limit: int, offset: int) -> dict` — call `list_entries(kb_root, kb_type=type, category=category)`; apply offset/limit slicing; for each entry read first 150 chars of body as `brief` using `read_entry()`; return `{entries: [{id, title, type, category, maturity, brief}], total, offset, limit}`

### kb_read handler

- [X] T019 [US1] In `kb/holmes/mcp/tools.py`: implement `handle_kb_read(kb_root: Path, entry_id: str) -> dict` — call `read_entry(kb_root, entry_id)`; if None return `{"error": f"Entry not found: {entry_id}"}`; otherwise return `{id: entry_id, type, maturity, content: raw_markdown}` — parse frontmatter to extract type/maturity fields; do NOT call append_evidence

### kb_confirm handler

- [X] T020 [US2] In `kb/holmes/mcp/tools.py`: implement `handle_kb_confirm(kb_root: Path, entry_id: str, session_id: str) -> dict` — call `append_evidence(kb_root, entry_id, {"session_id": session_id, "contributor": _get_contributor(kb_root), "date": date.today().isoformat()})`; if returns True reload entry frontmatter to get updated maturity and whether it changed; return `{ok: true, entry_id, maturity, promoted, contributor}` or `{ok: false, reason: "duplicate", entry_id}`

### MCP Server

- [X] T021 [US1] Create `kb/holmes/mcp/server.py`: import `FastMCP` from `mcp.server.fastmcp`; import tool handlers from `holmes.mcp.tools`; create `mcp = FastMCP("holmes-kb")`; define module-level `_kb_root: Path` and `_session_id: str = str(uuid4())[:8]`; register all 4 tool handlers as `@mcp.tool()` decorated functions with full description strings from `contracts/mcp-tools.md`; implement `run_server(kb_root: Path, port: int = 8765) -> None` that sets `_kb_root`, then calls `mcp.run(transport="streamable-http")`

### CLI entry point

- [X] T022 [US1] In `kb/holmes/cli.py`: add top-level command `@cli.command("start")` with `@click.option("--port", default=8765, help="Port for MCP server (default: 8765)")` and `@click.pass_context`; body calls `_require_kb_root(ctx)` then `from holmes.mcp.server import run_server` then `run_server(kb_root, port=port)`; add startup echo: `click.echo(f"Holmes KB MCP server running at http://localhost:{port}")`

- [X] T023 [US1] Manual smoke test: start `holmes start --kb-path <test_kb> --port 8765` in background; use `python -c "import httpx; ..."` or MCP test client to call `kb_overview`; verify JSON response; kill server

**Checkpoint**: US1+US2 complete — MCP server starts, 4 tools respond correctly.

---

## Phase 5: User Story 3 — MCP Submit (Priority: P2)

**Goal**: 实现 `kb_submit` MCP tool，创建 pending 条目并写入提交者 evidence（依赖 Phase 2 的 include_pending fix）。

**Independent Test**: 调用 `kb_submit`；`contributions/pending/` 出现条目文件；`contributions/evidence/<id>/` 出现提交者 sidecar；调用 `holmes kb confirm <id>` 成功 promote。

### kb_submit handler

- [X] T024 [US3] In `kb/holmes/mcp/tools.py`: implement `handle_kb_submit(kb_root: Path, title: str, type: str, content: str, session_id: str, category: str|None, tags: list[str]|None) -> dict` — assemble frontmatter header: `id` left empty (assigned by `write_pending`), `type`, `title`, `maturity: pending`, `category`, `tags`, `created_at: datetime.now(timezone.utc).isoformat()`; prepend to content; call `write_pending(kb_root, full_markdown)`; then call `append_evidence(kb_root, pending_id, {"session_id": session_id, "contributor": _get_contributor(kb_root), "date": date.today().isoformat()})` — this works because Phase 2 fixed include_pending; return `{id: pending_id, status: "pending", message: f"Entry submitted. Approve with: holmes kb confirm {pending_id}"}`

### Register kb_submit in server

- [X] T025 [US3] In `kb/holmes/mcp/server.py`: add `@mcp.tool()` decorated `kb_submit` function wrapping `handle_kb_submit`; include full description from contracts/mcp-tools.md including MUST/MUST NOT guidance

- [X] T026 [US3] Integration test: call `kb_submit` via MCP; then call `holmes kb confirm <returned_id> --contributor test` in subprocess; verify entry appears in `kb_list` results after confirm

**Checkpoint**: US3 complete — full knowledge contribution loop: submit → pending → confirm → official.

---

## Phase 6: User Story 4 — Tests for include_pending (Priority: P1, parallel with Phase 3)

**Note**: T004–T007 in Phase 2 already cover US4 implementation and testing. This phase adds edge case tests.

- [X] T027 [P] [US4] Add test `test_list_entries_include_pending_false_by_default` in `kb/tests/test_store.py`: create pending entry at `contributions/pending/`; call `list_entries(tmp_path)` without flag; assert pending entry NOT in results
- [X] T028 [P] [US4] Add test `test_list_entries_include_pending_true` in `kb/tests/test_store.py`: create pending entry; call `list_entries(tmp_path, include_pending=True)`; assert pending entry IS in results alongside official entries
- [X] T029 [US4] Run `cd kb && python -m pytest tests/test_store.py -q -k "pending"` — all pass

---

## Phase 7: Polish & Validation

**Purpose**: Full regression, MCP tool description quality check, port configuration.

- [X] T030 Run full KB test suite: `cd kb && python -m pytest -q 2>&1 | tail -3` — no regressions, count ≥ 733 + new tests
- [X] T031 Run full agent test suite: `cd agent && python -m pytest -q 2>&1 | tail -3` — no regressions
- [X] T032 Verify `holmes start --help` shows `--kb-path` and `--port` options; verify `holmes --help` shows `start` subcommand
- [X] T033 Verify MCP tool descriptions in `server.py` contain MUST/MUST NOT language matching contracts/mcp-tools.md for all 5 tools
- [X] T034 End-to-end smoke: `holmes start --kb-path <test_kb>`; connect MCP client; execute full loop: `kb_overview` → `kb_list` → `kb_read` → `kb_confirm` → verify evidence file exists and maturity updated; then `kb_submit` → `holmes kb confirm <id>` → `kb_list` shows new entry

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies
- **Phase 2 (Foundational)**: Depends on Phase 1 — blocks US3 (kb_submit needs include_pending)
- **Phase 3 (US5 engine fix)**: Depends on Phase 1; independent of Phase 2 — different packages
- **Phase 4 (US1+US2 MCP)**: Depends on Phase 1; independent of Phase 2 and 3 — different files
- **Phase 5 (US3 kb_submit)**: Depends on Phase 2 (include_pending) AND Phase 4 (server.py exists)
- **Phase 6 (US4 tests)**: Depends on Phase 2 — parallel with Phase 3
- **Phase 7 (Polish)**: Depends on all phases complete

### Parallel Opportunities

```
Phase 1 (Setup)
  ↓
Phase 2 (Foundational) ──────┐
  ↓                           │
Phase 3 (US5, agent)    Phase 4 (US1+2, MCP)    Phase 6 (US4 tests)
  ↓                           ↓
                         Phase 5 (US3, submit) — needs Phase 2 + Phase 4
                              ↓
                         Phase 7 (Polish)
```

- **Phase 3, Phase 4, Phase 6** can run in parallel after Phase 2

### Within Each Phase (sequential)

- T004 → T005 → T006 → T007 (same file, each builds on previous)
- T008 → T009 → T010 → T011 → T012 → T013 → T014 (same file engine.py)
- T015 → T016 → T017 → T018 → T019 → T020 → T021 → T022 → T023 (new module, sequential)
- T024 → T025 → T026 (same file tools.py)

---

## Implementation Strategy

### MVP First (Phase 2 + Phase 4 only)

1. Phase 1: Setup
2. Phase 2: include_pending fix
3. Phase 4: MCP server with kb_overview + kb_list + kb_read + kb_confirm
4. **STOP and VALIDATE**: `holmes start` runs; 4 tools respond; `kb_confirm` writes evidence
5. Proceed to Phase 3 (engine fix), Phase 5 (kb_submit), Phase 6 (tests)

### Incremental Delivery

1. Setup → baseline confirmed
2. Foundational (include_pending) → unblocks kb_submit evidence
3. MCP server 4 tools live → usable immediately
4. Engine fix → internal agent aligned with MCP semantics
5. kb_submit → full contribution loop
6. Tests + Polish → full validation

---

## Notes

- `FastMCP` from `mcp.server.fastmcp` supports `transport="streamable-http"` directly — confirmed at T001
- MCP server port default 8765; client config: `{"url": "http://localhost:8765"}`
- Pending directory: `contributions/pending/` (not `pending/`) — confirmed from existing codebase
- `write_pending()` assigns the pending ID automatically — `kb_submit` must NOT pre-assign ID
- `holmes kb confirm <id>` already handles the full approve flow (3-gate) — US6 not needed
- `_get_contributor()` helper reads git config from KB repo directory, not CWD
- MCP tool descriptions in `server.py` MUST reproduce the MUST/MUST NOT guidance from contracts verbatim or close paraphrase
