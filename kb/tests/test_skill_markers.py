"""Tests for FR-1: extract_skill_markers() — skill invocation marker parser."""

from __future__ import annotations

import pytest

from holmes.kb.skill.markers import extract_skill_markers


RESOLUTION_MIXED = """\
总览：分步排查。

### Step 1：确认型号

lspci 确认。

### Step 2：读取固件版本

ethtool 读取。

### Step 3：执行固件升级

> skill: e810-firmware-upgrade

此步骤通过 skill 执行完整的固件升级流程。

### Step 4：调整驱动参数

inline 步骤，无 skill。

### Step 5：验证修复

3. 执行驱动调参 → `[skill:e810-driver-tuning]`
"""


class TestBlockquoteMarker:
    def test_single_blockquote_detected(self):
        text = "> skill: my-skill\n\n正文。\n"
        result = extract_skill_markers(text)
        assert len(result) == 1
        assert result[0]["skill_name"] == "my-skill"
        assert result[0]["marker_type"] == "blockquote"

    def test_blockquote_with_leading_spaces(self):
        text = "   > skill: my-skill\n"
        result = extract_skill_markers(text)
        assert len(result) == 1
        assert result[0]["skill_name"] == "my-skill"

    def test_blockquote_heading_association(self):
        text = "### Step 3：升级固件\n\n> skill: e810-firmware-upgrade\n"
        result = extract_skill_markers(text)
        assert result[0]["step_heading"] == "### Step 3：升级固件"

    def test_blockquote_without_preceding_heading(self):
        text = "> skill: my-skill\n"
        result = extract_skill_markers(text)
        assert result[0]["step_heading"] == ""


class TestInlineMarker:
    def test_single_inline_detected(self):
        text = "3. 执行固件升级 → `[skill:e810-firmware-upgrade]`\n"
        result = extract_skill_markers(text)
        assert len(result) == 1
        assert result[0]["skill_name"] == "e810-firmware-upgrade"
        assert result[0]["marker_type"] == "inline"

    def test_inline_heading_association(self):
        text = "### Step 5：验证修复\n\n3. 执行调参 → `[skill:e810-driver-tuning]`\n"
        result = extract_skill_markers(text)
        assert result[0]["step_heading"] == "### Step 5：验证修复"


class TestMixedMarkers:
    def test_mixed_markers_both_detected(self):
        result = extract_skill_markers(RESOLUTION_MIXED)
        names = [m["skill_name"] for m in result]
        assert "e810-firmware-upgrade" in names
        assert "e810-driver-tuning" in names
        assert len(result) == 2

    def test_mixed_markers_ordered_by_line(self):
        result = extract_skill_markers(RESOLUTION_MIXED)
        assert result[0]["skill_name"] == "e810-firmware-upgrade"
        assert result[1]["skill_name"] == "e810-driver-tuning"
        assert result[0]["line"] < result[1]["line"]

    def test_mixed_marker_types(self):
        result = extract_skill_markers(RESOLUTION_MIXED)
        types = {m["skill_name"]: m["marker_type"] for m in result}
        assert types["e810-firmware-upgrade"] == "blockquote"
        assert types["e810-driver-tuning"] == "inline"


class TestInvalidSkillName:
    def test_invalid_name_uppercase_skipped(self):
        text = "> skill: MySkill\n"
        result = extract_skill_markers(text)
        assert result == []

    def test_invalid_name_with_underscores_skipped(self):
        text = "> skill: my_skill\n"
        result = extract_skill_markers(text)
        assert result == []

    def test_invalid_name_starts_with_dash_skipped(self):
        text = "> skill: -bad-name\n"
        result = extract_skill_markers(text)
        assert result == []

    def test_valid_two_char_name(self):
        text = "> skill: ab\n"
        result = extract_skill_markers(text)
        assert len(result) == 1
        assert result[0]["skill_name"] == "ab"


class TestNoMarkers:
    def test_empty_text_returns_empty(self):
        assert extract_skill_markers("") == []

    def test_plain_resolution_returns_empty(self):
        text = "Step 1: do something.\nStep 2: do something else.\n"
        assert extract_skill_markers(text) == []

    def test_blockquote_without_skill_prefix_ignored(self):
        text = "> This is a regular blockquote.\n"
        assert extract_skill_markers(text) == []


class TestDuplicateMarkers:
    def test_duplicate_skill_name_both_returned(self):
        text = "> skill: my-skill\n\n> skill: my-skill\n"
        result = extract_skill_markers(text)
        assert len(result) == 2
        assert all(m["skill_name"] == "my-skill" for m in result)

    def test_same_name_different_forms_both_returned(self):
        text = "> skill: my-skill\n\n`[skill:my-skill]`\n"
        result = extract_skill_markers(text)
        assert len(result) == 2


class TestLineNumbers:
    def test_line_number_is_correct(self):
        text = "Line 1\nLine 2\n> skill: my-skill\nLine 4\n"
        result = extract_skill_markers(text)
        assert result[0]["line"] == 3

    def test_inline_line_number_is_correct(self):
        text = "Line 1\n`[skill:my-skill]`\n"
        result = extract_skill_markers(text)
        assert result[0]["line"] == 2
