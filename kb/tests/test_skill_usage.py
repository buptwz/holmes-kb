"""Unit tests for SkillUsageRecord sidecar (T027 [US5]).

Tests:
  - read_usage on absent file returns defaults
  - write_usage creates .skill_usage.json atomically
  - bump_use increments use_count
  - mark_agent_created sets agent_created=True
  - absorbed_into set on tombstone
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestSkillUsageRecord:
    """T027: SkillUsageRecord sidecar read/write operations."""

    def test_read_absent_file_returns_defaults(self, tmp_path: Path):
        """T027a: read_usage on skill dir with no .skill_usage.json → default zeros."""
        from holmes.kb.skill.usage import read_usage

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)

        record = read_usage(skill_dir)
        assert record.use_count == 0
        assert record.patch_count == 0
        assert record.agent_created is False
        assert record.last_used_at is None
        assert record.absorbed_into is None

    def test_write_usage_creates_file_atomically(self, tmp_path: Path):
        """T027b: write_usage creates .skill_usage.json and it's valid JSON."""
        from holmes.kb.skill.usage import SkillUsageRecord, write_usage

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)

        record = SkillUsageRecord(created_at="2026-06-07T00:00:00+00:00", agent_created=True)
        write_usage(skill_dir, record)

        path = skill_dir / ".skill_usage.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["agent_created"] is True
        assert data["use_count"] == 0

    def test_bump_use_increments_count(self, tmp_path: Path):
        """T027c: bump_use increments use_count by 1 and sets last_used_at."""
        from holmes.kb.skill.usage import SkillUsageRecord, bump_use, write_usage

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)

        record = SkillUsageRecord(created_at="2026-06-07T00:00:00+00:00")
        write_usage(skill_dir, record)

        updated = bump_use(skill_dir)
        assert updated.use_count == 1
        assert updated.last_used_at is not None

        # Bump again.
        updated2 = bump_use(skill_dir)
        assert updated2.use_count == 2

    def test_mark_agent_created_sets_flag(self, tmp_path: Path):
        """T027d: mark_agent_created sets agent_created=True on existing record."""
        from holmes.kb.skill.usage import SkillUsageRecord, mark_agent_created, write_usage

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)

        record = SkillUsageRecord(created_at="2026-06-07T00:00:00+00:00", agent_created=False)
        write_usage(skill_dir, record)
        assert record.agent_created is False

        updated = mark_agent_created(skill_dir)
        assert updated.agent_created is True

        # Verify persisted.
        path = skill_dir / ".skill_usage.json"
        data = json.loads(path.read_text())
        assert data["agent_created"] is True

    def test_set_absorbed_into_creates_tombstone(self, tmp_path: Path):
        """T027e: set_absorbed_into records absorbed_into field in sidecar."""
        from holmes.kb.skill.usage import SkillUsageRecord, set_absorbed_into, write_usage

        skill_dir = tmp_path / "skills" / "old-skill"
        skill_dir.mkdir(parents=True)

        record = SkillUsageRecord(created_at="2026-06-07T00:00:00+00:00", agent_created=True)
        write_usage(skill_dir, record)

        updated = set_absorbed_into(skill_dir, "new-merged-skill")
        assert updated.absorbed_into == "new-merged-skill"

        data = json.loads((skill_dir / ".skill_usage.json").read_text())
        assert data["absorbed_into"] == "new-merged-skill"
