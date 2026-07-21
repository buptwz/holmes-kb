"""Reproduction tests for spec 043 first-tier breakages (P1/P2/P3).

Each test asserts the DESIRED behavior and is expected to FAIL before the
corresponding fix lands:

- P2: import writes pending to ``contributions/pending/`` but approve only
  scans ``_pending/`` -> import->approve chain broken.
- P3: management commands registered only on hidden ``kb`` group ->
  ``holmes approve`` etc. do not exist as documented.
- P1: ``kb_read(detail="full")`` records a ``referenced`` evidence under the
  caller's session_id, so the follow-up ``kb_confirm`` with the same
  session_id is rejected as duplicate -> maturity can never be promoted
  through the documented workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.pending import write_pending
from holmes.kb.store import _find_pending_entry
from holmes.mcp.tools import handle_kb_confirm, handle_kb_read


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


def _make_confirmed_entry(kb_root: Path, entry_id: str = "PT-DB-001") -> Path:
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    entry_path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        "type: pitfall\n"
        "title: Redis Connection Pool Exhausted\n"
        "maturity: draft\n"
        "category: database\n"
        "tags: [redis, connection-pool]\n"
        'created_at: "2024-01-01T00:00:00+00:00"\n'
        'updated_at: "2024-01-01T00:00:00+00:00"\n'
        "---\n\n"
        "## Symptoms\n"
        "- Redis operations timing out under load\n\n"
        "## Root Cause\n"
        "maxclients too low for current workload.\n\n"
        "## Resolution\n"
        "1. [api] `redis-cli CONFIG GET maxclients`\n"
        "2. [api] `redis-cli CONFIG SET maxclients 10000`\n",
        encoding="utf-8",
    )
    return entry_path


# ---------------------------------------------------------------------------
# P2: import -> approve chain
# ---------------------------------------------------------------------------


def test_import_then_approve_finds_entry(kb_root: Path) -> None:
    """A pending entry produced by the import pipeline must be findable by approve."""
    content = (
        "---\n"
        "type: pitfall\n"
        "title: PLL lock failure on Gen2 DVT\n"
        "category: hardware\n"
        "tags: [pll, dvt]\n"
        "---\n\n"
        "## Symptoms\n- PLL_LOCK stays low\n\n"
        "## Root Cause\nREFCLK amplitude out of spec.\n\n"
        "## Resolution\n1. [physical] Probe REFCLK with oscilloscope\n"
    )
    pending_id = write_pending(kb_root, content, source="auto")

    assert _find_pending_entry(kb_root, pending_id) is not None, (
        f"approve cannot locate pending entry {pending_id!r}: import writes to "
        "contributions/pending/ but _find_pending_entry only scans _pending/"
    )


# ---------------------------------------------------------------------------
# P3: documented top-level commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["approve", "pending", "search", "show", "list", "decay", "doctor"],
)
def test_top_level_commands_exist(command: str) -> None:
    """Docs promise `holmes <cmd>`; commands must be registered on the top-level CLI."""
    runner = CliRunner()
    result = runner.invoke(cli, [command, "--help"])
    assert result.exit_code == 0, (
        f"`holmes {command}` does not exist (exit={result.exit_code}): "
        f"{result.output.strip()[:200]}"
    )


# ---------------------------------------------------------------------------
# P1: read(full) -> confirm must not be rejected as duplicate
# ---------------------------------------------------------------------------


def test_read_full_then_confirm_not_duplicate(kb_root: Path) -> None:
    """The documented workflow (read full with session, then confirm) must record solved."""
    entry_id = "PT-DB-001"
    _make_confirmed_entry(kb_root, entry_id)
    session_id = "sess-043-repro"

    read_result = handle_kb_read(kb_root, entry_id, detail="full", session_id=session_id)
    assert "content" in read_result

    confirm_result = handle_kb_confirm(kb_root, entry_id, session_id, outcome="solved")
    assert confirm_result.get("ok") is True, (
        f"kb_confirm after kb_read(full) was rejected: {confirm_result}. "
        "An agent following the documented workflow can never report solved."
    )

    import frontmatter

    post = frontmatter.load(str(kb_root / "pitfall" / "database" / f"{entry_id}.md"))
    assert post.metadata.get("maturity") == "verified"
