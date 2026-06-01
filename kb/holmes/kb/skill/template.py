"""SKILL.md and run.sh template generators."""

from __future__ import annotations


def generate_skill_template(name: str, description: str, platforms: str = "linux,macos") -> str:
    """Generate a SKILL.md template string.

    Args:
        name: Skill name (kebab-case).
        description: One-sentence description.
        platforms: Comma-separated platform list.

    Returns:
        SKILL.md content string with YAML frontmatter.
    """
    return f"""\
---
name: {name}
description: {description}
version: 1.0.0
platforms: {platforms}
timeout: 30
# Uncomment and fill in params if your script accepts parameters:
# params:
#   - name: host
#     description: Target host address
#     required: false
#     default: "127.0.0.1"
# Uncomment if your script requires specific tools:
# prerequisites:
#   - redis-cli
---

# {name}

## When to Use

{description}

## Parameters

_(No parameters defined. Edit the frontmatter `params` section to add parameters.)_

## Quick Reference

```bash
# Example usage:
bash scripts/run.sh
```

## Notes

_(Add additional context, caveats, or examples here.)_
"""


def generate_run_sh_template(description: str) -> str:
    """Generate a run.sh template string.

    Args:
        description: One-sentence description of what the script does.

    Returns:
        Bash script template content.
    """
    return f"""\
#!/usr/bin/env bash
# Skill: {description}
#
# Parameters are injected as environment variables with the SKILL_PARAM_ prefix.
# Example: SKILL_PARAM_HOST, SKILL_PARAM_PORT
#
# Uncomment and adapt the following examples:
# HOST="${{SKILL_PARAM_HOST:-127.0.0.1}}"
# PORT="${{SKILL_PARAM_PORT:-8080}}"

set -euo pipefail

echo "=== {description} ==="

# TODO: Add your diagnostic commands here.
# Example:
# redis-cli -h "$HOST" -p "$PORT" info | grep -E "connected_clients|maxclients"
"""
