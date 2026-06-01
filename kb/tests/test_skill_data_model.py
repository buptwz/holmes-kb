"""T-DM-*: Data model validation tests for KB Skill Mounting."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.schema import validate_entry
from holmes.kb.skill.manager import (
    create_skill,
    get_skill_dir,
    link_skill,
    parse_skill_md,
    validate_skill_name,
)
from holmes.kb.skill.runner import run_skill
from tests.conftest import make_entry, make_skill_with_script


# ---------------------------------------------------------------------------
# T-DM-001: SkillDefinition directory structure
# ---------------------------------------------------------------------------


def test_dm001_create_skill_directory_structure(kb_root):
    """Verify create_skill produces exactly the required file-system layout."""
    skill_dir = create_skill(kb_root, "check-redis", "检查 Redis 连接数")

    assert skill_dir.is_dir(), "skill directory must exist"
    assert (skill_dir / "SKILL.md").is_file(), "SKILL.md must exist"
    assert (skill_dir / "scripts").is_dir(), "scripts/ directory must exist"
    assert (skill_dir / "scripts" / "run.sh").is_file(), "run.sh must exist"
    assert os.access(skill_dir / "scripts" / "run.sh", os.X_OK), "run.sh must be executable"


def test_dm001_dir_name_matches_skillmd_name(kb_root):
    """Directory name must equal the 'name' field in SKILL.md frontmatter."""
    create_skill(kb_root, "check-redis", "test")
    defn = parse_skill_md(kb_root / "skills" / "check-redis" / "SKILL.md")
    assert defn.name == "check-redis"


# ---------------------------------------------------------------------------
# T-DM-002: SKILL.md frontmatter field completeness
# ---------------------------------------------------------------------------


def test_dm002_frontmatter_all_required_fields(kb_root):
    """Generated SKILL.md must contain name/description/version/platforms."""
    create_skill(kb_root, "my-skill", "My description")
    defn = parse_skill_md(kb_root / "skills" / "my-skill" / "SKILL.md")

    assert defn.name == "my-skill"
    assert defn.description == "My description"
    assert defn.version, "version must be non-empty"
    assert defn.platforms, "platforms must be non-empty"


def test_dm002_version_semver_format(kb_root):
    """version field must be semantic versioning format x.y.z."""
    create_skill(kb_root, "semver-skill", "test")
    defn = parse_skill_md(kb_root / "skills" / "semver-skill" / "SKILL.md")
    parts = defn.version.split(".")
    assert len(parts) == 3, f"Expected x.y.z format, got {defn.version!r}"
    assert all(p.isdigit() for p in parts), f"Each part must be numeric, got {defn.version!r}"


def test_dm002_default_timeout(kb_root):
    """Default timeout must be 30 seconds."""
    create_skill(kb_root, "timeout-skill", "test")
    defn = parse_skill_md(kb_root / "skills" / "timeout-skill" / "SKILL.md")
    assert defn.timeout == 30


def test_dm002_default_platforms(kb_root):
    """Default platforms must include both linux and macos."""
    create_skill(kb_root, "plat-skill", "test")
    defn = parse_skill_md(kb_root / "skills" / "plat-skill" / "SKILL.md")
    assert "linux" in defn.platforms
    assert "macos" in defn.platforms


# ---------------------------------------------------------------------------
# T-DM-003: SkillParam structure parsing
# ---------------------------------------------------------------------------


def test_dm003_params_parsed_correctly(tmp_path):
    """parse_skill_md correctly parses a full SkillParam list."""
    skill_dir = tmp_path / "skills" / "check-redis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: check-redis
        description: 检查 Redis 连接数
        version: 1.0.0
        platforms: linux,macos
        params:
          - name: host
            description: Redis host
            required: false
            default: "127.0.0.1"
          - name: port
            description: Redis port
            required: true
        ---
        body
    """), encoding="utf-8")

    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert len(defn.params) == 2

    host = defn.params[0]
    assert host.name == "host"
    assert host.required is False
    assert host.default == "127.0.0.1"

    port = defn.params[1]
    assert port.name == "port"
    assert port.required is True
    assert port.default == ""  # not declared → empty string


# ---------------------------------------------------------------------------
# T-DM-004: prerequisites format variants
# ---------------------------------------------------------------------------


def test_dm004_prerequisites_string_list(tmp_path):
    """prerequisites as plain list of strings."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: s
        description: test
        version: 1.0.0
        platforms: linux,macos
        prerequisites:
          - redis-cli
          - netstat
        ---
        body
    """), encoding="utf-8")
    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert "redis-cli" in defn.prerequisites
    assert "netstat" in defn.prerequisites


def test_dm004_prerequisites_dict_commands(tmp_path):
    """prerequisites as dict with 'commands' key."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: s
        description: test
        version: 1.0.0
        platforms: linux,macos
        prerequisites:
          commands: [redis-cli]
        ---
        body
    """), encoding="utf-8")
    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert "redis-cli" in defn.prerequisites


def test_dm004_prerequisites_empty(tmp_path):
    """Missing prerequisites field parses as empty list, no error."""
    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: s\ndescription: t\nversion: 1.0.0\nplatforms: linux\n---\nbody\n",
        encoding="utf-8",
    )
    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert defn.prerequisites == []


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
# T-DM-007: SkillExecution data completeness
# ---------------------------------------------------------------------------


def test_dm007_skill_execution_all_fields(kb_root):
    """run_skill result must contain all SkillExecution fields with correct types."""
    make_skill_with_script(kb_root, "my-skill", "#!/usr/bin/env bash\necho hi\n")
    result = run_skill(kb_root, "my-skill", {"host": "127.0.0.1"})

    assert isinstance(result.skill, str) and result.skill == "my-skill"
    assert isinstance(result.exit_code, int)
    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)
    assert isinstance(result.duration_ms, int) and result.duration_ms > 0
    assert isinstance(result.truncated, bool)


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
