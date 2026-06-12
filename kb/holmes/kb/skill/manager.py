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

# Allowed frontmatter keys per Anthropic Agent Skills standard.
ALLOWED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
)

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
# SKILL.md validator
# ---------------------------------------------------------------------------


def validate_skill_md(path: Path) -> tuple[bool, str]:
    """Validate a SKILL.md file against the Anthropic Agent Skills standard.

    Rules:
    - Frontmatter must be present and parseable.
    - ``name`` and ``description`` are required fields.
    - Only these keys are allowed: name, description, license, allowed-tools,
      metadata, compatibility.
    - ``name`` must be ≤64 characters and kebab-case.
    - ``description`` must be ≤1024 characters and contain no angle brackets.

    Returns:
        ``(True, "")`` when valid.
        ``(False, "<error description>")`` when invalid.
    """
    if not path.exists():
        return False, f"SKILL.md not found: {path}"

    raw = path.read_text(encoding="utf-8")
    try:
        post = frontmatter.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to parse frontmatter: {exc}"

    meta = post.metadata

    # Required fields.
    if "name" not in meta:
        return False, "Missing required field: name"
    if "description" not in meta:
        return False, "Missing required field: description"

    # Unexpected keys.
    unexpected = set(meta.keys()) - ALLOWED_FRONTMATTER_KEYS
    if unexpected:
        allowed_str = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        unexpected_str = ", ".join(sorted(unexpected))
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {unexpected_str}. "
            f"Allowed: {allowed_str}"
        )

    # Validate name format.
    name = str(meta["name"])
    if len(name) > SKILL_NAME_MAX:
        return False, f"name must be ≤{SKILL_NAME_MAX} characters, got {len(name)}"
    try:
        validate_skill_name(name)
    except ValueError as exc:
        return False, f"Invalid name: {exc}"

    # Validate description.
    description = str(meta["description"])
    if len(description) > 1024:
        return False, f"description must be ≤1024 characters, got {len(description)}"
    if "<" in description or ">" in description:
        return False, "description must not contain angle brackets (< or >)"

    return True, ""


# ---------------------------------------------------------------------------
# SKILL.md parser
# ---------------------------------------------------------------------------


@dataclass
class SkillDefinition:
    """Parsed representation of a SKILL.md file (Anthropic Agent Skills format)."""

    name: str
    description: str = ""
    content: str = ""  # full raw SKILL.md text


def parse_skill_md(path: Path) -> SkillDefinition:
    """Parse a SKILL.md file and return a SkillDefinition.

    Backward-compatible: extra frontmatter keys (e.g. version, platforms) are
    silently ignored; only name and description are extracted.

    Args:
        path: Absolute path to SKILL.md.

    Returns:
        SkillDefinition with name, description, and full raw content.

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
    return SkillDefinition(
        name=str(meta.get("name", path.parent.name)),
        description=str(meta.get("description", "")),
        content=raw,
    )


# ---------------------------------------------------------------------------
# Skill creation
# ---------------------------------------------------------------------------


def create_skill(
    kb_root: Path,
    name: str,
    description: str,
    instructions: str = "",
) -> Path:
    """Create a new skill directory with a SKILL.md agent instruction file.

    Creates the skill directory and SKILL.md only.  Optional subdirectories
    (``scripts/``, ``references/``, ``assets/``) can be added freely by the
    agent or user as needed — no restrictions on skill structure per the
    Anthropic Agent Skills standard.

    Args:
        kb_root: Root directory of the knowledge base.
        name: Skill name (kebab-case, validated).
        description: Trigger description (≤1024 chars, no angle brackets).
        instructions: Markdown body for the SKILL.md.  If empty, a default
                      three-section placeholder is written.

    Returns:
        Path to the created skill directory.

    Raises:
        ValueError: if name is invalid or skill already exists.
    """
    from holmes.kb.skill.template import generate_skill_template

    validate_skill_name(name)
    skill_dir = get_skill_dir(kb_root, name)
    if skill_dir.exists():
        raise ValueError(f"Skill '{name}' already exists.")

    skill_dir.mkdir(parents=True)

    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(
        generate_skill_template(name, description, instructions), encoding="utf-8"
    )

    return skill_dir


# ---------------------------------------------------------------------------
# Link / unlink
# ---------------------------------------------------------------------------


def _find_entry_path(kb_root: Path, entry_id: str) -> Optional[Path]:
    """Find the filesystem path for a KB entry by scanning known type directories and pending."""
    search_dirs = [kb_root / t for t in ("pitfall", "model", "guideline", "process", "decision")]
    # Also scan contributions/pending/ so link_skill works for newly-imported entries.
    pending_dir = kb_root / "contributions" / "pending"
    if pending_dir.is_dir():
        search_dirs.append(pending_dir)
    for search_dir in search_dirs:
        for md_file in search_dir.rglob("*.md") if search_dir.is_dir() else []:
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
        raise FileNotFoundError(f"Skill '{skill_name}' not found in skills/ directory.")

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
            linked_entries=linked.get(name, []),
        ))

    return results


# ---------------------------------------------------------------------------
# Command detection (for skill advisor — counting only)
# ---------------------------------------------------------------------------


@dataclass
class CommandCandidate:
    """A detected command candidate for skill generation decisions."""

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

    Used for counting only: ≥3 commands → RECOMMENDED, 1-2 → informational, 0 → SKIP.
    Results are NOT used to generate run.sh scripts.

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
