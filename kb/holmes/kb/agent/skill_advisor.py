"""Skill generation advisor — evaluates whether a KB entry warrants a skill (US5 / FR-010-011).

SkillAdvisor implements the deterministic criteria from research.md R-007:

  RECOMMENDED  : ≥3 distinct command steps detected
  OPTIONAL     : 1-2 command steps detected (single-step command)
  LINK         : Entry already has skill_refs (existing skill covers it)
  SKIP         : No shell commands detected in resolution text
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import frontmatter as fm

from holmes.kb.skill.manager import detect_commands
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
    OPTIONAL = "OPTIONAL"        # Skip silently, add suggestion to report
    LINK = "LINK"                # Link to existing skill, do not create
    SKIP = "SKIP"                # No skill value detected


@dataclass
class SkillAdvice:
    """Output of SkillAdvisor.advise().

    Attributes:
        recommendation: The generated recommendation.
        suggested_name: Suggested skill slug, or empty string.
        reason: Human-readable reasoning.
        existing_skill: Existing skill name if recommendation is LINK, else None.
    """

    recommendation: Recommendation
    suggested_name: str = ""
    reason: str = ""
    existing_skill: Optional[str] = None


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

        # Step 2: count command steps via existing detect_commands().
        commands = detect_commands(resolution_text)
        step_count = len(commands)
        has_placeholder = bool(_PLACEHOLDER_RE.search(resolution_text))

        # Step 3: apply criteria (R-007).
        # E-8 fix: threshold restored to ≥3; 1-2 steps → OPTIONAL (no auto-create).
        if step_count >= 3:
            reason = (
                f"{step_count} steps detected"
                + (" + parameter placeholders" if has_placeholder else "")
            )
            slug = self._make_slug(entry_id)
            return SkillAdvice(
                recommendation=Recommendation.RECOMMENDED,
                suggested_name=slug,
                reason=reason,
            )
        elif step_count >= 1:
            slug = self._make_slug(entry_id)
            return SkillAdvice(
                recommendation=Recommendation.OPTIONAL,
                suggested_name=slug,
                reason=f"{step_count} step(s) detected — single/few-step command",
            )
        else:
            return SkillAdvice(
                recommendation=Recommendation.SKIP,
                reason="No shell commands detected in Resolution",
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
    def _make_slug(entry_id: str) -> str:
        """Generate a skill slug from an entry ID (e.g. PT-DB-001 → skill-ptdb001)."""
        if not entry_id:
            return "agent-skill"
        slug = re.sub(r"[^a-z0-9]", "", entry_id.lower())[:20]
        return f"skill-{slug}" if slug else "agent-skill"
