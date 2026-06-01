"""Skill runner — execute a skill's scripts/run.sh with parameter injection."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from holmes.kb.skill.manager import get_skill_dir, parse_skill_md

logger = logging.getLogger(__name__)

STDOUT_MAX_BYTES = 10 * 1024  # 10 KB truncation limit
DEFAULT_TIMEOUT = 30  # seconds


class SkillNotFoundError(Exception):
    """Raised when the requested skill directory does not exist."""


class RunScriptNotFoundError(Exception):
    """Raised when scripts/run.sh is absent in the skill directory."""


class PrerequisiteError(Exception):
    """Raised when a prerequisite command is not available on PATH."""


class MissingParamError(Exception):
    """Raised when a required skill parameter is not provided."""


@dataclass
class SkillExecution:
    """Result of executing a skill's run.sh."""

    skill: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
    error: str = ""


def run_skill(
    kb_root: Path,
    name: str,
    params: Optional[dict[str, str]] = None,
    timeout_override: Optional[int] = None,
) -> SkillExecution:
    """Execute a skill's scripts/run.sh and return the result.

    Args:
        kb_root: Root directory of the knowledge base.
        name: Skill name.
        params: Key-value parameter dict. Keys should match SKILL.md param names.
        timeout_override: Override default timeout in seconds.

    Returns:
        SkillExecution with stdout, stderr, exit_code, duration_ms, truncated.

    Raises:
        SkillNotFoundError: if skill directory does not exist.
        RunScriptNotFoundError: if scripts/run.sh is absent.
        PrerequisiteError: if a prerequisite command is not on PATH.
        MissingParamError: if a required parameter is not provided.
    """
    params = params or {}
    skill_dir = get_skill_dir(kb_root, name)
    if not skill_dir.is_dir():
        raise SkillNotFoundError(f"Skill '{name}' not found.")

    run_sh = skill_dir / "scripts" / "run.sh"
    if not run_sh.exists():
        raise RunScriptNotFoundError(f"No run.sh in skills/{name}/scripts/.")

    # Parse SKILL.md for metadata (prerequisites, params, timeout).
    skill_md = skill_dir / "SKILL.md"
    timeout = DEFAULT_TIMEOUT
    defn = None
    if skill_md.exists():
        try:
            defn = parse_skill_md(skill_md)
            timeout = defn.timeout or DEFAULT_TIMEOUT
        except Exception:  # noqa: BLE001
            pass

    if timeout_override is not None:
        timeout = timeout_override

    # Check prerequisites.
    if defn and defn.prerequisites:
        for prereq in defn.prerequisites:
            cmd = prereq.split()[0]  # take first token as command name
            if not shutil.which(cmd):
                raise PrerequisiteError(f"Prerequisite command not found: {cmd}")

    # Check required parameters.
    if defn and defn.params:
        for p in defn.params:
            if p.required and p.name not in params:
                raise MissingParamError(f"Missing required param: {p.name}")

    # Build environment: inject SKILL_PARAM_* variables.
    import os
    env = os.environ.copy()
    for k, v in params.items():
        env[f"SKILL_PARAM_{k.upper().replace('-', '_')}"] = str(v)

    start_ms = int(time.monotonic() * 1000)
    try:
        proc = subprocess.run(
            ["bash", str(run_sh)],
            capture_output=True,
            env=env,
            timeout=timeout,
            cwd=str(skill_dir),
        )
        duration_ms = int(time.monotonic() * 1000) - start_ms
        stdout_bytes = proc.stdout
        truncated = len(stdout_bytes) > STDOUT_MAX_BYTES
        stdout_str = stdout_bytes[:STDOUT_MAX_BYTES].decode("utf-8", errors="replace")
        stderr_str = proc.stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode

    except subprocess.TimeoutExpired:
        duration_ms = int(time.monotonic() * 1000) - start_ms
        logger.info(
            "skill_run skill=%s params=%s exit_code=-1 duration_ms=%d truncated=False timeout=True",
            name, list(params.keys()), duration_ms,
        )
        return SkillExecution(
            skill=name,
            exit_code=-1,
            stdout="",
            stderr="",
            duration_ms=duration_ms,
            truncated=False,
            error=f"Timeout after {timeout}s",
        )

    logger.info(
        "skill_run skill=%s params=%s exit_code=%d duration_ms=%d truncated=%s",
        name, list(params.keys()), exit_code, duration_ms, truncated,
    )

    return SkillExecution(
        skill=name,
        exit_code=exit_code,
        stdout=stdout_str,
        stderr=stderr_str,
        duration_ms=duration_ms,
        truncated=truncated,
    )
