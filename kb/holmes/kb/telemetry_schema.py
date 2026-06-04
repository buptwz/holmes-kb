"""Telemetry schema: KBEvent Pydantic model and EventType enum."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    WRITE_PENDING = "kb.write_pending"
    CONFIRM = "kb.confirm"
    REJECT = "kb.reject"
    CORRECTION_APPLIED = "kb.correction_applied"
    DECAY = "kb.decay"
    ARCHIVE_ORPHAN = "kb.archive_orphan"
    UPDATE_REFS = "kb.update_refs"
    HEALTH_SNAPSHOT = "kb.health_snapshot"
    BUFFER_OVERFLOW = "kb.buffer_overflow"


class KBEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    contributor: str
    contributor_is_fallback: bool = False
    entry_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str  # ISO 8601 UTC
    metadata: Optional[dict[str, Any]] = None
    holmes_version: str = "0.1.0"
