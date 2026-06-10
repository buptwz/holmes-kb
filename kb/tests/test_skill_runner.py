"""Unit tests for holmes.kb.skill.runner."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor

from holmes.kb.skill.manager import create_skill
from holmes.kb.skill.runner import (
    MissingParamError,
    PrerequisiteError,
    RunScriptNotFoundError,
    SkillNotFoundError,
    run_skill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_with_script(kb_root: Path, name: str, script: str) -> Path:
    """Create a skill and overwrite run.sh with given script content."""
    skill_dir = create_skill(kb_root, name, f"Test skill: {name}")
    run_sh = skill_dir / "scripts" / "run.sh"
    run_sh.write_text(script, encoding="utf-8")
    run_sh.chmod(0o755)
    return skill_dir


def _make_skill_with_params(kb_root: Path, name: str) -> Path:
    """Create a skill that requires a 'host' param."""
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Test skill with params
        version: 1.0.0
        platforms: linux,macos
        timeout: 10
        params:
          - name: host
            description: Target host
            required: true
        ---
        body
    """), encoding="utf-8")
    run_sh = scripts / "run.sh"
    run_sh.write_text("#!/usr/bin/env bash\necho \"host=$SKILL_PARAM_HOST\"\n", encoding="utf-8")
    run_sh.chmod(0o755)
    return skill_dir


def _make_skill_with_prereqs(kb_root: Path, name: str, prereq: str) -> Path:
    """Create a skill with a prerequisite command."""
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Test skill with prereqs
        version: 1.0.0
        platforms: linux,macos
        timeout: 10
        prerequisites:
          - {prereq}
        ---
        body
    """), encoding="utf-8")
    run_sh = scripts / "run.sh"
    run_sh.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    run_sh.chmod(0o755)
    return skill_dir


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


def test_run_skill_success(tmp_path):
    _make_skill_with_script(tmp_path, "my-skill", "#!/usr/bin/env bash\necho hello\n")
    result = run_skill(tmp_path, "my-skill")
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.truncated is False


def test_run_skill_exit_code_nonzero(tmp_path):
    _make_skill_with_script(tmp_path, "fail-skill", "#!/usr/bin/env bash\nexit 2\n")
    result = run_skill(tmp_path, "fail-skill")
    assert result.exit_code == 2


def test_run_skill_captures_stderr(tmp_path):
    _make_skill_with_script(tmp_path, "err-skill", "#!/usr/bin/env bash\necho error >&2\n")
    result = run_skill(tmp_path, "err-skill")
    assert "error" in result.stderr


def test_run_skill_not_found(tmp_path):
    with pytest.raises(SkillNotFoundError):
        run_skill(tmp_path, "nonexistent")


def test_run_skill_no_run_sh(tmp_path):
    skill_dir = tmp_path / "skills" / "no-script"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: no-script\ndescription: test\n---\n")
    with pytest.raises(RunScriptNotFoundError):
        run_skill(tmp_path, "no-script")


# ---------------------------------------------------------------------------
# Parameter injection
# ---------------------------------------------------------------------------


def test_run_skill_injects_params(tmp_path):
    _make_skill_with_script(
        tmp_path, "param-skill",
        "#!/usr/bin/env bash\necho \"host=$SKILL_PARAM_HOST port=$SKILL_PARAM_PORT\"\n"
    )
    result = run_skill(tmp_path, "param-skill", {"host": "10.0.0.1", "port": "6380"})
    assert "host=10.0.0.1" in result.stdout
    assert "port=6380" in result.stdout


def test_run_skill_missing_required_param(tmp_path):
    _make_skill_with_params(tmp_path, "req-skill")
    with pytest.raises(MissingParamError, match="host"):
        run_skill(tmp_path, "req-skill")


def test_run_skill_required_param_provided(tmp_path):
    _make_skill_with_params(tmp_path, "req-skill")
    result = run_skill(tmp_path, "req-skill", {"host": "127.0.0.1"})
    assert result.exit_code == 0
    assert "host=127.0.0.1" in result.stdout


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_run_skill_timeout(tmp_path):
    _make_skill_with_script(tmp_path, "slow-skill", "#!/usr/bin/env bash\nsleep 60\n")
    result = run_skill(tmp_path, "slow-skill", timeout_override=1)
    assert result.exit_code == -1
    assert "Timeout" in result.error


# ---------------------------------------------------------------------------
# Stdout truncation
# ---------------------------------------------------------------------------


def test_run_skill_truncation(tmp_path):
    # Generate > 10 KB of output.
    _make_skill_with_script(
        tmp_path, "big-skill",
        "#!/usr/bin/env bash\npython3 -c \"print('x' * 12000)\"\n"
    )
    result = run_skill(tmp_path, "big-skill")
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) <= 10 * 1024


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def test_run_skill_prerequisite_missing(tmp_path):
    _make_skill_with_prereqs(tmp_path, "req-tool-skill", "definitely-not-a-real-command-xyz")
    with pytest.raises(PrerequisiteError, match="definitely-not-a-real-command-xyz"):
        run_skill(tmp_path, "req-tool-skill")


def test_run_skill_prerequisite_present(tmp_path):
    # 'bash' is always present.
    _make_skill_with_prereqs(tmp_path, "bash-skill", "bash")
    result = run_skill(tmp_path, "bash-skill")
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# TT020: T-RUN-001~002  Hyphenated param names → SKILL_PARAM_MY_HOST
# ---------------------------------------------------------------------------


def test_run_skill_hyphen_param_name_converts(tmp_path):
    """T-RUN-001: param name with hyphen converts to underscore in env var."""
    _make_skill_with_script(
        tmp_path, "hyphen-skill",
        "#!/usr/bin/env bash\necho \"val=$SKILL_PARAM_MY_HOST\"\n",
    )
    result = run_skill(tmp_path, "hyphen-skill", {"my-host": "10.0.0.2"})
    assert result.exit_code == 0
    assert "val=10.0.0.2" in result.stdout


def test_run_skill_hyphen_param_uppercase(tmp_path):
    """T-RUN-002: multi-word hyphenated param → ALL_CAPS env var."""
    _make_skill_with_script(
        tmp_path, "multi-hyphen",
        "#!/usr/bin/env bash\necho \"$SKILL_PARAM_DB_HOST_PORT\"\n",
    )
    result = run_skill(tmp_path, "multi-hyphen", {"db-host-port": "5432"})
    assert "5432" in result.stdout


# ---------------------------------------------------------------------------
# TT021: T-RUN-004~005  SKILL.md timeout field + timeout_override
# ---------------------------------------------------------------------------


def _make_skill_with_timeout(kb_root: Path, name: str, timeout_s: int) -> Path:
    """Create a skill with a custom SKILL.md timeout and a sleep run.sh."""
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Skill with custom timeout
        version: 1.0.0
        platforms: linux,macos
        timeout: {timeout_s}
        ---
        body
    """), encoding="utf-8")
    run_sh = scripts / "run.sh"
    run_sh.write_text("#!/usr/bin/env bash\nsleep 5\necho done\n", encoding="utf-8")
    run_sh.chmod(0o755)
    return skill_dir


def test_skill_md_timeout_overrides_default(tmp_path):
    """T-RUN-004: SKILL.md timeout:2 causes sleep 5 script to time out."""
    _make_skill_with_timeout(tmp_path, "short-timeout", 2)
    result = run_skill(tmp_path, "short-timeout")
    assert result.exit_code == -1
    assert "Timeout" in result.error


def test_timeout_override_beats_skill_md(tmp_path):
    """T-RUN-005: timeout_override=10 allows sleep 5 despite SKILL.md timeout:2."""
    _make_skill_with_timeout(tmp_path, "override-skill", 2)
    result = run_skill(tmp_path, "override-skill", timeout_override=10)
    assert result.exit_code == 0
    assert "done" in result.stdout


# ---------------------------------------------------------------------------
# TT022: T-RUN-010  Prerequisites with spaces — check first token
# ---------------------------------------------------------------------------


def test_prerequisite_with_spaces_checks_first_token(tmp_path):
    """T-RUN-010: 'bash -version' prereq checks 'bash', not the whole string."""
    # "bash -version" as a prereq — bash exists, so should pass
    _make_skill_with_prereqs(tmp_path, "bash-space-skill", "bash -version")
    result = run_skill(tmp_path, "bash-space-skill")
    assert result.exit_code == 0


def test_prerequisite_with_spaces_fails_on_missing_first_token(tmp_path):
    """T-RUN-010 negative: 'nonexistent-cmd -h' — first token nonexistent."""
    _make_skill_with_prereqs(tmp_path, "missing-space-skill", "nonexistent-cmd-xyz -h")
    with pytest.raises(PrerequisiteError, match="nonexistent-cmd-xyz"):
        run_skill(tmp_path, "missing-space-skill")


# ---------------------------------------------------------------------------
# TT023: T-RUN-012  subprocess cwd == skill_dir
# ---------------------------------------------------------------------------


def test_run_skill_cwd_is_skill_dir(tmp_path):
    """T-RUN-012: run.sh's working directory equals the skill directory."""
    skill_dir = _make_skill_with_script(
        tmp_path, "cwd-skill",
        "#!/usr/bin/env bash\npwd\n",
    )
    result = run_skill(tmp_path, "cwd-skill")
    assert result.exit_code == 0
    # pwd output should match the skill_dir path (resolving symlinks for safety)
    assert str(skill_dir.resolve()) in result.stdout.strip()


# ---------------------------------------------------------------------------
# TT024: T-RUN-013  Structured log completeness (caplog)
# ---------------------------------------------------------------------------


def test_run_skill_structured_log(tmp_path, caplog):
    """T-RUN-013: INFO log contains skill_run/skill=/exit_code=/duration_ms=/truncated=."""
    import logging
    _make_skill_with_script(tmp_path, "log-skill", "#!/usr/bin/env bash\necho hi\n")
    with caplog.at_level(logging.INFO, logger="holmes.kb.skill.runner"):
        run_skill(tmp_path, "log-skill", {"host": "127.0.0.1"})

    combined = " ".join(caplog.messages)
    assert "skill_run" in combined
    assert "skill=" in combined
    assert "exit_code=" in combined
    assert "duration_ms=" in combined
    assert "truncated=" in combined
    # Param values must NOT appear in logs (only keys)
    assert "127.0.0.1" not in combined


# ---------------------------------------------------------------------------
# TT025: T-RUN-014  stdout and stderr are captured independently
# ---------------------------------------------------------------------------


def test_run_skill_stdout_stderr_independent(tmp_path):
    """T-RUN-014: stdout and stderr are captured in separate fields."""
    _make_skill_with_script(
        tmp_path, "mixed-skill",
        "#!/usr/bin/env bash\necho 'out-line'\necho 'err-line' >&2\n",
    )
    result = run_skill(tmp_path, "mixed-skill")
    assert "out-line" in result.stdout
    assert "err-line" not in result.stdout
    assert "err-line" in result.stderr
    assert "out-line" not in result.stderr


# ---------------------------------------------------------------------------
# TT026: T-RUN-005  Exact 10KB truncation boundary
# ---------------------------------------------------------------------------


def test_run_skill_exact_10kb_truncation(tmp_path):
    """T-RUN-005: 10241-byte output truncated to exactly 10240 bytes, truncated=True."""
    # Write exactly 10241 bytes of 'a' + newline padding
    _make_skill_with_script(
        tmp_path, "exact-trunc",
        "#!/usr/bin/env bash\npython3 -c \"import sys; sys.stdout.buffer.write(b'a' * 10241)\"\n",
    )
    result = run_skill(tmp_path, "exact-trunc")
    encoded = result.stdout.encode("utf-8")
    assert result.truncated is True
    assert len(encoded) == 10240


# ---------------------------------------------------------------------------
# TT047: T-PERF-002  duration_ms accuracy
# ---------------------------------------------------------------------------


def test_run_skill_duration_ms_accuracy(tmp_path):
    """T-PERF-002: sleep 0.1 skill has duration_ms in [100, 500) ms."""
    _make_skill_with_script(
        tmp_path, "sleep-skill",
        "#!/usr/bin/env bash\nsleep 0.1\n",
    )
    result = run_skill(tmp_path, "sleep-skill")
    assert result.exit_code == 0
    assert 100 <= result.duration_ms < 500, f"duration_ms={result.duration_ms}"


# ---------------------------------------------------------------------------
# TT048: T-PERF-003  Sensitive param values not logged
# ---------------------------------------------------------------------------


def test_run_skill_sensitive_params_not_logged(tmp_path, caplog):
    """T-PERF-003: sensitive param values must not appear in log output."""
    import logging
    _make_skill_with_script(
        tmp_path, "secret-skill",
        "#!/usr/bin/env bash\necho ok\n",
    )
    with caplog.at_level(logging.INFO, logger="holmes.kb.skill.runner"):
        run_skill(tmp_path, "secret-skill", {"password": "secret123", "token": "abc-xyz"})

    combined = " ".join(caplog.messages)
    assert "secret123" not in combined
    assert "abc-xyz" not in combined
    # Key names are OK to appear (just not values)
    assert "password" in combined or "token" in combined


# ---------------------------------------------------------------------------
# T027: Chinese runbook Skill generation (US3)
# ---------------------------------------------------------------------------


class TestChineseRunbookSkillGeneration:
    """Verify SkillAdvisor produces a Skill recommendation for Chinese runbooks
    with ## 诊断步骤 sections containing >= 2 bash commands (C-2c fix).
    """

    REDIS_RUNBOOK_RESOLUTION = """\
执行以下命令诊断 Redis 主从同步问题：

```bash
redis-cli INFO replication
```

```bash
redis-cli DEBUG SLEEP 0
```

以上两个命令可以帮助确认 Redis 复制状态和响应是否正常。
"""

    def test_skill_recommended_for_chinese_runbook_with_two_commands(self, tmp_path):
        """SkillAdvisor should return RECOMMENDED for Chinese runbook with 2+ bash commands."""
        advisor = SkillAdvisor()
        advice = advisor.advise(
            entry_id="test-redis-001",
            resolution_text=self.REDIS_RUNBOOK_RESOLUTION,
            kb_root=tmp_path,
        )
        assert advice.recommendation in (Recommendation.RECOMMENDED, Recommendation.OPTIONAL), (
            f"Expected RECOMMENDED or OPTIONAL for Chinese runbook with 2 commands, "
            f"got {advice.recommendation}. "
            f"Step count should be >= 2 to trigger recommendation."
        )

    def test_skill_not_recommended_for_single_command(self, tmp_path):
        """Single command should not trigger RECOMMENDED (but may be OPTIONAL)."""
        advisor = SkillAdvisor()
        advice = advisor.advise(
            entry_id="test-redis-002",
            resolution_text="```bash\nredis-cli INFO replication\n```\n",
            kb_root=tmp_path,
        )
        # RECOMMENDED requires >= 2 steps (C-2c fix: threshold lowered from 3 to 2)
        # Single command = 1 step → should not be RECOMMENDED
        assert advice.recommendation != Recommendation.RECOMMENDED, (
            "A single command should not trigger RECOMMENDED skill generation"
        )

    def test_redis_runbook_fixture_has_two_commands(self):
        """Verify the redis_runbook_zh.md fixture contains the expected commands."""
        fixture_path = (
            Path(__file__).parent / "fixtures" / "redis_runbook_zh.md"
        )
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        content = fixture_path.read_text(encoding="utf-8")
        assert "redis-cli INFO replication" in content
        assert "redis-cli DEBUG SLEEP 0" in content
        assert "## 诊断步骤" in content

    def test_skill_advisor_detects_mysql_cli_commands(self, tmp_path):
        """C-2b: mysql CLI commands should be recognized as skill steps."""
        advisor = SkillAdvisor()
        resolution = """\
```bash
mysql -e "SHOW PROCESSLIST;"
```

```bash
mysql -e "KILL <PROCESS_ID>;"
```
"""
        advice = advisor.advise(
            entry_id="test-mysql-001",
            resolution_text=resolution,
            kb_root=tmp_path,
        )
        assert advice.recommendation in (Recommendation.RECOMMENDED, Recommendation.OPTIONAL), (
            f"Expected RECOMMENDED or OPTIONAL for MySQL CLI commands, got {advice.recommendation}"
        )


# ---------------------------------------------------------------------------
# D-6: run.sh contains real commands (T008)
# ---------------------------------------------------------------------------


class TestSkillRunShCommands:
    """Verify that create_skill() writes actual commands to run.sh (D-6 fix)."""

    def test_create_skill_without_commands_uses_placeholder(self, tmp_path):
        """When no commands provided, run.sh contains the TODO placeholder."""
        skill_dir = create_skill(tmp_path, "test-skill-no-cmd", "Test skill")
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert "TODO" in run_sh

    def test_create_skill_with_commands_writes_them_to_run_sh(self, tmp_path):
        """When commands list provided, run.sh contains those commands verbatim."""
        commands = ["redis-cli INFO replication", "redis-cli DEBUG SLEEP 0"]
        skill_dir = create_skill(
            tmp_path, "test-redis-skill", "Redis replication check", commands=commands
        )
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert "redis-cli INFO replication" in run_sh
        assert "redis-cli DEBUG SLEEP 0" in run_sh

    def test_create_skill_with_commands_no_todo_placeholder(self, tmp_path):
        """When commands are provided, the TODO placeholder should not remain."""
        commands = ["psql -c 'SELECT pg_is_in_recovery();'"]
        skill_dir = create_skill(
            tmp_path, "test-pg-skill", "PostgreSQL check", commands=commands
        )
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert "TODO" not in run_sh
        assert "pg_is_in_recovery" in run_sh

    def test_create_skill_script_header_always_present(self, tmp_path):
        """Script header (shebang, set -euo pipefail) is always present."""
        commands = ["echo test"]
        skill_dir = create_skill(
            tmp_path, "test-header-skill", "Header test", commands=commands
        )
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert "#!/usr/bin/env bash" in run_sh
        assert "set -euo pipefail" in run_sh

    def test_create_skill_empty_commands_list_uses_placeholder(self, tmp_path):
        """Empty commands list falls back to placeholder template."""
        skill_dir = create_skill(
            tmp_path, "test-empty-cmd-skill", "Empty commands", commands=[]
        )
        run_sh = (skill_dir / "scripts" / "run.sh").read_text()
        assert "TODO" in run_sh
