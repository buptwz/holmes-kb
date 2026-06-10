"""Knowledge importer — LLM-based document classification and structuring.

Reads any document and uses an LLM (OpenAI-compatible API) to produce
a KB-formatted Markdown entry with proper YAML frontmatter.

Minimum content length: 50 characters (raises ContentTooShortError otherwise).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import frontmatter
import openai

from holmes.kb.pending import write_pending


def compute_source_hash(content: str) -> str:
    """Compute a short idempotency key for import deduplication.

    Returns the first 16 hex characters of the SHA-256 hash of the
    UTF-8 encoded content string.  Used as ``source_hash`` in KB entry
    frontmatter (FR-007).

    Args:
        content: Raw source text.

    Returns:
        16-character lowercase hex string.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class ContentTooShortError(ValueError):
    """Raised when the source document is too short to classify meaningfully."""


class DuplicatePendingError(ValueError):
    """Raised when a pending entry with the same title already exists and --force is not set."""

    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__(f"Duplicate pending entry already exists: {existing_id}")


_CLASSIFY_SYSTEM = """\
You are a knowledge classification specialist.
Given a document, classify it into a knowledge base entry with proper structure.

Respond with a valid Markdown document containing YAML frontmatter:
---
id: ""
type: <pitfall|model|guideline|process|decision>
title: <concise title>
maturity: draft
category: <for pitfall: network|system|application|database|kubernetes|messaging|cache|monitoring; others: omit>
tags: [<tag1>, <tag2>]
created_at: ""
updated_at: ""
---

Then write the Markdown body with appropriate sections for the type:
- pitfall: ## Symptoms, ## Root Cause, ## Resolution
- model: ## Definition
- guideline: ## Rule
- process: ## Steps
- decision: ## Context, ## Decision

IMPORTANT:
- Return ONLY the raw Markdown with frontmatter — do NOT wrap in a code block.
- Section headings (e.g. ## Symptoms, ## Root Cause, ## Resolution) MUST always be in English.
- The section body text may remain in the original document language."""


@dataclass
class ImportResult:
    """Result of a document import operation."""

    pending_id: str
    kb_type: str
    title: str
    category: Optional[str]
    dry_run: bool
    content_preview: str


async def import_document(
    kb_root: Path,
    source_path: Path,
    model: str = "gpt-4o",
    api_base_url: str = "",
    api_key: str = "",
    kb_type: Optional[str] = None,
    category: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> ImportResult:
    """Import a document into the KB pending area via LLM classification.

    Args:
        kb_root: Root directory of the knowledge base.
        source_path: Path to the document to import.
        model: OpenAI-compatible model name.
        api_base_url: API base URL (empty = default OpenAI).
        api_key: API key.
        kb_type: Optional type override (skips LLM classification).
        category: Optional category override.
        dry_run: If True, classify but do not write to disk.

    Returns:
        ImportResult with pending entry details.

    Raises:
        ContentTooShortError: If source content is shorter than 50 characters.
        DuplicatePendingError: If a pending entry with the same title exists and force=False.
    """
    content = source_path.read_text(encoding="utf-8")
    if len(content.strip()) < 50:
        raise ContentTooShortError(
            f"Content too short ({len(content.strip())} chars). Minimum is 50 characters."
        )

    # If the document already has valid KB frontmatter, skip LLM classification.
    structured_content: str = ""
    try:
        pre = frontmatter.loads(content)
        if pre.metadata.get("type") and pre.metadata.get("title"):
            structured_content = content
    except Exception:  # noqa: BLE001
        pass

    if not structured_content:
        if dry_run:
            structured_content = content
        else:
            # Call LLM to classify and structure the document.
            client = openai.AsyncOpenAI(
                api_key=api_key or None,
                base_url=api_base_url or None,
            )

            type_hint = ""
            if kb_type:
                type_hint += f"\nForce type: {kb_type}"
            if category:
                type_hint += f"\nForce category: {category}"

            response = await client.chat.completions.create(
                model=model,
                max_completion_tokens=2048,
                messages=[
                    {"role": "system", "content": _CLASSIFY_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Classify and structure this document into a KB entry:"
                            f"{type_hint}\n\n{content}"
                        ),
                    },
                ],
            )

            structured_content = response.choices[0].message.content or ""

            # Strip markdown code block wrapper if LLM wrapped the output.
            if structured_content.startswith("```"):
                lines = structured_content.splitlines()
                end = len(lines) - 1
                while end > 0 and not lines[end].strip().startswith("```"):
                    end -= 1
                structured_content = "\n".join(lines[1:end])

    # Parse result metadata.
    post = frontmatter.loads(structured_content)

    # Apply caller overrides (these take precedence over LLM output).
    if kb_type:
        post.metadata["type"] = kb_type
    if category:
        post.metadata["category"] = category
    if title:
        post.metadata["title"] = title
    if tags is not None:
        post.metadata["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    result_type = str(post.metadata.get("type", "pitfall"))
    result_title = str(post.metadata.get("title", source_path.stem))
    result_category = post.metadata.get("category") or None

    # Re-serialise with overrides applied.
    structured_content = frontmatter.dumps(post)

    if dry_run:
        return ImportResult(
            pending_id="(dry-run)",
            kb_type=result_type,
            title=result_title,
            category=result_category,
            dry_run=True,
            content_preview=structured_content[:500],
        )

    # Duplicate pending check (skip when --force).
    if not force:
        from holmes.kb.pending import list_pending
        existing = [p for p in list_pending(kb_root) if p["title"] == result_title]
        if existing:
            raise DuplicatePendingError(existing[0]["id"])

    pending_id = write_pending(kb_root, structured_content, source="auto")
    return ImportResult(
        pending_id=pending_id,
        kb_type=result_type,
        title=result_title,
        category=result_category,
        dry_run=False,
        content_preview=structured_content[:500],
    )
