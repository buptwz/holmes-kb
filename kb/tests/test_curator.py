"""Unit tests for SkillCurator (T026 [US5]).

Tests the three finding types:
  - merge_candidate: Jaccard > 0.6
  - oversized: SKILL.md body > 3000 chars
  - update_candidate: patch_count=0 + linked entry updated after skill creation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_skill(kb_root: Path, name: str, description: str, body_content: str = "",
                agent_created: bool = True, patch_count: int = 0,
                created_at: str = "2026-01-01T00:00:00+00:00") -> Path:
    """Helper: create a skill directory with SKILL.md and .skill_usage.json."""
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts").mkdir(exist_ok=True)

    skill_md = f"""\
---
name: {name}
description: {description}
version: 1.0.0
platforms: linux,macos
timeout: 30
---

## Usage

{body_content or 'Run this skill to perform the operation.'}
"""
    (skill_dir / "SKILL.md").write_text(skill_md)
    (skill_dir / "scripts" / "run.sh").write_text("#!/bin/bash\necho 'ok'\n")

    usage_data = {
        "created_at": created_at,
        "agent_created": agent_created,
        "use_count": 0,
        "last_used_at": None,
        "patch_count": patch_count,
        "last_patched_at": None,
        "absorbed_into": None,
    }
    (skill_dir / ".skill_usage.json").write_text(json.dumps(usage_data))
    return skill_dir


class TestSkillCurator:
    """T026: SkillCurator identifies merge/oversized/update_candidate findings."""

    def test_jaccard_above_threshold_returns_merge_candidate(self, tmp_path: Path):
        """T026a: two skills with similar descriptions (Jaccard > 0.6) → merge_candidate."""
        from holmes.kb.agent.curator import MERGE_JACCARD_THRESHOLD, SkillCurator

        kb_root = tmp_path / "kb"
        _make_skill(kb_root, "check-pg-connections",
                    "check PostgreSQL database connection pool status and count")
        _make_skill(kb_root, "pg-connection-monitor",
                    "monitor PostgreSQL database connection pool count and status")

        curator = SkillCurator()
        findings = curator.curate(kb_root, category=None)

        merge_findings = [f for f in findings if f.finding_type == "merge_candidate"]
        assert len(merge_findings) >= 1
        names_in_finding = set()
        for f in merge_findings:
            names_in_finding.update(f.skill_names)
        assert "check-pg-connections" in names_in_finding or "pg-connection-monitor" in names_in_finding

    def test_oversized_body_returns_oversized_finding(self, tmp_path: Path):
        """T026b: SKILL.md body > 3000 chars → oversized finding."""
        from holmes.kb.agent.curator import OVERSIZED_BODY_THRESHOLD, SkillCurator

        kb_root = tmp_path / "kb"
        big_body = "Step: do something important.\n" * 200  # well over 3000 chars
        _make_skill(kb_root, "giant-skill", "Giant skill with too much content", body_content=big_body)

        curator = SkillCurator()
        findings = curator.curate(kb_root, category=None)

        oversized_findings = [f for f in findings if f.finding_type == "oversized"]
        assert len(oversized_findings) >= 1
        assert "giant-skill" in oversized_findings[0].skill_names

    def test_update_candidate_when_entry_updated_after_skill(self, tmp_path: Path):
        """T026c: patch_count=0 + linked entry updated after skill created → update_candidate."""
        from holmes.kb.agent.curator import SkillCurator

        kb_root = tmp_path / "kb"
        # Skill created early.
        _make_skill(kb_root, "pg-oom-recovery",
                    "Recover from PostgreSQL OOM crash",
                    created_at="2026-01-01T00:00:00+00:00",
                    patch_count=0)

        # Linked KB entry updated more recently.
        (kb_root / "pitfall" / "database").mkdir(parents=True, exist_ok=True)
        entry_content = """\
---
id: PT-DB-001
type: pitfall
title: PostgreSQL OOM
maturity: draft
category: database
tags: []
created_at: "2026-01-01"
updated_at: "2026-06-01T00:00:00+00:00"
skill_refs:
  - pg-oom-recovery
---

## Resolution
Reduce shared_buffers.
"""
        (kb_root / "pitfall" / "database" / "PT-DB-001.md").write_text(entry_content)

        curator = SkillCurator()
        findings = curator.curate(kb_root, category=None)

        update_findings = [f for f in findings if f.finding_type == "update_candidate"]
        assert len(update_findings) >= 1
        assert "pg-oom-recovery" in update_findings[0].skill_names
