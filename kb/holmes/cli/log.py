"""Holmes CLI — log group and subcommands."""

from __future__ import annotations

import json
import sys
from typing import Optional

import click

from holmes.cli import cli
from holmes.config import _holmes_home


@cli.group("log")
def log_group() -> None:
    """View Holmes operation logs (traces and spans)."""


@log_group.command("list")
def log_list() -> None:
    """List all traces with a one-line summary each.

    Traces are classified as: import / draft / session / ? based on their spans.
    """
    log_dir = _holmes_home() / "logs"
    if not log_dir.exists():
        click.echo("No log entries found.")
        return

    # Collect all events grouped by trace_id.
    traces: dict[str, list[dict]] = {}
    for jsonl_file in sorted(log_dir.glob("*.jsonl")):
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                tid = str(rec.get("trace", ""))
                if tid:
                    traces.setdefault(tid, []).append(rec)
            except json.JSONDecodeError:
                pass

    if not traces:
        click.echo("No log entries found.")
        return

    def _classify(events: list[dict]) -> str:
        spans = {str(e.get("span", "")) for e in events}
        trace_id = str(events[0].get("trace", "")) if events else ""
        if trace_id.startswith("session-"):
            return "session"
        for sp in spans:
            if sp.startswith("agent1.") or sp.startswith("agent2.") or sp == "lint":
                return "import"
        if "mcp.draft" in spans:
            return "draft"
        return "?"

    def _summary(events: list[dict], kind: str) -> str:
        if kind == "import":
            created = sum(1 for e in events if e.get("span") == "lint" and "created" in str(e.get("msg", "")))
            warns = sum(1 for e in events if e.get("level") == "WARN")
            parts = []
            if created:
                parts.append(f"created={created}")
            if warns:
                parts.append(f"warnings={warns}")
            return " ".join(parts) if parts else "in progress"
        if kind == "draft":
            return "pending import"
        if kind == "session":
            reads = sum(1 for e in events if str(e.get("span", "")).startswith("mcp.kb_read"))
            confirms = sum(1 for e in events if e.get("span") == "mcp.kb_confirm")
            drafts = sum(1 for e in events if e.get("span") == "mcp.draft")
            parts = []
            if reads:
                parts.append(f"read={reads}")
            if confirms:
                parts.append(f"confirmed={confirms}")
            if drafts:
                parts.append(f"draft={drafts}")
            return " ".join(parts) if parts else ""
        return ""

    click.echo(f"{'TRACE':<35} {'TYPE':<10} {'LAST DATE':<12} SUMMARY")
    click.echo("-" * 75)
    for tid, events in sorted(traces.items()):
        kind = _classify(events)
        last_ts = max(str(e.get("ts", "")) for e in events)
        last_date = last_ts[:10] if last_ts else "?"
        summary = _summary(events, kind)
        click.echo(f"{tid:<35} {kind:<10} {last_date:<12} {summary}")


@log_group.command("show")
@click.argument("trace_id")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON Lines.")
@click.option("--since", "since_date", default=None,
              help="Only show events from this date onwards (YYYY-MM-DD).")
def log_show(trace_id: str, as_json: bool, since_date: Optional[str]) -> None:
    """Show the full span timeline for a trace.

    TRACE_ID: The trace identifier (e.g. gpu-troubleshooting or session-a3f1).
    """
    from datetime import date as _date

    log_dir = _holmes_home() / "logs"

    # Validate --since date.
    since: Optional[_date] = None
    if since_date:
        try:
            since = _date.fromisoformat(since_date)
        except ValueError:
            click.echo("Error: --since must be YYYY-MM-DD format", err=True)
            sys.exit(1)

    # Collect matching events from all .jsonl files.
    events: list[dict] = []
    if log_dir.exists():
        for jsonl_file in sorted(log_dir.glob("*.jsonl")):
            # Quick skip: if --since provided and file date is before since, skip.
            if since:
                try:
                    from datetime import date as _d
                    file_date = _d.fromisoformat(jsonl_file.stem)
                    if file_date < since:
                        continue
                except ValueError:
                    pass
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if str(rec.get("trace", "")) != trace_id:
                        continue
                    if since:
                        event_date_str = str(rec.get("ts", ""))[:10]
                        try:
                            if _date.fromisoformat(event_date_str) < since:
                                continue
                        except ValueError:
                            pass
                    events.append(rec)
                except json.JSONDecodeError:
                    pass

    if not events:
        click.echo(f"No events found for trace: {trace_id}")
        return

    # Sort by timestamp.
    events.sort(key=lambda e: str(e.get("ts", "")))

    if as_json:
        for e in events:
            click.echo(json.dumps(e, ensure_ascii=False))
        return

    # Human-readable span tree.
    click.echo(f"trace: {trace_id}")
    click.echo("")

    for e in events:
        ts_str = str(e.get("ts", ""))
        # Format timestamp: remove T and trailing Z for readability.
        display_ts = ts_str.replace("T", " ").replace("Z", "").replace("+00:00", "")[:19]
        span = str(e.get("span", ""))
        level = str(e.get("level", "INFO"))
        msg = str(e.get("msg", ""))
        # Build extra summary from remaining fields.
        skip = {"ts", "trace", "span", "level", "msg"}
        extras = {k: v for k, v in e.items() if k not in skip}
        extra_str = "  ".join(f"{k}={v}" for k, v in extras.items())
        # Duration in seconds if available.
        dur = e.get("duration_ms")
        dur_str = f"{int(dur) // 1000}s" if dur is not None else ""
        level_tag = f" [{level}]" if level in ("WARN", "ERROR") else ""
        line = f"  {display_ts}  {span:<22} {dur_str:<5} {msg}"
        if extra_str:
            line = f"{line}  {extra_str}"
        if level_tag:
            line = f"{line}{level_tag}"
        click.echo(line)
