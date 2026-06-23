"""Holmes observability: dual-format log writer (human-readable .log + JSON Lines .jsonl).

Usage::

    from holmes.kb.logger import HolmesLogger, derive_trace_id

    logger = HolmesLogger(log_dir=Path("~/.holmes/logs").expanduser(), verbose=False)
    logger.write_span("gpu-troubleshooting", "agent1.draft", "INFO", "write_dag", nodes=8)
    logger.rotate()

    trace_id = derive_trace_id("gpu-troubleshooting.md")
    trace_id = derive_trace_id("gpu-troubleshooting.md", "a3f1b2c3")  # → "gpu-troubleshooting-a3f1"
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def derive_trace_id(source_file: str, source_hash: str = "") -> str:
    """Derive a trace_id from a source file path.

    Args:
        source_file: Path to the source file (or just the filename).
        source_hash: Optional hash for disambiguation when multiple files share
                     the same stem.  Only the first 4 characters are used.

    Returns:
        trace_id string, e.g. "gpu-troubleshooting" or "gpu-troubleshooting-a3f1".
    """
    stem = Path(source_file).stem
    if source_hash:
        return f"{stem}-{source_hash[:4]}"
    return stem


class HolmesLogger:
    """Dual-format logger that writes to ~/.holmes/logs/<YYYY-MM-DD>.{log,jsonl}.

    Each write_span call appends:
    - One JSON Lines record to  <today>.jsonl
    - One human-readable line to <today>.log

    The logger is a plain instance (not a singleton) so tests can inject a
    temporary directory and other modules can hold independent instances.
    """

    def __init__(self, log_dir: Path, verbose: bool = False) -> None:
        """Initialise the logger and ensure the log directory exists.

        Args:
            log_dir: Directory for log files, e.g. ~/.holmes/logs/.
            verbose: When True, write_span also prints the human-readable line
                     to stdout (useful for ``holmes import --verbose``).
        """
        self.log_dir = log_dir
        self.verbose = verbose
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Core write method
    # ------------------------------------------------------------------

    def write_span(
        self,
        trace_id: str,
        span: str,
        level: str,
        msg: str,
        **extra: object,
    ) -> None:
        """Write a single span event to both .jsonl and .log files.

        Args:
            trace_id: Identifier for the document/session trace
                      (e.g. "gpu-troubleshooting" or "session-a3f1").
            span:     Name of the operation step (e.g. "agent1.draft", "lint").
            level:    Log level string: "INFO", "WARN", or "ERROR".
            msg:      Short event description (e.g. "write_dag", "ok").
            **extra:  Arbitrary additional fields appended to both formats
                      (e.g. nodes=8, duration_ms=42100, entry_id="PT-001").
        """
        now = datetime.now(timezone.utc)
        ts = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        today = now.strftime("%Y-%m-%d")

        # Build the JSON record (required fields first, then extras).
        record: dict[str, object] = {
            "ts": ts,
            "trace": trace_id,
            "span": span,
            "level": level,
            "msg": msg,
        }
        record.update(extra)

        # Write .jsonl (JSON Lines)
        jsonl_path = self.log_dir / f"{today}.jsonl"
        with jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Build human-readable line
        extra_str = " ".join(f"{k}={v}" for k, v in extra.items())
        log_line = f"{ts} [{level:<5}] {trace_id} | {span} | {msg}"
        if extra_str:
            log_line = f"{log_line} {extra_str}"

        # Write .log (human-readable)
        log_path = self.log_dir / f"{today}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(log_line + "\n")

        if self.verbose:
            print(log_line)

    # ------------------------------------------------------------------
    # Log rotation
    # ------------------------------------------------------------------

    def rotate(self) -> None:
        """Delete .log and .jsonl files older than 30 days.

        Files whose stem cannot be parsed as a YYYY-MM-DD date are silently
        skipped (e.g. README.txt, other non-log files in the directory).
        """
        cutoff = date.today() - timedelta(days=30)
        for pattern in ("*.log", "*.jsonl"):
            for f in self.log_dir.glob(pattern):
                try:
                    file_date = date.fromisoformat(f.stem)
                    if file_date < cutoff:
                        f.unlink()
                except ValueError:
                    pass  # not a date-named file — skip
