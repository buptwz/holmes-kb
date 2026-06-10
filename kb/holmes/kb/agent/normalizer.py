"""DraftNormalizer — deterministic post-Extractor normalization layer (018).

Applies structural fixes to raw draft KB entries without any LLM calls.
Guarantees idempotency and zero side effects (pure function wrapped in class).
"""

from __future__ import annotations

import re
from typing import Optional

import frontmatter

from holmes.kb.schema import VALID_PITFALL_CATEGORIES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mapping of Chinese / non-standard section headers to English canonical forms.
HEADER_MAP: dict[str, str] = {
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
    "## 经验": "## Resolution",
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
    try:
        from langdetect import detect as _ld_detect  # type: ignore[import]
        result = _ld_detect(text)
        # langdetect may return zh-cn, zh-tw — normalise to zh.
        if isinstance(result, str) and result.startswith("zh"):
            return "zh"
        if isinstance(result, str):
            return result
    except Exception:  # noqa: BLE001
        pass

    # Unicode range heuristics fallback.
    if re.search(r"[\u3040-\u30ff]", text):  # Hiragana / Katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):  # Hangul syllables
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):  # CJK unified ideographs
        return "zh"
    return "en"
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
        2. Translate Chinese/non-standard section headers.
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

        if kb_type == "guideline":
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

        return body, warnings

    def _normalize_category(self, category: str) -> tuple[str, list[str]]:
        """Ensure category is in VALID_PITFALL_CATEGORIES; map or default to 'system'."""
        warnings: list[str] = []
        if category in VALID_PITFALL_CATEGORIES:
            return category, warnings  # already valid — no warning needed

        # Try a simple prefix match for common variations.
        normalized = "system"
        for valid in VALID_PITFALL_CATEGORIES:
            if category.lower().startswith(valid) or valid.startswith(category.lower()):
                normalized = valid
                break

        warnings.append(
            f"category: \"{category}\" not in valid set — normalized to \"{normalized}\""
        )
        return normalized, warnings
