"""SkillExecutor — general-purpose skill invocation engine.

Provides the ability to load and execute any Holmes KB skill (or any
Anthropic Agent Skill on the local filesystem) by reading its SKILL.md
and invoking an LLM with the skill's instructions as the system prompt.

Usage:
    executor = SkillExecutor(provider, kb_root=kb_root, extra_roots=[...])

    # List all available skills
    skills = executor.list_available()

    # Read a skill's SKILL.md
    md = executor.get_skill_md("skill-creator")

    # Execute a skill
    result = executor.invoke("skill-creator", task="Write a SKILL.md for ...",
                             context="...", max_tokens=2048)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import frontmatter

from holmes.kb.agent.provider.base import LLMProvider


class SkillNotFoundError(FileNotFoundError):
    """Raised when a skill cannot be located in any search root."""


class SkillInfo:
    """Lightweight metadata parsed from a skill's SKILL.md frontmatter."""

    def __init__(self, name: str, description: str, path: Path) -> None:
        self.name = name
        self.description = description
        self.path = path  # Path to the SKILL.md file

    def __repr__(self) -> str:
        return f"SkillInfo(name={self.name!r})"


class SkillExecutor:
    """Load and execute skills from the local filesystem via LLM.

    Skills are searched in this order:
      1. ``kb_root / "skills"``          — KB's own generated skills
      2. Each path in ``extra_roots``    — caller-supplied additional roots
      3. ``~/project/skills/skills``     — dev convention (Anthropic dev layout)

    Each root is expected to contain one subdirectory per skill, each with
    a ``SKILL.md`` file (Anthropic Agent Skills format).

    Args:
        provider: LLMProvider instance for making LLM calls.
        kb_root: KB root directory. Its ``skills/`` subdirectory is always
                 searched first. Pass ``None`` to skip.
        extra_roots: Additional skill root directories to search (in order).
    """

    def __init__(
        self,
        provider: LLMProvider,
        kb_root: Optional[Path] = None,
        extra_roots: Optional[list[Path]] = None,
    ) -> None:
        self._provider = provider
        self._search_roots: list[Path] = []

        if kb_root is not None:
            self._search_roots.append(kb_root / "skills")
        if extra_roots:
            self._search_roots.extend(extra_roots)
        # Dev convention: ~/project/skills/skills
        dev_root = Path.home() / "project" / "skills" / "skills"
        if dev_root not in self._search_roots:
            self._search_roots.append(dev_root)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_available(self) -> list[SkillInfo]:
        """Return metadata for every skill found across all search roots.

        Deduplicates by name — first occurrence (highest-priority root) wins.
        """
        seen: set[str] = set()
        skills: list[SkillInfo] = []
        for root in self._search_roots:
            if not root.is_dir():
                continue
            for skill_dir in sorted(root.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    post = frontmatter.load(str(skill_md))
                    name = str(post.metadata.get("name", skill_dir.name)).strip()
                    description = str(post.metadata.get("description", "")).strip()
                except Exception:  # noqa: BLE001
                    name = skill_dir.name
                    description = ""
                if name in seen:
                    continue
                seen.add(name)
                skills.append(SkillInfo(name=name, description=description, path=skill_md))
        return skills

    def get_skill_md(self, skill_name: str) -> str:
        """Return the full SKILL.md text for a named skill.

        Args:
            skill_name: Skill directory name or ``name`` frontmatter field.

        Returns:
            Full SKILL.md content as a string.

        Raises:
            SkillNotFoundError: If the skill cannot be found in any root.
        """
        path = self._find_skill_path(skill_name)
        return path.read_text(encoding="utf-8")

    def _find_skill_path(self, skill_name: str) -> Path:
        """Locate SKILL.md for the given skill name.

        Matches against both the directory name and the ``name`` frontmatter
        field so that skills installed under a different directory name still
        resolve correctly.
        """
        for root in self._search_roots:
            # Fast path: directory name matches.
            candidate = root / skill_name / "SKILL.md"
            if candidate.exists():
                return candidate
            # Slow path: scan and match by frontmatter name field.
            if not root.is_dir():
                continue
            for skill_dir in root.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    post = frontmatter.load(str(skill_md))
                    if str(post.metadata.get("name", "")).strip() == skill_name:
                        return skill_md
                except Exception:  # noqa: BLE001
                    pass
        raise SkillNotFoundError(
            f"Skill '{skill_name}' not found. "
            f"Searched: {[str(r) for r in self._search_roots]}"
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def invoke(
        self,
        skill_name: str,
        task: str,
        context: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Execute a skill: load its SKILL.md and call LLM with its instructions.

        The skill's SKILL.md body (frontmatter stripped) becomes the system
        prompt. ``task`` and ``context`` form the user message.

        Follows the Anthropic Agent Skills convention:
        - ``${CLAUDE_SKILL_DIR}`` in the body is replaced with the real path.
        - ``Base directory for this skill: <path>`` is prepended to the system
          prompt so the LLM can reference scripts/, references/, assets/ via
          filesystem tools at runtime.

        Args:
            skill_name: Skill to invoke (directory name or frontmatter name).
            task: Primary instruction for this invocation.
            context: Optional additional context appended to the user message.
            max_tokens: Maximum LLM response tokens (default 2048).

        Returns:
            Raw LLM response text.

        Raises:
            SkillNotFoundError: If the skill cannot be found.
        """
        skill_md_path = self._find_skill_path(skill_name)
        skill_dir = str(skill_md_path.parent)
        skill_md_text = skill_md_path.read_text(encoding="utf-8")

        body = self._extract_body(skill_md_text)
        # Substitute ${CLAUDE_SKILL_DIR} so skill bodies can reference subdirs.
        body = body.replace("${CLAUDE_SKILL_DIR}", skill_dir)
        # Prepend base-directory hint so LLM can access scripts/, references/, assets/.
        system_prompt = f"Base directory for this skill: {skill_dir}\n\n{body}"

        user_content = f"{task}\n\n{context}".strip() if context else task

        return self._provider.simple_complete(
            messages=[{"role": "user", "content": user_content}],
            system=system_prompt,
            max_tokens=max_tokens,
        )

    def get_allowed_tools(self, skill_name: str) -> list[str]:
        """Return the ``allowed-tools`` list from a skill's frontmatter, or [].

        Skills may declare which tools they need via the ``allowed-tools``
        frontmatter key (Anthropic Agent Skills convention).  Callers can use
        this to configure tool permissions before invoking the skill.
        """
        try:
            path = self._find_skill_path(skill_name)
            post = frontmatter.load(str(path))
            raw = post.metadata.get("allowed-tools", [])
            if isinstance(raw, list):
                return [str(t) for t in raw]
            if isinstance(raw, str):
                return [t.strip() for t in raw.split(",") if t.strip()]
        except Exception:  # noqa: BLE001
            pass
        return []

    def invoke_safe(
        self,
        skill_name: str,
        task: str,
        context: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Like ``invoke`` but returns "" instead of raising on any error.

        Use this when skill execution is best-effort and failure should
        gracefully degrade to a fallback rather than propagating an exception.
        """
        try:
            return self.invoke(skill_name, task=task, context=context, max_tokens=max_tokens)
        except (SkillNotFoundError, Exception):  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # KB entry → skill creation
    # ------------------------------------------------------------------

    def create_from_kb_entry(
        self,
        title: str,
        resolution_text: str,
        symptoms_text: str = "",
        root_cause_text: str = "",
    ) -> tuple[str, str]:
        """Generate a SKILL.md description and body from a KB entry via skill-creator.

        This is the primary entry point for skill creation during import.
        It invokes the ``skill-creator`` skill with the KB entry context,
        then parses the generated SKILL.md into (description, instructions).

        Falls back to (``"Resolve: <title>"``, ``resolution_text``) when
        skill-creator is not installed or the LLM call fails.

        Args:
            title: KB entry title — used to derive skill purpose and fallback description.
            resolution_text: ## Resolution section body from the KB entry.
            symptoms_text: ## Symptoms section body (optional context for skill-creator).
            root_cause_text: ## Root Cause section body (optional context).

        Returns:
            (description, instructions_body) ready for ``create_skill()``.
        """
        task = (
            "Based on the KB entry below, write a SKILL.md for an Anthropic Agent Skill.\n"
            "Output ONLY the raw Markdown — a YAML frontmatter block with 'name' and "
            "'description' fields, followed by the agent instructions body.\n"
            "Do NOT wrap in a code block. Do NOT add any preamble or commentary.\n\n"
            f"## KB Entry: {title}\n\n"
        )
        if symptoms_text.strip():
            task += f"### Symptoms\n{symptoms_text.strip()}\n\n"
        if root_cause_text.strip():
            task += f"### Root Cause\n{root_cause_text.strip()}\n\n"
        task += f"### Resolution\n{resolution_text.strip()}"

        raw = self.invoke_safe("skill-creator", task)

        if raw:
            desc, body = self._parse_skill_md_output(raw)
            if desc and body:
                return desc, body

        # Fallback when skill-creator is unavailable or output unparseable.
        return f"Resolve: {title}", resolution_text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(skill_md_text: str) -> str:
        """Strip YAML frontmatter and return just the body as the system prompt."""
        text = skill_md_text.strip()
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                return text[end + 3:].strip()
        return text

    @staticmethod
    def _parse_skill_md_output(raw: str) -> tuple[str, str]:
        """Parse LLM output that should be a SKILL.md.

        Returns:
            (description, instructions_body) parsed from frontmatter.
            Falls back to ("", raw) if parsing fails.
        """
        if not raw:
            return "", ""
        # Strip markdown code fence if LLM wrapped the output.
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            end = len(lines) - 1
            while end > 0 and not lines[end].strip().startswith("```"):
                end -= 1
            stripped = "\n".join(lines[1:end]).strip()
        try:
            post = frontmatter.loads(stripped)
            description = str(post.metadata.get("description", "")).strip()
            body = post.content.strip()
            if description and body:
                return description, body
        except Exception:  # noqa: BLE001
            pass
        return "", raw
