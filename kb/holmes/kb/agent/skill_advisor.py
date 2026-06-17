"""Skill generation advisor — evaluates whether a KB entry warrants a skill (US5 / FR-010-011).

SkillAdvisor implements the Anthropic Agent Skills criteria:

  RECOMMENDED  : Entry has non-empty Resolution content (agent instruction body)
  LINK         : Entry already has skill_refs (existing skill covers it)
  SKIP         : No Resolution content
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import frontmatter as fm

from holmes.kb.skill.markers import extract_skill_markers
from holmes.kb.store import list_entries

# Regex to detect {parameter} placeholders.
_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")

# Stopwords excluded from Jaccard similarity computation.
_SIMPLE_STOPWORDS: frozenset[str] = frozenset(
    {"the", "a", "an", "for", "of", "in", "on", "at", "to", "and", "or", "is",
     "be", "with", "this", "that", "it", "by", "from", "as", "are", "was"}
)


class Recommendation(Enum):
    """Skill generation recommendation."""

    RECOMMENDED = "RECOMMENDED"  # Create skill and prompt user (if interactive)
    LINK = "LINK"                # Link to existing skill, do not create
    SKIP = "SKIP"                # No Resolution content


@dataclass
class SkillAdvice:
    """Output of SkillAdvisor.advise().

    Attributes:
        recommendation: The generated recommendation.
        suggested_name: Suggested skill slug, or empty string.
        reason: Human-readable reasoning.
        existing_skill: Existing skill name if recommendation is LINK, else None.
        form: FR-3 — "A" (whole-entry skill) or "B" (per-step skills).
        step_skills: FR-3 — Form B step skill list.
            Each entry: {step_heading, skill_name, content}.
    """

    recommendation: Recommendation
    suggested_name: str = ""
    reason: str = ""
    existing_skill: Optional[str] = None
    form: str = "A"
    step_skills: list = field(default_factory=list)


class SkillAdvisor:
    """Evaluate skill generation value for a KB entry (FR-010, FR-011).

    Usage::

        advisor = SkillAdvisor()
        advice = advisor.advise(entry_id="PT-DB-001",
                                resolution_text="...",
                                kb_root=kb_root)
        if advice.recommendation == Recommendation.RECOMMENDED:
            ...
    """

    def advise(
        self,
        entry_id: str,
        resolution_text: str,
        kb_root: Path,
        description: str = "",
    ) -> SkillAdvice:
        """Evaluate whether ``entry_id``'s resolution warrants skill creation.

        Args:
            entry_id: KB entry ID (used to check existing skill_refs).
            resolution_text: The ## Resolution section body.
            kb_root: Root directory of the knowledge base.
            description: Optional proposed skill description (used for LINK check).

        Returns:
            SkillAdvice with recommendation and reasoning.
        """
        # Step 1: check if entry already has skill_refs → LINK.
        existing_skill = self._find_existing_skill(entry_id, kb_root)
        if existing_skill:
            return SkillAdvice(
                recommendation=Recommendation.LINK,
                suggested_name=existing_skill,
                reason=f"Entry already linked to skill: {existing_skill}",
                existing_skill=existing_skill,
            )

        # Step 1b: E-11 fix (018): check for existing skill by description similarity → LINK.
        if description:
            similar = self._find_similar_skill(kb_root, description)
            if similar:
                return SkillAdvice(
                    recommendation=Recommendation.LINK,
                    suggested_name=similar,
                    reason=f"similar skill found: {similar}",
                    existing_skill=similar,
                )

        # No Resolution content → SKIP.
        if not resolution_text.strip():
            return SkillAdvice(
                recommendation=Recommendation.SKIP,
                reason="No Resolution content",
            )

        # FR-3: check for skill markers → Form B (per-step skills).
        markers = extract_skill_markers(resolution_text)
        if markers:
            # Deduplicate by skill_name while preserving first occurrence order.
            seen: set[str] = set()
            step_skills = []
            for mk in markers:
                if mk["skill_name"] in seen:
                    continue
                seen.add(mk["skill_name"])
                step_skills.append({
                    "step_heading": mk["step_heading"],
                    "skill_name": mk["skill_name"],
                    "content": self._extract_step_content(
                        resolution_text, mk["step_heading"], mk["line"]
                    ),
                })
            return SkillAdvice(
                recommendation=Recommendation.RECOMMENDED,
                suggested_name=step_skills[0]["skill_name"] if step_skills else "",
                reason=f"Resolution has {len(step_skills)} skill marker(s) — Form B per-step skills",
                form="B",
                step_skills=step_skills,
            )

        # FR-3: auto-split when resolution is very large and branching (Form B).
        if _count_steps(resolution_text) > 10 and _count_parallel_branches(resolution_text) >= 3:
            return SkillAdvice(
                recommendation=Recommendation.RECOMMENDED,
                suggested_name=self._make_slug(entry_id),
                reason=(
                    f"Resolution has >{_count_steps(resolution_text)} steps and "
                    f">={_count_parallel_branches(resolution_text)} branches — auto Form B"
                ),
                form="B",
                step_skills=[],  # caller extracts branches via _extract_branches()
            )

        # Form A: whole Resolution → single skill.
        slug = self._make_slug(entry_id, title=description)
        # Dedup: append -2, -3, ... if the name is already taken.
        suggested_name = slug
        counter = 2
        while (kb_root / "skills" / suggested_name).is_dir():
            suggested_name = f"{slug}-{counter}"
            counter += 1
        return SkillAdvice(
            recommendation=Recommendation.RECOMMENDED,
            suggested_name=suggested_name,
            reason="Entry has Resolution content — agent instruction skill (Form A)",
            form="A",
        )

    def _find_existing_skill(self, entry_id: str, kb_root: Path) -> Optional[str]:
        """Return the first skill_ref from the entry's frontmatter, if any."""
        if not entry_id:
            return None
        for entry_meta in list_entries(kb_root):
            if entry_meta.id.upper() != entry_id.upper():
                continue
            file_path = Path(entry_meta.file_path)
            if not file_path.exists():
                return None
            try:
                post = fm.load(str(file_path))
                skill_refs = list(post.metadata.get("skill_refs") or [])
                if skill_refs:
                    return str(skill_refs[0])
            except Exception:  # noqa: BLE001
                pass
            return None
        return None

    def _find_similar_skill(self, kb_root: Path, description: str) -> Optional[str]:
        """Return a skill name if an existing skill's description is highly similar.

        Uses Jaccard token overlap (≥ 0.7 ratio) to detect near-duplicate skills.
        Returns None if no similar skill found or skills/ directory doesn't exist.
        """
        skills_dir = kb_root / "skills"
        if not skills_dir.is_dir():
            return None

        def _tokens(text: str) -> set[str]:
            return {
                t.lower() for t in re.split(r"[\W_]+", text)
                if len(t) >= 2 and t.lower() not in _SIMPLE_STOPWORDS
            }

        desc_tokens = _tokens(description)
        if not desc_tokens:
            return None

        for skill_md_path in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                post = fm.load(str(skill_md_path))
                existing_desc = str(post.metadata.get("description", ""))
                if not existing_desc:
                    continue
                existing_tokens = _tokens(existing_desc)
                if not existing_tokens:
                    continue
                union = desc_tokens | existing_tokens
                intersection = desc_tokens & existing_tokens
                ratio = len(intersection) / len(union)
                if ratio >= 0.7:
                    return skill_md_path.parent.name
            except Exception:  # noqa: BLE001
                pass
        return None

    @staticmethod
    def _make_slug(entry_id: str, title: str = "") -> str:
        """Generate a skill slug from title (preferred) or entry ID."""
        if title:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            slug = re.sub(r"-{2,}", "-", slug)[:40]
            if len(slug) >= 3:
                return slug
        if not entry_id:
            return "agent-skill"
        slug = re.sub(r"[^a-z0-9]", "", entry_id.lower())[:20]
        return f"skill-{slug}" if slug else "agent-skill"

    @staticmethod
    def _extract_step_content(resolution_text: str, step_heading: str, marker_line: int) -> str:
        """Extract Markdown content of the step section that contains the marker.

        Finds the nearest preceding heading before marker_line, then returns
        text from that heading to the next same-or-higher-level heading (or EOF).
        """
        if not step_heading:
            return ""
        lines = resolution_text.splitlines()
        # Find the heading line index.
        heading_idx = None
        for idx, line in enumerate(lines):
            if line.strip() == step_heading.strip():
                heading_idx = idx
                break
        if heading_idx is None:
            return ""
        # Determine heading level from the number of leading '#'.
        level = len(step_heading) - len(step_heading.lstrip("#"))
        # Collect lines until the next heading of the same or higher level.
        content_lines = [lines[heading_idx]]
        for line in lines[heading_idx + 1:]:
            m = re.match(r"^(#{2,})\s", line)
            if m and len(m.group(1)) <= level:
                break
            content_lines.append(line)
        return "\n".join(content_lines).strip()


# ---------------------------------------------------------------------------
# Module-level helpers (T021) — used by SkillAdvisor.advise()
# ---------------------------------------------------------------------------

# Patterns for step numbering.
_STEP_RE = re.compile(
    r"^(?:\d+\.|Step\s+\d+|步骤\s*\d+)\s",
    re.MULTILINE | re.IGNORECASE,
)

# Patterns for parallel branch identification.
_BRANCH_RE = re.compile(
    r"(?:"
    r"Step\s+\d+[A-Z]\b"          # Step 3A, Step 5B
    r"|分支\s*[A-Z\d]"             # 分支A, 分支1
    r"|[若如当].{1,20}[则就]"       # 若...则..., 如...就...
    r")",
    re.MULTILINE,
)


def _count_steps(resolution_text: str) -> int:
    """Count numbered/labelled steps in a Resolution section."""
    return len(_STEP_RE.findall(resolution_text))


def _count_parallel_branches(resolution_text: str) -> int:
    """Count distinct parallel branch indicators in a Resolution section."""
    return len(_BRANCH_RE.findall(resolution_text))
