"""Tests for kb/holmes/kb/agent/dag/tools2.py — tool_write_entry content quality.

Covers:
  TC-BT01: Steps behavior tag completeness
  TC-BT02: [api]/[remote] steps must include executable content
  TC-S02:  match_failed content_source warning
"""

from __future__ import annotations

from pathlib import Path

import pytest

from holmes.kb.agent.dag.tools2 import tool_write_entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> dict:
    """Minimal ctx for tool_write_entry in dry_run mode."""
    return {
        "state_dir": tmp_path / "_import-state",
        "source_hash": "abc12345678901ab",
        "source_file": "test.md",
        "source_text": "test",
        "kb_root": tmp_path,
        "pending_root": tmp_path / "_pending",
        "dry_run": True,
        "dag_json": {},
        "entry_ids": {},
        "written_entries": [],
    }


_FM_PROCESS = """\
---
id: proc-001
title: Firmware Repair
description: Repair firmware on GPU
type: process
category: hardware
kb_status: pending
source_file: test.md
source_hash: abc12345678901ab
import_trace_id: trace-001
parent_id: pitfall-001
maturity: draft
decay_status: active
next_decay_check: "2027-01-01"
created_at: "2026-07-01T00:00:00+00:00"
updated_at: "2026-07-01T00:00:00+00:00"
contributors:
  - user: testuser
    role: initiator
tags:
  - gpu
---

"""


def _make_entry(steps_body: str) -> str:
    return _FM_PROCESS + "## Steps\n\n" + steps_body


# ---------------------------------------------------------------------------
# TC-BT01: valid behavior tags → no content_warnings
# ---------------------------------------------------------------------------


def test_write_entry_all_behavior_tags_no_warnings(tmp_path):
    """Steps with proper behavior tags produce no content_warnings."""
    steps = (
        "1. **[api]** Run `nvidia-smi -pm 1` to enable persistence mode.\n"
        "2. **[observe]** Check the output for `Enabled`.\n"
        "3. **[decide]** If success → done, else retry.\n"
    )
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-001",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    assert "content_warnings" not in result


def test_write_entry_physical_observe_decide_no_code_no_warnings(tmp_path):
    """[physical]/[observe]/[decide] steps without code blocks are valid."""
    steps = (
        "1. **[physical]** Remove the GPU card from the slot.\n"
        "2. **[observe]** Check for visible burn marks.\n"
        "3. **[decide]** If burn marks found → escalate, else reinstall.\n"
    )
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-002",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    assert "content_warnings" not in result


# ---------------------------------------------------------------------------
# TC-BT01: missing behavior tags → content_warnings (non-blocking)
# ---------------------------------------------------------------------------


def test_write_entry_step_missing_behavior_tag_warns(tmp_path):
    """Step without **[tag]** generates a content_warning; entry still written."""
    steps = (
        "1. Run nvidia-smi to check GPU status.\n"
        "2. **[observe]** Check output.\n"
    )
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-003",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    assert len(warnings) >= 1
    assert any("missing behavior tag" in w for w in warnings)


def test_write_entry_all_steps_missing_tags_warns_each(tmp_path):
    """Each tagless step generates its own content_warning."""
    steps = (
        "1. Do step one without tag.\n"
        "2. Do step two without tag.\n"
    )
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-004",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    assert len(warnings) >= 2


# ---------------------------------------------------------------------------
# TC-BT02: [api]/[remote] without code block → content_warnings
# ---------------------------------------------------------------------------


def test_write_entry_api_step_with_code_block_no_warning(tmp_path):
    """[api] step with code block produces no content_warning for that step."""
    steps = (
        "1. **[api]** Run the following command:\n\n"
        "   ```bash\n"
        "   nvidia-smi -pm 1\n"
        "   ```\n\n"
        "2. **[observe]** Verify output shows `Enabled`.\n"
    )
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-005",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    # Should not have api-related code-missing warning
    assert not any("missing executable command" in w for w in warnings)


def test_write_entry_api_step_with_inline_code_no_warning(tmp_path):
    """[api] step with inline backtick code produces no code-missing warning."""
    steps = "1. **[api]** Run `nvidia-smi -pm 1` to enable persistence.\n"
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-006",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    assert not any("missing executable command" in w for w in warnings)


def test_write_entry_api_step_without_code_warns(tmp_path):
    """[api] step with no code at all generates a content_warning."""
    steps = "1. **[api]** Enable persistence mode on the GPU card.\n"
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-007",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    assert any("missing executable command" in w for w in warnings)


def test_write_entry_remote_step_without_code_warns(tmp_path):
    """[remote] step with no code at all generates a content_warning."""
    steps = "1. **[remote]** Connect via SSH and restart the service.\n"
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-008",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    warnings = result.get("content_warnings", [])
    assert any("missing executable command" in w for w in warnings)


# ---------------------------------------------------------------------------
# TC-BT02: content_warnings are non-blocking (entry still written)
# ---------------------------------------------------------------------------


def test_write_entry_content_warnings_non_blocking(tmp_path):
    """Even with content_warnings, success=True and entry is recorded."""
    steps = "1. Do something without a tag.\n"
    ctx = _ctx(tmp_path)
    result = tool_write_entry(ctx, {
        "entry_id": "proc-009",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    # Entry recorded in written_entries
    assert any(e["entry_id"] == "proc-009" for e in ctx["written_entries"])


# ---------------------------------------------------------------------------
# TC-S02: match_failed content_source → warning field in result
# ---------------------------------------------------------------------------


_FM_PROCESS_MATCH_FAILED = """\
---
id: proc-mf-001
title: Firmware Repair
description: Repair firmware on GPU
type: process
category: hardware
kb_status: pending
source_file: test.md
source_hash: abc12345678901ab
import_trace_id: trace-001
parent_id: pitfall-001
content_source: match_failed
maturity: draft
decay_status: active
next_decay_check: "2027-01-01"
created_at: "2026-07-01T00:00:00+00:00"
updated_at: "2026-07-01T00:00:00+00:00"
contributors:
  - user: testuser
    role: initiator
tags:
  - gpu
---

"""


def test_write_entry_match_failed_returns_warning(tmp_path):
    """content_source: match_failed → result contains 'warning' key."""
    steps = "1. **[observe]** Check system logs manually.\n"
    content = _FM_PROCESS_MATCH_FAILED + "## Steps\n\n" + steps
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-010",
        "content": content,
    })
    assert result.get("success") is True
    assert "warning" in result
    assert "match_failed" in result["warning"]


def test_write_entry_no_content_source_no_warning_field(tmp_path):
    """Without content_source, no 'warning' key in result."""
    steps = "1. **[observe]** Check LEDs.\n"
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-011",
        "content": _make_entry(steps),
    })
    assert result.get("success") is True
    assert "warning" not in result


def test_write_entry_description_match_failed_also_warns(tmp_path):
    """Legacy content_source: description_match_failed also triggers warning."""
    fm = _FM_PROCESS_MATCH_FAILED.replace(
        "content_source: match_failed",
        "content_source: description_match_failed",
    )
    steps = "1. **[observe]** Check LEDs.\n"
    content = fm + "## Steps\n\n" + steps
    result = tool_write_entry(_ctx(tmp_path), {
        "entry_id": "proc-012",
        "content": content,
    })
    assert result.get("success") is True
    assert "warning" in result
