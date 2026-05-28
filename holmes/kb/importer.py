"""Knowledge importer — reads a document and uses LLM to classify and structure it.

Supports --type and --category overrides to skip LLM classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import openai

from holmes.kb.pending import write_pending
from holmes.logging_config import get_logger


logger = get_logger("kb.importer")

CLASSIFY_SYSTEM = """You are a knowledge classification specialist.
Given a document, classify it into a knowledge base entry with proper structure.

Respond with a valid Markdown document containing YAML frontmatter:
---
type: <pitfall|model|guideline|process|decision>
title: <concise title>
maturity: draft
category: <for pitfall: network|system|application|database; others can be omitted>
tags: [<tag1>, <tag2>]
created_at: ""
updated_at: ""
---

Then write the Markdown body with the appropriate sections for the type:
- pitfall: ## Symptoms, ## Root Cause, ## Resolution
- model: ## Definition
- guideline: ## Rule
- process: ## Steps
- decision: ## Context, ## Decision

Return ONLY the Markdown with frontmatter."""


@dataclass
class ImportResult:
    """Result of an import operation."""

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
    dry_run: bool = False,
) -> ImportResult:
    """Import a document into the KB pending area.

    If kb_type is not provided, uses LLM to auto-classify.

    Args:
        kb_root: Root directory of the knowledge base.
        source_path: Path to the document to import.
        model: Anthropic model to use for classification.
        kb_type: Optional type override.
        category: Optional category override.
        dry_run: If True, only classify and preview — don't write.

    Returns:
        ImportResult with the pending entry details.
    """
    content = source_path.read_text(encoding="utf-8")
    logger.info("Importing %s (%d chars)", source_path, len(content))

    client = openai.AsyncOpenAI(
        api_key=api_key or None,
        base_url=api_base_url or None,
    )

    # Build classification prompt
    type_hint = ""
    if kb_type:
        type_hint = f"\nForce type: {kb_type}"
    if category:
        type_hint += f"\nForce category: {category}"

    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=2048,
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": f"Classify and structure this document into a KB entry:{type_hint}\n\n{content}"},
        ],
    )

    structured_content = response.choices[0].message.content or ""

    # Parse result
    import frontmatter

    post = frontmatter.loads(structured_content)
    result_type = str(post.metadata.get("type", kb_type or "pitfall"))
    result_title = str(post.metadata.get("title", source_path.stem))
    result_category = post.metadata.get("category") or category

    if dry_run:
        return ImportResult(
            pending_id="(dry-run)",
            kb_type=result_type,
            title=result_title,
            category=result_category,
            dry_run=True,
            content_preview=structured_content[:500],
        )

    pending_id = write_pending(kb_root, structured_content)
    return ImportResult(
        pending_id=pending_id,
        kb_type=result_type,
        title=result_title,
        category=result_category,
        dry_run=False,
        content_preview=structured_content[:500],
    )
