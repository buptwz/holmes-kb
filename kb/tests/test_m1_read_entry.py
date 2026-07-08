"""Tests for M1: read_entry() — basic read functionality."""

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
    # Pitfall entry
    _write_entry(tmp_path, "pitfall", "gpu-root-001.md", {
        "id": "gpu-root-001",
        "type": "pitfall",
        "title": "GPU Init Failure",
        "maturity": "draft",
        "category": "system",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }, body="## Symptoms\nGPU fails.\n\n## Root Cause\nUnknown.\n\n## Resolution\nSee docs.")
    # Simple entry
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


class TestReadEntry:
    def test_read_existing_entry(self, kb_root: Path) -> None:
        """read_entry() returns content for an existing entry."""
        content = read_entry(kb_root, "gpu-root-001")
        assert content is not None
        assert "GPU Init Failure" in content
        assert "## Symptoms" in content
        assert "## Root Cause" in content

    def test_read_simple_entry(self, kb_root: Path) -> None:
        """read_entry() returns content for simple entry."""
        content = read_entry(kb_root, "simple-001")
        assert content is not None
        assert "Simple pitfall" in content

    def test_read_nonexistent_entry(self, kb_root: Path) -> None:
        """read_entry() returns None for nonexistent entry."""
        content = read_entry(kb_root, "nonexistent-999")
        assert content is None
