"""Unit tests for telemetry buffer: emit_event, _trim_buffer, trigger_flush_async."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holmes.kb.telemetry_schema import EventType, KBEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, enabled: bool = True) -> MagicMock:
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.buffer_path = tmp_path / "telemetry.jsonl"
    cfg.max_buffer_bytes = 1024 * 1024  # 1 MB for tests
    cfg.flush_timeout_secs = 5
    cfg.collector_endpoint = "http://localhost:4318"
    return cfg


# ---------------------------------------------------------------------------
# emit_event
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_disabled_noop(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path, enabled=False)
        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import emit_event

            emit_event(EventType.CONFIRM, contributor="alice")
        assert not cfg.buffer_path.exists()

    def test_writes_jsonl_line(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import emit_event

            emit_event(EventType.CONFIRM, contributor="alice", entry_id="e1")

        lines = cfg.buffer_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "kb.confirm"
        assert data["contributor"] == "alice"
        assert data["entry_id"] == "e1"

    def test_appends_multiple_events(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import emit_event

            emit_event(EventType.CONFIRM, contributor="alice")
            emit_event(EventType.REJECT, contributor="bob")

        lines = cfg.buffer_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_swallows_exceptions(self, tmp_path: Path) -> None:
        """emit_event must never raise."""
        with patch("holmes.kb.telemetry.load_telemetry_config", side_effect=RuntimeError("boom")):
            from holmes.kb.telemetry import emit_event

            # Should not raise
            emit_event(EventType.CONFIRM, contributor="alice")

    def test_auto_resolves_contributor(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        with (
            patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg),
            patch("holmes.kb.telemetry.get_contributor_identity", return_value=("auto-host", True)),
        ):
            from holmes.kb.telemetry import emit_event

            emit_event(EventType.CONFIRM)

        data = json.loads(cfg.buffer_path.read_text().strip())
        assert data["contributor"] == "auto-host"
        assert data["contributor_is_fallback"] is True


# ---------------------------------------------------------------------------
# _trim_buffer
# ---------------------------------------------------------------------------


class TestTrimBuffer:
    def test_trims_oldest_lines(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.max_buffer_bytes = 200  # very small limit

        # Write 10 lines
        lines = []
        for i in range(10):
            ev = KBEvent(
                event_type=EventType.CONFIRM,
                contributor="x",
                timestamp="2024-01-01T00:00:00Z",
                metadata={"seq": i},
            )
            lines.append(ev.model_dump_json())

        cfg.buffer_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        from holmes.kb.telemetry import _trim_buffer

        _trim_buffer(cfg.buffer_path, cfg)

        remaining = cfg.buffer_path.read_text(encoding="utf-8").splitlines(keepends=True)
        # Last line should be buffer_overflow sentinel
        sentinel = json.loads(remaining[-1])
        assert sentinel["event_type"] == "kb.buffer_overflow"
        assert sentinel["metadata"]["dropped_count"] > 0

        # Offset should be reset to 0
        offset_path = cfg.buffer_path.parent / "telemetry.offset"
        assert offset_path.read_text(encoding="utf-8").strip() == "0"

    def test_no_trim_if_within_limit(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.max_buffer_bytes = 100_000

        cfg.buffer_path.write_text('{"event_type":"kb.confirm"}\n', encoding="utf-8")

        from holmes.kb.telemetry import _trim_buffer

        _trim_buffer(cfg.buffer_path, cfg)

        # No sentinel appended since no drop occurred
        content = cfg.buffer_path.read_text(encoding="utf-8")
        assert "buffer_overflow" not in content


# ---------------------------------------------------------------------------
# trigger_flush_async
# ---------------------------------------------------------------------------


class TestTriggerFlushAsync:
    def test_disabled_noop(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path, enabled=False)
        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import trigger_flush_async

            with patch("os.fork") as mock_fork:
                trigger_flush_async()
                mock_fork.assert_not_called()

    def test_skips_when_within_cooldown(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        last_flush_path = tmp_path / "telemetry.last_flush"
        last_flush_path.write_text(str(time.time()), encoding="utf-8")

        cfg.buffer_path.write_text('{"event_type":"kb.confirm"}\n', encoding="utf-8")

        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import trigger_flush_async

            with patch("os.fork") as mock_fork:
                trigger_flush_async()
                mock_fork.assert_not_called()

    def test_no_buffer_noop(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import trigger_flush_async

            with patch("os.fork") as mock_fork:
                trigger_flush_async()
                mock_fork.assert_not_called()

    def test_forks_when_pending_data(self, tmp_path: Path) -> None:
        cfg = _make_config(tmp_path)
        cfg.buffer_path.write_text('{"event_type":"kb.confirm"}\n', encoding="utf-8")
        # No last flush file → will trigger

        with patch("holmes.kb.telemetry.load_telemetry_config", return_value=cfg):
            from holmes.kb.telemetry import trigger_flush_async

            with patch("os.fork", return_value=1) as mock_fork:  # parent PID=1, skip child
                trigger_flush_async()
                mock_fork.assert_called_once()
