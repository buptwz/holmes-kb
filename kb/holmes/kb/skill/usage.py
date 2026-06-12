"""Skill usage record — per-skill sidecar (.skill_usage.json).

Each skill directory may contain a ``.skill_usage.json`` file that tracks
lifecycle metadata: creation time, agent-creation flag, usage and patch
counts, and optional absorbed_into tombstone on deletion.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

USAGE_FILENAME = ".skill_usage.json"


@dataclass
class SkillUsageRecord:
    """Lifecycle metadata for a single skill."""

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
    """Read the skill usage record; returns default if file absent."""
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
    """Write the skill usage record to ``skill_dir/.skill_usage.json``."""
    path = skill_dir / USAGE_FILENAME
    path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")


def bump_use(skill_dir: Path) -> SkillUsageRecord:
    """Increment use_count and update last_used_at."""
    record = read_usage(skill_dir)
    record.use_count += 1
    record.last_used_at = _now_iso()
    write_usage(skill_dir, record)
    return record


def bump_patch(skill_dir: Path) -> SkillUsageRecord:
    """Increment patch_count and update last_patched_at."""
    record = read_usage(skill_dir)
    record.patch_count += 1
    record.last_patched_at = _now_iso()
    write_usage(skill_dir, record)
    return record


def mark_agent_created(skill_dir: Path) -> SkillUsageRecord:
    """Set agent_created=True on an existing or new usage record (idempotent)."""
    record = read_usage(skill_dir)
    record.agent_created = True
    write_usage(skill_dir, record)
    return record


def set_absorbed_into(skill_dir: Path, absorbed_into: str) -> SkillUsageRecord:
    """Record that this skill was merged into another skill (tombstone)."""
    record = read_usage(skill_dir)
    record.absorbed_into = absorbed_into
    write_usage(skill_dir, record)
    return record
