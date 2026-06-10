"""Skill usage record — per-skill sidecar (.skill_usage.json).

Each skill directory may contain a ``.skill_usage.json`` file that tracks
lifecycle metadata: creation time, agent-creation flag, usage and patch
counts, and optional absorbed_into tombstone on deletion.

All writes are atomic via atomic_write() so the file is always either the
old complete version or the new complete version.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from holmes.kb.atomic import atomic_write

USAGE_FILENAME = ".skill_usage.json"


@dataclass
class SkillUsageRecord:
    """Lifecycle metadata for a single skill (data-model.md Entity 3).

    Attributes:
        created_at: ISO-8601 timestamp when the skill was created.
        agent_created: True if created by the import agent (not manually).
        use_count: Number of times the skill has been run.
        last_used_at: ISO-8601 timestamp of last run, or None.
        patch_count: Number of times SKILL.md has been patched.
        last_patched_at: ISO-8601 timestamp of last patch, or None.
        absorbed_into: Name of skill this was merged into on deletion, or None.
    """

    created_at: str
    agent_created: bool = False
    use_count: int = 0
    last_used_at: Optional[str] = None
    patch_count: int = 0
    last_patched_at: Optional[str] = None
    absorbed_into: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_record() -> SkillUsageRecord:
    return SkillUsageRecord(created_at=_now_iso())


def read_usage(skill_dir: Path) -> SkillUsageRecord:
    """Read the skill usage record from ``skill_dir/.skill_usage.json``.

    If the file does not exist, returns a default record with all counts at
    zero and ``agent_created=False``.

    Args:
        skill_dir: Path to the skill directory.

    Returns:
        SkillUsageRecord populated from file, or a default record.
    """
    path = skill_dir / USAGE_FILENAME
    if not path.exists():
        return _default_record()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_record()
    return SkillUsageRecord(
        created_at=data.get("created_at", _now_iso()),
        agent_created=bool(data.get("agent_created", False)),
        use_count=int(data.get("use_count", 0)),
        last_used_at=data.get("last_used_at"),
        patch_count=int(data.get("patch_count", 0)),
        last_patched_at=data.get("last_patched_at"),
        absorbed_into=data.get("absorbed_into"),
    )


def write_usage(skill_dir: Path, record: SkillUsageRecord) -> None:
    """Write the skill usage record atomically to ``skill_dir/.skill_usage.json``.

    Args:
        skill_dir: Path to the skill directory.
        record: SkillUsageRecord to persist.
    """
    path = skill_dir / USAGE_FILENAME
    atomic_write(path, json.dumps(asdict(record), indent=2))


def bump_use(skill_dir: Path) -> SkillUsageRecord:
    """Increment use_count and update last_used_at; returns updated record.

    Args:
        skill_dir: Path to the skill directory.

    Returns:
        Updated SkillUsageRecord after write.
    """
    record = read_usage(skill_dir)
    record.use_count += 1
    record.last_used_at = _now_iso()
    write_usage(skill_dir, record)
    return record


def bump_patch(skill_dir: Path) -> SkillUsageRecord:
    """Increment patch_count and update last_patched_at; returns updated record.

    Args:
        skill_dir: Path to the skill directory.

    Returns:
        Updated SkillUsageRecord after write.
    """
    record = read_usage(skill_dir)
    record.patch_count += 1
    record.last_patched_at = _now_iso()
    write_usage(skill_dir, record)
    return record


def mark_agent_created(skill_dir: Path) -> SkillUsageRecord:
    """Set agent_created=True on an existing or new usage record.

    Preserves all other fields.  Idempotent.

    Args:
        skill_dir: Path to the skill directory.

    Returns:
        Updated SkillUsageRecord after write.
    """
    record = read_usage(skill_dir)
    record.agent_created = True
    write_usage(skill_dir, record)
    return record


def set_absorbed_into(skill_dir: Path, absorbed_into: str) -> SkillUsageRecord:
    """Record that this skill was merged into another skill (tombstone).

    The skill directory is not deleted here; callers handle deletion
    separately so the tombstone record persists for auditability.

    Args:
        skill_dir: Path to the skill directory.
        absorbed_into: Name of the target skill.

    Returns:
        Updated SkillUsageRecord after write.
    """
    record = read_usage(skill_dir)
    record.absorbed_into = absorbed_into
    write_usage(skill_dir, record)
    return record
