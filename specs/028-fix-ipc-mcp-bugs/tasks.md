# Tasks: Fix IPC Server & MCP Client Bugs

**Input**: Design documents from `specs/028-fix-ipc-mcp-bugs/`

**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓

**Organization**: Tasks grouped by user story. US1 and US2 both touch `ipc_server.py`
so they are sequentially dependent within that file. US3 is fully independent (different files).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

---

## Phase 1: Setup

**Purpose**: Create test files; no new modules required (all fixes are in existing files)

- [X] T001 Create test file `agent/tests/test_ipc_server.py` with pytest boilerplate and import structure
- [X] T002 [P] Create test file `agent/tests/test_mcp_manager.py` with pytest boilerplate and import structure

---

## Phase 2: Foundational

No shared foundational prerequisites. Each user story is independently implementable.
US1 and US2 both edit `agent/holmes/agent/ipc_server.py`; complete US1 before US2.

---

## Phase 3: User Story 1 — Session Knowledge Saving Works End-to-End (P1) 🎯 MVP

**Goal**: Fix IPC deadlock so `session.resolve` + `tool.approve` can complete without timeout.

**Independent Test**: Start agent, call `session.resolve`, then `tool.approve` on same connection;
assert pending KB entry is created within 5 seconds (not 120-second timeout).

### Implementation

- [X] T003 [US1] Add `_dispatch_isolated` method to `IPCServer` in `agent/holmes/agent/ipc_server.py`:
  wraps `_dispatch` with a `try/except Exception` block that logs the error and sends an
  `_error_response` to the writer if `req_id` is present; swallows the exception so the
  read-loop is never affected.
- [X] T004 [US1] Replace `await self._dispatch(request, writer)` with
  `asyncio.create_task(self._dispatch_isolated(request, writer))` in `_handle_client`
  in `agent/holmes/agent/ipc_server.py`; the read-loop now returns immediately and
  can receive subsequent messages (e.g. `tool.approve`) while `session.resolve` is suspended.

### Tests

- [X] T005 [US1] Add unit tests for concurrent dispatch in `agent/tests/test_ipc_server.py`:
  - `test_concurrent_dispatch_does_not_block`: mock reader yields `session.resolve` then
    `tool.approve`; assert both tasks complete without deadlock.
  - `test_dispatch_exception_does_not_kill_reader`: mock handler raises; assert read-loop
    continues and error response is sent.

**Checkpoint**: `session.resolve` + `tool.approve` complete independently on same connection.

---

## Phase 4: User Story 2 — Reliable IPC Protocol Compliance (P2)

**Goal**: `chat.send` with a JSON-RPC `id` receives `{"ok": true}` before streaming starts.

**Independent Test**: Send `{"jsonrpc":"2.0","id":42,"method":"chat.send","params":{...}}`
and verify first response is `{"jsonrpc":"2.0","id":42,"result":{"ok":true}}`.

### Implementation

- [X] T006 [US2] Change `_handle_chat_send` signature to accept `req_id=None` as third parameter
  in `agent/holmes/agent/ipc_server.py`; at the top of the method (before the `async for` loop),
  add: `if req_id is not None: await self._send(writer, _ok_response(req_id, {"ok": True}))`.
- [X] T007 [US2] Update `_dispatch` in `agent/holmes/agent/ipc_server.py` to pass `req_id`
  when calling `_handle_chat_send` and `_handle_skill_invoke` (both are streaming handlers
  that return `None`); call them as `await handler(params, writer, req_id)` and skip
  the existing `if req_id is not None and result is not None` ack for these methods.

### Tests

- [X] T008 [US2] Add unit tests in `agent/tests/test_ipc_server.py`:
  - `test_chat_send_with_id_sends_ack`: mock writer; dispatch `chat.send` with `id=42`;
    mock engine yields nothing; assert `_ok_response(42, {"ok": True})` was sent first.
  - `test_chat_send_without_id_no_ack`: dispatch `chat.send` without `id`; assert no
    JSON-RPC response is sent (only notifications).

**Checkpoint**: All `chat.send` requests with `id` field receive an ack response.

---

## Phase 5: User Story 3 — MCP External Tools Reachable from Agent (P3)

**Goal**: MCP server connections stay open for agent lifetime; tools appear in agent tool set.

**Independent Test**: Configure a stdio MCP server; start agent; call an MCP tool from
the agent; verify it succeeds (not "connection closed" error).

### Implementation (Fix 3: connection lifetime)

- [X] T009 [P] [US3] Add `import contextlib` to `agent/holmes/agent/mcp_manager.py`;
  add `self._exit_stack: contextlib.AsyncExitStack` field initialized in `__init__`.
- [X] T010 [US3] Update `MCPManager.initialize()` in `agent/holmes/agent/mcp_manager.py`:
  call `await self._exit_stack.__aenter__()` at the start of `initialize()`.
  Add `async def close(self) -> None` method: `await self._exit_stack.aclose()`.
- [X] T011 [US3] Rewrite `MCPManager._connect_server()` in `agent/holmes/agent/mcp_manager.py`
  to use `self._exit_stack.enter_async_context(stdio_client(params))` and
  `self._exit_stack.enter_async_context(ClientSession(read, write))` instead of
  nested `async with` blocks; this keeps the session open past `initialize()`.

### Implementation (Fix 4: inject tools into build_tools)

- [X] T012 [US3] Add `extra_tools: Optional[list[BaseTool]] = None` parameter to
  `build_tools()` in `agent/holmes/agent_server.py`; at the end of the function add
  `if extra_tools: tools.extend(extra_tools)`. Update `Optional` import if needed.
- [X] T013 [US3] Rewrite MCP initialization block in `run_server()` in
  `agent/holmes/agent_server.py`:
  - Create `mcp_mgr` before `server` creation.
  - After `mcp_mgr.initialize()`, snapshot `mcp_tools = list(mcp_mgr.tools)`.
  - Define `_tools_factory(cfg, sid="")` closure that calls `build_tools(cfg, sid, extra_tools=mcp_tools)`.
  - Pass `_tools_factory` to `IPCServer(tools_factory=_tools_factory)`.
  - In shutdown path (after `await server.stop()`), call `await mcp_mgr.close()`.
  - If no MCP servers configured, use original `build_tools` directly (no closure needed).

### Tests

- [X] T014 [P] [US3] Add unit tests in `agent/tests/test_mcp_manager.py`:
  - `test_connection_stays_open_after_initialize`: mock `stdio_client` and `ClientSession`;
    assert context manager `__aexit__` is NOT called after `initialize()` returns.
  - `test_close_exits_context`: call `initialize()` then `close()`; assert `__aexit__`
    is called exactly once.
  - `test_graceful_degrade_on_connect_failure`: mock `stdio_client` to raise; assert
    `initialize()` completes, `tools` is empty, `server_status` shows `connected: False`.
- [X] T015 [P] [US3] Add unit tests in `agent/tests/test_ipc_server.py`:
  - `test_build_tools_extra_tools_injected`: create mock `BaseTool`; call `build_tools`
    with `extra_tools=[mock_tool]`; assert mock_tool is in the returned list.
  - `test_build_tools_no_extra_tools_unchanged`: call `build_tools` without `extra_tools`;
    assert result same as original behavior.

**Checkpoint**: MCP tool calls succeed on turn 1 and turn 5 of a multi-turn session.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T016 [P] Add debug log line in `_handle_client` after `asyncio.create_task` call
  in `agent/holmes/agent/ipc_server.py`: `logger.debug("Dispatching %s as async task", method)`
- [X] T017 [P] Add info log in `MCPManager.close()` in `agent/holmes/agent/mcp_manager.py`:
  `logger.info("MCPManager closed %d server connections", len(self._server_status))`
- [X] T018 Run all agent tests: `cd agent && python -m pytest tests/ -v` and confirm no regressions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — T001 and T002 can run in parallel
- **Foundational (Phase 2)**: N/A for this feature
- **US1 (Phase 3)**: No dependencies — can start after T001
- **US2 (Phase 4)**: Must start AFTER US1 is complete (both edit `ipc_server.py`)
- **US3 (Phase 5)**: Independent of US1/US2 — can run in parallel with Phase 3/4 (different files)
- **Polish (Phase 6)**: After all implementation tasks complete

### User Story Dependencies

- **US1 (P1)**: Independent — only blocks US2 due to shared file
- **US2 (P2)**: Depends on US1 completion (same file, sequential edits)
- **US3 (P3)**: Fully independent — `mcp_manager.py` and `agent_server.py` are separate files

### Within Each User Story

- Implementation before tests (bugs are pre-existing; confirm fix works, then lock in tests)
- US3 Fix 3 (T009–T011) before Fix 4 (T012–T013): manager must be correct before injecting tools

---

## Parallel Opportunities

```bash
# Phase 1 — parallel:
T001 Create agent/tests/test_ipc_server.py
T002 Create agent/tests/test_mcp_manager.py

# US3 — T009 and T014/T015 tests can start in parallel with US1/US2 work:
T009 Add AsyncExitStack to mcp_manager.py     # independent file
T014 Write mcp_manager tests                   # independent file
T015 Write build_tools tests                   # independent file

# Polish — all parallel:
T016 Add dispatch debug log
T017 Add MCP close info log
```

---

## Implementation Strategy

### MVP (US1 only — 2 tasks + 1 test)

1. T001 (create test file)
2. T003–T004 (add `_dispatch_isolated`, replace `await` with `create_task`)
3. T005 (write concurrent dispatch tests)
4. **VALIDATE**: Run `python -m pytest tests/test_ipc_server.py -v`

### Full Delivery Order

1. T001, T002 (setup — parallel)
2. T003, T004 (US1 impl) → T005 (US1 tests)
3. T006, T007 (US2 impl) → T008 (US2 tests)
4. T009, T010, T011 (US3 fix-3) → T012, T013 (US3 fix-4) → T014, T015 (US3 tests)
5. T016, T017, T018 (polish — parallel)

---

## Notes

- All three user stories edit distinct file sets (US1/US2 share `ipc_server.py`, US3 is separate)
- No new modules: all changes in existing files + 2 new test files
- `asyncio.create_task` fix is the highest-risk change; test it with a mock that simulates the exact deadlock scenario
- MCP `AsyncExitStack` requires the `mcp` SDK to be installed; if not installed, `_connect_server` gracefully degrades (existing behavior)
