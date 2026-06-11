"""Session management for Holmes Agent.

Sessions are persisted as JSON files in ~/.holmes/sessions/{id}.json.
Each session tracks messages, tool calls, and KB references.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from holmes.logging_config import get_logger


logger = get_logger("agent.session")

SESSIONS_DIR = Path.home() / ".holmes" / "sessions"

SessionStatus = Literal["active", "resolved", "abandoned"]


class ToolCallRecord(BaseModel):
    """Record of a single tool call within a session."""

    id: str
    tool_name: str
    input: dict[str, Any]
    output: Optional[str] = None
    status: Literal["pending", "running", "done", "denied", "error"] = "pending"
    started_at: str = Field(default_factory=lambda: _now_iso())
    ended_at: Optional[str] = None


class MessageRecord(BaseModel):
    """Record of a single conversation message."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: str = Field(default_factory=lambda: _now_iso())


class Session(BaseModel):
    """A troubleshooting session."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Session"
    status: SessionStatus = "active"
    created_at: str = Field(default_factory=lambda: _now_iso())
    updated_at: str = Field(default_factory=lambda: _now_iso())
    messages: list[MessageRecord] = []
    tool_calls: list[ToolCallRecord] = []
    kb_entry_id: Optional[str] = None

    def add_message(self, role: str, content: str) -> MessageRecord:
        """Append a message to the session.

        Args:
            role: 'user' or 'assistant'.
            content: Message content.

        Returns:
            The created MessageRecord.
        """
        record = MessageRecord(role=role, content=content)  # type: ignore[arg-type]
        self.messages.append(record)
        if self.title == "New Session" and role == "user" and len(self.messages) == 1:
            self.title = content[:60] + ("..." if len(content) > 60 else "")
        self.updated_at = _now_iso()
        return record

    def start_tool_call(
        self, tool_call_id: str, tool_name: str, input_data: dict[str, Any]
    ) -> ToolCallRecord:
        """Record the start of a tool call.

        Args:
            tool_call_id: Unique ID for this tool call.
            tool_name: Name of the tool.
            input_data: Tool input parameters.

        Returns:
            The created ToolCallRecord.
        """
        record = ToolCallRecord(
            id=tool_call_id,
            tool_name=tool_name,
            input=input_data,
            status="running",
        )
        self.tool_calls.append(record)
        self.updated_at = _now_iso()
        return record

    def finish_tool_call(
        self,
        tool_call_id: str,
        output: str,
        status: Literal["done", "denied", "error"] = "done",
    ) -> None:
        """Update a tool call record with its result.

        Args:
            tool_call_id: ID of the tool call to update.
            output: Tool output string.
            status: Final status.
        """
        for record in self.tool_calls:
            if record.id == tool_call_id:
                record.output = output
                record.status = status
                record.ended_at = _now_iso()
                break
        self.updated_at = _now_iso()

    def resolve(self) -> None:
        """Mark session as resolved."""
        self.status = "resolved"
        self.updated_at = _now_iso()

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a summary dict for listing."""
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_session(session: Session) -> Path:
    """Persist session to ~/.holmes/sessions/{id}.json.

    Args:
        session: Session to save.

    Returns:
        Path where the session was written.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{session.id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(session.model_dump(), f, indent=2, ensure_ascii=False)
    logger.debug("Saved session %s", session.id)
    return path


def load_session(session_id: str) -> Optional[Session]:
    """Load a session by ID.

    Args:
        session_id: Session UUID.

    Returns:
        Session if found, None otherwise.
    """
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Session(**data)


def list_sessions(
    status: Optional[SessionStatus] = None, limit: int = 50
) -> list[dict[str, Any]]:
    """List sessions ordered by updated_at descending.

    Args:
        status: Optional status filter.
        limit: Maximum number of sessions to return.

    Returns:
        List of session summary dicts.
    """
    if not SESSIONS_DIR.exists():
        return []
    sessions: list[Session] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append(Session(**data))
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Could not load session from %s: %s", path, e)

    if status:
        sessions = [s for s in sessions if s.status == status]

    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return [s.to_summary_dict() for s in sessions[:limit]]
