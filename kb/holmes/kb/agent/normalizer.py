"""DraftNormalizer — deterministic post-Extractor normalization layer (018).

Applies structural fixes to raw draft KB entries without any LLM calls.
Guarantees idempotency and zero side effects (pure function wrapped in class).
"""

from __future__ import annotations

import re
from typing import Optional

import frontmatter

from holmes.kb.schema import _CATEGORY_RE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mapping of Chinese / non-standard section headers to English canonical forms.
HEADER_MAP: dict[str, str] = {
    # Chinese → English (pitfall)
    "## 症状": "## Symptoms",
    "## 根因": "## Root Cause",
    "## 根本原因": "## Root Cause",
    "## 解决": "## Resolution",
    "## 解决方案": "## Resolution",
    "## 解决步骤": "## Resolution",
    "## 修复": "## Resolution",
    "## 修复步骤": "## Resolution",
    "## 处理方案": "## Resolution",
    "## 处理步骤": "## Resolution",
    "## 恢复": "## Resolution",
    "## 恢复步骤": "## Resolution",
    "## 操作步骤": "## Resolution",
    "## 诊断步骤": "## Resolution",
    "## 排查过程": "## Resolution",
    "## 排查步骤": "## Resolution",
    "## 排查": "## Resolution",
    "## 经验": "## Resolution",
    "## 根因总结": "## Root Cause",
    "## 经验总结": "## Resolution",
    # Chinese → English (process)
    "## 步骤": "## Steps",
    "## 执行步骤": "## Steps",
    # Chinese → English (model)
    "## 概述": "## Overview",
    "## 概要": "## Overview",
    # Chinese → English (guideline)
    "## 指南": "## Guideline",
    "## 规范": "## Guideline",
    "## 准则": "## Guideline",
    # Chinese → English (decision)
    "## 背景": "## Context",
    "## 上下文": "## Context",
    "## 决策": "## Decision",
    "## 决定": "## Decision",
    # Old schema section names → canonical extractor names (backward compat)
    "## Definition": "## Overview",   # model: old → new canonical
    "## Rule": "## Guideline",        # guideline: old → new canonical
    # Legacy navigation heading → standard Contents (042)
    "## Diagnostic Flow": "## Contents",
    "## 目录": "## Contents",
    "## 诊断流程": "## Contents",
}

# Words excluded from tag auto-extraction.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "on",
        "at", "by", "for", "with", "from", "and", "or", "but", "not", "no",
        "this", "that", "it", "its", "when", "where", "how", "why", "what",
        "if", "then", "than", "as", "so", "about", "after", "before",
        "due", "cause", "caused", "result", "results", "use", "using",
        "导致", "导致了", "原因", "解决", "问题",
    }
)

MAX_TITLE_LENGTH: int = 60
MIN_TAGS: int = 3
MAX_TAGS: int = 8

# Pattern to match `## SomeHeader` lines.
_HEADER_RE = re.compile(r"^(## .+)$", re.MULTILINE)
# Pattern to remove a named ## Section including its content.
_SECTION_RE = re.compile(r"(?m)^## Symptoms\s*\n.*?(?=^##|\Z)", re.DOTALL)
# Token split pattern for tag extraction.
# Covers ASCII, CJK unified (incl. extensions/compat), Japanese kana, Korean Hangul.
_TOKEN_RE = re.compile(r"[A-Za-z0-9\u3040-\u9fff\uac00-\ud7af\uf900-\ufaff]+")


def _detect_language(text: str) -> str:
    """Detect the primary language of *text* and return a BCP-47 language tag.

    Detection order:
    1. Try ``langdetect`` if available (library-based detection).
    2. Fallback: Unicode range heuristics (Japanese kana → ja, Korean Hangul → ko,
       CJK ideographs → zh).
    3. Final fallback: ``en``.
    """
    # Unicode range heuristics first — more reliable for CJK mixed with English.
    if re.search(r"[\u3040-\u30ff]", text):  # Hiragana / Katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):  # Hangul syllables
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):  # CJK unified ideographs
        return "zh"

    try:
        from langdetect import detect as _ld_detect  # type: ignore[import]
        result = _ld_detect(text)
        if isinstance(result, str) and result.startswith("zh"):
            return "zh"
        if isinstance(result, str):
            return result
    except Exception:  # noqa: BLE001
        pass

    return "en"


# ---------------------------------------------------------------------------
# Contents section builder — deterministic, used by normalizer and MCP tools
# ---------------------------------------------------------------------------

# Regex for ## headings (not ###).
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def build_contents_table(body: str, exclude: frozenset[str] = frozenset({"Contents"})) -> str:
    """Build a Markdown table listing all ## sections in *body*.

    Args:
        body: Markdown body text (without YAML frontmatter).
        exclude: Section names to omit from the table (case-insensitive match).

    Returns:
        A ``## Contents`` block with a ``| Section | Description |`` table,
        or empty string if no sections are found.
    """
    exclude_lower = frozenset(s.lower() for s in exclude)
    headings = [m.group(1).strip() for m in _H2_RE.finditer(body)]
    headings = [h for h in headings if h.lower() not in exclude_lower]
    if not headings:
        return ""

    # Build short descriptions from the first non-empty line after each heading
    rows: list[str] = []
    for heading in headings:
        desc = _extract_section_brief(body, heading)
        rows.append(f"| {heading} | {desc} |")

    lines = ["## Contents", "", "| Section | Description |", "|---|---|"]
    lines.extend(rows)
    return "\n".join(lines)


def _extract_section_brief(body: str, heading: str) -> str:
    """Extract a short description from the first content line of a section."""
    pattern = re.compile(rf"^## {re.escape(heading)}\s*$", re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return ""
    rest = body[m.end():]
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        # Skip blank lines, sub-headings, tables, code fences
        if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("```"):
            continue
        # Use first content line, truncated
        brief = stripped.lstrip("- *").strip()
        if len(brief) > 80:
            # Truncate at word boundary
            brief = brief[:77].rsplit(" ", 1)[0] + "..."
        return brief
    return ""


def ensure_contents_section(body: str) -> tuple[str, list[str]]:
    """Insert a ``## Contents`` section if the body lacks one.

    If the body already contains a ``## Contents`` heading (case-insensitive),
    no changes are made.  If a decision-tree code block already exists under
    Contents (complex branching), it is preserved as-is.

    Returns:
        Tuple of (possibly modified body, list of warning strings).
    """
    # Check if Contents already exists
    if re.search(r"(?mi)^## Contents\s*$", body):
        return body, []

    contents = build_contents_table(body)
    if not contents:
        return body, []

    # Insert before the first ## heading
    first_h2 = _H2_RE.search(body)
    if first_h2:
        pos = first_h2.start()
        body = body[:pos] + contents + "\n\n" + body[pos:]
    else:
        body = contents + "\n\n" + body

    return body, ["contents: auto-generated ## Contents from body headings"]


# Pattern matching empty ## Resolution section.
_RESOLUTION_SECTION_RE = re.compile(
    r"(?m)^## Resolution\s*\n(.*?)(?=^##|\Z)", re.DOTALL
)


class DraftNormalizer:
    """Deterministic normalizer for draft KB entries.

    Stateless; safe to call from multiple threads in parallel.
    All constants are class-level (not instance state).
    """

    # Expose constants as class attributes for test introspection.
    HEADER_MAP = HEADER_MAP
    MAX_TITLE_LENGTH = MAX_TITLE_LENGTH
    MIN_TAGS = MIN_TAGS
    MAX_TAGS = MAX_TAGS

    def normalize(
        self, draft: str, kb_type: Optional[str] = None
    ) -> tuple[str, list[str]]:
        """Normalize a raw KB entry draft string.

        Operations applied in order:
        1. Parse frontmatter (abort on failure).
        2. Translate Chinese/non-standard section headers + ensure ## Contents.
        3. Enforce title length ≤ MAX_TITLE_LENGTH.
        4. Auto-extract tags when fewer than MIN_TAGS are present.
        5. Apply type-level structural constraints.
        6. Normalize category to a valid value.
        7. Serialize and return.

        Args:
            draft: Raw KB entry Markdown string with YAML frontmatter.
            kb_type: Optional type override; if None, type is read from frontmatter.

        Returns:
            Tuple of (normalized_draft, warnings) where warnings is a list of
            human-readable strings describing each normalization action taken.
        """
        warnings: list[str] = []

        # Step 1: Parse frontmatter.
        try:
            post = frontmatter.loads(draft)
        except Exception:  # noqa: BLE001
            return draft, ["warning: could not parse frontmatter — skipped normalization"]

        body: str = post.content
        meta: dict = post.metadata  # type: ignore[assignment]

        # Step 2: Translate section headers.
        body, header_warnings = self._translate_headers(body)
        warnings.extend(header_warnings)

        # Step 2a: Ensure ## Contents section exists (042).
        body, contents_warnings = ensure_contents_section(body)
        warnings.extend(contents_warnings)

        # Step 2b: Clean up kp-N internal references (042 defensive).
        body, kp_warnings = self._clean_kp_references(body)
        warnings.extend(kp_warnings)

        # Step 3: Enforce title length.
        title = str(meta.get("title", "") or "")
        root_cause = str(meta.get("root_cause", "") or "")
        title, title_warnings = self._enforce_title(title, root_cause)
        meta["title"] = title
        warnings.extend(title_warnings)

        # Step 3a: Language detection (020/021).
        lang = str(meta.get("language", "") or "").strip()
        if not lang:
            combined = f"{title} {body}"
            meta["language"] = _detect_language(combined)
            warnings.append(f'language: injected "{meta["language"]}" (auto-detected)')

        # Step 4: Auto-extract tags.
        tags = meta.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        if len(tags) < self.MIN_TAGS:
            category = str(meta.get("category", "") or "")
            new_tags, tag_warnings = self._extract_tags(
                title, root_cause, existing=tags, category=category
            )
            meta["tags"] = new_tags
            warnings.extend(tag_warnings)

        # Step 5: Type-level structural constraints.
        effective_type = str(kb_type or meta.get("type", "") or "")
        body, struct_warnings = self._apply_structural_constraints(body, effective_type, meta)
        warnings.extend(struct_warnings)

        # Step 6: Category normalization.
        category = str(meta.get("category", "") or "")
        if category:
            category, cat_warnings = self._normalize_category(category)
            meta["category"] = category
            warnings.extend(cat_warnings)

        # Step 6a: Validate decision_map if present.
        decision_map = meta.get("decision_map")
        if decision_map and isinstance(decision_map, list):
            body, decision_map, dm_warnings = self._validate_decision_map(body, decision_map)
            meta["decision_map"] = decision_map
            warnings.extend(dm_warnings)

        # Step 7: Serialize.
        post.content = body
        post.metadata = meta
        return frontmatter.dumps(post), warnings

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _translate_headers(self, body: str) -> tuple[str, list[str]]:
        """Replace Chinese/non-standard headers with English canonical forms."""
        warnings: list[str] = []
        for original, replacement in HEADER_MAP.items():
            # Match header at start of line (case-sensitive).
            pattern = re.compile(rf"^{re.escape(original)}\s*$", re.MULTILINE)
            if pattern.search(body):
                body = pattern.sub(replacement, body)
                warnings.append(f'header: "{original}" → "{replacement}"')
        return body, warnings

    @staticmethod
    def _clean_kp_references(body: str) -> tuple[str, list[str]]:
        """Remove internal kp-N references left over from legacy pipeline."""
        warnings: list[str] = []
        # Match patterns like "kp-1", "kp-2", "(kp-3)", "[kp-4]" etc.
        pattern = re.compile(r"\b(?:kp-\d+)\b", re.IGNORECASE)
        matches = pattern.findall(body)
        if matches:
            body = pattern.sub("", body)
            # Clean up any resulting double spaces or empty parens
            body = re.sub(r"\(\s*\)", "", body)
            body = re.sub(r"\[\s*\]", "", body)
            body = re.sub(r"  +", " ", body)
            warnings.append(f"cleaned {len(matches)} kp-N reference(s)")
        return body, warnings

    def _enforce_title(self, title: str, root_cause: str) -> tuple[str, list[str]]:
        """Ensure title is non-empty and ≤ MAX_TITLE_LENGTH characters."""
        warnings: list[str] = []
        if not title.strip():
            # Generate from first MAX_TITLE_LENGTH chars of root_cause.
            fallback = root_cause.strip()[:self.MAX_TITLE_LENGTH].strip()
            if not fallback:
                fallback = "Untitled"
            warnings.append(f"title: empty title generated from root_cause: \"{fallback[:30]}...\"")
            return fallback, warnings

        if len(title) > self.MAX_TITLE_LENGTH:
            # Truncate at last space boundary ≤ MAX_TITLE_LENGTH.
            truncated = title[:self.MAX_TITLE_LENGTH]
            last_space = truncated.rfind(" ")
            if last_space > 0:
                truncated = truncated[:last_space]
            warnings.append(
                f"title: truncated from {len(title)} to {len(truncated)} chars"
            )
            return truncated, warnings

        return title, warnings

    def _extract_tags(
        self,
        title: str,
        root_cause: str,
        existing: list[str],
        category: str = "",
    ) -> tuple[list[str], list[str]]:
        """Auto-extract tags from title + root_cause to reach MIN_TAGS."""
        source = f"{title} {root_cause}"
        tokens = _TOKEN_RE.findall(source.lower())
        seen: set[str] = {t.lower() for t in existing}
        new_tags: list[str] = list(existing)
        added = 0
        for token in tokens:
            if len(new_tags) >= self.MAX_TAGS:
                break
            if token in _STOPWORDS or len(token) < 2:
                continue
            if token not in seen:
                seen.add(token)
                new_tags.append(token)
                added += 1
            if len(new_tags) >= self.MAX_TAGS:
                break

        warnings: list[str] = []
        if added:
            warnings.append(f"tags: auto-extracted {added} tag(s) (total: {len(new_tags)})")

        # T004 fix (020): if still empty after extraction, inject category as fallback tag.
        if not new_tags:
            fallback = category or "unknown"
            new_tags.append(fallback)
            warnings.append(f'tags: no tokens found — injected category fallback "{fallback}"')

        return new_tags, warnings

    def _apply_structural_constraints(
        self, body: str, kb_type: str, meta: dict
    ) -> tuple[str, list[str]]:
        """Apply type-level structural constraints to the body."""
        warnings: list[str] = []

        if kb_type == "model":
            # Model entries must NOT contain pitfall-only sections.
            for forbidden in ("## Symptoms", "## Root Cause", "## Resolution"):
                if re.search(rf"(?m)^{re.escape(forbidden)}\s*$", body):
                    warnings.append(
                        f"structure: model entry contains pitfall section {forbidden}"
                    )

        elif kb_type == "guideline":
            # Guideline entries must NOT contain ## Symptoms.
            if re.search(r"(?m)^## Symptoms\s*$", body):
                body = _SECTION_RE.sub("", body)
                warnings.append("structure: removed ## Symptoms from guideline entry")

        elif kb_type == "pitfall":
            # Pitfall entries must have a non-empty ## Resolution.
            m = _RESOLUTION_SECTION_RE.search(body)
            if m is None or not m.group(1).strip():
                warnings.append(
                    "structure: pitfall ## Resolution is empty — "
                    "verbatim fallback will attempt recovery"
                )

        elif kb_type == "decision":
            # Decision entries must NOT have ## Resolution — rename to ## Decision.
            if re.search(r"(?m)^## Resolution\s*$", body):
                body = re.sub(r"(?m)^## Resolution\s*$", "## Decision", body)
                warnings.append(
                    "structure: renamed ## Resolution → ## Decision in decision entry"
                )
            # Warn about other pitfall-only sections.
            for forbidden in ("## Symptoms", "## Root Cause"):
                if re.search(rf"(?m)^{re.escape(forbidden)}\s*$", body):
                    warnings.append(
                        f"structure: decision entry contains forbidden section {forbidden}"
                    )

        return body, warnings

    @staticmethod
    def _validate_decision_map(
        body: str, decision_map: list,
    ) -> tuple[str, list, list[str]]:
        """Validate decision_map entries against ### headings in body.

        Removes entries whose branch label doesn't match any ### heading.
        Returns (body, cleaned_decision_map, warnings).
        """
        warnings: list[str] = []

        # Collect all ### headings in the body
        h3_headings = [
            line.strip()[4:].strip().lower()
            for line in body.splitlines()
            if line.strip().startswith("### ")
        ]

        cleaned: list[dict] = []
        for entry in decision_map:
            if not isinstance(entry, dict):
                continue
            symptom = str(entry.get("symptom", "")).strip()
            branch = str(entry.get("branch", "")).strip()
            if not symptom or not branch:
                continue

            # Check if branch label matches any ### heading (fuzzy)
            branch_lower = branch.lower()
            matched = any(
                branch_lower in h or h in branch_lower
                for h in h3_headings
            )
            if matched:
                cleaned.append({"symptom": symptom, "branch": branch})
            else:
                warnings.append(
                    f"decision_map: branch '{branch}' has no matching ### heading — removed"
                )

        if decision_map and not cleaned:
            warnings.append(
                "decision_map: all entries removed (no matching ### headings)"
            )

        return body, cleaned, warnings

    def _normalize_category(self, category: str) -> tuple[str, list[str]]:
        """Slugify category to lowercase; supports hierarchy via '/' separator."""
        warnings: list[str] = []
        # Slugify: lowercase, spaces→hyphens, strip non-slug chars.
        slugified = category.lower().strip()
        slugified = re.sub(r"\s+", "-", slugified)
        slugified = re.sub(r"[^a-z0-9/_-]", "", slugified)
        slugified = slugified.strip("-_/")
        if not slugified:
            slugified = "general"
            warnings.append(f'category: "{category}" is empty after slugify — defaulted to "general"')
        elif slugified != category:
            warnings.append(f'category: "{category}" → "{slugified}" (slugified)')
        return slugified, warnings
