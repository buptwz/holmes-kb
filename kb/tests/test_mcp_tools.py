"""Tests for MCP tool handlers (042 redesign: kb_browse, kb_read, kb_confirm, kb_draft)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from holmes.mcp.tools import (
    _sanitize_title,
    handle_kb_browse,
    handle_kb_confirm,
    handle_kb_draft,
    handle_kb_read,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    return tmp_path


def _make_entry(
    kb_root: Path,
    entry_id: str = "PT-DB-001",
    title: str = "Test Entry",
    entry_type: str = "pitfall",
    category: str = "database",
    brief: str = "",
) -> Path:
    entry_dir = kb_root / entry_type / category
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    brief_line = f"brief: \"{brief}\"\n" if brief else ""
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: {entry_type}\n"
        f"title: {title}\n"
        f"maturity: draft\n"
        f"category: {category}\n"
        f"tags: [redis, memory]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f"{brief_line}"
        "---\n\n"
        "## Symptoms\n"
        "- High memory usage\n"
        "- Connection timeouts\n\n"
        "## Root Cause\n"
        "Redis OOM condition due to key expiry misconfiguration.\n\n"
        "## Resolution\n"
        "### Branch A: Flush keys\n"
        "1. [api] `redis-cli dbsize`\n"
        "2. [api] `redis-cli flushdb`\n\n"
        "### Branch B: Increase memory\n"
        "1. [api] `redis-cli config set maxmemory 4gb`\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_model_entry(kb_root: Path, entry_id: str = "MD-SVC-001") -> Path:
    entry_dir = kb_root / "model" / "infrastructure"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: model\n"
        f"title: Service Mesh Architecture\n"
        f"maturity: draft\n"
        f"category: infrastructure\n"
        f"tags: [istio, mesh]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f'brief: "Service mesh pattern for microservice communication"\n'
        "---\n\n"
        "## Overview\n"
        "A service mesh is an infrastructure layer for microservice communication.\n\n"
        "## Key Concepts\n"
        "- Sidecar proxy\n"
        "- Control plane\n"
        "- Data plane\n\n"
        "## Usage\n"
        "Deploy with Istio or Linkerd.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_process_entry(kb_root: Path, entry_id: str = "PR-OPS-001") -> Path:
    entry_dir = kb_root / "process" / "operations"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: process\n"
        f"title: Deploy Runbook\n"
        f"maturity: draft\n"
        f"category: operations\n"
        f"tags: [deploy]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        "---\n\n"
        "## Purpose\n"
        "Standard procedure for production deployments.\n\n"
        "## Steps\n"
        "1. Run tests\n"
        "2. Tag release\n"
        "3. Deploy to staging\n"
        "4. Verify health\n"
        "5. Deploy to production\n\n"
        "## Outcome\n"
        "Application deployed and verified.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_guideline_entry(kb_root: Path, entry_id: str = "GL-SEC-001") -> Path:
    entry_dir = kb_root / "guideline" / "security"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: guideline\n"
        f"title: API Key Rotation Policy\n"
        f"maturity: draft\n"
        f"category: security\n"
        f"tags: [api-key, rotation]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f'brief: "Rotate API keys every 90 days"\n'
        "---\n\n"
        "## Context\n"
        "API keys are long-lived credentials that pose security risk if leaked.\n\n"
        "## Guideline\n"
        "All API keys must be rotated every 90 days.\n\n"
        "## Rationale\n"
        "Limits blast radius of credential compromise.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_decision_entry(kb_root: Path, entry_id: str = "DC-ARCH-001") -> Path:
    entry_dir = kb_root / "decision" / "architecture"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: decision\n"
        f"title: Use PostgreSQL over MySQL\n"
        f"maturity: draft\n"
        f"category: architecture\n"
        f"tags: [database, postgresql]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
        f'brief: "PostgreSQL chosen for JSON support and extensibility"\n'
        "---\n\n"
        "## Context\n"
        "The team needed a database supporting JSON queries and custom types.\n\n"
        "## Decision\n"
        "Use PostgreSQL 16 for all new services.\n\n"
        "## Rationale\n"
        "Better JSON support, extensibility, and community ecosystem.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


# ---------------------------------------------------------------------------
# handle_kb_browse
# ---------------------------------------------------------------------------


class TestKbBrowse:
    def test_browse_full_index(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_browse(kb_root)
        assert "entries" in result
        assert "total" in result
        assert "session_id" in result
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["total_pages"] == 1

    def test_browse_includes_directory_and_guide(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_browse(kb_root)
        assert "directory" in result
        assert "by_type" in result["directory"]
        assert "by_category" in result["directory"]
        assert "guide" in result

    def test_browse_with_type_filter(self, kb_root: Path):
        _make_entry(kb_root)
        _make_model_entry(kb_root)
        result = handle_kb_browse(kb_root, type="model")
        assert all(e["type"] == "model" for e in result["entries"])

    def test_browse_type_filter_no_directory(self, kb_root: Path):
        """When filtering by type, directory overview is not included."""
        _make_entry(kb_root)
        result = handle_kb_browse(kb_root, type="pitfall")
        assert "directory" not in result

    def test_browse_session_id_generated(self, kb_root: Path):
        r1 = handle_kb_browse(kb_root)
        r2 = handle_kb_browse(kb_root)
        assert r1["session_id"] != r2["session_id"]

    def test_browse_entry_has_brief(self, kb_root: Path):
        _make_entry(kb_root, brief="Redis OOM troubleshooting")
        result = handle_kb_browse(kb_root)
        entry = result["entries"][0]
        assert entry["brief"] == "Redis OOM troubleshooting"

    def test_browse_entry_fallback_brief(self, kb_root: Path):
        _make_entry(kb_root)  # no brief in frontmatter
        result = handle_kb_browse(kb_root)
        entry = result["entries"][0]
        assert len(entry["brief"]) > 0

    def test_browse_empty_kb(self, kb_root: Path):
        result = handle_kb_browse(kb_root)
        assert result["entries"] == []
        assert result["total"] == 0

    def test_browse_lean_entry_structure(self, kb_root: Path):
        """Entry has id/type/title/maturity/brief — no tags, category."""
        _make_entry(kb_root, entry_id="PT-DB-001", title="Redis OOM")
        result = handle_kb_browse(kb_root)
        entry = result["entries"][0]
        assert set(entry.keys()) == {"id", "type", "title", "maturity", "brief", "applies_to"}

    def test_browse_directory_counts(self, kb_root: Path):
        _make_entry(kb_root)
        _make_model_entry(kb_root)
        result = handle_kb_browse(kb_root)
        by_type = result["directory"]["by_type"]
        assert by_type.get("pitfall", 0) == 1
        assert by_type.get("model", 0) == 1


# ---------------------------------------------------------------------------
# handle_kb_read — summary layer (default)
# ---------------------------------------------------------------------------


class TestKbReadSummary:
    def test_read_pitfall_summary(self, kb_root: Path):
        _make_entry(kb_root, entry_id="PT-DB-001", brief="Redis OOM fix")
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert result["id"] == "PT-DB-001"
        assert result["type"] == "pitfall"
        assert "symptoms" in result
        assert "root_cause" in result
        assert "resolution_overview" in result
        assert "next" in result
        assert "navigate" in result["next"] or "section" in result["next"]
        # Should NOT have full content
        assert "content" not in result

    def test_read_pitfall_symptoms_extracted(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert isinstance(result["symptoms"], list)
        assert len(result["symptoms"]) >= 1

    def test_read_pitfall_resolution_overview(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-001")
        overview = result["resolution_overview"]
        assert "Branch" in overview or "branches" in overview or "steps" in overview

    def test_read_model_summary(self, kb_root: Path):
        _make_model_entry(kb_root)
        result = handle_kb_read(kb_root, "MD-SVC-001")
        assert result["type"] == "model"
        assert "overview" in result
        assert "key_concepts" in result
        assert isinstance(result["key_concepts"], list)

    def test_read_process_summary(self, kb_root: Path):
        _make_process_entry(kb_root)
        result = handle_kb_read(kb_root, "PR-OPS-001")
        assert result["type"] == "process"
        assert "purpose" in result
        assert result["steps_count"] == 5

    def test_read_guideline_summary(self, kb_root: Path):
        _make_guideline_entry(kb_root)
        result = handle_kb_read(kb_root, "GL-SEC-001")
        assert result["type"] == "guideline"
        assert "context" in result
        assert "guideline" in result
        assert "API keys" in result["context"] or "credential" in result["context"]

    def test_read_decision_summary(self, kb_root: Path):
        _make_decision_entry(kb_root)
        result = handle_kb_read(kb_root, "DC-ARCH-001")
        assert result["type"] == "decision"
        assert "context" in result
        assert "decision" in result
        assert "PostgreSQL" in result["decision"]

    def test_read_not_found(self, kb_root: Path):
        result = handle_kb_read(kb_root, "NONEXISTENT")
        assert "error" in result


# ---------------------------------------------------------------------------
# handle_kb_read — full layer
# ---------------------------------------------------------------------------


class TestKbReadFull:
    def test_read_full_returns_content(self, kb_root: Path):
        _make_entry(kb_root, entry_id="PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001", full=True)
        assert "content" in result
        assert "## Symptoms" in result["content"]
        assert "## Resolution" in result["content"]

    def test_read_full_has_next_hint(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-001", full=True)
        assert "next" in result
        assert "kb_confirm" in result["next"]

    def test_read_full_includes_type_and_maturity(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-001", full=True)
        assert result["type"] == "pitfall"
        assert result["maturity"] == "draft"

    def test_read_pending_entry(self, kb_root: Path):
        # Create a pending entry
        pending_dir = kb_root / "contributions" / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            "id: pending-20260706-test\n"
            "type: pitfall\n"
            "title: Pending Test\n"
            "maturity: draft\n"
            "category: test\n"
            "tags: [test]\n"
            "pending: true\n"
            'created_at: "2024-01-01"\n'
            'updated_at: "2024-01-01"\n'
            "---\n\n"
            "## Symptoms\nTest\n\n## Root Cause\nTest\n\n## Resolution\nTest\n"
        )
        (pending_dir / "pending-20260706-test.md").write_text(content, encoding="utf-8")
        result = handle_kb_read(kb_root, "pending-20260706-test", full=True)
        assert result.get("pending") is True


# ---------------------------------------------------------------------------
# handle_kb_read — navigate + section
# ---------------------------------------------------------------------------


def _make_entry_with_contents(kb_root: Path, entry_id: str = "PT-DB-002") -> Path:
    """Create a pitfall entry WITH ## Contents section."""
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: pitfall\n"
        f"title: Redis OOM with Contents\n"
        f"maturity: draft\n"
        f"category: database\n"
        f"tags: [redis]\n"
        f'created_at: "2024-01-01"\n'
        f'updated_at: "2024-01-01"\n'
        f'brief: "Redis OOM due to misconfigured maxmemory"\n'
        "---\n\n"
        "## Contents\n\n"
        "| Section | Description |\n"
        "|---|---|\n"
        "| Symptoms | 2 observable symptoms: high memory, timeouts |\n"
        "| Root Cause | maxmemory misconfiguration |\n"
        "| Resolution | 2 branches, 3 commands |\n\n"
        "## Symptoms\n"
        "- High memory usage above 90%\n"
        "- Client connection timeouts after 30s\n\n"
        "## Root Cause\n"
        "Redis maxmemory not set, causing unbounded growth.\n"
        "Key expiry TTL misconfigured to never expire.\n\n"
        "## Resolution\n"
        "### Branch A: Flush keys\n"
        "1. [api] `redis-cli dbsize`\n"
        "2. [api] `redis-cli flushdb`\n\n"
        "### Branch B: Increase memory\n"
        "1. [api] `redis-cli config set maxmemory 4gb`\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


class TestKbReadNavigate:
    """Tests for detail='navigate' — Contents section."""

    def test_navigate_returns_contents(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", detail="navigate")
        assert "contents" in result
        assert "Symptoms" in result["contents"]
        assert "Root Cause" in result["contents"]
        assert "Resolution" in result["contents"]

    def test_navigate_lists_sections(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", detail="navigate")
        assert "sections" in result
        assert "Symptoms" in result["sections"]
        assert "Root Cause" in result["sections"]
        assert "Resolution" in result["sections"]

    def test_navigate_lists_branches(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", detail="navigate")
        assert "branches" in result
        assert len(result["branches"]) == 2

    def test_navigate_has_next_hints(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", detail="navigate")
        assert "section=" in result["next"]
        assert "branch=" in result["next"]

    def test_navigate_fallback_no_contents(self, kb_root: Path):
        """Legacy entries without ## Contents still work."""
        _make_entry(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-001", detail="navigate")
        assert "contents" in result
        # Should have a fallback section list
        assert "Symptoms" in result["contents"]

    def test_navigate_model_entry(self, kb_root: Path):
        _make_model_entry(kb_root)
        result = handle_kb_read(kb_root, "MD-SVC-001", detail="navigate")
        assert "sections" in result
        assert "Overview" in result["sections"]
        assert "Key Concepts" in result["sections"]


class TestKbReadSection:
    """Tests for section= parameter — read specific ## section."""

    def test_read_section_by_name(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", section="Symptoms")
        assert result["section"] == "Symptoms"
        assert "High memory" in result["content"]
        assert "connection timeout" in result["content"].lower()

    def test_read_section_root_cause(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", section="Root Cause")
        assert "maxmemory" in result["content"]

    def test_read_section_not_found(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", section="Nonexistent")
        assert "error" in result
        assert "available_sections" in result
        assert "Symptoms" in result["available_sections"]

    def test_read_section_has_next_hint(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002", section="Symptoms")
        assert "navigate" in result["next"]

    def test_read_model_section(self, kb_root: Path):
        _make_model_entry(kb_root)
        result = handle_kb_read(kb_root, "MD-SVC-001", section="Key Concepts")
        assert "Sidecar" in result["content"] or "sidecar" in result["content"].lower()


class TestKbReadSummaryContents:
    """Tests for summary level including Contents."""

    def test_summary_includes_contents(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002")
        assert "contents" in result
        assert "Symptoms" in result["contents"]

    def test_summary_includes_sections_list(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002")
        assert "sections" in result or "branches" in result

    def test_summary_next_hints_section_and_branch(self, kb_root: Path):
        _make_entry_with_contents(kb_root)
        result = handle_kb_read(kb_root, "PT-DB-002")
        assert "section=" in result["next"]
        assert "branch=" in result["next"]


# ---------------------------------------------------------------------------
# handle_kb_confirm
# ---------------------------------------------------------------------------


class TestKbConfirm:
    def test_confirm_not_found(self, kb_root: Path):
        result = handle_kb_confirm(kb_root, "NONEXISTENT", "session-1")
        assert result["ok"] is False
        assert result["reason"] == "not_found"

    def test_confirm_invalid_outcome(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_confirm(kb_root, "PT-DB-001", "session-1", outcome="wrong")
        assert result["ok"] is False
        assert result["reason"] == "invalid_outcome"

    def test_confirm_valid_solved(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_confirm(kb_root, "PT-DB-001", "session-1", outcome="solved")
        assert result["ok"] is True
        assert result["outcome"] == "solved"

    def test_confirm_valid_not_solved(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_confirm(kb_root, "PT-DB-001", "session-1", outcome="not_solved")
        assert result["ok"] is True
        assert result["outcome"] == "not_solved"

    def test_confirm_duplicate_session(self, kb_root: Path):
        _make_entry(kb_root)
        handle_kb_confirm(kb_root, "PT-DB-001", "session-1", outcome="solved")
        result = handle_kb_confirm(kb_root, "PT-DB-001", "session-1", outcome="solved")
        assert result["ok"] is False
        assert result["reason"] == "duplicate"

    def test_confirm_pending_rejected(self, kb_root: Path):
        pending_dir = kb_root / "_pending" / "pitfall" / "test"
        pending_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            "id: pending-test\n"
            "type: pitfall\n"
            "title: Pending\n"
            "maturity: draft\n"
            "category: test\n"
            "tags: []\n"
            'created_at: "2024-01-01"\n'
            'updated_at: "2024-01-01"\n'
            "---\n\n## Symptoms\nX\n\n## Root Cause\nX\n\n## Resolution\nX\n"
        )
        (pending_dir / "pending-test.md").write_text(content, encoding="utf-8")
        result = handle_kb_confirm(kb_root, "pending-test", "session-1")
        assert result["ok"] is False
        assert result["reason"] == "pending"


# ---------------------------------------------------------------------------
# handle_kb_draft
# ---------------------------------------------------------------------------


class TestSanitizeTitle:
    def test_normal_title(self):
        assert _sanitize_title("redis-oom-2026-06-23") == "redis-oom-2026-06-23"

    def test_strips_forward_slash(self):
        assert _sanitize_title("a/b") == "a_b"

    def test_strips_backslash(self):
        assert _sanitize_title("a\\b") == "a_b"

    def test_strips_dotdot(self):
        assert _sanitize_title("../etc/passwd") == "__etc_passwd"

    def test_empty_becomes_untitled(self):
        assert _sanitize_title("") == "untitled"


class TestKbDraft:
    def _make_config(self, username: str = "testuser") -> object:
        from holmes.config import HolmesConfig
        return HolmesConfig(username=username)

    def test_username_not_set_returns_error(self, kb_root: Path):
        cfg = self._make_config(username="")
        result = handle_kb_draft(kb_root, content="test content", title="draft", config=cfg)
        assert "error" in result

    def test_creates_draft_file(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="Redis OOM content", title="redis-oom", config=cfg)
        assert "error" not in result
        assert (kb_root / "_drafts" / "redis-oom.md").exists()

    def test_returns_ok_and_hint(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="content", title="test-draft", config=cfg)
        assert result["ok"] is True
        assert result["path"] == "_drafts/test-draft.md"
        assert "holmes import" in result["hint"]

    def test_frontmatter_contains_author(self, kb_root: Path):
        cfg = self._make_config(username="engineer01")
        handle_kb_draft(kb_root, content="content", title="my-draft", config=cfg)
        text = (kb_root / "_drafts" / "my-draft.md").read_text()
        assert "author: engineer01" in text

    def test_no_title_uses_timestamp_filename(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="content", title=None, config=cfg)
        assert result["path"].startswith("_drafts/")
        import re
        filename = result["path"].replace("_drafts/", "")
        assert re.match(r"\d{4}-\d{2}-\d{2}-\d{6}\.md", filename)

    def test_no_llm_called(self, kb_root: Path):
        import holmes.mcp.tools as mcp_tools
        cfg = self._make_config()
        assert not hasattr(mcp_tools, "ImportAgentRunner")
        result = handle_kb_draft(kb_root, content="content", title="no-llm", config=cfg)
        assert "error" not in result
