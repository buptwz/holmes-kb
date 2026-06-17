"""Tests for FR-5: kb_read(entry_id) returns skill_invocations field."""

from __future__ import annotations

from pathlib import Path

import pytest


ENTRY_WITH_MARKERS = """\
---
id: PT-NW-001
type: pitfall
title: E810 TX Hang 排查
maturity: draft
category: network
tags: [e810]
created_at: 2026-06-17T00:00:00+00:00
updated_at: 2026-06-17T00:00:00+00:00
skill_refs:
  - e810-firmware-upgrade
  - e810-driver-tuning
---

## Symptoms

间歇性 TX Hang。

## Root Cause

固件版本过低。

## Resolution

### Step 3：执行固件升级

> skill: e810-firmware-upgrade

执行完整升级流程。

### Step 5：驱动调参

3. 执行调参 → `[skill:e810-driver-tuning]`
"""

ENTRY_NO_MARKERS = """\
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
    pitfall_dir = kb_root / "pitfall"
    pitfall_dir.mkdir(parents=True, exist_ok=True)
    (pitfall_dir / "PT-NW-001.md").write_text(ENTRY_WITH_MARKERS, encoding="utf-8")
    (pitfall_dir / "PT-DB-001.md").write_text(ENTRY_NO_MARKERS, encoding="utf-8")
    return kb_root


class TestSkillInvocations:
    def test_entry_with_markers_has_skill_invocations(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        assert "skill_invocations" in result
        invocations = result["skill_invocations"]
        assert len(invocations) == 2

        skills = {inv["skill"] for inv in invocations}
        assert "e810-firmware-upgrade" in skills
        assert "e810-driver-tuning" in skills

    def test_skill_invocations_has_step_field(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        invocations = result["skill_invocations"]
        for inv in invocations:
            assert "step" in inv
            assert "skill" in inv

    def test_entry_without_markers_returns_empty_list(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-DB-001")

        assert "skill_invocations" in result
        assert result["skill_invocations"] == []

    def test_skill_invocations_step_heading_matches_resolution(self, tmp_path: Path):
        from holmes.mcp.tools import handle_kb_read

        kb_root = _setup_kb(tmp_path)
        result = handle_kb_read(kb_root, "PT-NW-001")

        invocations = result["skill_invocations"]
        firmware_inv = next(i for i in invocations if i["skill"] == "e810-firmware-upgrade")
        assert "Step 3" in firmware_inv["step"]
