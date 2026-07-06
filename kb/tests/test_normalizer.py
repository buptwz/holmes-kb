"""Unit tests for DraftNormalizer (018 Root A)."""

from __future__ import annotations

import frontmatter
import pytest

from holmes.kb.agent.normalizer import DraftNormalizer


def _make_draft(
    *,
    title: str = "Test Title",
    kb_type: str = "pitfall",
    category: str = "system",
    tags: list[str] | None = None,
    root_cause: str = "root cause text here",
    body: str | None = None,
) -> str:
    """Build a minimal valid draft string for testing."""
    tags_yaml = str(tags if tags is not None else ["tag1", "tag2", "tag3"])
    if body is None:
        body = (
            "\n## Symptoms\n\nSome symptoms.\n\n"
            "## Root Cause\n\nroot cause text here.\n\n"
            "## Resolution\n\nkubectl rollout restart deployment/api\n"
        )
    return (
        f"---\n"
        f"id: test-001\n"
        f"type: {kb_type}\n"
        f"category: {category}\n"
        f"title: {title}\n"
        f"tags: {tags_yaml}\n"
        f"root_cause: {root_cause}\n"
        f"maturity: draft\n"
        f"created_at: 2026-06-09T00:00:00Z\n"
        f"updated_at: 2026-06-09T00:00:00Z\n"
        f"---\n{body}"
    )


class TestHeaderTranslation:
    def test_symptoms_header_translated(self):
        draft = _make_draft(body="\n## 症状\n\nSome symptoms.\n\n## 根因\n\nCause.\n\n## 解决方案\n\nFix it.\n")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        post = frontmatter.loads(result)
        assert "## Symptoms" in post.content
        assert "## 症状" not in post.content
        assert any("症状" in w for w in warnings)

    def test_root_cause_header_translated(self):
        draft = _make_draft(body="\n## Symptoms\n\nSome.\n\n## 根因\n\nCause.\n\n## Resolution\n\ncmd\n")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        post = frontmatter.loads(result)
        assert "## Root Cause" in post.content
        assert "## 根因" not in post.content
        assert any("根因" in w for w in warnings)

    def test_resolution_header_translated(self):
        draft = _make_draft(body="\n## Symptoms\n\nSome.\n\n## Root Cause\n\nCause.\n\n## 解决方案\n\nFix.\n")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        post = frontmatter.loads(result)
        assert "## Resolution" in post.content
        assert "## 解决方案" not in post.content
        assert any("解决方案" in w for w in warnings)

    def test_multiple_headers_translated(self):
        body = "\n## 症状\n\nSym.\n\n## 根本原因\n\nCause.\n\n## 修复步骤\n\nFix.\n"
        draft = _make_draft(body=body)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        post = frontmatter.loads(result)
        assert "## Symptoms" in post.content
        assert "## Root Cause" in post.content
        assert "## Resolution" in post.content
        assert len([w for w in warnings if w.startswith("header:")]) == 3


class TestTitleEnforcement:
    def test_long_title_truncated_at_word_boundary(self):
        long_title = "This Is A Very Long Title That Exceeds The Sixty Character Limit For KB Entries"
        draft = _make_draft(title=long_title)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert len(post.metadata["title"]) <= DraftNormalizer.MAX_TITLE_LENGTH
        assert any("title: truncated" in w for w in warnings)

    def test_long_title_truncates_at_space(self):
        # Title of exactly 70 chars ending mid-word should truncate at previous space.
        long_title = "abcdef ghijklm nopqrs tuvwxyz abcdef ghijklm nopqrs tuvwxyz extra123"
        draft = _make_draft(title=long_title)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        title = post.metadata["title"]
        assert len(title) <= DraftNormalizer.MAX_TITLE_LENGTH
        assert not title.endswith(" ")  # no trailing space after truncation

    def test_short_title_unchanged(self):
        draft = _make_draft(title="Short Title")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata["title"] == "Short Title"
        assert not any("title:" in w for w in warnings)

    def test_empty_title_generates_from_root_cause(self):
        draft = _make_draft(title="", root_cause="Database connection pool exhausted")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata["title"] != ""
        assert "database" in post.metadata["title"].lower() or "pool" in post.metadata["title"].lower()
        assert any("title: empty" in w for w in warnings)

    def test_null_title_generates_fallback(self):
        # frontmatter with no title field
        draft = (
            "---\n"
            "id: test-001\n"
            "type: pitfall\n"
            "category: system\n"
            "tags: [a, b, c]\n"
            "root_cause: Service connection refused due to exhausted pool\n"
            "maturity: draft\n"
            "created_at: 2026-06-09T00:00:00Z\n"
            "updated_at: 2026-06-09T00:00:00Z\n"
            "---\n\n## Symptoms\n\nFails.\n"
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata.get("title", "") != ""
        assert any("title:" in w for w in warnings)


class TestTagsExtraction:
    def test_missing_tags_auto_extracted(self):
        draft = _make_draft(tags=[], title="Kubernetes OOMKilled pod memory", root_cause="pod exceeded memory limit")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert len(post.metadata["tags"]) >= DraftNormalizer.MIN_TAGS
        assert any("tags: auto-extracted" in w for w in warnings)

    def test_tags_already_three_unchanged(self):
        draft = _make_draft(tags=["kubernetes", "oom", "memory"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        # Should have at least 3 tags (original 3 preserved)
        assert len(post.metadata["tags"]) >= 3
        # No tags warning for already-sufficient tags
        assert not any("tags: auto-extracted" in w for w in warnings)

    def test_two_tags_get_extended(self):
        draft = _make_draft(tags=["redis", "cache"], title="Redis connection timeout", root_cause="max connections exceeded")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert len(post.metadata["tags"]) >= DraftNormalizer.MIN_TAGS


class TestStructuralConstraints:
    def test_guideline_symptoms_removed(self):
        body = "\n## Symptoms\n\nSome symptoms here.\n\n## Rule\n\nFollow this rule.\n"
        draft = _make_draft(kb_type="guideline", category="system", body=body, tags=["a", "b", "c"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="guideline")
        post = frontmatter.loads(result)
        assert "## Symptoms" not in post.content
        assert any("structure: removed ## Symptoms" in w for w in warnings)

    def test_pitfall_empty_resolution_warns(self):
        body = "\n## Symptoms\n\nSome symptoms.\n\n## Root Cause\n\nCause.\n\n## Resolution\n\n"
        draft = _make_draft(kb_type="pitfall", body=body)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        assert any("structure: pitfall ## Resolution is empty" in w for w in warnings)
        # Header must still be present after normalization
        post = frontmatter.loads(result)
        assert "## Resolution" in post.content

    def test_pitfall_nonempty_resolution_no_warning(self):
        draft = _make_draft(kb_type="pitfall")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        assert not any("structure: pitfall ## Resolution is empty" in w for w in warnings)

    def test_guideline_no_symptoms_no_change(self):
        body = "\n## Rule\n\nFollow this rule.\n"
        draft = _make_draft(kb_type="guideline", body=body, tags=["a", "b", "c"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="guideline")
        assert not any("structure: removed" in w for w in warnings)


class TestCategoryNormalization:
    def test_kubernetes_category_accepted(self):
        draft = _make_draft(category="kubernetes")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata["category"] == "kubernetes"
        assert not any("category:" in w for w in warnings)

    def test_category_with_spaces_slugified(self):
        draft = _make_draft(category="team management")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata["category"] == "team-management"
        assert any("slugified" in w for w in warnings)

    def test_hierarchical_category_preserved(self):
        draft = _make_draft(category="hardware/gpu")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata["category"] == "hardware/gpu"
        assert not any("category:" in w for w in warnings)

    def test_valid_categories_accepted_without_warning(self):
        for cat in ("network", "system", "application", "database", "hardware/gpu", "power/psu"):
            draft = _make_draft(category=cat)
            normalizer = DraftNormalizer()
            result, warnings = normalizer.normalize(draft)
            post = frontmatter.loads(result)
            assert post.metadata["category"] == cat, f"Category {cat} changed unexpectedly"
            assert not any("category:" in w for w in warnings), f"Unexpected warning for valid category {cat}"


class TestEdgeCases:
    def test_unparseable_frontmatter_returns_original(self):
        bad_draft = "---\nbad: yaml: : :\n---\n\nsome body"
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(bad_draft)
        assert result == bad_draft
        assert len(warnings) == 1
        assert "could not parse frontmatter" in warnings[0]

    def test_idempotency(self):
        draft = _make_draft(
            title="Kubernetes OOMKilled",
            body="\n## 症状\n\nSome symptoms.\n\n## Root Cause\n\nCause.\n\n## Resolution\n\nkubectl delete pod\n",
        )
        normalizer = DraftNormalizer()
        first_result, _ = normalizer.normalize(draft, kb_type="pitfall")
        second_result, _ = normalizer.normalize(first_result, kb_type="pitfall")
        assert first_result == second_result


# ---------------------------------------------------------------------------
# T005: Language injection and fallback tag (Feature 020)
# ---------------------------------------------------------------------------


def _make_draft_no_language(
    *,
    title: str = "Test Title",
    kb_type: str = "pitfall",
    category: str = "system",
    tags: list | None = None,
    body: str | None = None,
) -> str:
    """Build a draft without a language field."""
    tags_yaml = str(tags if tags is not None else ["tag1", "tag2", "tag3"])
    if body is None:
        body = "\n## Symptoms\n\nSome symptoms.\n\n## Root Cause\n\nCause.\n\n## Resolution\n\nkubectl rollout restart deployment/api\n"
    return (
        f"---\n"
        f"id: test-lang-001\n"
        f"title: {title}\n"
        f"type: {kb_type}\n"
        f"category: {category}\n"
        f"tags: {tags_yaml}\n"
        f"---\n{body}"
    )


class TestLanguageInjection:
    """DraftNormalizer injects language field when missing (020 T005)."""

    def test_english_content_gets_language_en(self):
        """Entry with English title/body and no language field gets language: en."""
        draft = _make_draft_no_language(
            title="Node.js Event Loop Blocking",
            body="\n## Symptoms\n\nHigh CPU usage.\n\n## Root Cause\n\nSynchronous JSON.parse blocks event loop.\n\n## Resolution\n\nkubectl set env deployment/api NODE_OPTIONS=--max-old-space-size=512\n",
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata.get("language") == "en", f"Expected language=en, got {post.metadata.get('language')}"
        assert any("language" in w for w in warnings), "Warning about language injection expected"

    def test_chinese_content_gets_language_zh(self):
        """Entry with Chinese title and no language field gets language: zh."""
        draft = _make_draft_no_language(
            title="MySQL 慢查询导致连接池耗尽",
            body="\n## Symptoms\n\n响应时间从 50ms 上升到 5000ms。\n\n## Root Cause\n\n索引缺失。\n\n## Resolution\n\nALTER TABLE orders ADD INDEX idx_status (status);\n",
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata.get("language") == "zh", f"Expected language=zh, got {post.metadata.get('language')}"

    def test_existing_language_field_not_overwritten(self):
        """If language is already set, normalizer must not overwrite it."""
        base = _make_draft_no_language(title="Redis Timeout", body="\n## Symptoms\n\nTimeout.\n\n## Root Cause\n\nPool exhausted.\n\n## Resolution\n\nkubectl rollout restart deployment/redis\n")
        # Insert language manually
        draft = base.replace("---\n", "---\nlanguage: fr\n", 1)
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        assert post.metadata.get("language") == "fr", "Existing language field must not be overwritten"
        assert not any("language: injected" in w for w in warnings)

    def test_empty_content_falls_back_to_category_tag(self):
        """Entry whose title and root_cause are all stopwords gets category as fallback tag."""
        # Use all-stopword title + root_cause frontmatter so token extraction yields nothing
        draft = (
            "---\n"
            "id: test-empty-001\n"
            "title: the a and or\n"
            "type: pitfall\n"
            "category: network\n"
            "root_cause: is are was were\n"
            "tags: []\n"
            "---\n\n## Symptoms\n\n.\n\n## Root Cause\n\n.\n\n## Resolution\n\nrun\n"
        )
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = frontmatter.loads(result)
        tags = post.metadata.get("tags", [])
        assert len(tags) >= 1, "At least one fallback tag must be present"
        assert "network" in tags, f"Expected category 'network' as fallback tag, got {tags}"
        assert any("fallback" in w for w in warnings)


# ---------------------------------------------------------------------------
# T013 (021): multilingual language detection and _TOKEN_RE universalization
# ---------------------------------------------------------------------------


class TestMultilingualLanguageDetection:
    """021 T013: normalizer detects ja/ko/zh/en; existing language not overwritten."""

    def _make_draft(self, title: str, body: str = "## Resolution\nfix it\n", lang: str = "") -> str:
        lang_line = f"language: {lang}\n" if lang else ""
        return (
            "---\n"
            "id: test-001\n"
            f"title: {title}\n"
            "type: pitfall\n"
            "category: network\n"
            f"{lang_line}"
            "---\n\n## Symptoms\n\nsome symptom\n\n" + body
        )

    def test_japanese_document_detected_as_ja(self):
        """Document with hiragana/katakana → language: ja."""
        from holmes.kb.agent.normalizer import _detect_language

        japanese_text = "ポッドがクラッシュする原因はメモリ不足です"  # Katakana + Kanji
        result = _detect_language(japanese_text)
        assert result == "ja", f"Expected 'ja', got '{result}'"

    def test_korean_document_detected_as_ko(self):
        """Document with Hangul → language: ko."""
        from holmes.kb.agent.normalizer import _detect_language

        korean_text = "파드가 충돌하는 이유는 메모리 부족입니다"  # Hangul
        result = _detect_language(korean_text)
        assert result == "ko", f"Expected 'ko', got '{result}'"

    def test_chinese_document_detected_as_zh(self):
        """Document with CJK ideographs → language: zh."""
        from holmes.kb.agent.normalizer import _detect_language

        chinese_text = "Redis 内存溢出导致 Pod 崩溃的根本原因"
        result = _detect_language(chinese_text)
        assert result == "zh", f"Expected 'zh', got '{result}'"

    def test_existing_language_field_not_overwritten(self):
        """If frontmatter already has language set, normalizer must not overwrite it."""
        import frontmatter as fm
        from holmes.kb.agent.normalizer import DraftNormalizer

        draft = self._make_draft("Redis OOM issue", lang="fr")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft)
        post = fm.loads(result)
        assert post.metadata.get("language") == "fr"
        assert not any("language" in w and "injected" in w for w in warnings)

    def test_token_re_extracts_japanese_tokens(self):
        """_TOKEN_RE matches Japanese kana characters."""
        from holmes.kb.agent.normalizer import _TOKEN_RE

        text = "ポッドクラッシュ memory"
        tokens = _TOKEN_RE.findall(text)
        # Should extract the katakana token and the English word
        combined = "".join(tokens)
        assert "ポッドクラッシュ" in combined or any("ポ" in t for t in tokens)

    def test_token_re_extracts_korean_tokens(self):
        """_TOKEN_RE matches Korean Hangul characters."""
        from holmes.kb.agent.normalizer import _TOKEN_RE

        text = "파드 memory 충돌"
        tokens = _TOKEN_RE.findall(text)
        combined = " ".join(tokens)
        assert "파드" in combined or "충돌" in combined


class TestDecisionTypeSectionsBug5:
    """T024: Bug-5 — decision entries get ## Resolution renamed to ## Decision."""

    def test_decision_resolution_renamed_to_decision(self):
        body = (
            "\n## Context\n\nWe chose PostgreSQL.\n\n"
            "## Resolution\n\nUse PostgreSQL for the primary datastore.\n"
        )
        draft = _make_draft(kb_type="decision", body=body, tags=["a", "b", "c"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="decision")
        post = frontmatter.loads(result)
        assert "## Decision" in post.content
        assert "## Resolution" not in post.content
        assert any("renamed ## Resolution" in w for w in warnings)

    def test_decision_with_correct_sections_passes(self):
        body = (
            "\n## Context\n\nWe evaluated options.\n\n"
            "## Decision\n\nGo with option A.\n\n"
            "## Rationale\n\nBecause of cost.\n"
        )
        draft = _make_draft(kb_type="decision", body=body, tags=["a", "b", "c"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="decision")
        post = frontmatter.loads(result)
        assert "## Decision" in post.content
        assert not any("renamed" in w for w in warnings)

    def test_pitfall_correct_sections_no_warning(self):
        draft = _make_draft(kb_type="pitfall")
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="pitfall")
        assert not any("renamed" in w for w in warnings)

    def test_decision_with_symptoms_warns(self):
        body = (
            "\n## Symptoms\n\nSystem is slow.\n\n"
            "## Decision\n\nUse caching.\n"
        )
        draft = _make_draft(kb_type="decision", body=body, tags=["a", "b", "c"])
        normalizer = DraftNormalizer()
        result, warnings = normalizer.normalize(draft, kb_type="decision")
        assert any("## Symptoms" in w for w in warnings)
