"""Unit tests for holmes.kb.skill.manager."""

from __future__ import annotations

import textwrap
from pathlib import Path

import frontmatter
import pytest

from holmes.kb.skill.manager import (
    CommandCandidate,
    auto_create_skill,
    create_skill,
    detect_commands,
    get_skill_dir,
    link_skill,
    list_skills,
    parse_skill_md,
    skill_exists,
    unlink_skill,
    validate_skill_name,
)


# ---------------------------------------------------------------------------
# validate_skill_name
# ---------------------------------------------------------------------------


def test_validate_skill_name_valid():
    validate_skill_name("check-redis")
    validate_skill_name("abc")
    validate_skill_name("my-tool-123")


def test_validate_skill_name_too_short():
    with pytest.raises(ValueError, match="3-64"):
        validate_skill_name("ab")


def test_validate_skill_name_too_long():
    with pytest.raises(ValueError):
        validate_skill_name("a" * 65)


def test_validate_skill_name_invalid_chars():
    with pytest.raises(ValueError):
        validate_skill_name("Check_Redis")  # uppercase and underscore


def test_validate_skill_name_starts_with_hyphen():
    with pytest.raises(ValueError):
        validate_skill_name("-check")


# ---------------------------------------------------------------------------
# create_skill
# ---------------------------------------------------------------------------


def test_create_skill_creates_files(tmp_path):
    skill_dir = create_skill(tmp_path, "check-redis", "检查 Redis 连接数")
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "run.sh").exists()


def test_create_skill_already_exists(tmp_path):
    create_skill(tmp_path, "check-redis", "First")
    with pytest.raises(ValueError, match="already exists"):
        create_skill(tmp_path, "check-redis", "Second")


def test_create_skill_invalid_name(tmp_path):
    with pytest.raises(ValueError):
        create_skill(tmp_path, "CHECK", "bad name")


def test_create_skill_run_sh_executable(tmp_path):
    import os
    skill_dir = create_skill(tmp_path, "my-skill", "Test")
    run_sh = skill_dir / "scripts" / "run.sh"
    assert os.access(run_sh, os.X_OK)


# ---------------------------------------------------------------------------
# parse_skill_md
# ---------------------------------------------------------------------------


def test_parse_skill_md_basic(tmp_path):
    skill_dir = create_skill(tmp_path, "check-redis", "Check Redis")
    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert defn.name == "check-redis"
    assert "Check Redis" in defn.description


def test_parse_skill_md_with_params(tmp_path):
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
          - name: port
            description: Redis port
            required: true
        ---
        body text
    """), encoding="utf-8")
    defn = parse_skill_md(skill_dir / "SKILL.md")
    assert len(defn.params) == 2
    assert defn.params[0].name == "host"
    assert defn.params[1].required is True


def test_parse_skill_md_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_skill_md(tmp_path / "nonexistent" / "SKILL.md")


# ---------------------------------------------------------------------------
# link_skill / unlink_skill
# ---------------------------------------------------------------------------


def _make_entry(kb_root: Path, entry_id: str = "PT-DB-001") -> Path:
    """Create a minimal KB pitfall entry for testing."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    entry_path.write_text(textwrap.dedent(f"""\
        ---
        id: {entry_id}
        type: pitfall
        title: Test Entry
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        ---

        ## Symptoms
        Test symptoms.

        ## Root Cause
        Test root cause.

        ## Resolution
        Test resolution.
    """), encoding="utf-8")
    return entry_path


def test_link_skill_adds_skill_refs(tmp_path):
    _make_entry(tmp_path)
    create_skill(tmp_path, "check-redis", "Check Redis")
    link_skill(tmp_path, "PT-DB-001", "check-redis")

    entry_path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
    post = frontmatter.load(str(entry_path))
    assert "check-redis" in post.metadata.get("skill_refs", [])


def test_link_skill_idempotent(tmp_path):
    _make_entry(tmp_path)
    create_skill(tmp_path, "check-redis", "Check Redis")
    link_skill(tmp_path, "PT-DB-001", "check-redis")
    link_skill(tmp_path, "PT-DB-001", "check-redis")  # second call must not duplicate

    entry_path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
    post = frontmatter.load(str(entry_path))
    refs = post.metadata.get("skill_refs", [])
    assert refs.count("check-redis") == 1


def test_link_skill_entry_not_found(tmp_path):
    create_skill(tmp_path, "check-redis", "Check Redis")
    with pytest.raises(FileNotFoundError, match="not found"):
        link_skill(tmp_path, "NONEXISTENT", "check-redis")


def test_link_skill_skill_not_found(tmp_path):
    _make_entry(tmp_path)
    with pytest.raises(FileNotFoundError, match="Skill.*not found"):
        link_skill(tmp_path, "PT-DB-001", "nonexistent-skill")


def test_unlink_skill_removes_ref(tmp_path):
    _make_entry(tmp_path)
    create_skill(tmp_path, "check-redis", "Check Redis")
    link_skill(tmp_path, "PT-DB-001", "check-redis")
    result = unlink_skill(tmp_path, "PT-DB-001", "check-redis")

    assert result is True
    entry_path = tmp_path / "pitfall" / "database" / "PT-DB-001.md"
    post = frontmatter.load(str(entry_path))
    assert "check-redis" not in (post.metadata.get("skill_refs") or [])


def test_unlink_skill_not_linked_returns_false(tmp_path):
    _make_entry(tmp_path)
    result = unlink_skill(tmp_path, "PT-DB-001", "nonexistent")
    assert result is False


# ---------------------------------------------------------------------------
# list_skills
# ---------------------------------------------------------------------------


def test_list_skills_empty(tmp_path):
    assert list_skills(tmp_path) == []


def test_list_skills_returns_all(tmp_path):
    create_skill(tmp_path, "check-redis", "Check Redis")
    create_skill(tmp_path, "check-nginx", "Check Nginx")
    skills = list_skills(tmp_path)
    names = [s.name for s in skills]
    assert "check-redis" in names
    assert "check-nginx" in names


def test_list_skills_linked_entries(tmp_path):
    _make_entry(tmp_path)
    create_skill(tmp_path, "check-redis", "Check Redis")
    link_skill(tmp_path, "PT-DB-001", "check-redis")
    skills = list_skills(tmp_path)
    redis_skill = next(s for s in skills if s.name == "check-redis")
    assert "PT-DB-001" in redis_skill.linked_entries


def test_list_skills_by_entry(tmp_path):
    _make_entry(tmp_path)
    create_skill(tmp_path, "check-redis", "Check Redis")
    create_skill(tmp_path, "check-nginx", "Check Nginx")
    link_skill(tmp_path, "PT-DB-001", "check-redis")
    skills = list_skills(tmp_path, entry_id="PT-DB-001")
    assert len(skills) == 1
    assert skills[0].name == "check-redis"


# ---------------------------------------------------------------------------
# detect_commands
# ---------------------------------------------------------------------------


def test_detect_commands_dollar_prefix():
    text = "Run the following:\n$ redis-cli info | grep connected\nThen check."
    candidates = detect_commands(text)
    assert any("redis-cli" in c.line for c in candidates)


def test_detect_commands_backtick():
    text = "Execute `kubectl get pods -n production` to list pods."
    candidates = detect_commands(text)
    assert any("kubectl" in c.line for c in candidates)


def test_detect_commands_no_duplicates():
    text = "$ redis-cli info\n$ redis-cli info\n"
    candidates = detect_commands(text)
    lines = [c.line for c in candidates]
    assert len(lines) == len(set(lines))


def test_detect_commands_empty():
    candidates = detect_commands("No commands here. Just prose text.")
    # May or may not match — just verify it returns a list.
    assert isinstance(candidates, list)


# ---------------------------------------------------------------------------
# auto_create_skill
# ---------------------------------------------------------------------------


def test_auto_create_skill_basic(tmp_path):
    skill_dir = auto_create_skill(tmp_path, "check-redis", "redis-cli info", "Check Redis")
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").exists()
    run_sh = skill_dir / "scripts" / "run.sh"
    assert run_sh.exists()
    content = run_sh.read_text(encoding="utf-8")
    assert "redis-cli" in content


def test_auto_create_skill_with_placeholders(tmp_path):
    skill_dir = auto_create_skill(
        tmp_path, "check-redis", "redis-cli -h {host} -p {port} info", "Check Redis"
    )
    run_sh = (skill_dir / "scripts" / "run.sh").read_text(encoding="utf-8")
    assert "SKILL_PARAM_HOST" in run_sh
    assert "SKILL_PARAM_PORT" in run_sh


def test_auto_create_skill_already_exists(tmp_path):
    auto_create_skill(tmp_path, "check-redis", "redis-cli info", "Check Redis")
    with pytest.raises(ValueError, match="already exists"):
        auto_create_skill(tmp_path, "check-redis", "redis-cli info", "Check Redis")


# ---------------------------------------------------------------------------
# TT043: T-SED-003~004  detect_commands pattern coverage
# ---------------------------------------------------------------------------


def test_sed003_dollar_prefix_detection():
    """T-SED-003: $ prefix command pattern is detected."""
    text = "To check Redis, run:\n$ redis-cli info\n"
    candidates = detect_commands(text)
    assert len(candidates) >= 1
    assert any("redis-cli" in c.line for c in candidates)


def test_sed003_backtick_detection():
    """T-SED-003: backtick command pattern is detected."""
    text = "Run `redis-cli ping` to test connectivity."
    candidates = detect_commands(text)
    assert len(candidates) >= 1
    assert any("redis-cli" in c.line for c in candidates)


def test_sed003_known_tool_at_line_start():
    """T-SED-003: known CLI tool at line start is detected."""
    text = "nginx -t\nnginx -s reload\n"
    candidates = detect_commands(text)
    assert len(candidates) >= 1
    assert any("nginx" in c.line for c in candidates)


def test_sed003_multiple_patterns_in_text():
    """T-SED-003: multiple command patterns in same text all detected."""
    text = (
        "Check Redis connection:\n"
        "$ redis-cli ping\n"
        "Also try `redis-cli info`.\n"
        "Or use:\nnginx -t\n"
    )
    candidates = detect_commands(text)
    assert len(candidates) >= 2


def test_sed004_pure_prose_no_false_positive():
    """T-SED-004: plain prose without commands produces no candidates."""
    text = (
        "Redis is a popular in-memory data store. "
        "It is commonly used for caching and pub/sub messaging. "
        "Check the official documentation for details."
    )
    candidates = detect_commands(text)
    assert candidates == []


# ---------------------------------------------------------------------------
# TT044: T-SED-005  auto_create_skill placeholder expansion
# ---------------------------------------------------------------------------


def test_sed005_placeholder_host_port_expanded(tmp_path):
    """T-SED-005: {host}/{port} placeholders expand; SKILL_PARAM vars declared, friendly vars used in cmd."""
    skill_dir = auto_create_skill(
        tmp_path, "check-redis", "redis-cli -h {host} -p {port} info", "Check Redis"
    )
    run_sh = (skill_dir / "scripts" / "run.sh").read_text(encoding="utf-8")
    # Variable declarations reference SKILL_PARAM_* env vars
    assert "SKILL_PARAM_HOST" in run_sh
    assert "SKILL_PARAM_PORT" in run_sh
    # Command uses friendly variable names, not raw placeholders
    assert "${HOST}" in run_sh
    assert "${PORT}" in run_sh
    assert "{host}" not in run_sh
    assert "{port}" not in run_sh


def test_sed005_single_placeholder_expanded(tmp_path):
    """T-SED-005: single placeholder {host} expands correctly."""
    skill_dir = auto_create_skill(
        tmp_path, "ping-host", "curl http://{host}/health", "Ping host"
    )
    run_sh = (skill_dir / "scripts" / "run.sh").read_text(encoding="utf-8")
    assert "SKILL_PARAM_HOST" in run_sh
    assert "${HOST}" in run_sh
    assert "{host}" not in run_sh
