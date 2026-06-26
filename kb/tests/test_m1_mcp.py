"""Tests for M1: mcp/tools.py — kb_status filter, sub-entry filter, routing, children."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.mcp.tools import handle_kb_list, handle_kb_read


def _write_entry(kb_root: Path, kb_type: str, filename: str, meta: dict, body: str = "") -> Path:
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / filename
    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    # Active pitfall
    _write_entry(tmp_path, "pitfall", "active-001.md", {
        "id": "active-001",
        "type": "pitfall",
        "title": "Active pitfall",
        "maturity": "draft",
        "kb_status": "active",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Symptoms\nX\n\n## Root Cause\nY\n\n## Resolution\nZ")

    # Deprecated pitfall
    _write_entry(tmp_path, "pitfall", "deprecated-001.md", {
        "id": "deprecated-001",
        "type": "pitfall",
        "title": "Deprecated pitfall",
        "maturity": "draft",
        "kb_status": "deprecated",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })

    # Process sub-entry (has parent_id)
    _write_entry(tmp_path, "process", "sub-process-001.md", {
        "id": "sub-process-001",
        "type": "process",
        "title": "Process sub-entry",
        "maturity": "draft",
        "kb_status": "active",
        "parent_id": "active-001",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Steps\nStep 1.")

    # Child entry for tree navigation
    _write_entry(tmp_path, "process", "child-001.md", {
        "id": "child-001",
        "type": "process",
        "title": "Child step",
        "maturity": "draft",
        "kb_status": "active",
        "parent_id": "root-with-children-001",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Steps\nStep A.")

    # Pitfall root with child_entry_ids
    _write_entry(tmp_path, "pitfall", "root-with-children-001.md", {
        "id": "root-with-children-001",
        "type": "pitfall",
        "title": "Root with children",
        "maturity": "draft",
        "kb_status": "active",
        "category": "network",
        "tags": [],
        "child_entry_ids": ["child-001"],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Symptoms\nX\n\n## Root Cause\nY\n\n## Resolution\nZ")

    # New-style ID entry
    _write_entry(tmp_path, "pitfall", "gpu-init-failure-root-001.md", {
        "id": "gpu-init-failure-root-001",
        "type": "pitfall",
        "title": "GPU Init Failure",
        "maturity": "draft",
        "kb_status": "active",
        "category": "system",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Symptoms\nGPU fails.\n\n## Root Cause\nFirmware.\n\n## Resolution\nUpdate firmware.")

    return tmp_path


class TestHandleKbList:
    def test_hides_deprecated_by_default(self, kb_root: Path) -> None:
        result = handle_kb_list(kb_root)
        ids = {e["id"] for e in result["entries"]}
        assert "deprecated-001" not in ids

    def test_hides_sub_entries_by_default(self, kb_root: Path) -> None:
        result = handle_kb_list(kb_root)
        ids = {e["id"] for e in result["entries"]}
        assert "sub-process-001" not in ids

    def test_shows_active_entries(self, kb_root: Path) -> None:
        result = handle_kb_list(kb_root)
        ids = {e["id"] for e in result["entries"]}
        assert "active-001" in ids


class TestHandleKbReadRouting:
    def test_new_style_id_routes_to_entry(self, kb_root: Path) -> None:
        """New-style ID is routed to _read_entry, not _read_skill."""
        result = handle_kb_read(kb_root, "gpu-init-failure-root-001")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result.get("type") == "pitfall"
        assert "GPU Init Failure" in result.get("content", "")

    def test_legacy_style_id_routes_to_entry(self, kb_root: Path) -> None:
        """Legacy-style ID still works."""
        result = handle_kb_read(kb_root, "active-001")
        assert "error" not in result
        assert result.get("type") == "pitfall"

    def test_unknown_id_treated_as_skill(self, kb_root: Path) -> None:
        """Unknown ID falls through to skill lookup and returns skill-style error."""
        result = handle_kb_read(kb_root, "no-such-skill-or-entry")
        # Should return a skill-not-found error, not an entry-not-found error
        assert "error" in result


class TestReadEntryChildren:
    def test_children_field_in_result(self, kb_root: Path) -> None:
        result = handle_kb_read(kb_root, "root-with-children-001")
        assert "error" not in result
        assert "children" in result
        children = result["children"]
        assert len(children) == 1
        assert children[0]["id"] == "child-001"
        assert children[0]["title"] == "Child step"

    def test_no_children_field_when_absent(self, kb_root: Path) -> None:
        result = handle_kb_read(kb_root, "active-001")
        assert "error" not in result
        assert "children" not in result
