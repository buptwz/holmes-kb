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


def test_sed003_multiple_dollar_commands():
    """T-SED-003: multiple $ prefix commands in same text are all detected."""
    text = (
        "Check Redis connection:\n"
        "$ redis-cli ping\n"
        "Then inspect replication:\n"
        "$ redis-cli info replication\n"
    )
    candidates = detect_commands(text)
    assert len(candidates) >= 2


def test_inline_tool_without_dollar_not_detected():
    """Known tool names in prose without $ prefix are NOT detected (no CMD_PREFIXES whitelist)."""
    text = "nginx -t\nnginx -s reload\nkubectl get pods"
    candidates = detect_commands(text)
    assert candidates == [], f"Expected empty for bare inline tools, got {[c.line for c in candidates]}"


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


# ---------------------------------------------------------------------------
# T009-T011: detect_commands — triple-backtick code block extraction
# ---------------------------------------------------------------------------


def test_detect_commands_code_block_commands_extracted():
    """T009: detect_commands() returns commands from triple-backtick bash blocks."""
    text = textwrap.dedent("""\
        ## Resolution

        Run the following commands:

        ```bash
        redis-cli info replication
        kubectl get pods -n production
        ```
    """)
    candidates = detect_commands(text)
    lines = [c.line for c in candidates]
    assert any("redis-cli" in l for l in lines)
    assert any("kubectl" in l for l in lines)


def test_detect_commands_code_block_comments_excluded():
    """T010: comment lines (# ...) inside code blocks are not detected as commands."""
    text = textwrap.dedent("""\
        ## Resolution

        ```bash
        # This is a comment
        redis-cli ping
        ```
    """)
    candidates = detect_commands(text)
    lines = [c.line for c in candidates]
    assert not any(l.startswith("#") for l in lines)
    assert any("redis-cli" in l for l in lines)


def test_detect_commands_empty_and_chinese_returns_empty():
    """T011: empty string and pure Chinese prose return no candidates."""
    assert detect_commands("") == []
    assert detect_commands("这是一段中文描述，没有任何命令行指令。请参考官方文档。") == []



# ---------------------------------------------------------------------------
# TestDetectCommandsFalsePositives — T013 (US4)
# ---------------------------------------------------------------------------


class TestDetectCommandsFalsePositives:
    """US4: detect_commands() must not return YAML frontmatter or SQL as commands."""

    def test_yaml_frontmatter_not_detected_as_commands(self):
        """T013a: YAML frontmatter fields like 'category: database' are not returned."""
        text = textwrap.dedent("""\
            ---
            id: PT-DB-001
            type: pitfall
            title: Connection pool exhausted
            category: database
            tags: [postgres]
            maturity: draft
            ---

            ## Resolution
            Restart the service.
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        assert not any("category" in l or "type:" in l or "tags" in l for l in lines), \
            f"YAML frontmatter leaked into commands: {lines}"

    def test_sql_not_detected_via_cmd_pattern(self):
        """T013b: SQL fragments like 'WHERE state = idle' are not returned by CMD_PATTERN path."""
        text = textwrap.dedent("""\
            Check active connections:

            $ psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'idle'"

            Also run: WHERE state = 'active' LIMIT 10

            FATAL: remaining connection slots are reserved for non-replication superuser connections
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        # The direct psql invocation in a code fence should be OK,
        # but bare SQL/FATAL lines must NOT appear.
        assert not any(l.strip().startswith("WHERE") for l in lines), \
            f"SQL WHERE clause leaked: {lines}"
        assert not any(l.strip().startswith("FATAL") for l in lines), \
            f"FATAL error message leaked: {lines}"

    def test_real_shell_commands_still_detected(self):
        """T013c: real shell commands are still detected after YAML strip + SQL filter."""
        text = textwrap.dedent("""\
            ---
            type: pitfall
            category: database
            ---

            ## Resolution

            Run the following:

            ```bash
            $ redis-cli info
            pg_dump -Fc mydb > mydb.dump
            ```
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        assert any("redis-cli" in l or "pg_dump" in l for l in lines), \
            f"Real shell commands not detected: {lines}"


# ---------------------------------------------------------------------------
# TestSQLClauseFilter — T006 (US1)
# ---------------------------------------------------------------------------


class TestSQLClauseFilter:
    """SQL clause keywords in bare inline prose are never detected as commands.

    With the universal approach, only $ prefix and code block lines are extracted.
    Bare prose (even with known SQL keywords) produces no candidates.
    """

    def test_where_from_filtered(self):
        """T006a: WHERE and FROM lines are not returned."""
        text = textwrap.dedent("""\
            Query active connections:

            WHERE state = 'idle'
            FROM pg_stat_activity
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        assert not any("WHERE" in l for l in lines), f"WHERE leaked: {lines}"
        assert not any("FROM" in l for l in lines), f"FROM leaked: {lines}"

    def test_real_commands_preserved(self):
        """T006b: real shell commands still appear despite SQL clause keywords nearby."""
        text = textwrap.dedent("""\
            Run diagnostics:

            ```bash
            psql -c "SELECT 1"
            redis-cli ping
            ```

            WHERE state = 'active'
            ORDER BY pid
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        assert any("redis-cli" in l or "psql" in l for l in lines), \
            f"Real commands missing: {lines}"
        assert not any(l.strip().upper().startswith("WHERE") for l in lines), \
            f"WHERE leaked: {lines}"

    def test_sql_clause_keywords_case_insensitive(self):
        """T006c: SQL clause keywords filtered regardless of case."""
        text = textwrap.dedent("""\
            having count(*) > 5
            LIMIT 100
            join users on users.id = orders.user_id
            on conflict do nothing
        """)
        results = detect_commands(text)
        lines = [c.line for c in results]
        for kw in ("having", "LIMIT", "join", "on"):
            assert not any(l.strip().lower().startswith(kw.lower()) for l in lines), \
                f"SQL clause '{kw}' leaked: {lines}"




# ---------------------------------------------------------------------------
# TestAutoCreateSkillParamComment — T010 (US3)
# ---------------------------------------------------------------------------


class TestAutoCreateSkillParamComment:
    """US3: auto_create_skill() generates run.sh with SKILL_PARAM_* comment block."""

    def test_skill_param_comment_present_with_var(self, tmp_path):
        """T010a: run.sh contains SKILL_PARAM_ when command uses $VAR syntax."""
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        auto_create_skill(kb_root, "check-host", "psql -h $HOST -U $USER", "Check host")
        run_sh = kb_root / "skills" / "check-host" / "scripts" / "run.sh"
        assert run_sh.exists(), "run.sh not created"
        content = run_sh.read_text()
        assert "SKILL_PARAM_" in content, f"SKILL_PARAM_ comment missing:\n{content}"

    def test_skill_param_comment_present_with_placeholder(self, tmp_path):
        """T010b: run.sh contains SKILL_PARAM_ when command uses {placeholder} syntax."""
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        auto_create_skill(kb_root, "run-query", "psql -c '{query}'", "Run query")
        run_sh = kb_root / "skills" / "run-query" / "scripts" / "run.sh"
        content = run_sh.read_text()
        assert "SKILL_PARAM_" in content, f"SKILL_PARAM_ comment missing:\n{content}"

    def test_skill_param_comment_present_no_params(self, tmp_path):
        """T010c: run.sh still contains SKILL_PARAM_ guidance even when no params used."""
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        auto_create_skill(kb_root, "simple-cmd", "echo hello", "Simple command")
        run_sh = kb_root / "skills" / "simple-cmd" / "scripts" / "run.sh"
        content = run_sh.read_text()
        assert "SKILL_PARAM_" in content, f"SKILL_PARAM_ comment missing:\n{content}"


# ---------------------------------------------------------------------------
# TestAutoCreatePlaceholderComment — T006 (US1)
# ---------------------------------------------------------------------------


class TestAutoCreatePlaceholderComment:
    """US1: auto_create_skill() run.sh comment uses single-brace {placeholder} syntax."""

    def test_no_double_braces_in_comment_no_params(self, tmp_path):
        """T006a: run.sh fallback comment line uses single braces, not double."""
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        auto_create_skill(kb_root, "simple-v6", "echo hello", "No params test")
        run_sh = kb_root / "skills" / "simple-v6" / "scripts" / "run.sh"
        content = run_sh.read_text()
        assert "{{placeholder}}" not in content, \
            f"Double-brace {{{{placeholder}}}} found in comment:\n{content}"
        assert "{placeholder}" in content, \
            f"Single-brace {{placeholder}} not found in comment:\n{content}"

    def test_skill_param_block_still_present(self, tmp_path):
        """T006b: SKILL_PARAM_* example block is still in the comment."""
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        auto_create_skill(kb_root, "with-param-v6", "psql -h {HOST}", "With param")
        run_sh = kb_root / "skills" / "with-param-v6" / "scripts" / "run.sh"
        content = run_sh.read_text()
        assert "SKILL_PARAM_" in content, \
            f"SKILL_PARAM_ block missing from run.sh:\n{content}"




# ---------------------------------------------------------------------------
# TestDetectCommandsCodeBlockLangFilter — T011 (US2 v8)
# ---------------------------------------------------------------------------


class TestDetectCommandsCodeBlockLangFilter:
    """US2 v8: detect_commands() only processes shell-family code blocks."""

    def test_nginx_block_filtered(self):
        """T011a: ```nginx block contents are not detected as commands."""
        text = "```nginx\nupstream backend {\n    server 127.0.0.1:8080;\n    keepalive 32;\n}\n```"
        result = detect_commands(text)
        lines = [c.line for c in result]
        assert not any("upstream" in l or "server" in l or "keepalive" in l for l in lines), \
            f"nginx block should be filtered but got: {lines}"

    def test_python_block_filtered(self):
        """T011b: ```python block contents are not detected as commands."""
        text = "```python\nimport os\nos.system('ls -la')\nprint('hello')\n```"
        result = detect_commands(text)
        lines = [c.line for c in result]
        assert not any("import" in l or "os.system" in l for l in lines), \
            f"python block should be filtered but got: {lines}"

    def test_bash_block_kept(self):
        """T011c: ```bash block commands are still detected."""
        text = "```bash\nredis-cli ping\n```"
        result = detect_commands(text)
        lines = [c.line for c in result]
        assert "redis-cli ping" in lines, \
            f"bash block command should be detected but got: {lines}"

    def test_no_lang_block_kept(self):
        """T011d: code block without language tag is still processed."""
        text = "```\npsql -U postgres\n```"
        result = detect_commands(text)
        lines = [c.line for c in result]
        assert any("psql" in l for l in lines), \
            f"no-lang block should be processed but got: {lines}"

    def test_shell_block_kept(self):
        """T011e: ```shell block commands are detected."""
        text = "```shell\ncurl -s http://localhost:8080/health\n```"
        result = detect_commands(text)
        lines = [c.line for c in result]
        assert any("curl" in l for l in lines), \
            f"shell block should be detected but got: {lines}"


# ---------------------------------------------------------------------------
# 018 E-10: param_names tests for create_skill()
# ---------------------------------------------------------------------------

import subprocess


class TestCreateSkillParamNames:
    """Tests for create_skill() param_names parameter (018 E-10)."""

    def test_param_names_written_to_skill_md(self, tmp_path):
        """018 E-10: create_skill with param_names writes params block to SKILL.md."""
        from holmes.kb.skill.manager import create_skill
        skill_dir = create_skill(
            tmp_path, "test-skill", "Test skill",
            param_names=["POD_NAME", "NAMESPACE"],
        )
        skill_md = (skill_dir / "SKILL.md").read_text()
        assert "params:" in skill_md
        assert "POD_NAME" in skill_md
        assert "NAMESPACE" in skill_md
        assert "required: false" in skill_md

    def test_param_names_in_run_sh(self, tmp_path):
        """018 E-10: param_names causes env-var bindings to appear in run.sh."""
        from holmes.kb.skill.manager import create_skill
        skill_dir = create_skill(
            tmp_path, "test-skill2", "Test skill 2",
            commands=["kubectl delete pod {POD_NAME} -n {NAMESPACE}"],
            param_names=["POD_NAME", "NAMESPACE"],
        )
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert 'POD_NAME="${SKILL_PARAM_POD_NAME:-}"' in run_sh
        assert 'NAMESPACE="${SKILL_PARAM_NAMESPACE:-}"' in run_sh

    def test_run_sh_syntax_valid(self, tmp_path):
        """018 E-10: generated run.sh passes bash syntax check."""
        from holmes.kb.skill.manager import create_skill
        skill_dir = create_skill(
            tmp_path, "test-skill3", "Test skill 3",
            commands=["kubectl delete pod {POD_NAME}"],
            param_names=["POD_NAME"],
        )
        run_sh_path = skill_dir / "scripts" / "run.sh"
        result = subprocess.run(
            ["bash", "-n", str(run_sh_path)],
            capture_output=True,
        )
        assert result.returncode == 0, f"bash -n failed: {result.stderr.decode()}"

    def test_no_param_names_no_params_block(self, tmp_path):
        """018 E-10: create_skill without param_names has no params block in SKILL.md."""
        from holmes.kb.skill.manager import create_skill
        skill_dir = create_skill(tmp_path, "test-skill4", "Test skill 4")
        skill_md = (skill_dir / "SKILL.md").read_text()
        # Should not have an uncommented params: block.
        lines = [l for l in skill_md.splitlines() if "params:" in l and not l.strip().startswith("#")]
        assert len(lines) == 0, f"Unexpected params: block: {lines}"


# ---------------------------------------------------------------------------
# T005 (021): _generate_skill_md Parameters markdown body fix
# ---------------------------------------------------------------------------


class TestGenerateSkillMdParametersBody:
    """021 T005: SKILL.md ## Parameters body reflects param_names, not placeholder."""

    def test_parameters_section_lists_param_names(self, tmp_path):
        """Given param_names=[NAMESPACE, APP_NAME], ## Parameters body contains both names."""
        from holmes.kb.skill.manager import create_skill

        skill_dir = create_skill(
            tmp_path, "deploy-restart", "Restart deployment",
            param_names=["NAMESPACE", "APP_NAME"],
        )
        skill_md = (skill_dir / "SKILL.md").read_text()
        assert "NAMESPACE" in skill_md
        assert "APP_NAME" in skill_md
        assert "No parameters defined" not in skill_md

    def test_parameters_section_no_placeholder_when_params_given(self, tmp_path):
        """The placeholder text must be fully absent when param_names is provided."""
        from holmes.kb.skill.manager import create_skill

        skill_dir = create_skill(
            tmp_path, "scale-app", "Scale application",
            param_names=["REPLICAS"],
        )
        skill_md = (skill_dir / "SKILL.md").read_text()
        # The placeholder should be replaced
        assert "No parameters defined" not in skill_md
        assert "REPLICAS" in skill_md

    def test_parameters_section_shows_placeholder_when_no_params(self, tmp_path):
        """Given param_names=[], ## Parameters body retains 'No parameters defined'."""
        from holmes.kb.skill.manager import create_skill

        skill_dir = create_skill(tmp_path, "simple-check", "Simple health check")
        skill_md = (skill_dir / "SKILL.md").read_text()
        assert "No parameters defined" in skill_md


class TestExtractCodeBlockLinesTrustLanguage:
    """_extract_code_block_lines() trusts code block language declaration.

    All non-empty, non-comment lines in shell-family blocks are returned as-is.
    Content quality is enforced at the Extractor prompt level.
    """

    def _extract(self, text: str) -> list:
        from holmes.kb.skill.manager import _extract_code_block_lines
        return _extract_code_block_lines(text)

    def test_commands_in_bash_block_returned(self):
        """All non-comment lines in bash block are returned."""
        text = "```bash\ncurl -v http://backend-host:8080/health\njournalctl -u nginx\n```"
        result = self._extract(text)
        assert any("curl" in r for r in result)
        assert any("journalctl" in r for r in result)

    def test_sql_in_sql_block_returned(self):
        """SQL commands in ```sql blocks are returned (trusted as executable commands)."""
        text = "```sql\nSHOW SLAVE STATUS\\G\nSELECT count(*) FROM pg_stat_activity;\n```"
        result = self._extract(text)
        assert any("SHOW" in r for r in result), f"SHOW not detected: {result}"
        assert any("SELECT" in r for r in result), f"SELECT not detected: {result}"

    def test_comments_always_excluded(self):
        """# comment lines are excluded from all shell-family blocks."""
        text = "```bash\n# This is a comment\nredis-cli ping\n```"
        result = self._extract(text)
        assert not any(r.startswith("#") for r in result)
        assert any("redis-cli" in r for r in result)
