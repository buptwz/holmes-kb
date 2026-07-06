"""Tests for kb_read(entry_id) — skill_refs enrichment.

Verifies that skill_refs in the response include name + description
when the skill exists, and stale refs (pointing to missing skills)
are silently omitted.
"""

from __future__ import annotations

from pathlib import Path

import pytest


ENTRY_WITH_REFS = """\
---
id: PT-NW-001
type: pitfall
title: E810 TX Hang
maturity: draft
category: network
tags: [e810]
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
skill_refs:
  - e810-firmware-upgrade
  - stale-missing-skill
---

## Symptoms

TX Hang.

## Root Cause

Old firmware.

## Resolution

Upgrade firmware.
"""

SKILL_MD = """\
---
name: e810-firmware-upgrade
description: Upgrade E810 NIC firmware to fix TX hang
---

## Steps

1. Download firmware.
"""

ENTRY_NO_REFS = """\
---
id: PT-DB-001
type: pitfall
title: Redis OOM
maturity: draft
category: database
tags: []
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
---

## Symptoms

OOM killer.

## Root Cause

Memory limit.

## Resolution

Restart the service with higher memory.
"""


def _setup_kb(tmp_path: Path) -> Path:
    kb_root = tmp_path / "kb"
    pitfall_dir = kb_root / "pitfall" / "network"
    pitfall_dir.mkdir(parents=True, exist_ok=True)
    (pitfall_dir / "PT-NW-001.md").write_text(ENTRY_WITH_REFS, encoding="utf-8")

    pitfall_db = kb_root / "pitfall" / "database"
    pitfall_db.mkdir(parents=True, exist_ok=True)
    (pitfall_db / "PT-DB-001.md").write_text(ENTRY_NO_REFS, encoding="utf-8")

    skill_dir = kb_root / "skills" / "e810-firmware-upgrade"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

    return kb_root


class TestEnrichedSkillRefs:
    def test_entry_with_refs_returns_enriched_skill_refs(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        assert "skill_refs" in result
        refs = result["skill_refs"]
        # Only the existing skill should appear (stale ref skipped)
        assert len(refs) == 1
        assert refs[0]["name"] == "e810-firmware-upgrade"
        assert "Upgrade E810" in refs[0]["description"]

    def test_stale_skill_ref_omitted(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        names = [r["name"] for r in result["skill_refs"]]
        assert "stale-missing-skill" not in names

    def test_entry_without_refs_returns_empty_list(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-DB-001")

        assert "skill_refs" in result
        assert result["skill_refs"] == []

    def test_skill_invocations_field_removed(self, tmp_path: Path):
        """skill_invocations was a dead field — verify it no longer appears."""
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")
        assert "skill_invocations" not in result

    def test_hint_includes_skill_names(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        assert "usage_guide" in result
        assert "e810-firmware-upgrade" in result["usage_guide"]
