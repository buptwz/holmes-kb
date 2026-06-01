"""Shared pytest fixtures for KB Skill tests."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Core KB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    """Return a fresh temporary KB root directory."""
    return tmp_path


def make_entry(
    kb_root: Path,
    entry_id: str = "PT-DB-001",
    extra_frontmatter: str = "",
) -> Path:
    """Create a minimal valid pitfall KB entry and return its path."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    entry_path.write_text(textwrap.dedent(f"""\
        ---
        id: {entry_id}
        type: pitfall
        title: Test Entry {entry_id}
        maturity: draft
        category: database
        tags: []
        created_at: "2024-01-01T00:00:00+00:00"
        updated_at: "2024-01-01T00:00:00+00:00"
        {extra_frontmatter}
        ---

        ## Symptoms
        Test symptoms.

        ## Root Cause
        Test root cause.

        ## Resolution
        Test resolution.
    """), encoding="utf-8")
    return entry_path


def make_skill_with_script(kb_root: Path, name: str, script: str) -> Path:
    """Create a skill directory with the given run.sh content."""
    from holmes.kb.skill.manager import create_skill
    skill_dir = create_skill(kb_root, name, f"Test skill: {name}")
    run_sh = skill_dir / "scripts" / "run.sh"
    run_sh.write_text(script, encoding="utf-8")
    run_sh.chmod(0o755)
    return skill_dir


# ---------------------------------------------------------------------------
# Convenience script fixtures
# ---------------------------------------------------------------------------


def run_sh_echo(kb_root: Path, name: str, message: str) -> Path:
    """Create a skill whose run.sh echoes a fixed message."""
    return make_skill_with_script(
        kb_root, name, f"#!/usr/bin/env bash\necho {message!r}\n"
    )


def run_sh_env(kb_root: Path, name: str, var: str) -> Path:
    """Create a skill whose run.sh echoes the value of a given env variable."""
    return make_skill_with_script(
        kb_root, name, f"#!/usr/bin/env bash\necho \"${{{var}}}\"\n"
    )


def skill_with_prereqs(kb_root: Path, name: str, prereq: str) -> Path:
    """Create a skill with a single prerequisite command declaration."""
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


def skill_with_required_param(kb_root: Path, name: str, param_name: str) -> Path:
    """Create a skill with one required parameter."""
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir()
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: Test skill with required param
        version: 1.0.0
        platforms: linux,macos
        timeout: 10
        params:
          - name: {param_name}
            description: Required param
            required: true
        ---
        body
    """), encoding="utf-8")
    run_sh = scripts / "run.sh"
    run_sh.write_text(
        f"#!/usr/bin/env bash\necho \"{param_name}=${{SKILL_PARAM_{param_name.upper()}}}\"\n",
        encoding="utf-8",
    )
    run_sh.chmod(0o755)
    return skill_dir
