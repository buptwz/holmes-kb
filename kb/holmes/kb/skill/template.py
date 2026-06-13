"""SKILL.md template generator — Anthropic Agent Skills format."""

from __future__ import annotations

import yaml

_DEFAULT_BODY = """\
## When to Use

Describe when an agent should use this skill. Include symptoms, conditions, and trigger events.

## Resolution Steps

1. First step: describe what to do and why.
2. Second step: describe what to do and why.
3. Third step: describe what to do and why.

## Key Points

- Important caveat or boundary condition.
- Common pitfall to avoid.
- Key thing to verify after resolution.
"""


def generate_skill_template(name: str, description: str, instructions: str = "") -> str:
    """Generate a SKILL.md template string.

    Args:
        name: Skill name (kebab-case).
        description: Trigger description (when to use / what it does, ≤1024 chars).
        instructions: Agent instruction markdown body. If empty, a default
                      three-section placeholder is used.

    Returns:
        SKILL.md content string with YAML frontmatter and instructions body.
    """
    body = instructions.strip() if instructions.strip() else f"# {name}\n\n{_DEFAULT_BODY}"
    # Use yaml.dump to safely serialize description — avoids YAML parse errors when
    # description contains a colon (e.g. "Resolve: Redis Sentinel fix"), which would
    # otherwise be interpreted as a YAML key-value separator.
    desc_yaml = yaml.dump(description, default_style=None, allow_unicode=True).strip()
    return f"""\
---
name: {name}
description: {desc_yaml}
---

{body}
"""
