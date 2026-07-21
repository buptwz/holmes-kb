# Feature Specification: Fix IPC Server & MCP Client Bugs

**Feature Branch**: `028-fix-ipc-mcp-bugs`

**Created**: 2026-06-11

**Status**: Draft

**Input**: 修复 IPC 服务器三个问题：session.resolve 死锁、chat.send 协议违规、MCP client 双重阻断

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Session Knowledge Saving Works End-to-End (Priority: P1)

A user finishes a troubleshooting session and asks the system to save the solution to the
knowledge base. The system extracts the knowledge, asks the user to confirm the entry, and
saves it to pending — without ever getting stuck waiting indefinitely.

**Why this priority**: This is the core knowledge capture loop. Currently completely blocked
by the IPC deadlock. Every session that ends without knowledge capture is a loss.

**Independent Test**: Start an agent session, resolve an issue, call session.resolve, approve
the tool confirmation, and verify a pending entry is created in `contributions/pending/`.

**Acceptance Scenarios**:

1. **Given** an active session with conversation history, **When** `session.resolve` is called, **Then** the system begins knowledge extraction and issues a tool confirmation request within 5 seconds
2. **Given** a pending tool confirmation for knowledge saving, **When** the client sends `tool.approve`, **Then** the approval is processed immediately and the pending entry is saved
3. **Given** a long-running `session.resolve` call, **When** a separate `session.list` request arrives on the same connection, **Then** both complete independently without either blocking the other
4. **Given** a tool confirmation that is denied, **When** the client sends `tool.deny`, **Then** session.resolve returns a clear result without hanging

---

### User Story 2 — Reliable IPC Protocol Compliance (Priority: P2)

A client sends a `chat.send` request with a JSON-RPC `id` field and receives a response
acknowledging receipt, letting it distinguish "request received" from "server error".

**Why this priority**: Protocol violations make automated clients unable to detect request
receipt vs errors. Affects reliability of any tooling built on the IPC interface.

**Independent Test**: Send a `chat.send` request with an `id` field; verify a JSON-RPC
response for that `id` is returned before streaming notifications begin.

**Acceptance Scenarios**:

1. **Given** a `chat.send` request with `id: 42`, **When** the server receives it, **Then** a JSON-RPC response `{"jsonrpc":"2.0","id":42,"result":{"ok":true}}` is sent before any streaming notifications
2. **Given** any IPC request with an `id` field, **When** processed, **Then** exactly one JSON-RPC response with that `id` is returned

---

### User Story 3 — MCP External Tools Reachable from Agent (Priority: P3)

An operator configures the agent with external MCP servers. When the agent runs, it can
discover and invoke tools from those servers like built-in tools — and those tools remain
callable for the entire agent session lifetime, not just during initialization.

**Why this priority**: MCP integration is a stated capability but currently non-functional
(two independent blocking bugs). Fixing it enables extensibility for any team wanting to
plug in external tools.

**Independent Test**: Configure a stdio MCP server; start the agent; ask it to invoke a
tool from that server; verify the call succeeds and returns a result.

**Acceptance Scenarios**:

1. **Given** an MCP server in agent config, **When** the agent starts, **Then** tools from that server appear in the agent's available tool list alongside built-in tools
2. **Given** an MCP tool available to the agent, **When** the agent calls it, **Then** the call succeeds and returns a result (not a "connection closed" error)
3. **Given** a multi-turn session, **When** an MCP tool is called in turn 5, **Then** it succeeds identically to turn 1 — the connection persists across turns
4. **Given** an MCP server unreachable at startup, **When** the agent starts, **Then** it starts successfully with a warning and runs with built-in tools only

---

### Edge Cases

- What happens when `session.resolve` produces no tool calls (nothing to extract)?
- What happens when two `session.resolve` calls arrive concurrently on the same connection?
- What happens when an MCP server crashes after initialization but before the first tool call?
- What happens when `tool.approve` arrives for a `session.resolve` that already timed out?
- What happens when an MCP server config points to a non-existent executable?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The IPC server MUST process concurrent requests on the same connection independently — a long-running request MUST NOT block subsequent requests from being received
- **FR-002**: When `session.resolve` issues a tool confirmation, the server MUST remain able to receive and process `tool.approve` / `tool.deny` on the same connection
- **FR-003**: Any IPC request with a `jsonrpc id` MUST receive exactly one JSON-RPC response for that `id`
- **FR-004**: `chat.send` MUST send an acknowledgment response before emitting streaming notifications
- **FR-005**: A single request failure MUST NOT terminate the IPC connection — other requests MUST continue to be processed
- **FR-006**: MCP server connections MUST remain open and reusable for the agent process lifetime, not closed after initialization
- **FR-007**: Tools from MCP servers MUST be included in the agent's active tool set alongside built-in tools
- **FR-008**: When an MCP server is unreachable at startup, the agent MUST start with a logged warning and run with built-in tools only

### Key Entities

- **IPC Connection**: A long-lived connection carrying multiple interleaved request/response/notification streams
- **Dispatch Task**: An independently running handler for one JSON-RPC request; isolated from other dispatch tasks
- **MCP Server Connection**: A persistent connection to an external MCP server; lifecycle tied to the agent process
- **Tool Registry**: Built-in tools plus MCP-sourced tools, composed at agent startup

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `session.resolve` completes (entry saved or explicitly declined) in under 30 seconds when the user responds — previously always timed out at 120 seconds
- **SC-002**: 100% of IPC requests with an `id` field receive a corresponding JSON-RPC response — previously `chat.send` responses were missing
- **SC-003**: MCP tool calls succeed in 100% of attempts when the server is running — previously 0% succeeded due to closed connection
- **SC-004**: A failing request on an IPC connection does not terminate other in-flight requests on the same connection
- **SC-005**: Agent startup time increases by less than 500ms when MCP servers are configured

---

## Assumptions

- The existing `asyncio` event loop in the IPC server is retained; solution uses cooperative concurrency only
- MCP servers are configured via existing `HolmesConfig.mcp_servers` — no new config schema needed
- `chat.send` acknowledgment is `{"ok": true}`; streaming completions continue as notifications as today
- The `tool.approve` / `tool.deny` mechanism is correct; only the dispatch concurrency model needs to change
- MCP client uses the existing Python MCP SDK — no SDK replacement
- If no MCP servers are configured, behavior is identical to today
