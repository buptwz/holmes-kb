"""Tests for M1: search.py — kb_status filter and exclude_sub_entries filter."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from holmes.kb.search import search


def _write_entry(kb_root: Path, kb_type: str, filename: str, meta: dict, body: str = "") -> Path:
    type_dir = kb_root / kb_type
    type_dir.mkdir(parents=True, exist_ok=True)
    path = type_dir / filename
    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    common = dict(
        maturity="draft",
        category="network",
        tags=["network", "timeout"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    body = "## Symptoms\nNetwork timeout.\n\n## Root Cause\nPacket loss.\n\n## Resolution\nRestart."

    _write_entry(tmp_path, "pitfall", "active-001.md", {
        "id": "active-001", "type": "pitfall", "title": "Active network pitfall",
        "kb_status": "active", **common,
    }, body=body)

    _write_entry(tmp_path, "pitfall", "deprecated-001.md", {
        "id": "deprecated-001", "type": "pitfall", "title": "Deprecated network pitfall",
        "kb_status": "deprecated", **common,
    }, body=body)

    _write_entry(tmp_path, "pitfall", "legacy-001.md", {
        "id": "legacy-001", "type": "pitfall", "title": "Legacy network pitfall",
        **common,  # no kb_status field
    }, body=body)

    _write_entry(tmp_path, "process", "sub-process-001.md", {
        "id": "sub-process-001", "type": "process", "title": "Network sub-process",
        "kb_status": "active", "parent_id": "active-001",
        **common,
    }, body="## Steps\nNetwork step.")

    _write_entry(tmp_path, "process", "top-process-001.md", {
        "id": "top-process-001", "type": "process", "title": "Top-level network process",
        "kb_status": "active", **common,
    }, body="## Steps\nNetwork step.")

    return tmp_path


class TestSearchFilter:
    def test_default_hides_deprecated(self, kb_root: Path) -> None:
        results = search(kb_root, "network")
        ids = {r.entry_id for r in results}
        assert "deprecated-001" not in ids

    def test_default_shows_active(self, kb_root: Path) -> None:
        results = search(kb_root, "network")
        ids = {r.entry_id for r in results}
        assert "active-001" in ids

    def test_legacy_entry_visible_by_default(self, kb_root: Path) -> None:
        """Legacy entry (no kb_status) treated as active and searchable."""
        results = search(kb_root, "network")
        ids = {r.entry_id for r in results}
        assert "legacy-001" in ids

    def test_default_hides_sub_entries(self, kb_root: Path) -> None:
        results = search(kb_root, "network")
        ids = {r.entry_id for r in results}
        assert "sub-process-001" not in ids

    def test_top_level_process_visible(self, kb_root: Path) -> None:
        results = search(kb_root, "network")
        ids = {r.entry_id for r in results}
        assert "top-process-001" in ids

    def test_all_flag_includes_deprecated(self, kb_root: Path) -> None:
        results = search(kb_root, "network", active_only=False, exclude_sub_entries=False)
        ids = {r.entry_id for r in results}
        assert "deprecated-001" in ids

    def test_all_flag_includes_sub_entries(self, kb_root: Path) -> None:
        results = search(kb_root, "network", active_only=False, exclude_sub_entries=False)
        ids = {r.entry_id for r in results}
        assert "sub-process-001" in ids
