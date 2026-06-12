"""T-EDGE-*: Edge condition and security constraint tests for KB Skill."""

from __future__ import annotations

import textwrap
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.schema import validate_entry
from holmes.kb.skill.manager import (
    create_skill,
    detect_commands,
    get_skill_dir,
    link_skill,
    list_skills,
    validate_skill_name,
)
from tests.conftest import make_entry


# ---------------------------------------------------------------------------
# TT035: T-EDGE-001~003  skills/ absence, multi-entry refs, missing SKILL.md
# ---------------------------------------------------------------------------


def test_edge001_skills_dir_absent_returns_empty(tmp_path):
    """T-EDGE-001: list_skills when skills/ dir does not exist returns empty list."""
    skills = list_skills(tmp_path)
    assert skills == []


def test_edge002_multiple_entries_reference_same_skill(tmp_path):
    """T-EDGE-002: multiple KB entries can reference the same skill."""
    make_entry(tmp_path, "PT-DB-001")
    make_entry(tmp_path, "PT-DB-002")
    create_skill(tmp_path, "check-redis", "test")

    link_skill(tmp_path, "PT-DB-001", "check-redis")
    link_skill(tmp_path, "PT-DB-002", "check-redis")

    skills = list_skills(tmp_path)
    assert any(s.name == "check-redis" for s in skills)
    skill_info = next(s for s in skills if s.name == "check-redis")
    assert "PT-DB-001" in skill_info.linked_entries
    assert "PT-DB-002" in skill_info.linked_entries


def test_edge003_list_skills_skips_missing_skill_md(tmp_path):
    """T-EDGE-003: directory under skills/ without SKILL.md is silently skipped."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "incomplete-skill").mkdir()  # no SKILL.md inside

    skills = list_skills(tmp_path)
    assert len(skills) == 0


# ---------------------------------------------------------------------------
# TT036: T-EDGE-004  Skill name boundary values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "abc",                           # 3 chars — minimum valid
    "a" * 64,                        # 64 chars — maximum valid
])
def test_edge004_valid_name_boundaries(name):
    """T-EDGE-004: boundary-valid names must not raise."""
    validate_skill_name(name)  # should not raise


@pytest.mark.parametrize("name", [
    "ab",                            # too short (2)
    "a" * 65,                        # too long (65)
    "Check",                         # uppercase
    "check_redis",                   # underscore
    "check redis",                   # space
    "-check",                        # leading hyphen
    "check-",                        # trailing hyphen
])
def test_edge004_invalid_name_raises(name):
    """T-EDGE-004: boundary-invalid names must raise ValueError."""
    with pytest.raises(ValueError):
        validate_skill_name(name)


# ---------------------------------------------------------------------------
# TT040: T-EDGE-008  Path traversal defense
# ---------------------------------------------------------------------------


def test_edge008_path_traversal_validate_skill_name():
    """T-EDGE-008: validate_skill_name raises ValueError for path traversal attempt."""
    with pytest.raises(ValueError):
        validate_skill_name("../../../etc/passwd")


def test_edge008_skill_refs_path_separator_invalid():
    """T-EDGE-008: skill_refs containing path separator fails schema validation."""
    content = textwrap.dedent("""\
        ---
        id: PT-DB-001
        type: pitfall
        title: Test
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        skill_refs:
          - skills/check-redis
        ---

        ## Symptoms
        s
        ## Root Cause
        r
        ## Resolution
        r
    """)
    result = validate_entry(content)
    assert result.valid is False


# ---------------------------------------------------------------------------
# TT042: T-EDGE-010  Repeated link_skill — no duplicate entries
# ---------------------------------------------------------------------------


def test_edge010_repeated_link_skill_no_duplicates(tmp_path):
    """T-EDGE-010: calling link_skill N times must not create duplicate skill_refs."""
    make_entry(tmp_path, "PT-DB-001")
    create_skill(tmp_path, "check-redis", "test")

    for _ in range(3):
        link_skill(tmp_path, "PT-DB-001", "check-redis")

    entry_path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
    post = frontmatter.load(str(entry_path))
    refs = list(post.metadata.get("skill_refs") or [])
    assert refs.count("check-redis") == 1, f"Expected 1, got {refs}"
