"""T-CLI-* / T-SETUP-*: CLI command tests for holmes kb skill subcommands."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import frontmatter
import pytest
from click.testing import CliRunner

from holmes.cli import cli
from tests.conftest import make_entry, make_skill_with_script


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner, kb_root, *args):
    """Invoke `holmes --kb-path <kb_root> <args...>` via CliRunner."""
    return runner.invoke(cli, ["--kb-path", str(kb_root)] + list(args))


# ---------------------------------------------------------------------------
# T-CLI-001~004: skill create
# ---------------------------------------------------------------------------


def test_cli001_skill_create_normal(runner, kb_root):
    """T-CLI-001: skill create produces correct output and files."""
    result = invoke(runner, kb_root, "kb", "skill", "create", "check-redis",
                    "--desc", "检查 Redis 连接数")
    assert result.exit_code == 0, result.output
    assert "✓ Skill created: skills/check-redis/" in result.output
    assert "Edit SKILL.md" in result.output
    assert "Write your diagnostics" in result.output
    assert "Link to an entry" in result.output
    assert (kb_root / "skills" / "check-redis" / "SKILL.md").exists()
    assert (kb_root / "skills" / "check-redis" / "scripts" / "run.sh").exists()


def test_cli002_skill_create_custom_platform(runner, kb_root):
    """T-CLI-002: --platform is written to SKILL.md frontmatter."""
    invoke(runner, kb_root, "kb", "skill", "create", "linux-only",
           "--desc", "test", "--platform", "linux")
    import frontmatter as fm
    post = fm.load(str(kb_root / "skills" / "linux-only" / "SKILL.md"))
    assert "macos" not in str(post.metadata.get("platforms", ""))


def test_cli003_skill_create_duplicate_error(runner, kb_root):
    """T-CLI-003: creating existing skill returns exit 1 and original is unchanged."""
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "first")
    result = invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "second")
    assert result.exit_code == 1
    assert "already exists" in result.output
    import frontmatter as fm
    post = fm.load(str(kb_root / "skills" / "check-redis" / "SKILL.md"))
    assert post.metadata["description"] == "first"


def test_cli004_skill_create_invalid_name(runner, kb_root):
    """T-CLI-004: invalid skill name returns exit 1, no directory created."""
    result = invoke(runner, kb_root, "kb", "skill", "create", "Check_Redis", "--desc", "bad")
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert not (kb_root / "skills" / "Check_Redis").exists()


# ---------------------------------------------------------------------------
# T-CLI-005~008: skill link
# ---------------------------------------------------------------------------


def test_cli005_skill_link_normal(runner, kb_root):
    """T-CLI-005: link adds skill_refs, preserves other fields, updates updated_at."""
    entry_path = make_entry(kb_root, "PT-DB-001")
    original = frontmatter.load(str(entry_path))
    original_title = original.metadata["title"]

    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    result = invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    assert result.exit_code == 0
    assert "✓ Linked skill 'check-redis' to PT-DB-001." in result.output

    post = frontmatter.load(str(entry_path))
    assert "check-redis" in (post.metadata.get("skill_refs") or [])
    assert post.metadata["title"] == original_title  # unchanged
    assert post.metadata["updated_at"] != original.metadata["updated_at"]


def test_cli006_skill_link_idempotent(runner, kb_root):
    """T-CLI-006: linking twice results in skill_refs with no duplicates."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    post = frontmatter.load(str(kb_root / "pitfall" / "database" / "PT-DB-001.md"))
    refs = list(post.metadata.get("skill_refs") or [])
    assert refs.count("check-redis") == 1


def test_cli007_skill_link_entry_not_found(runner, kb_root):
    """T-CLI-007: linking to nonexistent entry returns exit 1."""
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    result = invoke(runner, kb_root, "kb", "skill", "link", "NONEXISTENT", "check-redis")
    assert result.exit_code == 1
    assert "NONEXISTENT" in result.output


def test_cli008_skill_link_skill_not_found(runner, kb_root):
    """T-CLI-008: linking nonexistent skill returns exit 1 with create suggestion."""
    make_entry(kb_root, "PT-DB-001")
    result = invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "ghost-skill")
    assert result.exit_code == 1
    assert "ghost-skill" in result.output
    assert "create" in result.output.lower()


# ---------------------------------------------------------------------------
# T-CLI-009~011: skill unlink
# ---------------------------------------------------------------------------


def test_cli009_skill_unlink_normal(runner, kb_root):
    """T-CLI-009: unlink removes skill_refs entry, skill folder stays."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "unlink", "PT-DB-001", "check-redis")
    assert result.exit_code == 0
    assert "✓ Unlinked" in result.output

    post = frontmatter.load(str(kb_root / "pitfall" / "database" / "PT-DB-001.md"))
    assert "check-redis" not in (post.metadata.get("skill_refs") or [])
    assert (kb_root / "skills" / "check-redis").is_dir()  # folder stays


def test_cli010_skill_unlink_idempotent(runner, kb_root):
    """T-CLI-010: unlinking a skill not linked returns exit 0 with info message."""
    make_entry(kb_root, "PT-DB-001")
    result = invoke(runner, kb_root, "kb", "skill", "unlink", "PT-DB-001", "never-linked")
    assert result.exit_code == 0
    assert "was not linked" in result.output


def test_cli011_skill_unlink_keeps_other_skills(runner, kb_root):
    """T-CLI-011: unlinking one skill leaves other skill_refs intact."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "a")
    invoke(runner, kb_root, "kb", "skill", "create", "reload-nginx", "--desc", "b")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "reload-nginx")

    invoke(runner, kb_root, "kb", "skill", "unlink", "PT-DB-001", "check-redis")

    post = frontmatter.load(str(kb_root / "pitfall" / "database" / "PT-DB-001.md"))
    refs = list(post.metadata.get("skill_refs") or [])
    assert "reload-nginx" in refs
    assert "check-redis" not in refs


# ---------------------------------------------------------------------------
# T-CLI-012~013: kb show with skill info
# ---------------------------------------------------------------------------


def test_cli012_kb_show_displays_skill_section(runner, kb_root):
    """T-CLI-012: kb show prints skill section with [可执行] tag."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "show", "PT-DB-001")
    assert result.exit_code == 0
    assert "── Skills ──" in result.output
    assert "check-redis [可执行]" in result.output
    assert "skills/check-redis/" in result.output


def test_cli013_kb_show_dangling_ref_warning(runner, kb_root):
    """T-CLI-013: dangling skill_ref prints Warning, exit 0."""
    import textwrap
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
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "检查 Redis")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

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
    """T-CLI-015: skill list --json returns array with all required fields."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "list", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    item = next(x for x in data if x["name"] == "check-redis")
    for field in ("name", "description", "version", "platforms", "linked_entries"):
        assert field in item, f"missing field: {field}"
    assert isinstance(item["linked_entries"], list)
    assert "PT-DB-001" in item["linked_entries"]


def test_cli016_skill_list_filter_by_entry(runner, kb_root):
    """T-CLI-016: skill list <entry-id> returns only linked skills."""
    make_entry(kb_root, "PT-DB-001")
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "a")
    invoke(runner, kb_root, "kb", "skill", "create", "check-nginx", "--desc", "b")
    invoke(runner, kb_root, "kb", "skill", "link", "PT-DB-001", "check-redis")

    result = invoke(runner, kb_root, "kb", "skill", "list", "PT-DB-001")
    assert result.exit_code == 0
    assert "check-redis" in result.output
    assert "check-nginx" not in result.output


# ---------------------------------------------------------------------------
# T-CLI-017~019: skill read
# ---------------------------------------------------------------------------


def test_cli017_skill_read_default_output(runner, kb_root):
    """T-CLI-017: skill read prints raw SKILL.md content."""
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    result = invoke(runner, kb_root, "kb", "skill", "read", "check-redis")
    assert result.exit_code == 0
    assert "---" in result.output  # YAML frontmatter delimiters
    assert "check-redis" in result.output


def test_cli018_skill_read_json_fields(runner, kb_root):
    """T-CLI-018: skill read --json returns all contract fields."""
    invoke(runner, kb_root, "kb", "skill", "create", "check-redis", "--desc", "test")
    result = invoke(runner, kb_root, "kb", "skill", "read", "check-redis", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "check-redis"
    assert data["content"]  # non-empty
    assert data["scripts_path"] == "skills/check-redis/scripts/run.sh"
    assert data["has_run_script"] is True


def test_cli019_skill_read_not_found_json(runner, kb_root):
    """T-CLI-019: skill read on nonexistent skill returns JSON error, exit 1."""
    result = invoke(runner, kb_root, "kb", "skill", "read", "nonexistent", "--json")
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data
    assert "nonexistent" in data["error"]


# ---------------------------------------------------------------------------
# T-CLI-020~025: skill run
# ---------------------------------------------------------------------------


def test_cli020_skill_run_normal(runner, kb_root):
    """T-CLI-020: skill run executes script and prints stdout."""
    make_skill_with_script(
        kb_root, "my-skill", '#!/usr/bin/env bash\necho "hello $SKILL_PARAM_NAME"\n'
    )
    result = invoke(runner, kb_root, "kb", "skill", "run", "my-skill", "--param", "name=world")
    assert result.exit_code == 0
    assert "hello world" in result.output


def test_cli021_skill_run_json_fields(runner, kb_root):
    """T-CLI-021: skill run --json returns all SkillExecution fields."""
    make_skill_with_script(kb_root, "check-redis", "#!/usr/bin/env bash\necho ok\n")
    result = invoke(runner, kb_root, "kb", "skill", "run", "check-redis", "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["skill"] == "check-redis"
    assert data["exit_code"] == 0
    assert isinstance(data["stdout"], str)
    assert isinstance(data["stderr"], str)
    assert data["duration_ms"] > 0
    assert data["truncated"] is False


def test_cli022_skill_run_multiple_params(runner, kb_root):
    """T-CLI-022: multiple --param flags are all injected correctly."""
    make_skill_with_script(
        kb_root, "check-redis",
        "#!/usr/bin/env bash\necho \"h=$SKILL_PARAM_HOST p=$SKILL_PARAM_PORT\"\n"
    )
    result = invoke(runner, kb_root, "kb", "skill", "run", "check-redis",
                    "--param", "host=192.168.1.100", "--param", "port=6380")
    assert result.exit_code == 0
    assert "h=192.168.1.100" in result.output
    assert "p=6380" in result.output


def test_cli023_skill_run_nonzero_exit_code(runner, kb_root):
    """T-CLI-023: skill run exit code is propagated; JSON mode still shows data."""
    make_skill_with_script(kb_root, "fail-skill", "#!/usr/bin/env bash\nexit 2\n")

    # Non-JSON mode: CLI exit code matches script
    result = invoke(runner, kb_root, "kb", "skill", "run", "fail-skill")
    assert result.exit_code == 2

    # JSON mode: exit_code in JSON, CLI itself exits with the script's code
    result = invoke(runner, kb_root, "kb", "skill", "run", "fail-skill", "--json")
    data = json.loads(result.output)
    assert data["exit_code"] == 2


def test_cli024_skill_run_not_found_json(runner, kb_root):
    """T-CLI-024: skill run on nonexistent skill returns JSON error, exit 1."""
    result = invoke(runner, kb_root, "kb", "skill", "run", "nonexistent", "--json")
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data
    assert "nonexistent" in data["error"]


def test_cli025_skill_run_no_run_sh(runner, kb_root):
    """T-CLI-025: skill run when run.sh absent returns JSON error, exit 1."""
    skill_dir = kb_root / "skills" / "no-script"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: no-script\ndescription: test\nversion: 1.0.0\nplatforms: linux\n---\nbody\n"
    )
    (skill_dir / "scripts").mkdir()
    # intentionally no run.sh

    result = invoke(runner, kb_root, "kb", "skill", "run", "no-script", "--json")
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data
    assert "run.sh" in data["error"]


# ---------------------------------------------------------------------------
# T-CLI-026~027: detect-commands + auto-create
# ---------------------------------------------------------------------------


def test_cli026_detect_commands_json(runner, kb_root):
    """T-CLI-026: detect-commands returns JSON array with line/suggested_name."""
    result = invoke(runner, kb_root, "kb", "skill", "detect-commands",
                    "--content", "Run $ redis-cli info | grep connected",
                    "--json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) > 0
    item = data[0]
    assert "line" in item
    assert "suggested_name" in item
    import re
    assert re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$", item["suggested_name"])


def test_cli027_auto_create_with_placeholder(runner, kb_root):
    """T-CLI-027: auto-create expands {placeholder} to SKILL_PARAM_* in run.sh."""
    result = invoke(runner, kb_root, "kb", "skill", "auto-create",
                    "--name", "check-host",
                    "--cmd", "curl -I {host}:{port}",
                    "--desc", "检查主机")
    assert result.exit_code == 0
    run_sh = (kb_root / "skills" / "check-host" / "scripts" / "run.sh").read_text()
    assert "SKILL_PARAM_HOST" in run_sh
    assert "SKILL_PARAM_PORT" in run_sh


# ---------------------------------------------------------------------------
# T-COMPAT-002: kb show on old entry (no skill_refs) has no skills section (TT032)
# ---------------------------------------------------------------------------


def test_compat002_kb_show_old_entry_no_skills_section(runner, kb_root):
    """T-COMPAT-002: kb show on entry without skill_refs has no Skills section."""
    make_entry(kb_root, "PT-DB-001")
    result = invoke(runner, kb_root, "kb", "show", "PT-DB-001")
    assert result.exit_code == 0
    assert "── Skills ──" not in result.output
    assert "Warning:" not in result.output


# ---------------------------------------------------------------------------
# T-COMPAT-003: kb list mixed old/new entries all shown (TT033)
# ---------------------------------------------------------------------------


def test_compat003_kb_list_mixed_entries(runner, kb_root):
    """T-COMPAT-003: kb list with mix of old (no skill_refs) and new entries shows both."""
    from holmes.kb.skill.manager import create_skill, link_skill
    make_entry(kb_root, "PT-DB-001")
    make_entry(kb_root, "PT-DB-002")
    create_skill(kb_root, "check-redis", "test")
    link_skill(kb_root, "PT-DB-002", "check-redis")

    result = invoke(runner, kb_root, "kb", "list")
    assert result.exit_code == 0
    assert "PT-DB-001" in result.output
    assert "PT-DB-002" in result.output


# ---------------------------------------------------------------------------
# T-SETUP-001: setup command writes new tool permissions
# ---------------------------------------------------------------------------


def test_setup001_setup_adds_skill_permissions(runner, tmp_path):
    """T-SETUP-001: holmes setup writes KbReadSkill and KbRunSkill to permissions."""
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
    assert "KbRunSkill" in allow, f"KbRunSkill missing from allow list: {allow}"


# ---------------------------------------------------------------------------
# T020 (021): --dir nonexistent directory returns exit 1
# ---------------------------------------------------------------------------


def test_import_dir_nonexistent_exits_1(tmp_path):
    """021 T020: holmes import --dir /nonexistent → exit 1, stderr contains error message."""
    from click.testing import CliRunner

    from holmes.cli import cli

    runner = CliRunner()
    kb_root = tmp_path / "kb"
    for d in ("pitfall", "contributions/pending"):
        (kb_root / d).mkdir(parents=True, exist_ok=True)

    nonexistent = tmp_path / "does-not-exist"

    result = runner.invoke(cli, [
        "--kb-path", str(kb_root),
        "import",
        "--dir", str(nonexistent),
    ])

    assert result.exit_code == 1
    # Error message must mention the missing directory
    output = (result.output or "") + (result.stderr if hasattr(result, "stderr") and result.stderr else "")
    assert "does not exist" in output.lower() or "Directory does not exist" in output
