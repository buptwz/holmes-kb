"""Skill manager for Holmes Agent.

Scans ~/.holmes/skills/*.md for skill definitions.
Skills are Markdown files with a YAML frontmatter header containing:
  name: skill-name
  description: Short description

The file body is the skill execution prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import frontmatter

from holmes.logging_config import get_logger


logger = get_logger("agent.skill_manager")

SKILLS_DIR = Path.home() / ".holmes" / "skills"


@dataclass
class Skill:
    """A loaded skill definition."""

    name: str
    description: str
    prompt: str
    source_path: Path


class SkillManager:
    """Loads and provides access to skill definitions from ~/.holmes/skills/."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._skills_dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        self._loaded = False

    def load_skills(self) -> None:
        """Scan the skills directory and load all .md skill files."""
        self._skills.clear()
        if not self._skills_dir.exists():
            logger.debug("Skills directory %s does not exist", self._skills_dir)
            return

        for path in sorted(self._skills_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                name = str(post.metadata.get("name", path.stem))
                description = str(post.metadata.get("description", ""))
                skill = Skill(
                    name=name,
                    description=description,
                    prompt=post.content,
                    source_path=path,
                )
                self._skills[name] = skill
                logger.debug("Loaded skill: %s from %s", name, path)
            except Exception as e:
                logger.warning("Could not load skill from %s: %s", path, e)

        self._loaded = True
        logger.info("Loaded %d skills from %s", len(self._skills), self._skills_dir)

    def list_skills(self) -> list[Skill]:
        """Return all loaded skills.

        Returns:
            List of Skill objects sorted by name.
        """
        if not self._loaded:
            self.load_skills()
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: Skill name to look up.

        Returns:
            Skill if found, None otherwise.
        """
        if not self._loaded:
            self.load_skills()
        return self._skills.get(name)
