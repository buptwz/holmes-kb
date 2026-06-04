"""Unit tests for telemetry schema: KBEvent and EventType."""

from __future__ import annotations

import json

import pytest

from holmes.kb.telemetry_schema import EventType, KBEvent


class TestEventType:
    def test_all_values_have_kb_prefix(self) -> None:
        for et in EventType:
            assert et.value.startswith("kb.")

    def test_string_coercion(self) -> None:
        assert EventType("kb.confirm") is EventType.CONFIRM

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            EventType("kb.nonexistent")

    def test_known_values(self) -> None:
        assert EventType.WRITE_PENDING.value == "kb.write_pending"
        assert EventType.CONFIRM.value == "kb.confirm"
        assert EventType.REJECT.value == "kb.reject"
        assert EventType.CORRECTION_APPLIED.value == "kb.correction_applied"
        assert EventType.DECAY.value == "kb.decay"
        assert EventType.ARCHIVE_ORPHAN.value == "kb.archive_orphan"
        assert EventType.UPDATE_REFS.value == "kb.update_refs"
        assert EventType.HEALTH_SNAPSHOT.value == "kb.health_snapshot"
        assert EventType.BUFFER_OVERFLOW.value == "kb.buffer_overflow"


class TestKBEvent:
    def test_defaults(self) -> None:
        ev = KBEvent(
            event_type=EventType.CONFIRM,
            contributor="alice",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        assert ev.contributor == "alice"
        assert ev.event_id  # non-empty UUID
        assert ev.contributor_is_fallback is False
        assert ev.entry_id is None
        assert ev.session_id is None
        assert ev.metadata is None
        assert ev.holmes_version == "0.1.0"

    def test_event_id_unique(self) -> None:
        ev1 = KBEvent(event_type=EventType.CONFIRM, contributor="a", timestamp="t")
        ev2 = KBEvent(event_type=EventType.CONFIRM, contributor="a", timestamp="t")
        assert ev1.event_id != ev2.event_id

    def test_model_dump_json_roundtrip(self) -> None:
        ev = KBEvent(
            event_type=EventType.REJECT,
            contributor="bob",
            timestamp="2024-06-01T12:00:00Z",
            entry_id="entry-42",
            session_id="sess-1",
            metadata={"reason": "duplicate"},
        )
        raw = ev.model_dump_json()
        data = json.loads(raw)
        assert data["event_type"] == "kb.reject"
        assert data["contributor"] == "bob"
        assert data["entry_id"] == "entry-42"
        assert data["metadata"] == {"reason": "duplicate"}

    def test_contributor_is_fallback(self) -> None:
        ev = KBEvent(
            event_type=EventType.DECAY,
            contributor="hostname",
            contributor_is_fallback=True,
            timestamp="t",
        )
        assert ev.contributor_is_fallback is True

    def test_buffer_overflow_event(self) -> None:
        ev = KBEvent(
            event_type=EventType.BUFFER_OVERFLOW,
            contributor="system",
            timestamp="2024-01-01T00:00:00Z",
            metadata={"dropped_count": 100, "buffer_size_bytes": 524288000},
        )
        assert ev.event_type == EventType.BUFFER_OVERFLOW
        assert ev.metadata["dropped_count"] == 100
