"""Unified progress reporting for Holmes CLI operations.

All user-facing progress goes through ProgressReporter so that:
  - Output destination (stderr / callback / silent) is configured once.
  - Every step produces a consistent format.
  - New integration points only need ``reporter.update(...)`` or similar.

Usage::

    from holmes.kb.progress import ProgressReporter, NullReporter

    reporter = ProgressReporter.stderr()   # CLI default
    reporter = NullReporter()              # tests / MCP / silent

    reporter.start("文档分类中")
    reporter.done("分类完成: incident / complex")
    reporter.step(1, 3, "Summarizer → 提取摘要")
    reporter.info("分类结果: pitfall / network")
    reporter.warn("Fidelity check 失败，重试生成")
"""

from __future__ import annotations

import sys
import threading
from typing import Callable, Optional


class ProgressReporter:
    """Thread-safe progress reporter that writes to an output function.

    Parameters:
        output_fn: A callable ``(str) -> None``. Each call emits one line.
    """

    def __init__(self, output_fn: Callable[[str], None]) -> None:
        self._out = output_fn
        self._lock = threading.Lock()

    # -- Factory helpers ---------------------------------------------------

    @classmethod
    def stderr(cls) -> "ProgressReporter":
        """Create a reporter that writes to stderr (suitable for CLI)."""
        def _write_stderr(msg: str) -> None:
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        return cls(_write_stderr)

    @classmethod
    def from_click(cls) -> "ProgressReporter":
        """Create a reporter using ``click.echo(..., err=True)``."""
        import click
        return cls(lambda msg: click.echo(msg, err=True))

    # -- Public API --------------------------------------------------------

    def start(self, msg: str) -> None:
        """Emit an "in-progress" message (⠿ prefix)."""
        self._emit(f"⠿ {msg}")

    def done(self, msg: str) -> None:
        """Emit a "completed" message (✓ prefix)."""
        self._emit(f"✓ {msg}")

    def step(self, current: int, total: int, msg: str) -> None:
        """Emit a step progress line: ``[current/total] msg``."""
        self._emit(f"  [{current}/{total}] {msg}")

    def info(self, msg: str) -> None:
        """Emit an informational message (no prefix)."""
        self._emit(f"  {msg}")

    def warn(self, msg: str) -> None:
        """Emit a warning message (⚠ prefix)."""
        self._emit(f"⚠ {msg}")

    def update(self, msg: str) -> None:
        """Generic progress update — the lowest-level emit with no prefix.

        Use this when existing prefixes don't fit (e.g. tool-call detail).
        """
        self._emit(msg)

    # -- Internal ----------------------------------------------------------

    def _emit(self, line: str) -> None:
        with self._lock:
            try:
                self._out(line)
            except Exception:  # noqa: BLE001
                pass  # Never let progress output crash the pipeline.


class NullReporter(ProgressReporter):
    """A reporter that discards all messages (for tests and MCP)."""

    def __init__(self) -> None:  # noqa: D107
        super().__init__(lambda _msg: None)
