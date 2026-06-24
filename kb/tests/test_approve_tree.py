"""Tests for M6b — Pending/Approve 树级联.

Covers:
- collect_tree: DFS traversal, cycle safety, cross-space search
- approve_tree: atomic approval, rollback on failure, pre-validation
- cancel_pending_tree: removes _pending/ files, no _trash/
- deprecate_tree: sets kb_status=deprecated on confirmed entries
- CLI: three-layer scenario via CliRunner
- CLI: sub-entry uses M6a path (not collect_tree)
- CLI: kb_pending tree-grouped display
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.store import (
    approve_entry,
    cancel_pending_tree,
    collect_tree,
    deprecate_entry,
    deprecate_tree,
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
    kb_status: str = "pending",
    source_file: str = "",
    parent_id: str = "",
    child_entry_ids: list[str] | None = None,
) -> str:
    src_line = f"source_file: {source_file}\n" if source_file else ""
    parent_line = f"parent_id: {parent_id}\n" if parent_id else ""
    if child_entry_ids:
        children_yaml = "\n".join(f"  - {c}" for c in child_entry_ids)
        children_line = f"child_entry_ids:\n{children_yaml}\n"
    else:
        children_line = ""
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
        f"{parent_line}"
        f"{children_line}"
        f"---\n\n## Description\nTest entry.\n"
    )


def _write_confirmed(kb_root: Path, entry_id: str, *, category: str = "hardware",
                     kb_type: str = "pitfall", source_file: str = "",
                     child_entry_ids: list[str] | None = None) -> Path:
    content = _make_entry(
        entry_id,
        kb_type=kb_type,
        category=category,
        kb_status="active",
        source_file=source_file,
        child_entry_ids=child_entry_ids,
    )
    path = kb_root / kb_type / category / f"{entry_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# T010: collect_tree tests
# ---------------------------------------------------------------------------

class TestCollectTree:
    def test_single_entry(self, kb_root: Path) -> None:
        write_pending(kb_root, "root-001", _make_entry("root-001"), "pitfall", "hardware")
        result = collect_tree(kb_root, "root-001")
        assert result == ["root-001"]

    def test_with_children(self, kb_root: Path) -> None:
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["child-001", "child-002"]),
            "pitfall", "hardware",
        )
        write_pending(kb_root, "child-001", _make_entry("child-001", kb_type="process"), "process", "hardware")
        write_pending(kb_root, "child-002", _make_entry("child-002", kb_type="process"), "process", "hardware")

        result = collect_tree(kb_root, "root-001")
        assert result[0] == "root-001"
        assert set(result) == {"root-001", "child-001", "child-002"}
        assert len(result) == 3

    def test_cycle_safe(self, kb_root: Path) -> None:
        # root points to child, child points back to root → should not loop
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["child-001"]),
            "pitfall", "hardware",
        )
        write_pending(
            kb_root, "child-001",
            _make_entry("child-001", kb_type="process", child_entry_ids=["root-001"]),
            "process", "hardware",
        )
        result = collect_tree(kb_root, "root-001")
        assert "root-001" in result
        assert "child-001" in result
        assert len(result) == 2  # no duplicates despite cycle

    def test_searches_pending_and_confirmed(self, kb_root: Path) -> None:
        # root is in pending, child is in confirmed space
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["child-conf-001"]),
            "pitfall", "hardware",
        )
        _write_confirmed(kb_root, "child-conf-001", category="hardware", kb_type="process")

        result = collect_tree(kb_root, "root-001")
        assert "root-001" in result
        assert "child-conf-001" in result

    def test_missing_child_skipped(self, kb_root: Path) -> None:
        # Child ID not found in either space — should not crash
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["nonexistent-child"]),
            "pitfall", "hardware",
        )
        result = collect_tree(kb_root, "root-001")
        # root is always included; missing child is listed (since it was visited)
        # actually per implementation: _visit adds to result before reading file,
        # and missing child has no file → still appended to result
        assert "root-001" in result


# ---------------------------------------------------------------------------
# T010: approve_tree tests
# ---------------------------------------------------------------------------

class TestApproveTree:
    def _setup_tree(self, kb_root: Path, source: str = "docs/hw.md") -> None:
        """Write root + 2 children to _pending/."""
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", source_file=source, child_entry_ids=["child-001", "child-002"]),
            "pitfall", "hardware",
        )
        write_pending(
            kb_root, "child-001",
            _make_entry("child-001", kb_type="process", source_file=source, parent_id="root-001"),
            "process", "hardware",
        )
        write_pending(
            kb_root, "child-002",
            _make_entry("child-002", kb_type="process", source_file=source, parent_id="root-001"),
            "process", "hardware",
        )

    def test_approves_all_entries(self, kb_root: Path) -> None:
        from holmes.kb.store import approve_tree
        self._setup_tree(kb_root)
        paths = approve_tree(kb_root, "root-001")
        assert len(paths) == 3
        for p in paths:
            assert Path(p).exists()
            post = frontmatter.load(p)
            assert post.metadata["kb_status"] == "active"

    def test_removes_pending_files(self, kb_root: Path) -> None:
        from holmes.kb.store import approve_tree
        self._setup_tree(kb_root)
        approve_tree(kb_root, "root-001")
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "root-001.md").exists()
        assert not (kb_root / "_pending" / "process" / "hardware" / "child-001.md").exists()
        assert not (kb_root / "_pending" / "process" / "hardware" / "child-002.md").exists()

    def test_raises_if_entry_not_in_pending(self, kb_root: Path) -> None:
        from holmes.kb.store import approve_tree
        # Only root is in pending; child-001 is missing
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["child-001"]),
            "pitfall", "hardware",
        )
        # child-001 NOT written anywhere
        with pytest.raises(FileNotFoundError, match="not found in _pending"):
            approve_tree(kb_root, "root-001")

    def test_rollback_on_failure(self, kb_root: Path) -> None:
        from holmes.kb.store import approve_tree
        self._setup_tree(kb_root)

        call_count = 0
        original_approve = approve_entry

        def failing_approve(kb_root: Path, entry_id: str) -> Path:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("simulated failure")
            return original_approve(kb_root, entry_id)

        with patch("holmes.kb.store.approve_entry", side_effect=failing_approve):
            with pytest.raises(RuntimeError, match="approve_tree"):
                approve_tree(kb_root, "root-001")

        # reversed([root-001, child-001, child-002]) → [child-002, child-001, root-001]
        # call 1: child-002 approved (succeeds) → confirmed
        # call 2: child-001 approve fails → rollback child-002 back to _pending/
        rolled_back = kb_root / "_pending" / "process" / "hardware" / "child-002.md"
        assert rolled_back.exists(), "child-002 should have been rolled back to _pending/"
        post = frontmatter.load(str(rolled_back))
        assert post.metadata["kb_status"] == "pending"

        # No confirmed files should remain after rollback
        process_confirmed = list((kb_root / "process").rglob("*.md")) if (kb_root / "process").exists() else []
        assert process_confirmed == [], f"Confirmed process files should be cleaned up: {process_confirmed}"


# ---------------------------------------------------------------------------
# T013: cancel_pending_tree tests
# ---------------------------------------------------------------------------

class TestCancelPendingTree:
    def test_cancel_removes_all_pending_files(self, kb_root: Path) -> None:
        write_pending(
            kb_root, "root-001",
            _make_entry("root-001", child_entry_ids=["child-001", "child-002"]),
            "pitfall", "hardware",
        )
        write_pending(kb_root, "child-001", _make_entry("child-001", kb_type="process"), "process", "hardware")
        write_pending(kb_root, "child-002", _make_entry("child-002", kb_type="process"), "process", "hardware")

        cancelled = cancel_pending_tree(kb_root, "root-001")
        assert len(cancelled) == 3
        for p in cancelled:
            assert not Path(p).exists()

    def test_cancel_no_trash(self, kb_root: Path) -> None:
        write_pending(kb_root, "root-001", _make_entry("root-001"), "pitfall", "hardware")
        cancel_pending_tree(kb_root, "root-001")
        # _trash/ should not be created
        assert not (kb_root / "_trash").exists()


# ---------------------------------------------------------------------------
# T013: deprecate_tree tests
# ---------------------------------------------------------------------------

class TestDeprecateTree:
    def test_deprecate_all_confirmed(self, kb_root: Path) -> None:
        _write_confirmed(kb_root, "root-001", child_entry_ids=["child-001", "child-002"])
        _write_confirmed(kb_root, "child-001", kb_type="process")
        _write_confirmed(kb_root, "child-002", kb_type="process")

        deprecated = deprecate_tree(kb_root, "root-001")
        assert set(deprecated) == {"root-001", "child-001", "child-002"}

        for entry_id in deprecated:
            # Find the file
            for path in kb_root.rglob(f"{entry_id}.md"):
                post = frontmatter.load(str(path))
                assert post.metadata["kb_status"] == "deprecated"
                break


# ---------------------------------------------------------------------------
# T013: three-layer scenario via CLI
# ---------------------------------------------------------------------------

class TestThreeLayerScenario:
    def test_three_layer_via_cli(self, kb_root: Path, tmp_path: Path) -> None:
        """confirmed hw-001 + old pending hw-002 + new pending hw-003."""
        source = "docs/hw.md"

        # Layer 1: confirmed hw-001 tree (2 entries)
        _write_confirmed(kb_root, "hw-root-001", source_file=source, child_entry_ids=["hw-child-001"])
        _write_confirmed(kb_root, "hw-child-001", kb_type="process", source_file=source)

        # Layer 2: old pending hw-002 tree (root only)
        write_pending(
            kb_root, "hw-root-002",
            _make_entry("hw-root-002", source_file=source, kb_status="pending"),
            "pitfall", "hardware",
        )

        # Layer 3: new pending hw-003 tree (root + 1 child)
        write_pending(
            kb_root, "hw-root-003",
            _make_entry("hw-root-003", source_file=source, kb_status="pending",
                        child_entry_ids=["hw-child-003"]),
            "pitfall", "hardware",
        )
        write_pending(
            kb_root, "hw-child-003",
            _make_entry("hw-child-003", kb_type="process", source_file=source,
                        parent_id="hw-root-003", kb_status="pending"),
            "process", "hardware",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "--no-interactive", "hw-root-003"],
        )
        assert result.exit_code == 0, result.output

        # New tree should be approved (active)
        root_path = kb_root / "pitfall" / "hardware" / "hw-root-003.md"
        assert root_path.exists()
        assert frontmatter.load(str(root_path)).metadata["kb_status"] == "active"

        child_path = kb_root / "process" / "hardware" / "hw-child-003.md"
        assert child_path.exists()
        assert frontmatter.load(str(child_path)).metadata["kb_status"] == "active"

        # Old pending hw-002 should be deleted
        assert not (kb_root / "_pending" / "pitfall" / "hardware" / "hw-root-002.md").exists()

        # Old confirmed hw-001 tree should be deprecated
        old_root_path = kb_root / "pitfall" / "hardware" / "hw-root-001.md"
        assert frontmatter.load(str(old_root_path)).metadata["kb_status"] == "deprecated"

    def test_sub_entry_uses_m6a_path(self, kb_root: Path) -> None:
        """Process sub-entry (has parent_id) → CLI uses M6a single-entry flow."""
        from holmes.kb.store import _find_pending_entry

        source = "docs/hw.md"
        write_pending(
            kb_root, "proc-001",
            _make_entry("proc-001", kb_type="process", source_file=source,
                        parent_id="some-root-001", kb_status="pending"),
            "process", "hardware",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--kb-path", str(kb_root), "kb", "approve", "--no-interactive", "proc-001"],
        )
        assert result.exit_code == 0, result.output
        # collect_tree should NOT have been called (output won't have "个关联 entries")
        assert "个关联 entries" not in result.output
        # Entry should now be confirmed
        assert _find_pending_entry(kb_root, "proc-001") is None
        assert (kb_root / "process" / "hardware" / "proc-001.md").exists()


# ---------------------------------------------------------------------------
# T016: kb_pending tree-grouped display
# ---------------------------------------------------------------------------

class TestPendingDisplay:
    def test_tree_grouped(self, kb_root: Path) -> None:
        """1 pitfall root + 2 process children + 1 guideline → tree-grouped output."""
        source = "docs/hw.md"
        write_pending(
            kb_root, "hw-root-001",
            _make_entry("hw-root-001", source_file=source, child_entry_ids=["hw-proc-001", "hw-proc-002"]),
            "pitfall", "hardware",
        )
        write_pending(
            kb_root, "hw-proc-001",
            _make_entry("hw-proc-001", kb_type="process", source_file=source, parent_id="hw-root-001"),
            "process", "hardware",
        )
        write_pending(
            kb_root, "hw-proc-002",
            _make_entry("hw-proc-002", kb_type="process", source_file=source, parent_id="hw-root-001"),
            "process", "hardware",
        )
        write_pending(
            kb_root, "net-guide-001",
            _make_entry("net-guide-001", kb_type="guideline", category="network"),
            "guideline", "network",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0, result.output
        output = result.output

        # Should show [pitfall root] label for root
        assert "[pitfall root]" in output
        # Should show hw-root-001
        assert "hw-root-001" in output
        # Should show child entries
        assert "hw-proc-001" in output
        assert "hw-proc-002" in output
        # Guideline should be flat
        assert "net-guide-001" in output
        assert "[guideline]" in output

    def test_no_sub_entry_duplication(self, kb_root: Path) -> None:
        """Process sub-entry should appear only once (under tree, not in flat list)."""
        write_pending(
            kb_root, "hw-root-001",
            _make_entry("hw-root-001", child_entry_ids=["hw-proc-001"]),
            "pitfall", "hardware",
        )
        write_pending(
            kb_root, "hw-proc-001",
            _make_entry("hw-proc-001", kb_type="process", parent_id="hw-root-001"),
            "process", "hardware",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0, result.output
        output = result.output

        # hw-proc-001 should appear exactly once in the output
        assert output.count("hw-proc-001") == 1

    def test_no_entries(self, kb_root: Path) -> None:
        """Empty _pending/ → 'No pending entries.' message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--kb-path", str(kb_root), "kb", "pending"])
        assert result.exit_code == 0, result.output
        assert "No pending entries." in result.output
