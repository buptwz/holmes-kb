"""Skill invocation marker parser — FR-1.

Parses skill call markers from KB entry Resolution text.
Two marker forms are supported:

  Blockquote:  > skill: skill-name   (standalone line)
  Inline:      `[skill:skill-name]`  (anywhere in a line)

Returns a list of SkillMarker dicts, one per recognised marker.
"""

from __future__ import annotations

import re
from typing import TypedDict

# Same pattern used in schema.py for skill_refs validation.
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$")

# Blockquote form: > skill: <name>   (leading optional spaces, full line)
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s*skill:\s*([^\s]+)\s*$", re.MULTILINE)

# Inline form: `[skill:<name>]`
_INLINE_RE = re.compile(r"`\[skill:([^\]]+)\]`")

# H2 or H3 heading line.
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)


class SkillMarker(TypedDict):
    """A single skill invocation marker found in Resolution text."""

    skill_name: str       # Validated kebab-case skill name.
    step_heading: str     # Nearest preceding ## / ### heading, or "".
    marker_type: str      # "blockquote" | "inline"
    line: int             # 1-indexed line number of the marker.


def extract_skill_markers(resolution_text: str) -> list[SkillMarker]:
    """Parse skill invocation markers from a Resolution Markdown section.

    Args:
        resolution_text: Full text of the Resolution section (frontmatter
                         already stripped).

    Returns:
        List of SkillMarker dicts.  Invalid skill names are silently skipped.
        Duplicate skill names are all returned (caller deduplicates as needed).
    """
    lines = resolution_text.splitlines()

    # Build a mapping: line_number (1-indexed) → nearest preceding heading text.
    line_to_heading: dict[int, str] = {}
    current_heading = ""
    for idx, line in enumerate(lines, start=1):
        m = _HEADING_RE.match(line)
        if m:
            current_heading = line.strip()
        line_to_heading[idx] = current_heading

    markers: list[SkillMarker] = []

    # --- Blockquote markers ---
    for m in _BLOCKQUOTE_RE.finditer(resolution_text):
        raw_name = m.group(1).strip()
        if not _SKILL_NAME_RE.match(raw_name):
            continue  # invalid name — skip silently
        # Compute 1-indexed line number from match start offset.
        line_no = resolution_text[: m.start()].count("\n") + 1
        markers.append(
            SkillMarker(
                skill_name=raw_name,
                step_heading=line_to_heading.get(line_no, ""),
                marker_type="blockquote",
                line=line_no,
            )
        )

    # --- Inline markers ---
    for m in _INLINE_RE.finditer(resolution_text):
        raw_name = m.group(1).strip()
        if not _SKILL_NAME_RE.match(raw_name):
            continue  # invalid name — skip silently
        line_no = resolution_text[: m.start()].count("\n") + 1
        markers.append(
            SkillMarker(
                skill_name=raw_name,
                step_heading=line_to_heading.get(line_no, ""),
                marker_type="inline",
                line=line_no,
            )
        )

    # Return sorted by line number for deterministic ordering.
    markers.sort(key=lambda mk: mk["line"])
    return markers
