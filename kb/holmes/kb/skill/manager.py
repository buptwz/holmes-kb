"""Skill manager — create, link, unlink, list, and detect skills in the KB."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$|^[a-z0-9]{3,64}$")
SKILL_NAME_MIN = 3
SKILL_NAME_MAX = 64

# Regex for detecting executable commands in resolution text.
# Matches: "$ command", `backtick command`, known CLI tools at line start
_CMD_PREFIXES = r"(?:redis-cli|nginx|curl|kubectl|docker|systemctl|journalctl|netstat|ss|ps|top|htop|df|du|lsof|strace|tcpdump|grep|awk|sed|tail|head|cat|ls|find)"
CMD_PATTERN = re.compile(
    r"(?:"
    r"\$\s+([^\n`]{5,120})"          # $ command …
    r"|`([^`\n]{5,120})`"             # `backtick command`
    r"|^(" + _CMD_PREFIXES + r"[^\n]*)"  # known CLI tool at line start
    r")",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def validate_skill_name(name: str) -> None:
    """Raise ValueError if name does not match [a-z0-9-] and 3-64 chars."""
    if not (SKILL_NAME_MIN <= len(name) <= SKILL_NAME_MAX):
        raise ValueError(
            f"Skill name must be {SKILL_NAME_MIN}-{SKILL_NAME_MAX} characters. Got {len(name)!r}."
        )
    if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$", name):
        raise ValueError(
            f"Skill name must match [a-z0-9-] (lowercase letters, digits, hyphens). Got {name!r}."
        )


def get_skill_dir(kb_root: Path, name: str) -> Path:
    """Return the path to the skill directory (may or may not exist)."""
    return kb_root / "skills" / name


def skill_exists(kb_root: Path, name: str) -> bool:
    """Return True if the skill directory exists."""
    return get_skill_dir(kb_root, name).is_dir()


# ---------------------------------------------------------------------------
# SKILL.md parser
# ---------------------------------------------------------------------------


@dataclass
class SkillParam:
    """A single skill parameter definition."""

    name: str
    description: str = ""
    required: bool = False
    default: str = ""


@dataclass
class SkillDefinition:
    """Parsed representation of a SKILL.md file."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    platforms: list[str] = field(default_factory=lambda: ["linux", "macos"])
    timeout: int = 30
    params: list[SkillParam] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    content: str = ""  # full raw SKILL.md text


def parse_skill_md(path: Path) -> SkillDefinition:
    """Parse a SKILL.md file and return a SkillDefinition.

    Args:
        path: Absolute path to SKILL.md.

    Returns:
        SkillDefinition populated from YAML frontmatter.

    Raises:
        FileNotFoundError: if path does not exist.
        ValueError: if frontmatter cannot be parsed.
    """
    if not path.exists():
        raise FileNotFoundError(f"SKILL.md not found: {path}")

    raw = path.read_text(encoding="utf-8")
    try:
        post = frontmatter.loads(raw)
    except Exception as exc:
        raise ValueError(f"Failed to parse SKILL.md frontmatter: {exc}") from exc

    meta = post.metadata

    # Parse params list.
    params: list[SkillParam] = []
    for p in meta.get("params", []) or []:
        if isinstance(p, dict):
            params.append(SkillParam(
                name=str(p.get("name", "")),
                description=str(p.get("description", "")),
                required=bool(p.get("required", False)),
                default=str(p.get("default", "")),
            ))

    # Parse prerequisites list (may be list of strings or dict with "commands").
    prerequisites: list[str] = []
    prereq_raw = meta.get("prerequisites", [])
    if isinstance(prereq_raw, dict):
        for cmd in prereq_raw.get("commands", []):
            prerequisites.append(str(cmd))
    elif isinstance(prereq_raw, list):
        for item in prereq_raw:
            if isinstance(item, str):
                prerequisites.append(item)
            elif isinstance(item, dict):
                cmd = item.get("command") or item.get("cmd") or item.get("name", "")
                if cmd:
                    prerequisites.append(str(cmd))

    # Parse platforms.
    platforms_raw = meta.get("platforms", "linux,macos")
    if isinstance(platforms_raw, str):
        platforms = [p.strip() for p in platforms_raw.split(",") if p.strip()]
    elif isinstance(platforms_raw, list):
        platforms = [str(p) for p in platforms_raw]
    else:
        platforms = ["linux", "macos"]

    return SkillDefinition(
        name=str(meta.get("name", path.parent.name)),
        description=str(meta.get("description", "")),
        version=str(meta.get("version", "1.0.0")),
        platforms=platforms,
        timeout=int(meta.get("timeout", 30)),
        params=params,
        prerequisites=prerequisites,
        content=raw,
    )


# ---------------------------------------------------------------------------
# Skill creation
# ---------------------------------------------------------------------------


def create_skill(
    kb_root: Path,
    name: str,
    description: str,
    platforms: str = "linux,macos",
) -> Path:
    """Create a new skill directory with SKILL.md and scripts/run.sh templates.

    Args:
        kb_root: Root directory of the knowledge base.
        name: Skill name (kebab-case, validated).
        description: One-sentence description.
        platforms: Comma-separated platform list.

    Returns:
        Path to the created skill directory.

    Raises:
        ValueError: if name is invalid or skill already exists.
    """
    from holmes.kb.skill.template import generate_run_sh_template, generate_skill_template

    validate_skill_name(name)
    skill_dir = get_skill_dir(kb_root, name)
    if skill_dir.exists():
        raise ValueError(f"Skill '{name}' already exists.")

    skill_dir.mkdir(parents=True)
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()

    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(
        generate_skill_template(name, description, platforms), encoding="utf-8"
    )

    run_sh_path = scripts_dir / "run.sh"
    run_sh_path.write_text(generate_run_sh_template(description), encoding="utf-8")
    run_sh_path.chmod(0o755)

    return skill_dir


# ---------------------------------------------------------------------------
# Link / unlink
# ---------------------------------------------------------------------------


def _find_entry_path(kb_root: Path, entry_id: str) -> Optional[Path]:
    """Find the filesystem path for a KB entry by scanning known type directories."""
    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        for md_file in (kb_root / kb_type).rglob("*.md") if (kb_root / kb_type).is_dir() else []:
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                if str(post.metadata.get("id", "")) == entry_id:
                    return md_file
            except Exception:  # noqa: BLE001
                pass
    return None


def link_skill(kb_root: Path, entry_id: str, skill_name: str) -> None:
    """Mount a skill onto a KB entry by adding it to skill_refs frontmatter.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: KB entry ID (e.g. PT-DB-001).
        skill_name: Skill name to link.

    Raises:
        FileNotFoundError: if entry or skill not found.
    """
    entry_path = _find_entry_path(kb_root, entry_id)
    if entry_path is None:
        raise FileNotFoundError(f"Entry '{entry_id}' not found.")
    if not skill_exists(kb_root, skill_name):
        raise FileNotFoundError(
            f"Skill '{skill_name}' not found. Run: holmes kb skill create {skill_name}"
        )

    post = frontmatter.load(str(entry_path))
    skill_refs: list[str] = list(post.metadata.get("skill_refs") or [])
    if skill_name in skill_refs:
        # Already linked — idempotent.
        return

    skill_refs.append(skill_name)
    post.metadata["skill_refs"] = skill_refs
    post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")


def unlink_skill(kb_root: Path, entry_id: str, skill_name: str) -> bool:
    """Remove a skill from a KB entry's skill_refs (idempotent).

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: KB entry ID.
        skill_name: Skill name to remove.

    Returns:
        True if the skill was present and removed; False if it was not linked.

    Raises:
        FileNotFoundError: if entry not found.
    """
    entry_path = _find_entry_path(kb_root, entry_id)
    if entry_path is None:
        raise FileNotFoundError(f"Entry '{entry_id}' not found.")

    post = frontmatter.load(str(entry_path))
    skill_refs: list[str] = list(post.metadata.get("skill_refs") or [])
    if skill_name not in skill_refs:
        return False

    skill_refs.remove(skill_name)
    if skill_refs:
        post.metadata["skill_refs"] = skill_refs
    else:
        post.metadata.pop("skill_refs", None)
    post.metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# List skills
# ---------------------------------------------------------------------------


@dataclass
class SkillSummary:
    """Lightweight info about a skill for listing purposes."""

    name: str
    description: str
    version: str
    platforms: list[str]
    linked_entries: list[str] = field(default_factory=list)


def list_skills(kb_root: Path, entry_id: Optional[str] = None) -> list[SkillSummary]:
    """List all skills in the KB skill library.

    Args:
        kb_root: Root directory of the knowledge base.
        entry_id: If given, return only skills linked to that entry.

    Returns:
        List of SkillSummary objects.
    """
    skills_dir = kb_root / "skills"
    if not skills_dir.is_dir():
        return []

    # Build reverse map: skill_name → [entry_ids] by scanning all KB entries.
    linked: dict[str, list[str]] = {}
    for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
        type_dir = kb_root / kb_type
        if not type_dir.is_dir():
            continue
        for md_file in type_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                post = frontmatter.load(str(md_file))
                eid = str(post.metadata.get("id", md_file.stem))
                for sname in post.metadata.get("skill_refs") or []:
                    linked.setdefault(str(sname), []).append(eid)
            except Exception:  # noqa: BLE001
                pass

    # If filtering by entry, first get the entry's skill_refs.
    if entry_id is not None:
        entry_path = _find_entry_path(kb_root, entry_id)
        if entry_path is None:
            return []
        try:
            post = frontmatter.load(str(entry_path))
            refs = [str(r) for r in post.metadata.get("skill_refs") or []]
        except Exception:  # noqa: BLE001
            return []
        target_names = set(refs)
    else:
        target_names = None

    results: list[SkillSummary] = []
    for skill_subdir in sorted(skills_dir.iterdir()):
        if not skill_subdir.is_dir():
            continue
        name = skill_subdir.name
        if target_names is not None and name not in target_names:
            continue
        skill_md = skill_subdir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            defn = parse_skill_md(skill_md)
        except Exception:  # noqa: BLE001
            defn = SkillDefinition(name=name)
        results.append(SkillSummary(
            name=name,
            description=defn.description,
            version=defn.version,
            platforms=defn.platforms,
            linked_entries=linked.get(name, []),
        ))

    return results


# ---------------------------------------------------------------------------
# Command detection (for agent sedimentation — US3)
# ---------------------------------------------------------------------------


@dataclass
class CommandCandidate:
    """A detected command candidate for skill auto-generation."""

    line: str
    suggested_name: str


def _slugify(text: str) -> str:
    """Convert text to kebab-case slug for skill names."""
    text = text.lower().strip()
    # Keep only alphanumeric and spaces/hyphens, collapse.
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    # Truncate.
    parts = text.split("-")
    result = "-".join(parts[:4])  # max 4 words
    return result[:64] or "skill"


def detect_commands(resolution_text: str) -> list[CommandCandidate]:
    """Detect executable command lines in a resolution text.

    Args:
        resolution_text: The resolution body of a KB entry.

    Returns:
        List of CommandCandidate with line and suggested_name.
    """
    candidates: list[CommandCandidate] = []
    seen: set[str] = set()

    for m in CMD_PATTERN.finditer(resolution_text):
        # Pick the first non-empty capture group.
        cmd_line = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not cmd_line or cmd_line in seen:
            continue
        seen.add(cmd_line)
        # Generate suggested name from first 3 tokens.
        tokens = cmd_line.split()[:3]
        raw_name = "-".join(t.lstrip("-") for t in tokens if t.lstrip("-"))
        suggested = _slugify(raw_name)
        # Ensure minimum length.
        if len(suggested) < 3:
            suggested = "check-cmd"
        candidates.append(CommandCandidate(line=cmd_line, suggested_name=suggested))

    return candidates


# ---------------------------------------------------------------------------
# Auto-create skill from detected command (US3)
# ---------------------------------------------------------------------------


def auto_create_skill(
    kb_root: Path,
    name: str,
    command: str,
    description: str,
) -> Path:
    """Create a skill directory from a detected command line.

    Generates a SKILL.md and scripts/run.sh that executes the given command.
    Detects {placeholder} patterns in the command and converts them to
    SKILL_PARAM_* environment variables.

    Args:
        kb_root: Root directory of the knowledge base.
        name: Skill name (validated).
        command: Shell command to wrap (may contain {param} placeholders).
        description: One-sentence description.

    Returns:
        Path to created skill directory.
    """
    validate_skill_name(name)
    skill_dir = get_skill_dir(kb_root, name)
    if skill_dir.exists():
        raise ValueError(f"Skill '{name}' already exists.")

    # Detect {placeholder} patterns and replace with friendly $VAR names.
    # Friendly name: HOST, PORT, etc. (uppercased, hyphens→underscores)
    # SKILL_PARAM_* env vars are read into these friendly names in the script.
    param_names = re.findall(r"\{([^}]+)\}", command)
    shell_cmd = command
    for p in param_names:
        friendly = p.upper().replace("-", "_").replace(" ", "_")
        shell_cmd = shell_cmd.replace(f"{{{p}}}", f"${{{friendly}}}")

    # Build SKILL.md frontmatter.
    params_yaml = ""
    if param_names:
        lines = ["params:"]
        for p in param_names:
            lines.append(f"  - name: {p}")
            lines.append(f"    description: {p}")
            lines.append(f"    required: false")
            lines.append(f"    default: \"\"")
        params_yaml = "\n" + "\n".join(lines)

    skill_md_content = f"""\
---
name: {name}
description: {description}
version: 1.0.0
platforms: linux,macos
timeout: 30{params_yaml}
---

# {name}

## When to Use

{description}

## Quick Reference

```bash
{command}
```
"""

    run_sh_content = f"""\
#!/usr/bin/env bash
# Auto-generated skill: {name}
# {description}

set -euo pipefail

{chr(10).join(f'{p.upper().replace("-", "_").replace(" ", "_")}="${{SKILL_PARAM_{p.upper().replace("-", "_").replace(" ", "_")}:-}}"' for p in param_names) if param_names else "# No parameters"}

{shell_cmd}
"""

    skill_dir.mkdir(parents=True)
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
    run_sh_path = scripts_dir / "run.sh"
    run_sh_path.write_text(run_sh_content, encoding="utf-8")
    run_sh_path.chmod(0o755)

    return skill_dir
