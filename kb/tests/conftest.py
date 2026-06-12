"""Shared pytest fixtures for KB Skill tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Core KB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Return a fresh temporary KB root directory."""
    return tmp_path


def make_entry(
    kb_root: Path,
    entry_id: str = "PT-DB-001",
    extra_frontmatter: str = "",
) -> Path:
    """Create a minimal valid pitfall KB entry and return its path."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    entry_path.write_text(textwrap.dedent(f"""\
        ---
        id: {entry_id}
        type: pitfall
        title: Test Entry {entry_id}
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        {extra_frontmatter}
        ---

        ## Symptoms
        Test symptoms.

        ## Root Cause
        Test root cause.

        ## Resolution
        Test resolution.
    """), encoding="utf-8")
    return entry_path
