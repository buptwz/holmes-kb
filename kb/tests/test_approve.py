"""Tests for M6a — Pending/Approve 基础流程.

Covers:
- write_pending: new-format _pending/<type>/<category>/<id>.md
- approve_entry: move pending → confirmed, kb_status=active
- deprecate_entry: in-place kb_status=deprecated, no file move
- find_entries_by_source_file: scans _pending/ + confirmed
- Three-layer scenario: confirmed + old pending + new pending
- holmes kb pending: category grouping + legacy compat (CLI)
- holmes kb approve: basic + conflict detection (CLI)
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.store import (
    approve_entry,
    deprecate_entry,
    find_entries_by_source_file,
    list_entries,
    write_pending,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    entry_id: str,
    *,
    kb_type: str = "pitfall",
    category: str = "hardware",
    kb_status: str = "active",
    source_file: str = "",
    source_hash: str = "",
) -> str:
    src_line = f"source_file: {source_file}\n" if source_file else ""
    hash_line = f"source_hash: {source_hash}\n" if source_hash else ""
    return (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: {kb_type}\n"
        f"title: Test Entry {entry_id}\n"
        f"category: {category}\n"
        f"kb_status: {kb_status}\n"
        f"maturity: draft\n"
        f"decay_status: active\n"
        f"created_at: '2026-06-24'\n"
        f"updated_at: '2026-06-24'\n"
        f"{src_line}"
        f"{hash_line}"
        f"---\n\n## Description\nTest entry.\n"
    )


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    """Return a fresh temporary KB root directory."""
    return tmp_path


# ---------------------------------------------------------------------------
# T003 — write_pending
# ---------------------------------------------------------------------------

class TestWritePending:
    def test_creates_file_in_pending_dir(self, kb_root: Path) -> None:
        content = _make_entry("hw-init-001", kb_status="pending")
        path = write_pending(kb_root, "hw-init-001", content, "pitfall", "hardware")
        assert path == kb_root / "_pending" / "pitfall" / "hardware" / "hw-init-001.md"
        assert path.exists()

    def test_creates_category_dir_if_missing(self, kb_root: Path) -> None:
        assert not (kb_root / "_pending" / "pitfall" / "network").exists()
        write_pending(kb_root, "dns-001", _make_entry("dns-001", kb_status="pending"), "pitfall", "network")
        assert (kb_root / "_pending" / "pitfall" / "network").is_dir()

    def test_content_is_preserved(self, kb_root: Path) -> None:
        content = _make_entry("hw-001", kb_status="pending", source_file="docs/hw.md")
        path = write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        post = frontmatter.load(str(path))
        assert post.metadata["id"] == "hw-001"
        assert post.metadata["source_file"] == "docs/hw.md"

    def test_overwrites_existing_file(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        new_content = _make_entry("hw-001", kb_status="pending", source_hash="newHash")
        write_pending(kb_root, "hw-001", new_content, "pitfall", "hardware")
        post = frontmatter.load(str(kb_root / "_pending" / "pitfall" / "hardware" / "hw-001.md"))
        assert post.metadata["source_hash"] == "newHash"


# ---------------------------------------------------------------------------
# T005 — approve_entry
# ---------------------------------------------------------------------------

class TestApproveEntry:
    def test_approve_moves_file_to_confirmed(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-init-001")
        # Approved entry lands in <type>/ (pitfall/) so list_entries can find it.
        assert new_path == kb_root / "pitfall" / "hardware" / "hw-init-001.md"
        assert new_path.exists()

    def test_approve_removes_pending_file(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        pending_path = kb_root / "_pending" / "pitfall" / "hardware" / "hw-init-001.md"
        assert pending_path.exists()
        approve_entry(kb_root, "hw-init-001")
        assert not pending_path.exists()

    def test_approve_sets_kb_status_active(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        new_path = approve_entry(kb_root, "hw-init-001")
        post = frontmatter.load(str(new_path))
        assert post.metadata["kb_status"] == "active"

    def test_approve_creates_type_dir(self, kb_root: Path) -> None:
        write_pending(kb_root, "net-001", _make_entry("net-001", kb_status="pending", category="network"), "pitfall", "network")
        assert not (kb_root / "pitfall").exists()
        approve_entry(kb_root, "net-001")
        # type=pitfall → pitfall/network/ directory created
        assert (kb_root / "pitfall" / "network").is_dir()

    def test_approve_nonexistent_raises(self, kb_root: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found in _pending"):
            approve_entry(kb_root, "does-not-exist")

    def test_approved_entry_visible_in_list(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        approve_entry(kb_root, "hw-init-001")
        # Entry lands in pitfall/hardware/ (type/category) → list_entries finds it.
        entries = list_entries(kb_root, kb_status="active")
        assert any(e.id == "hw-init-001" for e in entries)


# ---------------------------------------------------------------------------
# T006 — deprecate_entry
# ---------------------------------------------------------------------------

class TestDeprecateEntry:
    def _write_confirmed(self, kb_root: Path, entry_id: str, category: str = "hardware") -> Path:
        """Write a confirmed (active) entry directly to pitfall/<category>/<id>.md."""
        content = _make_entry(entry_id, kb_type="pitfall", category=category, kb_status="active")
        path = kb_root / "pitfall" / category / f"{entry_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_deprecate_sets_kb_status(self, kb_root: Path) -> None:
        path = self._write_confirmed(kb_root, "hw-001")
        result = deprecate_entry(kb_root, "hw-001")
        assert result is True
        post = frontmatter.load(str(path))
        assert post.metadata["kb_status"] == "deprecated"

    def test_deprecate_does_not_move_file(self, kb_root: Path) -> None:
        path = self._write_confirmed(kb_root, "hw-001")
        deprecate_entry(kb_root, "hw-001")
        assert path.exists(), "File must not be moved or deleted"

    def test_deprecate_nonexistent_returns_false(self, kb_root: Path) -> None:
        result = deprecate_entry(kb_root, "does-not-exist")
        assert result is False

    def test_deprecate_pending_entry_returns_false(self, kb_root: Path) -> None:
        """deprecate_entry must not modify pending entries."""
        write_pending(kb_root, "hw-pending-001", _make_entry("hw-pending-001", kb_status="pending"), "pitfall", "hardware")
        # The entry is in _pending/ — deprecate_entry should refuse.
        result = deprecate_entry(kb_root, "hw-pending-001")
        assert result is False


# ---------------------------------------------------------------------------
# T004 — find_entries_by_source_file (with _pending/ coverage)
# ---------------------------------------------------------------------------

class TestFindEntriesBySourceFile:
    def test_finds_new_pending_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-001", kb_status="pending", source_file="docs/hw.md")
        write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert any(e.id == "hw-001" for e in results)

    def test_finds_confirmed_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-old-001", kb_status="active", source_file="docs/hw.md")
        path = kb_root / "pitfall" / "hw-old-001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert any(e.id == "hw-old-001" for e in results)

    def test_empty_source_file_returns_nothing(self, kb_root: Path) -> None:
        results = find_entries_by_source_file(kb_root, "")
        assert results == []

    def test_no_match_returns_empty(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file="docs/other.md"), "pitfall", "hardware")
        results = find_entries_by_source_file(kb_root, "docs/hw.md")
        assert results == []


# ---------------------------------------------------------------------------
# Three-layer scenario (US2)
# ---------------------------------------------------------------------------

class TestThreeLayerScenario:
    """
    Scenario: same source_file has three layers:
      - hw-001 (confirmed, active)
      - hw-002 (pending, old import)
      - hw-003 (pending, new import — being approved)

    Approving hw-003 should cancel hw-002 and deprecate hw-001.
    """

    def _setup(self, kb_root: Path) -> None:
        src = "docs/hw-troubleshooting.md"

        # Confirmed active entry (hw-001)
        content_001 = _make_entry("hw-001", kb_status="active", source_file=src)
        path_001 = kb_root / "pitfall" / "hw-001.md"
        path_001.parent.mkdir(parents=True, exist_ok=True)
        path_001.write_text(content_001, encoding="utf-8")

        # Old pending entry (hw-002)
        write_pending(kb_root, "hw-002", _make_entry("hw-002", kb_status="pending", source_file=src), "pitfall", "hardware")

        # New pending entry (hw-003 — the one being approved)
        write_pending(kb_root, "hw-003", _make_entry("hw-003", kb_status="pending", source_file=src), "pitfall", "hardware")

    def test_three_layer_approve_via_functions(self, kb_root: Path) -> None:
        self._setup(kb_root)
        src = "docs/hw-troubleshooting.md"

        # Simulate the approve flow for hw-003.
        all_same = find_entries_by_source_file(kb_root, src)
        old_pending = [e for e in all_same if e.kb_status == "pending" and e.id != "hw-003"]
        old_confirmed = [e for e in all_same if e.kb_status == "active"]

        assert len(old_pending) == 1 and old_pending[0].id == "hw-002"
        assert len(old_confirmed) == 1 and old_confirmed[0].id == "hw-001"

        # Approve new entry first.
        approve_entry(kb_root, "hw-003")

        # Cancel old pending.
        import os
        for e in old_pending:
            os.unlink(e.file_path)

        # Deprecate old confirmed.
        for e in old_confirmed:
            deprecate_entry(kb_root, e.id)

        # Verify state.
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-002.md").exists(), "hw-002 should be cancelled"
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-003.md").exists(), "hw-003 pending file removed"
        assert (kb_root / "pitfall" / "hardware" / "hw-003.md").exists(), "hw-003 approved"

        post_001 = frontmatter.load(str(kb_root / "pitfall" / "hw-001.md"))
        assert post_001.metadata["kb_status"] == "deprecated", "hw-001 should be deprecated"

        post_003 = frontmatter.load(str(kb_root / "pitfall" / "hardware" / "hw-003.md"))
        assert post_003.metadata["kb_status"] == "active", "hw-003 should be active"


# ---------------------------------------------------------------------------
# CLI — holmes kb pending (US3)
# ---------------------------------------------------------------------------

class TestCliPending:
    def test_no_pending_shows_message(self, kb_root: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0
        assert "No pending entries" in result.output

    def test_new_format_grouped_by_category(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        write_pending(kb_root, "net-001", _make_entry("net-001", kb_status="pending", category="network"), "pitfall", "network")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0
        assert "[hardware]" in result.output
        assert "[network]" in result.output
        assert "hw-001" in result.output
        assert "net-001" in result.output

    def test_json_output_contains_format_field(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending"), "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending", "--json"])
        assert result.exit_code == 0
        import json as _json
        data = _json.loads(result.output)
        assert any(e.get("format") == "new" for e in data)

    def test_show_new_format_entry(self, kb_root: Path) -> None:
        content = _make_entry("hw-001", kb_status="pending")
        write_pending(kb_root, "hw-001", content, "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending", "--show", "hw-001"])
        assert result.exit_code == 0
        assert "hw-001" in result.output


# ---------------------------------------------------------------------------
# CLI — holmes kb approve (US1 + US2)
# ---------------------------------------------------------------------------

class TestCliApprove:
    def test_approve_basic_no_conflicts(self, kb_root: Path) -> None:
        write_pending(kb_root, "hw-init-001", _make_entry("hw-init-001", kb_status="pending"), "pitfall", "hardware")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-init-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        assert "✓ Approved" in result.output
        assert (kb_root / "pitfall" / "hardware" / "hw-init-001.md").exists()

    def test_approve_nonexistent_exits_1(self, kb_root: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "does-not-exist", "--no-interactive"],
        )
        assert result.exit_code == 1

    def test_approve_with_old_pending_cancelled(self, kb_root: Path) -> None:
        src = "docs/hw.md"
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file=src), "pitfall", "hardware")
        write_pending(kb_root, "hw-002", _make_entry("hw-002", kb_status="pending", source_file=src), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-002", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        # hw-001 (old pending) should be cancelled.
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-001.md").exists()
        # hw-002 should be approved (type=pitfall → pitfall/hardware/).
        assert (kb_root / "pitfall" / "hardware" / "hw-002.md").exists()

    def test_approve_with_old_confirmed_deprecated(self, kb_root: Path) -> None:
        src = "docs/hw.md"
        # Confirmed active entry.
        content_old = _make_entry("hw-000", kb_status="active", source_file=src)
        path_old = kb_root / "pitfall" / "hw-000.md"
        path_old.parent.mkdir(parents=True, exist_ok=True)
        path_old.write_text(content_old, encoding="utf-8")

        # New pending entry.
        write_pending(kb_root, "hw-001", _make_entry("hw-001", kb_status="pending", source_file=src), "pitfall", "hardware")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "hw-001", "--no-interactive"],
        )
        assert result.exit_code == 0, result.output
        # hw-000 should be deprecated.
        post = frontmatter.load(str(path_old))
        assert post.metadata["kb_status"] == "deprecated"
        # hw-001 should be approved (type=pitfall → pitfall/hardware/).
        assert (kb_root / "pitfall" / "hardware" / "hw-001.md").exists()
