"""Integration test for telemetry_forwarder: mock OTLP server + flush_once()."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from holmes.kb.telemetry_schema import EventType, KBEvent


def _mock_otlp_server(host: str = "127.0.0.1") -> tuple[HTTPServer, list[bytes]]:
    """Start a minimal HTTP server that accepts OTLP POST and records bodies."""
    received: list[bytes] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            received.append(body)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:  # suppress server output
            pass

    server = HTTPServer((host, 0), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, received


def _make_config(tmp_path: Path, endpoint: str) -> MagicMock:
    cfg = MagicMock()
    cfg.enabled = True
    cfg.buffer_path = tmp_path / "telemetry.jsonl"
    cfg.collector_endpoint = endpoint
    cfg.flush_timeout_secs = 5
    return cfg


class TestFlushOnce:
    def test_posts_events_to_mock_server(self, tmp_path: Path) -> None:
        server, received = _mock_otlp_server()
        port = server.server_address[1]
        endpoint = f"http://127.0.0.1:{port}"

        cfg = _make_config(tmp_path, endpoint)

        # Write 3 events to buffer.
        events = []
        for i in range(3):
            ev = KBEvent(
                event_type=EventType.CONFIRM,
                contributor=f"user{i}",
                timestamp="2024-01-01T00:00:00Z",
                entry_id=f"entry-{i}",
            )
            events.append(ev)
            (tmp_path / "telemetry.jsonl").open("a").write(ev.model_dump_json() + "\n")

        with patch("holmes.kb.telemetry_forwarder._load_config", return_value=cfg):
            from holmes.kb.telemetry_forwarder import flush_once
            flush_once()

        server.shutdown()

        # Should have received exactly 1 batch POST (3 events < batch size 500).
        assert len(received) == 1
        payload = json.loads(received[0])
        log_records = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
        assert len(log_records) == 3

        # Check event_ids match.
        sent_event_ids = {r["attributes"][0]["value"]["stringValue"] for r in log_records}
        expected_event_ids = {e.event_id for e in events}
        assert sent_event_ids == expected_event_ids

    def test_advances_offset_after_flush(self, tmp_path: Path) -> None:
        server, _ = _mock_otlp_server()
        port = server.server_address[1]
        endpoint = f"http://127.0.0.1:{port}"

        cfg = _make_config(tmp_path, endpoint)

        ev = KBEvent(
            event_type=EventType.REJECT,
            contributor="bob",
            timestamp="2024-01-01T00:00:00Z",
        )
        buf = tmp_path / "telemetry.jsonl"
        buf.write_text(ev.model_dump_json() + "\n", encoding="utf-8")

        with patch("holmes.kb.telemetry_forwarder._load_config", return_value=cfg):
            from holmes.kb.telemetry_forwarder import flush_once
            flush_once()

        server.shutdown()

        offset_path = tmp_path / "telemetry.offset"
        assert offset_path.exists()
        assert int(offset_path.read_text().strip()) == buf.stat().st_size

    def test_deduplication_skips_already_sent(self, tmp_path: Path) -> None:
        server, received = _mock_otlp_server()
        port = server.server_address[1]
        endpoint = f"http://127.0.0.1:{port}"

        cfg = _make_config(tmp_path, endpoint)

        ev = KBEvent(
            event_type=EventType.CONFIRM,
            contributor="alice",
            timestamp="2024-01-01T00:00:00Z",
        )
        buf = tmp_path / "telemetry.jsonl"
        buf.write_text(ev.model_dump_json() + "\n", encoding="utf-8")

        # Pre-populate sent_ids with this event's ID.
        sent_ids_path = tmp_path / "telemetry.sent_ids"
        sent_ids_path.write_text(ev.event_id + "\n", encoding="utf-8")

        with patch("holmes.kb.telemetry_forwarder._load_config", return_value=cfg):
            from holmes.kb.telemetry_forwarder import flush_once
            flush_once()

        server.shutdown()

        # No POST should have been made (all events already sent).
        assert len(received) == 0

    def test_noop_when_disabled(self, tmp_path: Path) -> None:
        server, received = _mock_otlp_server()
        port = server.server_address[1]
        endpoint = f"http://127.0.0.1:{port}"

        cfg = _make_config(tmp_path, endpoint)
        cfg.enabled = False

        ev = KBEvent(
            event_type=EventType.CONFIRM,
            contributor="alice",
            timestamp="2024-01-01T00:00:00Z",
        )
        (tmp_path / "telemetry.jsonl").write_text(ev.model_dump_json() + "\n", encoding="utf-8")

        with patch("holmes.kb.telemetry_forwarder._load_config", return_value=cfg):
            from holmes.kb.telemetry_forwarder import flush_once
            flush_once()

        server.shutdown()
        assert len(received) == 0
