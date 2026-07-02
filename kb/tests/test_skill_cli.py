"""T-CLI-*: CLI command tests for holmes skill subcommands (new concept)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from holmes.kb.skill.manager import create_skill, link_skill
from tests.conftest import make_entry


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner, kb_root, *args):
    """Invoke `holmes --kb-path <kb_root> <args...>` via CliRunner."""
    return runner.invoke(cli, ["--kb-path", str(kb_root)] + list(args))


# ---------------------------------------------------------------------------
# Deleted commands — must return "No such command"
# ---------------------------------------------------------------------------


def test_deleted_skill_create_no_such_command(runner, kb_root):
    """skill create has been removed — CLI must report 'No such command'."""
    result = invoke(runner, kb_root, "kb", "skill", "create", "check-redis",
                    "--desc", "test")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_deleted_skill_link_no_such_command(runner, kb_root):
    """skill link has been removed."""
    result = invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_deleted_skill_unlink_no_such_command(runner, kb_root):
    """skill unlink has been removed."""
    result = invoke(runner, kb_root, "kb", "skill", "unlink", "PT-DB-001", "check-redis")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_deleted_skill_run_no_such_command(runner, kb_root):
    """skill run has been removed."""
    result = invoke(runner, kb_root, "kb", "skill", "run", "check-redis")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_deleted_skill_detect_commands_no_such_command(runner, kb_root):
    """skill detect-commands has been removed."""
    result = invoke(runner, kb_root, "kb", "skill", "detect-commands",
                    "--content", "Run $ redis-cli info")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


def test_deleted_skill_auto_create_no_such_command(runner, kb_root):
    """skill auto-create has been removed."""
    result = invoke(runner, kb_root, "kb", "skill", "auto-create",
                    "--name", "check-redis", "--cmd", "redis-cli info", "--desc", "test")
    assert result.exit_code != 0
    assert "no such command" in result.output.lower()


# ---------------------------------------------------------------------------
# skill --help shows only list and read
# ---------------------------------------------------------------------------


def test_skill_help_shows_only_list_and_read(runner, kb_root):
    """holmes skill --help must list only 'list' and 'read' subcommands."""
    result = invoke(runner, kb_root, "kb", "skill", "--help")
    assert result.exit_code == 0
    # Click lists commands as "  <name>  <description>"; check for command-name tokens
    lines = result.output.splitlines()
    # Extract command names from help output lines (lines starting with spaces then a word)
    import re
    cmd_lines = [re.match(r"^\s{2}(\S+)", l) for l in lines]
    commands = {m.group(1) for m in cmd_lines if m}
    assert "list" in commands
    assert "read" in commands
    # Removed commands must not appear as top-level commands
    assert "create" not in commands
    assert "link" not in commands
    assert "unlink" not in commands
    assert "run" not in commands
    assert "auto-create" not in commands
    assert "detect-commands" not in commands


# ---------------------------------------------------------------------------
# T-CLI-012~013: kb show with skill info
# ---------------------------------------------------------------------------


def test_cli012_kb_show_displays_skill_tag(runner, kb_root):
    """T-CLI-012: kb show prints skill section with [skill] tag."""
    make_entry(kb_root, "PT-DB-001")
    create_skill(kb_root, "check-redis", "Diagnose Redis pool exhaustion.")
    link_skill(kb_root, "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "show", "PT-DB-001")
    assert result.exit_code == 0
    assert "── Skills ──" in result.output
    assert "[skill]" in result.output
    assert "check-redis" in result.output
    # Old [可执行] label must not appear
    assert "[可执行]" not in result.output


def test_cli013_kb_show_dangling_ref_warning(runner, kb_root):
    """T-CLI-013: dangling skill_ref prints Warning, exit 0."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / "PT-DB-001.md").write_text(textwrap.dedent("""\
        ---
        id: PT-DB-001
        type: pitfall
        title: Test Entry
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        skill_refs:
          - deleted-skill
        ---

        ## Symptoms
        Test symptoms.

        ## Root Cause
        Test root cause.

        ## Resolution
        Test resolution.
    """), encoding="utf-8")

    result = invoke(runner, kb_root, "kb", "show", "PT-DB-001")
    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "deleted-skill" in result.output


# ---------------------------------------------------------------------------
# T-CLI-014~016: skill list
# ---------------------------------------------------------------------------


def test_cli014_skill_list_table_output(runner, kb_root):
    """T-CLI-014: skill list shows table with NAME/DESCRIPTION/REFS columns."""
    make_entry(kb_root, "PT-DB-001")
    create_skill(kb_root, "check-redis", "检查 Redis")
    link_skill(kb_root, "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "list")
    assert result.exit_code == 0
    assert "check-redis" in result.output
    assert "PT-DB-001" in result.output


def test_cli014_skill_list_empty(runner, kb_root):
    """T-CLI-014: skill list on fresh KB returns 'No skills found.' exit 0."""
    result = invoke(runner, kb_root, "kb", "skill", "list")
    assert result.exit_code == 0
    assert "No skills found." in result.output


def test_cli015_skill_list_json_fields(runner, kb_root):
    """T-CLI-015: skill list --json returns name/description/linked_entries only."""
    make_entry(kb_root, "PT-DB-001")
    create_skill(kb_root, "check-redis", "test")
    link_skill(kb_root, "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "list", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    item = next(x for x in data if x["name"] == "check-redis")
    # Required fields
    for field in ("name", "description", "linked_entries"):
        assert field in item, f"missing field: {field}"
    # Removed fields must not appear
    assert "version" not in item, "version must not appear in new skill list JSON"
    assert "platforms" not in item, "platforms must not appear in new skill list JSON"
    assert isinstance(item["linked_entries"], list)
    assert "PT-DB-001" in item["linked_entries"]


def test_cli016_skill_list_filter_by_entry(runner, kb_root):
    """T-CLI-016: skill list <entry-id> returns only linked skills."""
    make_entry(kb_root, "PT-DB-001")
    create_skill(kb_root, "check-redis", "a")
    create_skill(kb_root, "check-nginx", "b")
    link_skill(kb_root, "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "list", "PT-DB-001")
    assert result.exit_code == 0
    assert "check-redis" in result.output
    assert "check-nginx" not in result.output


# ---------------------------------------------------------------------------
# T-CLI-017~019: skill read
# ---------------------------------------------------------------------------


def test_cli017_skill_read_default_output(runner, kb_root):
    """T-CLI-017: skill read prints raw SKILL.md content."""
    create_skill(kb_root, "check-redis", "test")
    result = invoke(runner, kb_root, "kb", "skill", "read", "check-redis")
    assert result.exit_code == 0
    assert "---" in result.output  # YAML frontmatter delimiters
    assert "check-redis" in result.output


def test_cli018_skill_read_json_fields(runner, kb_root):
    """T-CLI-018: skill read --json returns name and content only."""
    create_skill(kb_root, "check-redis", "test")
    result = invoke(runner, kb_root, "kb", "skill", "read", "check-redis", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "check-redis"
    assert data["content"]  # non-empty
    # Removed fields must not appear
    assert "scripts_path" not in data, "scripts_path must not appear in new skill read JSON"
    assert "has_run_script" not in data, "has_run_script must not appear in new skill read JSON"


def test_cli019_skill_read_not_found_json(runner, kb_root):
    """T-CLI-019: skill read on nonexistent skill returns JSON error, exit 1."""
    result = invoke(runner, kb_root, "kb", "skill", "read", "nonexistent", "--json")
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data
    assert "nonexistent" in data["error"]


# ---------------------------------------------------------------------------
# T-COMPAT-002: kb show on old entry (no skill_refs) has no skills section
# ---------------------------------------------------------------------------


def test_compat002_kb_show_old_entry_no_skills_section(runner, kb_root):
    """T-COMPAT-002: kb show on entry without skill_refs has no Skills section."""
    make_entry(kb_root, "PT-DB-001")
    result = invoke(runner, kb_root, "kb", "show", "PT-DB-001")
    assert result.exit_code == 0
    assert "── Skills ──" not in result.output
    assert "Warning:" not in result.output


# ---------------------------------------------------------------------------
# T-COMPAT-003: kb list mixed old/new entries all shown
# ---------------------------------------------------------------------------


def test_compat003_kb_list_mixed_entries(runner, kb_root):
    """T-COMPAT-003: kb list with mix of old (no skill_refs) and new entries shows both."""
    make_entry(kb_root, "PT-DB-001")
    make_entry(kb_root, "PT-DB-002")
    create_skill(kb_root, "check-redis", "test")
    link_skill(kb_root, "PT-DB-002", "check-redis")

    result = invoke(runner, kb_root, "kb", "list")
    assert result.exit_code == 0
    assert "PT-DB-001" in result.output
    assert "PT-DB-002" in result.output


# ---------------------------------------------------------------------------
# T-SETUP-001: setup command writes tool permissions (KbRunSkill removed)
# ---------------------------------------------------------------------------


def test_setup001_setup_adds_skill_read_permission(runner, tmp_path):
    """T-SETUP-001: holmes setup writes KbReadSkill permission (KbRunSkill no longer needed)."""
    import os
    from unittest.mock import patch

    holmes_home = tmp_path / ".holmes"
    holmes_home.mkdir()

    with patch("holmes.config._holmes_home", return_value=holmes_home):
        result = runner.invoke(cli, [
            "--kb-path", str(tmp_path / "kb"),
            "setup",
            "--kb-path", str(tmp_path / "kb"),
            "--model", "gpt-4o",
        ])

    settings_path = holmes_home / "settings.json"
    assert settings_path.exists(), f"settings.json not found; output: {result.output}"
    settings = json.loads(settings_path.read_text())
    allow = settings.get("permissions", {}).get("allow", [])
    assert "KbReadSkill" in allow, f"KbReadSkill missing from allow list: {allow}"
    # KbRunSkill should no longer be required
    assert "KbRunSkill" not in allow, f"KbRunSkill should be removed from allow list"
