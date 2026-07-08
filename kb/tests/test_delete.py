"""Tests for move_to_trash() soft-delete functionality."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.store import move_to_trash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PITFALL_ENTRY = """\
---
id: pitfall-flat-001
type: pitfall
title: Network Timeout
category: network
maturity: draft
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Symptoms
Network timeout on startup.
"""

_PROCESS_ENTRY = """\
---
id: process-standalone-001
type: process
title: Standalone Process
category: storage
maturity: draft
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Steps
1. Do something.
"""


def _write(path: Path, content: str) -> Path:
    """Write content to path, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Basic delete
# ---------------------------------------------------------------------------


def test_move_to_trash_single_entry(tmp_path: Path) -> None:
    """A standalone entry is moved to _trash/<type>/<category>/."""
    src = _write(
        tmp_path / "process" / "storage" / "process-standalone-001.md",
        _PROCESS_ENTRY,
    )

    moved = move_to_trash(tmp_path, "process-standalone-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    assert dst.exists()
    assert dst.parent == tmp_path / "_trash" / "process" / "storage"
    assert not src.exists()


def test_move_to_trash_pending_entry(tmp_path: Path) -> None:
    """A pending entry in _pending/<type>/<category>/ is moved to _trash/."""
    content = """\
---
id: pending-entry-001
type: process
title: Pending Process
category: hardware
maturity: draft
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Steps
1. Check hardware.
"""
    src = _write(
        tmp_path / "_pending" / "process" / "hardware" / "pending-entry-001.md",
        content,
    )

    moved = move_to_trash(tmp_path, "pending-entry-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    assert dst.exists()
    assert dst.parent == tmp_path / "_trash" / "process" / "hardware"
    assert not src.exists()


# ---------------------------------------------------------------------------
# Filename collision in _trash/
# ---------------------------------------------------------------------------


def test_move_to_trash_filename_collision(tmp_path: Path) -> None:
    """When a same-named file already exists in _trash/, a timestamp variant is created."""
    existing_trash = tmp_path / "_trash" / "pitfall" / "network" / "pitfall-flat-001.md"
    existing_trash.parent.mkdir(parents=True, exist_ok=True)
    existing_trash.write_text("old content", encoding="utf-8")

    src = _write(
        tmp_path / "pitfall" / "network" / "pitfall-flat-001.md",
        _PITFALL_ENTRY,
    )

    moved = move_to_trash(tmp_path, "pitfall-flat-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    assert existing_trash.exists()
    assert existing_trash.read_text() == "old content"
    assert dst.name != "pitfall-flat-001.md"
    assert "pitfall-flat-001-" in dst.name
    assert dst.exists()
    assert not src.exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_move_to_trash_entry_not_found(tmp_path: Path) -> None:
    """Raises FileNotFoundError for a non-existent entry ID."""
    with pytest.raises(FileNotFoundError, match="not found"):
        move_to_trash(tmp_path, "does-not-exist-999")


def test_move_to_trash_creates_trash_dir(tmp_path: Path) -> None:
    """_trash directory is created automatically if it does not exist."""
    _write(
        tmp_path / "process" / "storage" / "process-standalone-001.md",
        _PROCESS_ENTRY,
    )
    assert not (tmp_path / "_trash").exists()

    move_to_trash(tmp_path, "process-standalone-001")

    assert (tmp_path / "_trash").is_dir()
