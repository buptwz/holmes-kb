"""Telemetry forwarder: read JSONL buffer → POST to OTel Collector via OTLP/HTTP.

Run as: python -m holmes.kb.telemetry_forwarder --once
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


_BATCH_SIZE = 500
_MAX_SENT_IDS = 50_000


def _load_config() -> Any:
    try:
        from holmes.kb.telemetry import load_telemetry_config
        return load_telemetry_config()
    except Exception:  # noqa: BLE001
        return None


def _read_pending_lines(buf_path: Path, offset_path: Path) -> tuple[list[dict], int]:
    """Read unforwarded lines from buffer starting at offset. Returns (events, end_offset)."""
    try:
        offset = int(offset_path.read_text(encoding="utf-8").strip()) if offset_path.exists() else 0
    except Exception:  # noqa: BLE001
        offset = 0

    if not buf_path.exists():
        return [], offset

    try:
        with open(buf_path, "rb") as f:
            f.seek(offset)
            raw = f.read()
        end_offset = offset + len(raw)
    except Exception:  # noqa: BLE001
        return [], offset

    events = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:  # noqa: BLE001
            pass

    return events, end_offset


def _load_sent_ids(sent_ids_path: Path) -> set[str]:
    if not sent_ids_path.exists():
        return set()
    try:
        return set(sent_ids_path.read_text(encoding="utf-8").splitlines())
    except Exception:  # noqa: BLE001
        return set()


def _save_sent_ids(sent_ids_path: Path, ids: set[str]) -> None:
    try:
        lines = list(ids)[-_MAX_SENT_IDS:]
        sent_ids_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _build_otlp_payload(events: list[dict]) -> bytes:
    """Build OTLP/HTTP JSON payload from a list of KBEvent dicts."""
    log_records = []
    for ev in events:
        ts_ns = _iso_to_ns(ev.get("timestamp", ""))
        severity = "WARN" if ev.get("event_type") == "kb.buffer_overflow" else "INFO"
        record = {
            "timeUnixNano": str(ts_ns),
            "severityText": severity,
            "body": {"stringValue": json.dumps(ev, ensure_ascii=False)},
            "attributes": [
                {"key": "event_id", "value": {"stringValue": str(ev.get("event_id", ""))}},
                {"key": "event_type", "value": {"stringValue": str(ev.get("event_type", ""))}},
                {"key": "contributor", "value": {"stringValue": str(ev.get("contributor", ""))}},
                {"key": "entry_id", "value": {"stringValue": str(ev.get("entry_id") or "")}},
            ],
        }
        log_records.append(record)

    payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "holmes-kb-cli"}},
                        {"key": "holmes.version", "value": {"stringValue": "0.1.0"}},
                    ]
                },
                "scopeLogs": [{"logRecords": log_records}],
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _iso_to_ns(iso: str) -> int:
    """Convert ISO 8601 UTC string to nanoseconds since Unix epoch."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except Exception:  # noqa: BLE001
        return 0


def _post_batch(endpoint: str, payload: bytes, timeout: int) -> int:
    """POST OTLP payload. Returns HTTP status code, or 0 on connection error."""
    url = endpoint + "/v1/logs"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def flush_once() -> None:
    """Read pending events from buffer and send to OTel Collector."""
    cfg = _load_config()
    if cfg is None or not cfg.enabled:
        return

    buf_path = cfg.buffer_path
    offset_path = buf_path.parent / "telemetry.offset"
    sent_ids_path = buf_path.parent / "telemetry.sent_ids"
    last_flush_path = buf_path.parent / "telemetry.last_flush"

    events, end_offset = _read_pending_lines(buf_path, offset_path)
    if not events:
        _update_last_flush(last_flush_path)
        return

    sent_ids = _load_sent_ids(sent_ids_path)

    # Filter already-sent events.
    new_events = [e for e in events if e.get("event_id") not in sent_ids]
    if not new_events:
        # Advance offset even if all dupes.
        _write_offset(offset_path, end_offset)
        _update_last_flush(last_flush_path)
        return

    # Send in batches.
    newly_sent: list[str] = []
    batch_start = 0
    success = True

    while batch_start < len(new_events):
        batch = new_events[batch_start: batch_start + _BATCH_SIZE]
        payload = _build_otlp_payload(batch)
        retries = 0
        status = 0
        while retries < 3:
            status = _post_batch(cfg.collector_endpoint, payload, cfg.flush_timeout_secs)
            if status == 200:
                break
            if status in (429, 500, 502, 503, 504):
                time.sleep(2 ** retries)
                retries += 1
            elif status == 400:
                break  # Bad payload — skip, don't retry
            else:
                # Connection error or unknown
                success = False
                break
        if status == 200:
            for ev in batch:
                eid = ev.get("event_id", "")
                if eid:
                    newly_sent.append(eid)
        elif status == 400:
            # Skip bad batch, still advance
            pass
        else:
            success = False
            break  # Stop processing further batches on connection error
        batch_start += _BATCH_SIZE

    if newly_sent:
        sent_ids.update(newly_sent)
        _save_sent_ids(sent_ids_path, sent_ids)

    if success:
        _write_offset(offset_path, end_offset)
        _update_last_flush(last_flush_path)


def _write_offset(offset_path: Path, offset: int) -> None:
    try:
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        offset_path.write_text(str(offset), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _update_last_flush(last_flush_path: Path) -> None:
    try:
        last_flush_path.write_text(str(time.time()), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    if "--once" in sys.argv:
        flush_once()
