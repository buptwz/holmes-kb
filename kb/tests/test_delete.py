"""Tests for move_to_trash() soft-delete functionality (M7)."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.store import move_to_trash


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PITFALL_ROOT_TREE = """\
---
id: pitfall-root-001
type: pitfall
title: GPU Init Failure
category: hardware
maturity: draft
pitfall_structure: tree
child_entry_ids:
  - process-child-001
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Symptoms
GPU fails on boot.
"""

_PROCESS_CHILD = """\
---
id: process-child-001
type: process
title: Driver Check Steps
category: hardware
maturity: draft
parent_id: pitfall-root-001
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Steps
1. Check driver version.
"""

_PITFALL_ROOT_FLAT = """\
---
id: pitfall-flat-001
type: pitfall
title: Network Timeout
category: network
maturity: draft
pitfall_structure: flat
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Symptoms
Network timeout on startup.
"""

_PITFALL_ROOT_NO_STRUCTURE = """\
---
id: pitfall-legacy-001
type: pitfall
title: Legacy Issue
category: database
maturity: draft
created_at: "2026-06-24"
updated_at: "2026-06-24"
---

## Symptoms
Legacy problem.
"""

_PROCESS_NON_ROOT = """\
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
# T007 — Delete single non-root confirmed entry
# ---------------------------------------------------------------------------


def test_move_to_trash_single_non_root_entry(tmp_path: Path) -> None:
    """A standalone process entry is moved to _trash/process/<category>/."""
    src = _write(
        tmp_path / "process" / "storage" / "process-standalone-001.md",
        _PROCESS_NON_ROOT,
    )

    moved = move_to_trash(tmp_path, "process-standalone-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    assert dst.exists()
    assert dst.parent == tmp_path / "_trash" / "process" / "storage"
    assert not src.exists()


# ---------------------------------------------------------------------------
# T008 — Delete pending entry
# ---------------------------------------------------------------------------


def test_move_to_trash_pending_entry(tmp_path: Path) -> None:
    """A pending entry in _pending/<type>/<category>/ is moved to _trash/."""
    src = _write(
        tmp_path / "_pending" / "process" / "hardware" / "process-child-001.md",
        _PROCESS_CHILD,
    )

    moved = move_to_trash(tmp_path, "process-child-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    assert dst.exists()
    assert dst.parent == tmp_path / "_trash" / "process" / "hardware"
    assert not src.exists()


# ---------------------------------------------------------------------------
# T010 — Cascade delete pitfall root tree
# ---------------------------------------------------------------------------


def test_move_to_trash_cascade_pitfall_root(tmp_path: Path) -> None:
    """Cascade delete moves root AND all child entries to _trash/."""
    root_src = _write(
        tmp_path / "pitfall" / "hardware" / "pitfall-root-001.md",
        _PITFALL_ROOT_TREE,
    )
    child_src = _write(
        tmp_path / "process" / "hardware" / "process-child-001.md",
        _PROCESS_CHILD,
    )

    moved = move_to_trash(tmp_path, "pitfall-root-001", cascade=True)

    assert len(moved) == 2
    assert not root_src.exists()
    assert not child_src.exists()

    trash_paths = {Path(dst).name for _, dst in moved}
    assert "pitfall-root-001.md" in trash_paths
    assert "process-child-001.md" in trash_paths

    original_paths = {Path(src).name for src, _ in moved}
    assert "pitfall-root-001.md" in original_paths
    assert "process-child-001.md" in original_paths

    # Root goes to _trash/pitfall/hardware/, child to _trash/process/hardware/.
    trash_pitfall = tmp_path / "_trash" / "pitfall" / "hardware" / "pitfall-root-001.md"
    trash_process = tmp_path / "_trash" / "process" / "hardware" / "process-child-001.md"
    assert trash_pitfall.exists()
    assert trash_process.exists()


# ---------------------------------------------------------------------------
# T011 — --no-cascade only deletes root
# ---------------------------------------------------------------------------


def test_move_to_trash_no_cascade(tmp_path: Path) -> None:
    """With cascade=False, only the root entry is moved; children untouched."""
    root_src = _write(
        tmp_path / "pitfall" / "hardware" / "pitfall-root-001.md",
        _PITFALL_ROOT_TREE,
    )
    child_src = _write(
        tmp_path / "process" / "hardware" / "process-child-001.md",
        _PROCESS_CHILD,
    )

    moved = move_to_trash(tmp_path, "pitfall-root-001", cascade=False)

    assert len(moved) == 1
    original_path, _ = moved[0]
    assert original_path == str(root_src)
    assert not root_src.exists()
    assert child_src.exists()  # child must remain untouched


# ---------------------------------------------------------------------------
# T012 — Legacy flat pitfall: no cascade even with cascade=True
# ---------------------------------------------------------------------------


def test_move_to_trash_legacy_flat_pitfall(tmp_path: Path) -> None:
    """Legacy pitfall entries (pitfall_structure: flat) are not cascaded."""
    src = _write(
        tmp_path / "pitfall" / "network" / "pitfall-flat-001.md",
        _PITFALL_ROOT_FLAT,
    )

    moved = move_to_trash(tmp_path, "pitfall-flat-001", cascade=True)

    assert len(moved) == 1
    original_path, _ = moved[0]
    assert original_path == str(src)
    assert not src.exists()


def test_move_to_trash_legacy_no_structure_field(tmp_path: Path) -> None:
    """Legacy pitfall entries without pitfall_structure field are not cascaded."""
    src = _write(
        tmp_path / "pitfall" / "database" / "pitfall-legacy-001.md",
        _PITFALL_ROOT_NO_STRUCTURE,
    )

    moved = move_to_trash(tmp_path, "pitfall-legacy-001", cascade=True)

    assert len(moved) == 1
    original_path, _ = moved[0]
    assert original_path == str(src)
    assert not src.exists()


# ---------------------------------------------------------------------------
# T014 — Filename collision in _trash/
# ---------------------------------------------------------------------------


def test_move_to_trash_filename_collision(tmp_path: Path) -> None:
    """When a same-named file already exists in _trash/, a timestamp variant is created."""
    # Pre-create an existing trash file.
    existing_trash = tmp_path / "_trash" / "pitfall" / "network" / "pitfall-flat-001.md"
    existing_trash.parent.mkdir(parents=True, exist_ok=True)
    existing_trash.write_text("old content", encoding="utf-8")

    # Now move a new entry that would collide.
    src = _write(
        tmp_path / "pitfall" / "network" / "pitfall-flat-001.md",
        _PITFALL_ROOT_FLAT,
    )

    moved = move_to_trash(tmp_path, "pitfall-flat-001")

    assert len(moved) == 1
    original_path, trash_path = moved[0]
    assert original_path == str(src)
    dst = Path(trash_path)
    # Original trash file must still exist (not overwritten).
    assert existing_trash.exists()
    assert existing_trash.read_text() == "old content"
    # New file must have a different (timestamped) name.
    assert dst.name != "pitfall-flat-001.md"
    assert "pitfall-flat-001-" in dst.name
    assert dst.exists()
    assert not src.exists()


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


def test_move_to_trash_entry_not_found(tmp_path: Path) -> None:
    """Raises FileNotFoundError for a non-existent entry ID."""
    with pytest.raises(FileNotFoundError, match="not found"):
        move_to_trash(tmp_path, "does-not-exist-999")


def test_move_to_trash_creates_trash_dir(tmp_path: Path) -> None:
    """_trash directory is created automatically if it does not exist."""
    _write(
        tmp_path / "process" / "storage" / "process-standalone-001.md",
        _PROCESS_NON_ROOT,
    )
    assert not (tmp_path / "_trash").exists()

    move_to_trash(tmp_path, "process-standalone-001")

    assert (tmp_path / "_trash").is_dir()


def test_move_to_trash_missing_child_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A child entry referenced in child_entry_ids but missing on disk is skipped with a warning."""
    import logging

    # Root references a child that does not exist on disk.
    root_src = _write(
        tmp_path / "pitfall" / "hardware" / "pitfall-root-001.md",
        _PITFALL_ROOT_TREE,
    )
    # process-child-001 is NOT created on disk.

    with caplog.at_level(logging.WARNING, logger="root"):
        moved = move_to_trash(tmp_path, "pitfall-root-001", cascade=True)

    # Only root was moved; child was skipped with a warning.
    assert len(moved) == 1
    original_path, _ = moved[0]
    assert original_path == str(root_src)
    assert not root_src.exists()
    assert any("process-child-001" in rec.message or "not found" in rec.message
               for rec in caplog.records)
