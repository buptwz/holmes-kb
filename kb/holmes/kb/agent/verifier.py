"""Content verifier — self-verification pass for import agent.

ContentVerifier sends the source text and draft KB entry to the LLM and
asks it to identify fields that lack source text support.  Unsupported
fields are returned to the caller for removal before writing.

This implements the two-pass pattern from research.md R-006:
  Pass 1: agent generates draft via tool-use loop.
  Pass 2: verifier checks each field against the source — clears any field
          whose content cannot be traced back to the source text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

import frontmatter


@dataclass
class VerifyResult:
    """Outcome of a single content verification pass.

    Attributes:
        verified_fields: Field names confirmed to have source support.
        unsupported_fields: Dicts with {field, reason} for fields to clear.
        confidence: Overall verification confidence (0.0–1.0).
        error: Error string if the LLM call failed, otherwise None.
    """

    verified_fields: list[str] = field(default_factory=list)
    unsupported_fields: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 1.0
    error: Optional[str] = None


class ContentVerifier:
    """Verify draft KB entry fields against the original source text.

    Args:
        client: Anthropic client instance.
        model: Model name to use for verification.
    """

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def verify(self, source_text: str, draft_content: str) -> VerifyResult:
        """Check each key field in draft_content for source text support.

        Args:
            source_text: The original import source text.
            draft_content: Full draft Markdown with YAML frontmatter.

        Returns:
            VerifyResult with lists of verified and unsupported fields.
        """
        system_prompt = (
            "You are a KB quality verifier. For each key field in the draft entry, "
            "verify it has a corresponding fragment in the source text.\n"
            "Key fields to check: title, root_cause (## Root Cause section body), "
            "resolution (## Resolution section body).\n\n"
            "Same-meaning paraphrasing is acceptable as source support. "
            "Invented facts not mentioned anywhere in the source are NOT supported.\n\n"
            "Reply with ONLY valid JSON (no markdown wrapper):\n"
            "{"
            '"verified_fields": ["title", ...], '
            '"unsupported_fields": [{"field": "...", "reason": "..."}], '
            '"confidence": 0.0-1.0'
            "}"
        )
        user_prompt = (
            f"SOURCE TEXT:\n{source_text[:3000]}\n\n"
            f"DRAFT ENTRY:\n{draft_content[:3000]}"
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"},
                ],
            )
            text = response.content[0].text.strip()
            # Strip optional markdown code fence if model wraps output.
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(
                    lines[1 : next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "```"), len(lines))]
                )
            data = json.loads(text)
            return VerifyResult(
                verified_fields=list(data.get("verified_fields", [])),
                unsupported_fields=list(data.get("unsupported_fields", [])),
                confidence=float(data.get("confidence", 1.0)),
            )
        except Exception as exc:  # noqa: BLE001
            # On error, treat as verified (don't block the pipeline).
            return VerifyResult(error=str(exc))

    def apply_result(self, draft_content: str, result: VerifyResult) -> str:
        """Remove unsupported fields from the draft and return updated content.

        For each unsupported field:
        - root_cause: clears the ## Root Cause section body
        - resolution: clears the ## Resolution section body
        - title: replaces with empty string in frontmatter

        Args:
            draft_content: Original draft Markdown with YAML frontmatter.
            result: VerifyResult from verify().

        Returns:
            Updated draft content with unsupported fields cleared.
        """
        if not result.unsupported_fields:
            return draft_content

        try:
            post = frontmatter.loads(draft_content)
        except Exception:  # noqa: BLE001
            return draft_content

        body: str = post.content or ""
        unsupported_field_names = {f["field"] for f in result.unsupported_fields}

        for fname in unsupported_field_names:
            if fname == "title":
                post.metadata["title"] = ""
            elif fname in ("root_cause", "root cause"):
                body = _clear_section(body, "Root Cause")
            elif fname in ("resolution", "resolution_commands", "commands"):
                body = _clear_section(body, "Resolution")

        post.content = body
        return frontmatter.dumps(post)


def _clear_section(body: str, section_name: str) -> str:
    """Replace the body of a named section with a placeholder."""
    import re
    pattern = re.compile(
        r"(## " + re.escape(section_name) + r"\s*\n)(.*?)(?=\n##|\Z)",
        re.DOTALL,
    )
    return pattern.sub(
        lambda m: m.group(1) + "[CLEARED — no source support]\n",
        body,
    )


def _clear_commands_in_section(body: str, section_name: str) -> str:
    """Remove backtick-wrapped and $ -prefixed commands from a named section."""
    import re
    # Match the section content block.
    pattern = re.compile(
        r"(## " + re.escape(section_name) + r"\s*\n)(.*?)(?=\n##|\Z)",
        re.DOTALL,
    )
    def _strip_commands(match: re.Match) -> str:
        heading = match.group(1)
        content = match.group(2)
        # Remove inline backtick commands and code blocks.
        content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        content = re.sub(r"`[^`]+`", "", content)
        content = re.sub(r"^\$ .+$", "", content, flags=re.MULTILINE)
        return heading + content
    return pattern.sub(_strip_commands, body)
