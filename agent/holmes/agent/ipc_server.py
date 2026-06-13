"""IPC server for Holmes Agent.

JSON-RPC 2.0 over Unix domain socket.
Handles: session.*, chat.send, kb.list, kb.get, tool.approve, tool.deny,
         skill.invoke, context.compact
Pushes: agent/token, agent/done, agent/error, agent/tool_start, agent/tool_end,
        agent/tool_confirm, context/update, mcp/status
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from holmes.agent.context_manager import ContextManager
from holmes.agent.engine import (
    AgentEngine,
    ConfirmDecision,
    DoneEvent,
    ErrorEvent,
    ToolConfirmEvent,
    ToolEndEvent,
    ToolStartEvent,
    TokenEvent,
)
from holmes.agent.memory import append_to_memory
from holmes.agent.session import (
    Session,
    load_session,
    list_sessions,
    save_session,
)
from holmes.agent.tools.base import BaseTool
from holmes.config import HolmesConfig
from holmes.kb.store import get_entry, list_entries
from holmes.logging_config import get_logger


logger = get_logger("agent.ipc_server")

SOCKET_PATH_TEMPLATE = "/tmp/holmes-{session_key}.sock"

# Methods that stream notifications and return None; they send their own JSON-RPC ack.
_STREAMING_METHODS: frozenset[str] = frozenset({"chat.send", "skill.invoke"})


class IPCServer:
    """JSON-RPC 2.0 server over Unix domain socket.

    One instance handles all sessions for a single agent process.
    """

    def __init__(
        self,
        config: HolmesConfig,
        tools_factory: Callable[..., list[BaseTool]],
        socket_path: Optional[str] = None,
    ) -> None:
        """Initialize IPC server.

        Args:
            config: Holmes configuration.
            tools_factory: Callable that returns tool list given config.
            socket_path: Unix socket path. Defaults to /tmp/holmes-{pid}.sock.
        """
        self._config = config
        self._tools_factory = tools_factory
        self._socket_path = socket_path or SOCKET_PATH_TEMPLATE.format(
            session_key=os.getpid()
        )
        self._engines: dict[str, AgentEngine] = {}
        self._sessions: dict[str, Session] = {}
        self._context_managers: dict[str, ContextManager] = {}
        # tool_call_id -> asyncio.Future[ConfirmDecision]
        self._pending_confirmations: dict[str, asyncio.Future[ConfirmDecision]] = {}
        self._server: Optional[asyncio.Server] = None

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        """Start the Unix socket server."""
        # Remove stale socket
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        self._server = await asyncio.start_unix_server(
            self._handle_client, path=self._socket_path
        )
        logger.info("IPC server listening on %s", self._socket_path)

    async def stop(self) -> None:
        """Stop the server and clean up the socket."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        logger.info("IPC server stopped")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single client connection. Reads newline-delimited JSON-RPC.

        Each request is dispatched as an independent asyncio task so that
        long-running handlers (e.g. session.resolve waiting for tool.approve)
        do not block the read-loop from receiving subsequent messages.
        """
        logger.debug("New IPC client connected")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    await self._send(writer, _error_response(None, -32700, f"Parse error: {e}"))
                    continue
                logger.debug("Dispatching %s as async task", request.get("method"))
                asyncio.create_task(self._dispatch_isolated(request, writer))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Client handler error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch_isolated(
        self, request: dict[str, Any], writer: asyncio.StreamWriter
    ) -> None:
        """Dispatch a single request, isolating any exception from the read-loop.

        If the handler raises an unhandled exception, an error response is sent
        to the client (when the request had an id) and the exception is logged,
        but it does NOT propagate — other in-flight requests are unaffected.
        """
        req_id = request.get("id")
        try:
            await self._dispatch(request, writer)
        except Exception as e:
            logger.exception(
                "Unhandled error dispatching request method=%s", request.get("method")
            )
            if req_id is not None:
                try:
                    await self._send(writer, _error_response(req_id, -32603, str(e)))
                except Exception:
                    pass

    async def _dispatch(
        self, request: dict[str, Any], writer: asyncio.StreamWriter
    ) -> None:
        """Route a JSON-RPC request to the appropriate handler."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        handlers: dict[str, Callable] = {
            "session.create": self._handle_session_create,
            "session.list": self._handle_session_list,
            "session.get": self._handle_session_get,
            "session.resolve": self._handle_session_resolve,
            "chat.send": self._handle_chat_send,
            "kb.list": self._handle_kb_list,
            "kb.get": self._handle_kb_get,
            "tool.approve": self._handle_tool_approve,
            "tool.deny": self._handle_tool_deny,
            "skill.invoke": self._handle_skill_invoke,
            "context.compact": self._handle_context_compact,
            "/remember": self._handle_remember,
        }

        handler = handlers.get(method)
        if handler is None:
            await self._send(
                writer, _error_response(req_id, -32601, f"Method not found: {method}")
            )
            return

        try:
            # Streaming handlers send their own ack and return None; pass req_id so
            # they can send the JSON-RPC response before emitting notifications.
            if method in _STREAMING_METHODS:
                result = await handler(params, writer, req_id=req_id)
            else:
                result = await handler(params, writer)
            if req_id is not None and result is not None:
                await self._send(writer, _ok_response(req_id, result))
        except Exception as e:
            logger.exception("Handler error for method %s", method)
            await self._send(writer, _error_response(req_id, -32603, str(e)))

    # ---- Session methods ----

    async def _handle_session_create(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        session = Session()
        save_session(session)
        self._sessions[session.id] = session
        ctx_mgr = ContextManager(max_tokens=self._config.max_tokens)
        self._context_managers[session.id] = ctx_mgr

        tools = self._tools_factory(self._config, session.id)
        confirm_cb = self._make_confirm_callback(writer)
        engine = AgentEngine(
            config=self._config,
            session=session,
            tools=tools,
            confirm_callback=confirm_cb,
        )
        self._engines[session.id] = engine
        logger.info("Created session %s", session.id)
        return {"session_id": session.id, "created_at": session.created_at}

    async def _handle_session_list(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        status = params.get("status")
        limit = params.get("limit", 50)
        sessions = list_sessions(status=status, limit=limit)
        return {"sessions": sessions}

    async def _handle_session_get(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        session_id = params["session_id"]
        session = load_session(session_id)
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        data = session.model_dump()
        data["message_count"] = len(session.messages)
        return {"session": data}

    async def _handle_session_resolve(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        session_id = params["session_id"]
        engine = self._engines.get(session_id)
        session = self._sessions.get(session_id) or load_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if engine is None:
            tools = self._tools_factory(self._config, session_id)
            confirm_cb = self._make_confirm_callback(writer)
            engine = AgentEngine(
                config=self._config,
                session=session,
                tools=tools,
                confirm_callback=confirm_cb,
            )

        kb_entry_md = await engine.extract_knowledge()
        preview = kb_entry_md[:200]
        session.resolve()
        save_session(session)

        # Trigger kb_write via the write tool
        write_tool = next(
            (t for t in self._tools_factory(self._config, session_id) if t.name == "kb_write_entry"),
            None,
        )
        if write_tool:
            event = ToolConfirmEvent(
                session_id=session_id,
                tool_call_id=str(uuid.uuid4()),
                tool_name="kb_write_entry",
                description="Save knowledge extracted from this session to the KB",
                input_preview={"content_preview": preview},
            )
            await self._send(writer, _notification("agent/tool_confirm", {
                "session_id": session_id,
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_name,
                "description": event.description,
                "input_preview": event.input_preview,
            }))
            future: asyncio.Future[ConfirmDecision] = asyncio.get_event_loop().create_future()
            self._pending_confirmations[event.tool_call_id] = future
            approved, _ = await asyncio.wait_for(future, timeout=120)
            if approved:
                result = await write_tool.execute(content=kb_entry_md)
                if not result.is_error:
                    # Use the structured artifact ID; fall back to parsing content
                    session.kb_entry_id = result.artifact or _extract_pending_id(result.content)
                else:
                    session.kb_entry_id = None
                save_session(session)

        return {
            "kb_entry_id": session.kb_entry_id or "",
            "summary_preview": preview,
        }

    # ---- Chat ----

    async def _handle_chat_send(
        self,
        params: dict[str, Any],
        writer: asyncio.StreamWriter,
        req_id: Any = None,
    ) -> None:
        """Handle chat.send.

        Sends a JSON-RPC ack ({"ok": true}) before emitting streaming notifications,
        so clients that sent a request with an id can distinguish receipt from error.
        """
        session_id = params["session_id"]
        message = params["message"]
        attachments = params.get("attachments", [])

        # JSON-RPC 2.0 compliance: acknowledge receipt before streaming begins
        if req_id is not None:
            await self._send(writer, _ok_response(req_id, {"ok": True}))

        engine = self._engines.get(session_id)
        if engine is None:
            raise ValueError(f"No active engine for session: {session_id}")

        ctx_mgr = self._context_managers.get(session_id)

        # Append file attachments to message
        if attachments:
            attachment_texts = []
            for att in attachments:
                path = att.get("path", "")
                content = att.get("content", "")
                line_start = att.get("line_start")
                line_end = att.get("line_end")
                range_info = (
                    f" (lines {line_start}–{line_end})" if line_start and line_end else ""
                )
                attachment_texts.append(f"[File: {path}{range_info}]\n```\n{content}\n```")
            message = message + "\n\n" + "\n\n".join(attachment_texts)

        async for event in engine.chat(message):
            if isinstance(event, TokenEvent):
                await self._send(writer, _notification("agent/token", {
                    "session_id": event.session_id,
                    "delta": event.delta,
                }))
            elif isinstance(event, ToolStartEvent):
                await self._send(writer, _notification("agent/tool_start", {
                    "session_id": event.session_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "input": event.input,
                }))
            elif isinstance(event, ToolEndEvent):
                await self._send(writer, _notification("agent/tool_end", {
                    "session_id": event.session_id,
                    "tool_call_id": event.tool_call_id,
                    "output": event.output,
                    "status": event.status,
                }))
            elif isinstance(event, ToolConfirmEvent):
                await self._send(writer, _notification("agent/tool_confirm", {
                    "session_id": event.session_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "description": event.description,
                    "input_preview": event.input_preview,
                }))
            elif isinstance(event, DoneEvent):
                if ctx_mgr:
                    ctx_mgr.update(event.input_tokens + event.output_tokens)
                    await self._send(writer, _notification("context/update", {
                        "session_id": event.session_id,
                        "used_tokens": ctx_mgr.used_tokens,
                        "max_tokens": ctx_mgr.max_tokens,
                        "warning": ctx_mgr.is_warning,
                    }))
                await self._send(writer, _notification("agent/done", {
                    "session_id": event.session_id,
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "kb_refs": event.kb_refs,
                }))
            elif isinstance(event, ErrorEvent):
                await self._send(writer, _notification("agent/error", {
                    "session_id": event.session_id,
                    "error": event.error,
                    "code": event.code,
                }))
        return None

    # ---- KB methods ----

    async def _handle_kb_list(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        kb_path = self._config.kb_path
        if not kb_path:
            return {"entries": []}
        kb_root = Path(kb_path)
        kb_type = params.get("type")
        entries = list_entries(kb_root, kb_type)  # type: ignore[arg-type]
        limit = params.get("limit", 100)
        return {
            "entries": [
                {
                    "id": e.id,
                    "type": e.type,
                    "title": e.title,
                    "maturity": e.maturity,
                    "category": e.category,
                    "tags": e.tags,
                    "updated_at": e.updated_at,
                }
                for e in entries[:limit]
            ]
        }

    async def _handle_kb_get(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        kb_path = self._config.kb_path
        if not kb_path:
            raise ValueError("KB path not configured")
        entry_id = params["entry_id"]
        entry = get_entry(Path(kb_path), entry_id)
        if entry is None:
            raise ValueError(f"Entry not found: {entry_id}")
        return {
            "entry": {
                **entry.to_dict(),
            }
        }

    # ---- Tool confirmation ----

    async def _handle_tool_approve(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        tool_call_id = params["tool_call_id"]
        future = self._pending_confirmations.pop(tool_call_id, None)
        if future and not future.done():
            future.set_result((True, None))
        return {"ok": True}

    async def _handle_tool_deny(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        tool_call_id = params["tool_call_id"]
        reason = params.get("reason")
        future = self._pending_confirmations.pop(tool_call_id, None)
        if future and not future.done():
            future.set_result((False, reason))
        return {"ok": True}

    # ---- Skill ----

    async def _handle_skill_invoke(
        self,
        params: dict[str, Any],
        writer: asyncio.StreamWriter,
        req_id: Any = None,
    ) -> None:
        session_id = params["session_id"]
        skill_name = params["skill_name"]
        args = params.get("args", "")
        engine = self._engines.get(session_id)
        if engine is None:
            raise ValueError(f"No active engine for session: {session_id}")

        # Load skill definition and inject as user message
        from holmes.agent.skill_manager import SkillManager

        skill_mgr = SkillManager()
        skill = skill_mgr.get_skill(skill_name)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_name}")
        message = f"[Execute skill: {skill_name}]\n\n{skill.prompt}\n\n{args}".strip()
        params_chat = {"session_id": session_id, "message": message}
        await self._handle_chat_send(params_chat, writer, req_id=req_id)
        return None

    # ---- Context ----

    async def _handle_context_compact(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        session_id = params["session_id"]
        engine = self._engines.get(session_id)
        session = self._sessions.get(session_id) or load_session(session_id)
        if not session or not engine:
            raise ValueError(f"Session not found: {session_id}")

        summary = await engine.compact_context(session)
        session.messages = []
        session.add_message("user", f"[Context compacted]\n\n{summary}")
        save_session(session)

        ctx_mgr = self._context_managers.get(session_id)
        if ctx_mgr:
            ctx_mgr.reset()
            await self._send(writer, _notification("context/update", {
                "session_id": session_id,
                "used_tokens": ctx_mgr.used_tokens,
                "max_tokens": ctx_mgr.max_tokens,
                "warning": False,
            }))
        return {"ok": True, "summary": summary[:200]}

    # ---- Memory ----

    async def _handle_remember(
        self, params: dict[str, Any], writer: asyncio.StreamWriter
    ) -> dict[str, Any]:
        content = params.get("content", "")
        if not content.strip():
            raise ValueError("Content cannot be empty")
        append_to_memory(content)
        return {"ok": True, "message": f"Saved to memory: {content[:60]}"}

    # ---- Helpers ----

    def _make_confirm_callback(self, writer: asyncio.StreamWriter):
        """Create a confirmation callback that uses IPC to ask the TUI."""
        async def confirm(event: ToolConfirmEvent) -> ConfirmDecision:
            await self._send(writer, _notification("agent/tool_confirm", {
                "session_id": event.session_id,
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_name,
                "description": event.description,
                "input_preview": event.input_preview,
            }))
            future: asyncio.Future[ConfirmDecision] = asyncio.get_event_loop().create_future()
            self._pending_confirmations[event.tool_call_id] = future
            try:
                return await asyncio.wait_for(future, timeout=120)
            except asyncio.TimeoutError:
                return (False, "Confirmation timed out")
        return confirm

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, data: dict[str, Any]) -> None:
        """Send a JSON-RPC message as a newline-delimited JSON line."""
        line = json.dumps(data, ensure_ascii=False) + "\n"
        writer.write(line.encode())
        await writer.drain()


def _extract_pending_id(content: str) -> str | None:
    """Parse the pending entry ID from KbWriteEntryTool output.

    Handles the format: "Entry saved to pending area with ID: pending-XXX\\n..."
    Returns None if the ID cannot be extracted.
    """
    import re
    m = re.search(r"(pending-[A-Za-z0-9_-]+)", content)
    return m.group(1) if m else None


def _ok_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _notification(method: str, params: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}
