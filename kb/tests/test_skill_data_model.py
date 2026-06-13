"""T-DM-*: Data model validation tests for KB Skill (Anthropic Agent Skills format)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.schema import validate_entry
from holmes.kb.skill.manager import (
    SkillDefinition,
    create_skill,
    link_skill,
    parse_skill_md,
    validate_skill_md,
    validate_skill_name,
)
from tests.conftest import make_entry


# ---------------------------------------------------------------------------
# T-DM-001: create_skill directory structure (new format)
# ---------------------------------------------------------------------------


def test_dm001_create_skill_directory_structure(kb_root):
    """Verify create_skill produces SKILL.md by default; scripts/ and other subdirs are optional."""
    skill_dir = create_skill(kb_root, "check-redis", "Diagnose Redis connection pool exhaustion.")

    assert skill_dir.is_dir(), "skill directory must exist"
    assert (skill_dir / "SKILL.md").is_file(), "SKILL.md must exist"


def test_dm001_dir_name_matches_skillmd_name(kb_root):
    """Directory name must equal the 'name' field in SKILL.md frontmatter."""
    create_skill(kb_root, "check-redis", "test")
    defn = parse_skill_md(kb_root / "skills" / "check-redis" / "SKILL.md")
    assert defn.name == "check-redis"


# ---------------------------------------------------------------------------
# T-DM-002: SKILL.md frontmatter — new minimal format
# ---------------------------------------------------------------------------


def test_dm002_frontmatter_only_name_and_description(kb_root):
    """Generated SKILL.md must contain only name and description in frontmatter."""
    create_skill(kb_root, "my-skill", "My description")
    skill_md = kb_root / "skills" / "my-skill" / "SKILL.md"
    post = frontmatter.load(str(skill_md))

    assert post.metadata.get("name") == "my-skill"
    assert post.metadata.get("description") == "My description"
    assert "version" not in post.metadata, "version must not appear in new SKILL.md"
    assert "platforms" not in post.metadata, "platforms must not appear in new SKILL.md"
    assert "timeout" not in post.metadata, "timeout must not appear in new SKILL.md"
    assert "params" not in post.metadata, "params must not appear in new SKILL.md"
    assert "prerequisites" not in post.metadata, "prerequisites must not appear in new SKILL.md"


def test_dm002_skill_definition_has_no_old_fields(kb_root):
    """SkillDefinition from create_skill must not have version/platforms/timeout/params."""
    create_skill(kb_root, "plat-skill", "test")
    defn = parse_skill_md(kb_root / "skills" / "plat-skill" / "SKILL.md")

    assert isinstance(defn, SkillDefinition)
    assert not hasattr(defn, "version"), "SkillDefinition must not have version field"
    assert not hasattr(defn, "platforms"), "SkillDefinition must not have platforms field"
    assert not hasattr(defn, "timeout"), "SkillDefinition must not have timeout field"
    assert not hasattr(defn, "params"), "SkillDefinition must not have params field"
    assert not hasattr(defn, "prerequisites"), "SkillDefinition must not have prerequisites field"


def test_dm002_skill_definition_fields(kb_root):
    """SkillDefinition has exactly name, description, content."""
    create_skill(kb_root, "my-skill", "My description")
    defn = parse_skill_md(kb_root / "skills" / "my-skill" / "SKILL.md")
    assert defn.name == "my-skill"
    assert defn.description == "My description"
    assert isinstance(defn.content, str) and len(defn.content) > 0


# ---------------------------------------------------------------------------
# T-DM-003: parse_skill_md backward compatibility
# ---------------------------------------------------------------------------


def test_dm003_parse_old_format_ignores_extra_fields(tmp_path):
    """parse_skill_md on old-format SKILL.md (with version/platforms/params) returns
    SkillDefinition with only name/description/content — no errors."""
    skill_dir = tmp_path / "skills" / "check-redis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: check-redis
        description: 检查 Redis 连接数
        version: 1.0.0
        platforms: linux,macos
        timeout: 30
        params:
          - name: host
            description: Redis host
            required: false
            default: "127.0.0.1"
        prerequisites:
          - redis-cli
        ---
        body
    """), encoding="utf-8")

    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert defn.name == "check-redis"
    assert defn.description == "检查 Redis 连接数"
    assert isinstance(defn.content, str)
    # Must not have old fields
    assert not hasattr(defn, "version")
    assert not hasattr(defn, "platforms")
    assert not hasattr(defn, "params")
    assert not hasattr(defn, "prerequisites")


# ---------------------------------------------------------------------------
# T-DM-004: validate_skill_md
# ---------------------------------------------------------------------------


def test_dm004_valid_minimal_frontmatter(tmp_path):
    """validate_skill_md returns True for minimal valid SKILL.md."""
    skill_dir = tmp_path / "skills" / "check-redis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: check-redis
        description: Diagnose Redis connection pool exhaustion.
        ---

        # check-redis

        ## When to Use

        When Redis connections are exhausted.

        ## Resolution Steps

        1. Check maxclients.

        ## Key Points

        - Verify root cause first.
    """), encoding="utf-8")

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is True
    assert error == ""


def test_dm004_invalid_old_keys(tmp_path):
    """validate_skill_md returns False when old keys (version, timeout) are present."""
    skill_dir = tmp_path / "skills" / "old-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: old-skill
        description: test
        version: 1.0.0
        timeout: 30
        ---
        body
    """), encoding="utf-8")

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is False
    assert "version" in error or "timeout" in error
    assert "Unexpected key" in error


def test_dm004_missing_name(tmp_path):
    """validate_skill_md returns False when name is missing."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\ndescription: test\n---\nbody\n", encoding="utf-8")

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is False
    assert "name" in error


def test_dm004_missing_description(tmp_path):
    """validate_skill_md returns False when description is missing."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nbody\n", encoding="utf-8")

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is False
    assert "description" in error


def test_dm004_description_too_long(tmp_path):
    """validate_skill_md returns False when description exceeds 1024 chars."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: my-skill\ndescription: {'x' * 1025}\n---\nbody\n",
        encoding="utf-8",
    )

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is False
    assert "1024" in error


def test_dm004_description_with_angle_brackets(tmp_path):
    """validate_skill_md returns False when description contains angle brackets."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Use <this> when needed.\n---\nbody\n",
        encoding="utf-8",
    )

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is False
    assert "angle bracket" in error


def test_dm004_optional_allowed_keys(tmp_path):
    """validate_skill_md returns True when optional allowed keys are present."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: my-skill
        description: Valid description.
        license: MIT
        allowed-tools: Read, Write
        ---
        body
    """), encoding="utf-8")

    valid, error = validate_skill_md(skill_dir / "SKILL.md")
    assert valid is True, f"Expected valid but got error: {error}"


def test_dm004_create_skill_produces_valid_skillmd(kb_root):
    """create_skill output passes validate_skill_md."""
    create_skill(kb_root, "check-redis", "Diagnose Redis pool exhaustion.")
    skill_md = kb_root / "skills" / "check-redis" / "SKILL.md"
    valid, error = validate_skill_md(skill_md)
    assert valid is True, f"Expected valid but got: {error}"


# ---------------------------------------------------------------------------
# T-DM-005: skill_refs field schema validation
# ---------------------------------------------------------------------------


def _make_pitfall(extra: str = "") -> str:
    extra_block = ("\n" + extra) if extra else ""
    return (
        "---\n"
        "id: PT-DB-001\n"
        "type: pitfall\n"
        "title: Test\n"
        "maturity: draft\n"
        "category: database\n"
        "tags: []\n"
        'created_at: "2024-01-01T00:00:00+00:00"\n'
        'updated_at: "2024-01-01T00:00:00+00:00"'
        + extra_block + "\n"
        "---\n"
        "\n"
        "## Symptoms\n"
        "s\n"
        "## Root Cause\n"
        "r\n"
        "## Resolution\n"
        "r\n"
    )


def test_dm005_valid_skill_refs():
    result = validate_entry(_make_pitfall("skill_refs:\n  - check-redis\n  - reload-nginx"))
    assert result.valid is True


def test_dm005_skill_refs_not_a_list():
    result = validate_entry(_make_pitfall('skill_refs: "check-redis"'))
    assert result.valid is False
    assert any("list" in e.lower() for e in result.errors)


def test_dm005_skill_refs_invalid_chars():
    result = validate_entry(_make_pitfall("skill_refs:\n  - Check_Redis"))
    assert result.valid is False
    assert any("Invalid skill_refs" in e for e in result.errors)


def test_dm005_skill_refs_path_separator():
    result = validate_entry(_make_pitfall("skill_refs:\n  - skills/check-redis"))
    assert result.valid is False


def test_dm005_no_skill_refs_field():
    """Entries without skill_refs must still validate (backward compat)."""
    result = validate_entry(_make_pitfall())
    assert result.valid is True
    assert result.errors == []


# ---------------------------------------------------------------------------
# T-DM-006: validate_skill_name boundary values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "abc",          # minimum 3 chars
    "check-redis",  # standard kebab-case
    "my-tool-v2",   # contains digit
    "a" * 30 + "-" + "b" * 32,  # 64 chars exactly
])
def test_dm006_valid_names(name):
    validate_skill_name(name)  # must not raise


@pytest.mark.parametrize("name,keyword", [
    ("ab", "3-64"),            # too short
    ("a" * 65, "3-64"),        # too long
    ("Check", "[a-z0-9-]"),    # uppercase
    ("check_redis", "[a-z0-9-]"),  # underscore
    ("-check", "[a-z0-9-]"),   # leading hyphen
    ("check-", "[a-z0-9-]"),   # trailing hyphen
    ("check redis", "[a-z0-9-]"),  # space
    ("", "3-64"),              # empty
])
def test_dm006_invalid_names(name, keyword):
    with pytest.raises(ValueError, match=keyword):
        validate_skill_name(name)


# ---------------------------------------------------------------------------
# T-DM-008: skill_refs deduplication constraint
# ---------------------------------------------------------------------------


def test_dm008_link_skill_deduplication(kb_root):
    """link_skill called twice must not create duplicate entries in skill_refs."""
    make_entry(kb_root, "PT-DB-001")
    create_skill(kb_root, "check-redis", "test")

    link_skill(kb_root, "PT-DB-001", "check-redis")
    link_skill(kb_root, "PT-DB-001", "check-redis")  # idempotent

    entry_path = kb_root / "pitfall" / "database" / "PT-DB-001.md"
    post = frontmatter.load(str(entry_path))
    refs = list(post.metadata.get("skill_refs") or [])
    assert refs.count("check-redis") == 1, f"Expected 1, got {refs}"
