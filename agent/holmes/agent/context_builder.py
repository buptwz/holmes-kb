"""Context builder for Holmes Agent.

Assembles the system prompt from:
- Troubleshooting role definition
- KB overview (injected at session start)
- Persistent memory (HOLMES.md + ~/.holmes/MEMORY.md)
- Registered tools
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from holmes.logging_config import get_logger


logger = get_logger("agent.context_builder")

SYSTEM_PROMPT_TEMPLATE = """You are Holmes, an expert troubleshooting assistant backed by a knowledge base.

Your role:
- Help users diagnose and resolve technical problems through systematic investigation
- Use the knowledge base tools (kb_read_overview, kb_read_category_index, kb_read_entry) to find relevant troubleshooting steps and patterns
- Execute diagnostic commands when needed (with user confirmation)
- When a problem is resolved, the user can save the troubleshooting knowledge for future use

Guidelines:
- Start by understanding the problem clearly before searching the KB
- Use kb_read_overview to discover available knowledge, then narrow down
- Be systematic: gather symptoms → check KB → run diagnostics → propose solution
- Always explain your reasoning before using tools
- For write operations or command execution, the user must approve

{memory_section}{kb_section}"""


def build_system_prompt(
    memory_text: Optional[str] = None,
    kb_overview: Optional[str] = None,
) -> str:
    """Build the system prompt for the agent.

    Args:
        memory_text: Combined persistent memory text (HOLMES.md + MEMORY.md).
        kb_overview: Optional KB overview to inject at session start.

    Returns:
        Assembled system prompt string.
    """
    memory_section = ""
    if memory_text and memory_text.strip():
        memory_section = f"\n## Persistent Memory\n\n{memory_text.strip()}\n"

    kb_section = ""
    if kb_overview and kb_overview.strip():
        kb_section = f"\n## Knowledge Base Overview\n\n{kb_overview.strip()}\n"

    return SYSTEM_PROMPT_TEMPLATE.format(
        memory_section=memory_section,
        kb_section=kb_section,
    )


def normalize_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize message list for the Anthropic API.

    Ensures alternating user/assistant turns. Consecutive same-role messages
    are merged into a single message.

    Args:
        messages: Raw message list with role/content dicts.

    Returns:
        Normalized message list suitable for the API.
    """
    if not messages:
        return []

    normalized: list[dict[str, Any]] = []
    for msg in messages:
        if normalized and normalized[-1]["role"] == msg["role"]:
            # Merge consecutive same-role messages
            if isinstance(normalized[-1]["content"], str):
                normalized[-1]["content"] += "\n\n" + msg["content"]
            else:
                normalized[-1]["content"].extend(
                    [{"type": "text", "text": "\n\n" + msg["content"]}]
                )
        else:
            normalized.append({"role": msg["role"], "content": msg["content"]})

    # API requires first message to be from user
    if normalized and normalized[0]["role"] != "user":
        normalized.insert(0, {"role": "user", "content": "[session started]"})

    return normalized
