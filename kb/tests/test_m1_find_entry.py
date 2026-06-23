"""Tests for M1: find_entry() — ID-format-agnostic filesystem scan."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.store import find_entry


def _write_entry(kb_root: Path, kb_type: str, filename: str, meta: dict) -> Path:
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / filename
    post = frontmatter.Post("", **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    # Old-style ID: PT-DB-001
    _write_entry(tmp_path, "pitfall", "PT-DB-001.md", {
        "id": "PT-DB-001",
        "type": "pitfall",
        "title": "Legacy DB pitfall",
        "maturity": "draft",
        "category": "database",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    # New-style ID: gpu-init-failure-root-001
    _write_entry(tmp_path, "pitfall", "gpu-init-failure-root-001.md", {
        "id": "gpu-init-failure-root-001",
        "type": "pitfall",
        "title": "GPU init failure",
        "maturity": "draft",
        "category": "system",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    # Entry without id field (fallback to stem)
    no_id_dir = tmp_path / "model"
    no_id_dir.mkdir(parents=True, exist_ok=True)
    (no_id_dir / "no-id-entry.md").write_text(
        "---\ntype: model\ntitle: No-ID entry\n---\nBody\n", encoding="utf-8"
    )
    # Pending entry
    pending_dir = tmp_path / "contributions" / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post("", **{
        "id": "pending-20260101-000000-abcd",
        "type": "pitfall",
        "title": "Pending entry",
        "maturity": "draft",
        "category": "network",
        "tags": [],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    })
    (pending_dir / "pending-20260101-000000-abcd.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    return tmp_path


class TestFindEntry:
    def test_legacy_id_format(self, kb_root: Path) -> None:
        """find_entry() finds old-style PT-DB-001 ID."""
        result = find_entry(kb_root, "PT-DB-001")
        assert result is not None
        assert result.name == "PT-DB-001.md"

    def test_new_style_id_format(self, kb_root: Path) -> None:
        """find_entry() finds new-style kebab-case ID."""
        result = find_entry(kb_root, "gpu-init-failure-root-001")
        assert result is not None
        assert result.name == "gpu-init-failure-root-001.md"

    def test_case_insensitive(self, kb_root: Path) -> None:
        """find_entry() is case-insensitive."""
        result = find_entry(kb_root, "pt-db-001")
        assert result is not None
        result2 = find_entry(kb_root, "PT-DB-001")
        assert result2 is not None
        assert result == result2

    def test_not_found_returns_none(self, kb_root: Path) -> None:
        """find_entry() returns None for unknown IDs."""
        assert find_entry(kb_root, "does-not-exist-999") is None

    def test_pending_entry_found(self, kb_root: Path) -> None:
        """find_entry() scans contributions/pending/ directory."""
        result = find_entry(kb_root, "pending-20260101-000000-abcd")
        assert result is not None

    def test_no_id_field_falls_back_to_stem(self, kb_root: Path) -> None:
        """find_entry() falls back to filename stem when frontmatter has no id."""
        result = find_entry(kb_root, "no-id-entry")
        assert result is not None
        assert result.stem == "no-id-entry"
