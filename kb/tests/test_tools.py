"""Unit tests for write_kb_entry tool: force_type enforcement (E-2) and dedup (D-5).

Feature 019: Import Pipeline v2 Report Bug Fixes.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter as fm
import pytest


def _make_ctx(kb_root: Path, force_type: str = "", dry_run: bool = False) -> dict:
    return {
        "kb_root": kb_root,
        "dry_run": dry_run,
        "force_type": force_type,
    }


def _make_content(kb_type: str = "pitfall") -> str:
    _SECTIONS = {
        "pitfall": "## Symptoms\ntest\n## Root Cause\ntest\n## Resolution\nrun something\n",
        "model": "## Overview\ntest model\n",
        "guideline": "## Guideline\ntest guideline\n",
        "process": "## Steps\n1. Do something\n",
        "decision": "## Context\ntest context\n## Decision\ntest decision\n",
    }
    body = _SECTIONS.get(kb_type, _SECTIONS["pitfall"])
    return (
        f"---\ntitle: Test Entry\ntype: {kb_type}\ncategory: network\n"
        f"tags:\n- test\nlanguage: zh\n---\n{body}"
    )


def _make_tool_input(kb_root: Path, source_hash: str = "abc123def456789a") -> dict:
    return {
        "content": _make_content("pitfall"),
        "source_hash": source_hash,
        "confidence": 0.9,
        "title": "Test Entry",
    }


# ---------------------------------------------------------------------------
# T009: force_type enforcement in write_kb_entry (E-2 fix)
# ---------------------------------------------------------------------------


class TestWriteKbEntryForceType:
    """write_kb_entry applies force_type from ctx, overriding LLM's classification."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        (kb / "contributions/pending").mkdir(parents=True)
        return kb

    def test_force_type_overrides_pitfall_to_guideline(self, kb_root: Path):
        """Content with type:pitfall is overridden to guideline when force_type=guideline."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root, force_type="guideline")
        tool_input = {
            "content": _make_content("guideline"),
            "source_hash": "abc123def456789a",
            "confidence": 0.9,
            "title": "Test Entry",
        }
        result = write_kb_entry(ctx, tool_input)

        assert result.get("duplicate") is not True, "Should create new entry"
        pending_id = result.get("pending_id")
        assert pending_id is not None

        # Verify written file has type: guideline
        pending_dir = kb_root / "contributions" / "pending"
        written_files = list(pending_dir.glob("*.md"))
        assert written_files, "Pending file must be created"
        post = fm.load(str(written_files[0]))
        assert post.metadata.get("type") == "guideline", (
            f"Expected type=guideline, got {post.metadata.get('type')}"
        )
        assert post.metadata.get("suggested_type") == "guideline"

    def test_force_type_overrides_across_all_valid_types(self, kb_root: Path):
        """force_type works for all valid type values."""
        from holmes.kb.agent.tools import write_kb_entry

        for kb_type in ("model", "process", "decision"):
            kb_sub = kb_root / f"test_{kb_type}"
            kb_sub.mkdir(parents=True, exist_ok=True)
            (kb_sub / "contributions/pending").mkdir(parents=True, exist_ok=True)

            ctx = _make_ctx(kb_sub, force_type=kb_type)
            tool_input = {
                "content": _make_content(kb_type),
                "source_hash": f"hash_{kb_type}_0000001a",
                "confidence": 0.9,
                "title": "Test",
            }
            result = write_kb_entry(ctx, tool_input)
            pending_id = result.get("pending_id")
            assert pending_id is not None

            pending_dir = kb_sub / "contributions" / "pending"
            written_files = list(pending_dir.glob("*.md"))
            post = fm.load(str(written_files[0]))
            assert post.metadata.get("type") == kb_type

    def test_no_force_type_preserves_original(self, kb_root: Path):
        """When force_type is empty, the original type in content is preserved."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root, force_type="")
        tool_input = _make_tool_input(kb_root, source_hash="noforcetype00001a")
        result = write_kb_entry(ctx, tool_input)

        pending_dir = kb_root / "contributions" / "pending"
        written_files = list(pending_dir.glob("*.md"))
        assert written_files
        post = fm.load(str(written_files[0]))
        assert post.metadata.get("type") == "pitfall"


# ---------------------------------------------------------------------------
# T012: source_hash dedup enforcement in write_kb_entry (D-5 fix)
# ---------------------------------------------------------------------------


class TestWriteKbEntryDedup:
    """write_kb_entry enforces source_hash dedup regardless of LLM tool call order."""

    @pytest.fixture
    def kb_root(self, tmp_path: Path) -> Path:
        kb = tmp_path / "kb"
        (kb / "contributions/pending").mkdir(parents=True)
        return kb

    def test_second_import_same_hash_returns_duplicate(self, kb_root: Path):
        """Second write_kb_entry with same source_hash returns duplicate=True, no new file."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root)
        tool_input = _make_tool_input(kb_root, source_hash="dedup00000000001a")

        # First import — should succeed
        result1 = write_kb_entry(ctx, tool_input)
        assert result1.get("duplicate") is not True
        assert result1.get("pending_id") is not None

        pending_dir = kb_root / "contributions" / "pending"
        count_after_first = len(list(pending_dir.glob("*.md")))

        # Second import with same source_hash — should be skipped
        result2 = write_kb_entry(ctx, tool_input)
        assert result2.get("duplicate") is True, "Second import must return duplicate=True"
        assert result2.get("pending_id") == result1.get("pending_id"), (
            "Duplicate response must reference the existing entry ID"
        )

        count_after_second = len(list(pending_dir.glob("*.md")))
        assert count_after_second == count_after_first, (
            "No new pending file should be created on duplicate import"
        )

    def test_third_import_same_hash_still_skipped(self, kb_root: Path):
        """Third import with same source_hash is also skipped (idempotent)."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root)
        tool_input = _make_tool_input(kb_root, source_hash="dedup00000000002a")

        write_kb_entry(ctx, tool_input)  # first
        write_kb_entry(ctx, tool_input)  # second
        result3 = write_kb_entry(ctx, tool_input)  # third

        assert result3.get("duplicate") is True

        pending_dir = kb_root / "contributions" / "pending"
        assert len(list(pending_dir.glob("*.md"))) == 1, "Still only 1 pending file"

    def test_force_flag_bypasses_dedup(self, kb_root: Path):
        """force=True bypasses the source_hash dedup check."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root)
        tool_input_1 = _make_tool_input(kb_root, source_hash="forcebypass0001a")
        tool_input_2 = {**tool_input_1, "force": True}

        result1 = write_kb_entry(ctx, tool_input_1)
        result2 = write_kb_entry(ctx, tool_input_2)

        assert result1.get("duplicate") is not True
        assert result2.get("duplicate") is not True, "force=True must bypass dedup"

        pending_dir = kb_root / "contributions" / "pending"
        assert len(list(pending_dir.glob("*.md"))) == 2

    def test_empty_source_hash_skips_dedup_check(self, kb_root: Path):
        """Empty source_hash does not trigger dedup (no hash to check)."""
        from holmes.kb.agent.tools import write_kb_entry

        ctx = _make_ctx(kb_root)
        tool_input = {**_make_tool_input(kb_root), "source_hash": ""}

        result1 = write_kb_entry(ctx, tool_input)
        result2 = write_kb_entry(ctx, tool_input)

        # Both should write (no hash to deduplicate on)
        assert result1.get("duplicate") is not True
        assert result2.get("duplicate") is not True

        pending_dir = kb_root / "contributions" / "pending"
        assert len(list(pending_dir.glob("*.md"))) == 2

