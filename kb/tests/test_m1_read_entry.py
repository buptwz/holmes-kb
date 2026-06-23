"""Tests for M1: read_entry() — children section appended when child_entry_ids present."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.store import read_entry


def _write_entry(kb_root: Path, kb_type: str, filename: str, meta: dict, body: str = "") -> Path:
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / filename
    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    # Child 1
    _write_entry(tmp_path, "process", "driver-check-001.md", {
        "id": "driver-check-001",
        "type": "process",
        "title": "Driver version check",
        "maturity": "draft",
        "category": "system",
        "tags": [],
        "parent_id": "gpu-root-001",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    # Child 2
    _write_entry(tmp_path, "process", "firmware-update-001.md", {
        "id": "firmware-update-001",
        "type": "process",
        "title": "Firmware upgrade steps",
        "maturity": "draft",
        "category": "system",
        "tags": [],
        "parent_id": "gpu-root-001",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    # Pitfall root with child_entry_ids
    _write_entry(tmp_path, "pitfall", "gpu-root-001.md", {
        "id": "gpu-root-001",
        "type": "pitfall",
        "title": "GPU Init Failure",
        "maturity": "draft",
        "category": "system",
        "tags": [],
        "child_entry_ids": ["driver-check-001", "firmware-update-001"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Symptoms\nGPU fails.\n\n## Root Cause\nUnknown.\n\n## Resolution\nSee children.")
    # Entry without child_entry_ids
    _write_entry(tmp_path, "pitfall", "simple-001.md", {
        "id": "simple-001",
        "type": "pitfall",
        "title": "Simple pitfall",
        "maturity": "draft",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    return tmp_path


class TestReadEntryChildren:
    def test_children_section_appended(self, kb_root: Path) -> None:
        """read_entry() appends ## Children when child_entry_ids is non-empty."""
        content = read_entry(kb_root, "gpu-root-001")
        assert content is not None
        assert "## Children" in content

    def test_children_table_contains_ids(self, kb_root: Path) -> None:
        """## Children table rows contain child IDs."""
        content = read_entry(kb_root, "gpu-root-001")
        assert content is not None
        assert "driver-check-001" in content
        assert "firmware-update-001" in content

    def test_children_table_contains_titles(self, kb_root: Path) -> None:
        """## Children table rows contain resolved titles."""
        content = read_entry(kb_root, "gpu-root-001")
        assert content is not None
        assert "Driver version check" in content
        assert "Firmware upgrade steps" in content

    def test_no_children_section_when_empty(self, kb_root: Path) -> None:
        """read_entry() does NOT append ## Children when no child_entry_ids."""
        content = read_entry(kb_root, "simple-001")
        assert content is not None
        assert "## Children" not in content

    def test_missing_child_shown_as_not_found(self, kb_root: Path) -> None:
        """Child IDs that don't exist show (not found) in the table."""
        # Add entry with a non-existent child
        pitfall_dir = kb_root / "pitfall"
        post = frontmatter.Post("## Symptoms\nX\n\n## Root Cause\nY\n\n## Resolution\nZ", **{
            "id": "orphan-root-001",
            "type": "pitfall",
            "title": "Orphan root",
            "maturity": "draft",
            "category": "network",
            "tags": [],
            "child_entry_ids": ["ghost-child-999"],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        })
        (pitfall_dir / "orphan-root-001.md").write_text(frontmatter.dumps(post), encoding="utf-8")

        content = read_entry(kb_root, "orphan-root-001")
        assert content is not None
        assert "ghost-child-999" in content
        assert "(not found)" in content

    def test_original_content_preserved(self, kb_root: Path) -> None:
        """Original frontmatter and body are intact when children are appended."""
        content = read_entry(kb_root, "gpu-root-001")
        assert content is not None
        assert "GPU Init Failure" in content  # frontmatter title preserved in yaml
        assert "## Symptoms" in content
        assert "## Root Cause" in content
