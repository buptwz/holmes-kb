"""CLI-side telemetry: emit KBEvents to local JSONL buffer and trigger async flush."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from holmes.kb.telemetry_schema import EventType, KBEvent

_HOLMES_VERSION = "0.1.0"
_FLUSH_COOLDOWN_SECS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TelemetryConfig:
    def __init__(
        self,
        enabled: bool = True,
        collector_endpoint: str = "http://localhost:4318",
        buffer_path: str = "~/.holmes/telemetry.jsonl",
        max_buffer_mb: int = 500,
        flush_timeout_secs: int = 10,
        enabled_events: Optional[list[str]] = None,
    ) -> None:
        self.enabled = enabled
        self.collector_endpoint = collector_endpoint.rstrip("/")
        self.buffer_path = Path(buffer_path).expanduser()
        self.max_buffer_bytes = max(10, min(10_000, max_buffer_mb)) * 1_048_576
        self.flush_timeout_secs = flush_timeout_secs
        # None means "all events enabled"; a list means only those event types are emitted.
        self.enabled_events: Optional[set[str]] = set(enabled_events) if enabled_events is not None else None

    def is_event_enabled(self, event_type: str) -> bool:
        """Return True if this event type should be emitted."""
        if self.enabled_events is None:
            return True
        return event_type in self.enabled_events


def load_telemetry_config() -> TelemetryConfig:
    """Load TelemetryConfig from HolmesConfig, applying env var overrides."""
    try:
        from holmes.config import load_config
        cfg = load_config()
        enabled = cfg.telemetry_enabled
        endpoint = cfg.otel_collector_endpoint
        buffer_path = cfg.telemetry_buffer_path
        max_mb = cfg.telemetry_max_buffer_mb
        timeout = cfg.telemetry_flush_timeout_secs
        enabled_events = cfg.telemetry_enabled_events  # list[str] or None
    except Exception:  # noqa: BLE001
        enabled = True
        endpoint = "http://localhost:4318"
        buffer_path = "~/.holmes/telemetry.jsonl"
        max_mb = 500
        timeout = 10
        enabled_events = None

    # Env var overrides.
    env_enabled = os.environ.get("HOLMES_TELEMETRY_ENABLED")
    if env_enabled is not None:
        enabled = env_enabled.lower() not in ("0", "false", "no", "off")
    env_endpoint = os.environ.get("HOLMES_OTEL_ENDPOINT")
    if env_endpoint:
        endpoint = env_endpoint
    env_buffer = os.environ.get("HOLMES_TELEMETRY_BUFFER_PATH")
    if env_buffer:
        buffer_path = env_buffer
    # HOLMES_TELEMETRY_EVENTS=kb.confirm,kb.reject  (comma-separated, overrides config)
    env_events = os.environ.get("HOLMES_TELEMETRY_EVENTS")
    if env_events is not None:
        enabled_events = [e.strip() for e in env_events.split(",") if e.strip()] or None

    # Validate endpoint URL.
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        enabled = False

    return TelemetryConfig(
        enabled=enabled,
        collector_endpoint=endpoint,
        buffer_path=buffer_path,
        max_buffer_mb=max_mb,
        flush_timeout_secs=timeout,
        enabled_events=enabled_events,
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def get_contributor_identity() -> tuple[str, bool]:
    """Return (contributor_id, is_fallback).

    Uses config contributor field; falls back to system hostname.
    """
    try:
        from holmes.config import load_config
        cfg = load_config()
        contributor = getattr(cfg, "contributor", None)
        if contributor and contributor.strip():
            return contributor.strip(), False
    except Exception:  # noqa: BLE001
        pass
    try:
        return os.uname().nodename, True
    except Exception:  # noqa: BLE001
        return "unknown", True


# ---------------------------------------------------------------------------
# Buffer write
# ---------------------------------------------------------------------------


def emit_event(
    event_type: EventType | str,
    contributor: Optional[str] = None,
    entry_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Append one KBEvent JSON line to the local JSONL buffer.

    Silently swallows ALL exceptions — telemetry must never break the CLI.
    No-op when telemetry is disabled.
    """
    try:
        cfg = load_telemetry_config()
        if not cfg.enabled:
            return

        # Resolve event_type before the filter check.
        if isinstance(event_type, str):
            event_type = EventType(event_type)

        if not cfg.is_event_enabled(event_type.value):
            return

        if contributor is None:
            contributor, is_fallback = get_contributor_identity()
        else:
            is_fallback = False

        now_iso = datetime.now(timezone.utc).isoformat()
        event = KBEvent(
            event_type=event_type,
            contributor=contributor,
            contributor_is_fallback=is_fallback,
            entry_id=entry_id,
            session_id=session_id,
            timestamp=now_iso,
            metadata=metadata,
            holmes_version=_HOLMES_VERSION,
        )

        buf = cfg.buffer_path
        buf.parent.mkdir(parents=True, exist_ok=True)

        line = event.model_dump_json() + "\n"
        with open(buf, "a", encoding="utf-8") as f:
            f.write(line)

        # Check overflow asynchronously.
        buf_size = buf.stat().st_size
        if buf_size > cfg.max_buffer_bytes:
            t = threading.Thread(target=_trim_buffer, args=(buf, cfg), daemon=True)
            t.start()

    except Exception:  # noqa: BLE001
        pass


def _trim_buffer(buf: Path, cfg: TelemetryConfig) -> None:
    """Trim oldest lines from buffer when size exceeds limit. Lock-protected."""
    try:
        lock_path = buf.parent / "telemetry.lock"
        import fcntl
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                content = buf.read_text(encoding="utf-8")
                lines = content.splitlines(keepends=True)
                target = int(cfg.max_buffer_bytes * 0.8)
                # Remove oldest lines until size ≤ 80% of limit.
                dropped = 0
                while lines:
                    current_size = sum(len(l.encode()) for l in lines)
                    if current_size <= target:
                        break
                    lines.pop(0)
                    dropped += 1
                if dropped > 0:
                    # Append overflow sentinel before rewriting.
                    old_size = buf.stat().st_size
                    overflow_event = KBEvent(
                        event_type=EventType.BUFFER_OVERFLOW,
                        contributor="system",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        metadata={"dropped_count": dropped, "buffer_size_bytes": old_size},
                        holmes_version=_HOLMES_VERSION,
                    )
                    lines.append(overflow_event.model_dump_json() + "\n")
                    buf.write_text("".join(lines), encoding="utf-8")
                    # Reset offset since lines before old offset may have been removed.
                    offset_path = buf.parent / "telemetry.offset"
                    offset_path.write_text("0", encoding="utf-8")
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Async flush trigger
# ---------------------------------------------------------------------------


def trigger_flush_async() -> None:
    """Fork a background process to flush the JSONL buffer to OTel Collector.

    Checks last flush timestamp; only forks if > FLUSH_COOLDOWN_SECS ago.
    Silently swallows all exceptions.
    """
    try:
        cfg = load_telemetry_config()
        if not cfg.enabled:
            return

        # Check cooldown.
        last_flush_path = cfg.buffer_path.parent / "telemetry.last_flush"
        if last_flush_path.exists():
            try:
                last_ts = float(last_flush_path.read_text(encoding="utf-8").strip())
                import time
                if time.time() - last_ts < _FLUSH_COOLDOWN_SECS:
                    return
            except Exception:  # noqa: BLE001
                pass

        # Check if there's anything to flush.
        if not cfg.buffer_path.exists():
            return

        offset_path = cfg.buffer_path.parent / "telemetry.offset"
        try:
            offset = int(offset_path.read_text(encoding="utf-8").strip()) if offset_path.exists() else 0
        except Exception:  # noqa: BLE001
            offset = 0

        if cfg.buffer_path.stat().st_size <= offset:
            return

        # Fork forwarder.
        pid = os.fork()
        if pid == 0:
            # Child: exec forwarder.
            try:
                os.setsid()
                os.execv(sys.executable, [sys.executable, "-m", "holmes.kb.telemetry_forwarder", "--once"])
            except Exception:  # noqa: BLE001
                os._exit(0)  # noqa: SLF001
        # Parent returns immediately.

    except Exception:  # noqa: BLE001
        pass
