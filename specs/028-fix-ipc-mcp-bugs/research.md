# Research: Fix IPC Server & MCP Client Bugs

**Feature**: 028-fix-ipc-mcp-bugs
**Date**: 2026-06-11

---

## Bug 1: IPC Deadlock in `session.resolve`

### Root Cause (confirmed by code)

`_handle_client` (ipc_server.py:108) reads lines sequentially and calls
`await self._dispatch(request, writer)` inline. This means the read-loop
is suspended for the entire duration of `_dispatch`. When `session.resolve`
is dispatched, it reaches `await asyncio.wait_for(future, timeout=120)` inside
`_handle_session_resolve` — waiting for a `tool.approve` Future to be resolved.
Because the read-loop is blocked, the `tool.approve` message that the client
sends can never be read. The Future never resolves → 120-second timeout.

### Decision: `asyncio.create_task` per request

- **Chosen**: `asyncio.create_task(self._dispatch(request, writer))` so each
  request runs as an independent task; the read-loop continues immediately.
- **Exception isolation**: each task is a self-contained coroutine; any unhandled
  exception inside `_dispatch` must be caught inside the task, not propagated to
  the read-loop. Add `try/except Exception` wrapper inside `create_task` coroutine.
- **Rationale**: Minimal change to existing architecture; preserves single-event-loop
  cooperative concurrency assumption from spec Assumptions section.
- **Alternative rejected — `asyncio.Queue` worker pool**: Over-engineering; adds
  ordering guarantees not needed here. Each request is already self-contained.

### Key API: `asyncio.create_task`

```python
task = asyncio.create_task(_dispatch_safe(request, writer))
```

Where `_dispatch_safe` wraps `_dispatch` with exception logging so a crash
in one handler does not surface to the read-loop.

---

## Bug 2: `chat.send` Missing JSON-RPC Response

### Root Cause (confirmed by code)

`_handle_chat_send` returns `None` (ipc_server.py:347).
`_dispatch` only sends `_ok_response` when `result is not None` (line 164).
Result: any `chat.send` call with an `id` field receives zero responses,
violating JSON-RPC 2.0 (§5 — every request must receive a response).

### Decision: send `{"ok": true}` ack before streaming

- **Chosen**: At the start of `_handle_chat_send`, before the `async for` loop,
  send `_ok_response(req_id, {"ok": True})` when `req_id is not None`.
- The `req_id` must be passed through from `_dispatch` to the handler,
  or the handler must extract it from the request dict. Cleanest path:
  pass `req_id` as a third argument to the handler.
- **Alternative rejected — keep returning None and handle in _dispatch**:
  Would require `_dispatch` to know about streaming handlers, coupling concerns.

---

## Bug 3: MCP Client Connection Closed After `initialize()`

### Root Cause (confirmed by code)

`_connect_server` (mcp_manager.py:104) uses:

```python
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # ... proxy tools created with reference to `session`
        self._tools.extend(proxy_tools)
        # ← context manager exits here, session & transport CLOSED
```

The `MCPProxyTool` instances store a reference to `session`, but by the time
`initialize()` returns, the context managers have exited and both the
`ClientSession` and the underlying stdio transport are closed.
Any subsequent `call_tool()` call fails with a connection-closed error.

### Decision: `AsyncExitStack` to keep connections alive for agent lifetime

- **Chosen**: Add `self._exit_stack: contextlib.AsyncExitStack` to `MCPManager`.
  Call `self._exit_stack.enter_async_context(stdio_client(params))` and
  `self._exit_stack.enter_async_context(ClientSession(read, write))`.
  The connections stay open until `await mcp_mgr.close()` is called on
  agent shutdown.
- `run_server()` in `agent_server.py` must call `await mcp_mgr.close()` on
  shutdown (in `finally` block or before `server.stop()`).
- **Rationale**: `AsyncExitStack` is the standard pattern for managing multiple
  async context managers with independent lifetimes; already available in stdlib.
- **Alternative rejected — reconnect on each call**: Adds latency per call;
  stdio transport initialization involves process spawn, unacceptably slow.

---

## Bug 4: MCP Tools Never Injected into `build_tools()`

### Root Cause (confirmed by code)

`run_server()` (agent_server.py:72-83) creates `MCPManager`, calls `initialize()`,
logs status — but `mcp_mgr.tools` is **never** passed to `build_tools` or the
`IPCServer`. The comment says "MCP tools will be included by re-running build_tools
after init" but this never happens. `build_tools` has no parameter for extra tools.

### Decision: add `extra_tools` parameter to `build_tools`

- **Chosen**: `build_tools(config, session_id="", extra_tools=None)` where
  `extra_tools: list[BaseTool] | None = None`. At the end of the function:
  `tools.extend(extra_tools or [])`.
- In `run_server()`, after MCP init: create a partial/closure that passes
  `mcp_mgr.tools` as `extra_tools` to the factory.
- Pass this closure to `IPCServer(tools_factory=...)`.
- **Rationale**: Minimal interface change; tools are stateless proxies so
  sharing across sessions is safe.
- **Alternative rejected — MCPManager on IPCServer**: Would require refactoring
  the server's factory pattern; more invasive.

---

## Test Strategy

All three fixes have independent unit test paths:

| Bug | Test approach |
|-----|--------------|
| IPC deadlock | Unit test: mock reader/writer; send `session.resolve` then `tool.approve` concurrently; assert both complete without timeout |
| chat.send ack | Unit test: call `_dispatch` with `id`-bearing `chat.send`; mock engine to yield nothing; assert `_ok_response` was sent |
| MCP lifetime | Unit test: mock `stdio_client` / `ClientSession`; verify `close()` is called only on explicit `mcp_mgr.close()`, not after `initialize()` |
| MCP injection | Unit test: mock MCP tools; call patched `run_server`; verify `build_tools` receives `extra_tools` with MCP proxies |

Existing `test_engine.py` pattern (pytest + mocks) is the established convention.
New tests go in `agent/tests/test_ipc_server.py` and `agent/tests/test_mcp_manager.py`.
