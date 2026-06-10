"""Incremental skill curation — identify quality improvement candidates (US5 / FR-014-015).

SkillCurator scans agent-created skills in a given category and reports
three types of findings:

  merge_candidate   : Two skills with description word-set Jaccard similarity > threshold
  oversized         : SKILL.md body exceeds 3,000 characters
  update_candidate  : skill has patch_count=0 and a linked KB entry was updated
                      after the skill was created

All findings are advisory only (FR-015) — they are appended to the
ImportReport for the user or a future curator agent to act upon.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter as fm

from holmes.kb.agent.report import CuratorFinding
from holmes.kb.skill.usage import read_usage
from holmes.kb.store import list_entries

# ---------------------------------------------------------------------------
# Thresholds (wired as module-level constants, not hidden in code)
# ---------------------------------------------------------------------------

MERGE_JACCARD_THRESHOLD: float = 0.6
OVERSIZED_BODY_THRESHOLD: int = 3_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _word_set(text: str) -> set[str]:
    """Return lowercase word tokens for Jaccard calculation."""
    import re
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Curator
# ---------------------------------------------------------------------------


class SkillCurator:
    """Scan agent-created skills and return incremental quality findings.

    Usage::

        curator = SkillCurator()
        findings = curator.curate(kb_root, category="database")
        for f in findings:
            print(f)
    """

    def curate(
        self,
        kb_root: Path,
        category: Optional[str] = None,
    ) -> list[CuratorFinding]:
        """Run all curation checks and return findings.

        Args:
            kb_root: Root directory of the knowledge base.
            category: Optional category filter (e.g., "database").
                      If None, all agent-created skills are checked.

        Returns:
            List of CuratorFinding items (may be empty).
        """
        skills = self._load_agent_skills(kb_root)
        if not skills:
            return []

        findings: list[CuratorFinding] = []
        findings.extend(self._check_oversized(skills))
        findings.extend(self._check_merge_candidates(skills))
        findings.extend(self._check_update_candidates(skills, kb_root))
        return findings

    # ------------------------------------------------------------------
    # Skill loading
    # ------------------------------------------------------------------

    def _load_agent_skills(self, kb_root: Path) -> list[dict]:
        """Load metadata for all agent-created skills."""
        skills_dir = kb_root / "skills"
        if not skills_dir.is_dir():
            return []

        skills = []
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            usage = read_usage(skill_dir)
            if not usage.agent_created:
                continue  # Only curate agent-created skills.

            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue

            description = skill_dir.name
            body = ""
            try:
                post = fm.load(str(skill_md_path))
                description = str(post.metadata.get("description", skill_dir.name))
                body = post.content or ""
            except Exception:  # noqa: BLE001
                pass

            skills.append({
                "name": skill_dir.name,
                "skill_dir": skill_dir,
                "description": description,
                "body": body,
                "usage": usage,
            })
        return skills

    # ------------------------------------------------------------------
    # Check: oversized
    # ------------------------------------------------------------------

    def _check_oversized(self, skills: list[dict]) -> list[CuratorFinding]:
        findings = []
        for skill in skills:
            body_len = len(skill["body"])
            if body_len > OVERSIZED_BODY_THRESHOLD:
                findings.append(CuratorFinding(
                    finding_type="oversized",
                    skill_names=[skill["name"]],
                    reason=f"SKILL.md body is {body_len:,} chars (limit: {OVERSIZED_BODY_THRESHOLD:,})",
                ))
        return findings

    # ------------------------------------------------------------------
    # Check: merge candidates
    # ------------------------------------------------------------------

    def _check_merge_candidates(self, skills: list[dict]) -> list[CuratorFinding]:
        findings = []
        n = len(skills)
        reported: set[frozenset] = set()

        for i in range(n):
            for j in range(i + 1, n):
                a, b = skills[i], skills[j]
                pair = frozenset([a["name"], b["name"]])
                if pair in reported:
                    continue
                words_a = _word_set(a["description"])
                words_b = _word_set(b["description"])
                score = _jaccard(words_a, words_b)
                if score >= MERGE_JACCARD_THRESHOLD:
                    findings.append(CuratorFinding(
                        finding_type="merge_candidate",
                        skill_names=[a["name"], b["name"]],
                        reason=f"Description Jaccard {score:.2f} (threshold {MERGE_JACCARD_THRESHOLD})",
                        confidence=score,
                    ))
                    reported.add(pair)
        return findings

    # ------------------------------------------------------------------
    # Check: update candidates
    # ------------------------------------------------------------------

    def _check_update_candidates(
        self, skills: list[dict], kb_root: Path
    ) -> list[CuratorFinding]:
        """Find skills whose patch_count is 0 and a linked entry was updated after creation."""
        findings = []
        for skill in skills:
            usage = skill["usage"]
            if usage.patch_count != 0:
                continue  # Already patched — skip.

            skill_created = _parse_iso(usage.created_at)
            if skill_created is None:
                continue

            # Scan KB entries that link to this skill.
            linked_entry_updated = self._find_linked_entry_updated_after(
                kb_root, skill["name"], skill_created
            )
            if linked_entry_updated:
                findings.append(CuratorFinding(
                    finding_type="update_candidate",
                    skill_names=[skill["name"]],
                    reason=(
                        f"patch_count=0; linked entry updated "
                        f"{linked_entry_updated} (after skill created {skill_created.date()})"
                    ),
                ))
        return findings

    def _find_linked_entry_updated_after(
        self, kb_root: Path, skill_name: str, skill_created: datetime
    ) -> Optional[str]:
        """Return the updated_at string of a linked entry updated after skill_created."""
        for entry_meta in list_entries(kb_root):
            file_path = Path(entry_meta.file_path)
            if not file_path.exists():
                continue
            try:
                post = fm.load(str(file_path))
                skill_refs = list(post.metadata.get("skill_refs") or [])
                if skill_name not in skill_refs:
                    continue
                updated_at = str(post.metadata.get("updated_at", ""))
                entry_updated = _parse_iso(updated_at)
                if entry_updated and entry_updated > skill_created:
                    return updated_at
            except Exception:  # noqa: BLE001
                pass
        return None
