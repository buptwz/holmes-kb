"""Tests for P0-3: evidence-freshness-based search ranking."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from holmes.kb.search import LinearScanBackend, search
from holmes.kb.store import EVIDENCE_SIDECAR_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    kb_root: Path,
    entry_id: str,
    title: str,
    category: str = "database",
    tags: str = "",
) -> Path:
    """Create a minimal pitfall KB entry and return its path."""
    entry_dir = kb_root / "pitfall" / category
    entry_dir.mkdir(parents=True, exist_ok=True)
    path = entry_dir / f"{entry_id}.md"
    path.write_text(
        textwrap.dedent(f"""\
            ---
            id: {entry_id}
            type: pitfall
            title: {title}
            maturity: draft
            category: {category}
            tags: [{tags}]
            created_at: "2024-01-01T00:00:00+00:00"
            updated_at: "2024-01-01T00:00:00+00:00"
            ---

            ## Symptoms
            common symptom keyword.

            ## Root Cause
            common root cause keyword.

            ## Resolution
            Fix it.
            """),
        encoding="utf-8",
    )
    return path


def _write_evidence(kb_root: Path, entry_id: str, session_id: str, date: str) -> None:
    """Write a sidecar evidence JSON file for an entry."""
    sidecar_dir = kb_root / EVIDENCE_SIDECAR_DIR / entry_id
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "session_id": session_id,
        "contributor": session_id,
        "date": date,
    }
    (sidecar_dir / f"{session_id}.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# T014 — entry with recent evidence ranks above same-keyword entry without evidence
# ---------------------------------------------------------------------------

def test_search_ranks_evidence_entry_higher(tmp_path: Path) -> None:
    """Entry with recent evidence must appear before entry with same keywords but no evidence."""
    _make_entry(tmp_path, "PT-001", "keyword common pitfall alpha")
    _make_entry(tmp_path, "PT-002", "keyword common pitfall beta")

    # Give PT-002 a recent evidence record; PT-001 has none.
    _write_evidence(tmp_path, "PT-002", "session-recent", "2026-06-11")

    backend = LinearScanBackend(tmp_path)
    results = backend.search("keyword common pitfall", limit=5)

    assert len(results) >= 2
    entry_ids = [r.entry_id for r in results]
    assert entry_ids.index("PT-002") < entry_ids.index("PT-001"), (
        f"PT-002 (has evidence) should rank before PT-001 (no evidence). Got: {entry_ids}"
    )


# ---------------------------------------------------------------------------
# T015 — when no entries have evidence, result order follows keyword score
# ---------------------------------------------------------------------------

def test_search_no_evidence_falls_back_to_score(tmp_path: Path) -> None:
    """With no evidence on any entry, results are ordered by keyword hit ratio."""
    # PT-HIGH matches 3 out of 3 query terms; PT-LOW matches 1.
    high_dir = tmp_path / "pitfall" / "database"
    high_dir.mkdir(parents=True, exist_ok=True)

    # PT-HIGH: title + tags all match
    (high_dir / "PT-HIGH.md").write_text(
        textwrap.dedent("""\
            ---
            id: PT-HIGH
            type: pitfall
            title: alpha bravo charlie
            maturity: draft
            category: database
            tags: [alpha, bravo]
            created_at: "2024-01-01T00:00:00+00:00"
            updated_at: "2024-01-01T00:00:00+00:00"
            ---

            ## Symptoms
            alpha bravo charlie.

            ## Root Cause
            root.

            ## Resolution
            fix.
            """),
        encoding="utf-8",
    )
    # PT-LOW: only title matches one term
    (high_dir / "PT-LOW.md").write_text(
        textwrap.dedent("""\
            ---
            id: PT-LOW
            type: pitfall
            title: alpha only
            maturity: draft
            category: database
            tags: []
            created_at: "2024-01-01T00:00:00+00:00"
            updated_at: "2024-01-01T00:00:00+00:00"
            ---

            ## Symptoms
            alpha.

            ## Root Cause
            unrelated root cause.

            ## Resolution
            fix.
            """),
        encoding="utf-8",
    )

    results = search(tmp_path, "alpha bravo charlie", limit=5)

    assert len(results) >= 2
    entry_ids = [r.entry_id for r in results]
    assert entry_ids.index("PT-HIGH") < entry_ids.index("PT-LOW"), (
        f"PT-HIGH (more keyword hits) should rank before PT-LOW. Got: {entry_ids}"
    )
