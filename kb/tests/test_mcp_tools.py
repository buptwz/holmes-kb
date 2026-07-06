"""Tests for MCP tool handlers (Feature 031: MCP KB Channel)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from holmes.mcp.tools import (
    _is_entry_id,
    _is_text_file,
    _sanitize_title,
    handle_kb_draft,
    handle_kb_list,
    handle_kb_overview,
    handle_kb_read,
    handle_kb_search,
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
    skill_refs: Optional[list[str]] = None,
) -> Path:
    entry_dir = kb_root / "pitfall" / "database"
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / f"{entry_id}.md"
    skill_refs_line = ""
    if skill_refs:
        refs_yaml = ", ".join(f'"{s}"' for s in skill_refs)
        skill_refs_line = f"skill_refs: [{refs_yaml}]"
    content = (
        f"---\n"
        f"id: {entry_id}\n"
        f"type: pitfall\n"
        f"title: {title}\n"
        f"maturity: draft\n"
        f"category: database\n"
        f"tags: [redis, memory]\n"
        f'created_at: "2024-01-01T00:00:00+00:00"\n'
        f'updated_at: "2024-01-01T00:00:00+00:00"\n'
    )
    if skill_refs_line:
        content += skill_refs_line + "\n"
    content += (
        "---\n\n"
        "## Symptoms\n"
        "High memory usage.\n\n"
        "## Root Cause\n"
        "Redis OOM condition.\n\n"
        "## Resolution\n"
        "Flush unused keys.\n"
    )
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def _make_skill(kb_root: Path, name: str, description: str = "A test skill") -> Path:
    skill_dir = kb_root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        "## Overview\nSkill instructions here.\n\n"
        "## Steps\n1. Run the check script.\n",
        encoding="utf-8",
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Phase 2: Foundational helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_entry_id_valid(self):
        assert _is_entry_id("PT-DB-001")
        assert _is_entry_id("MD-SVC-003")
        assert _is_entry_id("GL-APP-099")

    def test_is_entry_id_invalid(self):
        assert not _is_entry_id("redis-oom-recovery")
        assert not _is_entry_id("pt-db-001")  # lowercase
        assert not _is_entry_id("PTDB001")  # no hyphens
        assert not _is_entry_id("")

    def test_is_text_file_valid(self, tmp_path: Path):
        for ext in [".sh", ".py", ".md", ".yaml", ".json", ".sql"]:
            f = tmp_path / f"file{ext}"
            f.touch()
            assert _is_text_file(f), f"Expected {ext} to be text"

    def test_is_text_file_binary(self, tmp_path: Path):
        for ext in [".png", ".jpg", ".pdf", ".zip", ".exe"]:
            f = tmp_path / f"file{ext}"
            f.touch()
            assert not _is_text_file(f), f"Expected {ext} to be binary"


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_overview
# ---------------------------------------------------------------------------


class TestKbOverview:
    def test_overview_basic_fields(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_overview(kb_root)
        assert "index" in result
        assert "total_entries" in result
        assert "skill_count" in result
        assert "session_id" in result
        assert "hint" in result

    def test_overview_skill_count_zero(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_overview(kb_root)
        assert result["skill_count"] == 0

    def test_overview_skill_count_with_skills(self, kb_root: Path):
        _make_entry(kb_root)
        _make_skill(kb_root, "redis-oom-recovery")
        _make_skill(kb_root, "nginx-reload")
        result = handle_kb_overview(kb_root)
        assert result["skill_count"] == 2

    def test_overview_session_id_is_string(self, kb_root: Path):
        result = handle_kb_overview(kb_root)
        assert isinstance(result["session_id"], str)
        assert len(result["session_id"]) > 0

    def test_overview_session_id_unique_per_call(self, kb_root: Path):
        r1 = handle_kb_overview(kb_root)
        r2 = handle_kb_overview(kb_root)
        assert r1["session_id"] != r2["session_id"]

    def test_overview_entry_index(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        _make_entry(kb_root, "PT-DB-002")
        result = handle_kb_overview(kb_root)
        assert result["total_entries"] == 2
        # Index is grouped by type → category
        assert "pitfall" in result["index"]
        assert "database" in result["index"]["pitfall"]
        ids = [e["id"] for e in result["index"]["pitfall"]["database"]]
        assert "PT-DB-001" in ids
        assert "PT-DB-002" in ids


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_list with type="skill"
# ---------------------------------------------------------------------------


class TestKbListSkill:
    def test_list_skill_empty(self, kb_root: Path):
        result = handle_kb_list(kb_root, type="skill")
        assert result["entries"] == []
        assert result["total"] == 0

    def test_list_skill_returns_skills(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM issues")
        _make_skill(kb_root, "nginx-reload", "Safely reload Nginx")
        result = handle_kb_list(kb_root, type="skill")
        assert result["total"] == 2
        ids = [e["id"] for e in result["entries"]]
        assert "redis-oom-recovery" in ids
        assert "nginx-reload" in ids

    def test_list_skill_entry_structure(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM issues")
        result = handle_kb_list(kb_root, type="skill")
        entry = result["entries"][0]
        assert "id" in entry
        assert "description" in entry
        assert entry["description"] == "Fix Redis OOM issues"

    def test_list_skill_hint_present(self, kb_root: Path):
        result = handle_kb_list(kb_root, type="skill")
        assert "hint" in result

    def test_list_entry_includes_hint(self, kb_root: Path):
        _make_entry(kb_root)
        result = handle_kb_list(kb_root)
        assert "hint" in result


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_read — unified addressing
# ---------------------------------------------------------------------------


class TestKbReadRouting:
    def test_read_entry_by_id(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert result.get("error") is None
        assert result["id"] == "PT-DB-001"
        assert result["type"] == "pitfall"

    def test_read_entry_includes_skill_refs_empty(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert "skill_refs" in result
        assert result["skill_refs"] == []

    def test_read_entry_includes_skill_refs_populated(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert len(result["skill_refs"]) == 1
        assert result["skill_refs"][0]["name"] == "redis-oom-recovery"

    def test_read_entry_usage_guide_with_skill_refs(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "PT-DB-001")
        assert "usage_guide" in result
        assert "redis-oom-recovery" in result["usage_guide"]

    def test_read_entry_not_found(self, kb_root: Path):
        result = handle_kb_read(kb_root, "PT-DB-999")
        assert "error" in result

    def test_read_entry_with_path_returns_error(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001")
        result = handle_kb_read(kb_root, "PT-DB-001", path="some/file.sh")
        assert "error" in result

    def test_read_skill_by_name(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery", "Fix Redis OOM")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert result.get("error") is None
        assert result["id"] == "redis-oom-recovery"
        assert result["type"] == "skill"
        assert result["description"] == "Fix Redis OOM"

    def test_read_skill_includes_linked_entries(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        _make_entry(kb_root, "PT-DB-001", skill_refs=["redis-oom-recovery"])
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert "linked_entries" in result
        assert "PT-DB-001" in result["linked_entries"]

    def test_read_skill_linked_entries_empty_when_none(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert result["linked_entries"] == []

    def test_read_skill_includes_files_list(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        # Add a script file
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "check.sh").write_text("#!/bin/bash\necho ok", encoding="utf-8")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        assert "files" in result
        assert "scripts/check.sh" in result["files"]

    def test_read_skill_files_excludes_binary(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        (skill_dir / "image.png").write_bytes(b"\x89PNG")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        files = result.get("files", [])
        assert not any("image.png" in f for f in files)

    def test_read_skill_files_excludes_skill_md(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        files = result.get("files", [])
        assert "SKILL.md" not in files

    def test_read_skill_not_found(self, kb_root: Path):
        result = handle_kb_read(kb_root, "nonexistent-skill")
        assert "error" in result

    def test_read_skill_content_excludes_frontmatter(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery")
        content = result.get("content", "")
        assert "---" not in content or content.startswith("##")


# ---------------------------------------------------------------------------
# Phase 3: handle_kb_read — skill subfile access
# ---------------------------------------------------------------------------


class TestKbReadSkillSubfile:
    def test_read_subfile_content(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        script_content = "#!/bin/bash\nredis-cli info memory"
        (scripts / "check.sh").write_text(script_content, encoding="utf-8")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="scripts/check.sh")
        assert result.get("error") is None
        assert result["id"] == "redis-oom-recovery"
        assert result["path"] == "scripts/check.sh"
        assert result["content"] == script_content

    def test_read_subfile_not_found(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="nonexistent.sh")
        assert "error" in result

    def test_read_subfile_binary_rejected(self, kb_root: Path):
        skill_dir = _make_skill(kb_root, "redis-oom-recovery")
        (skill_dir / "image.png").write_bytes(b"\x89PNG")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="image.png")
        assert "error" in result

    def test_read_subfile_path_traversal_rejected(self, kb_root: Path):
        _make_skill(kb_root, "redis-oom-recovery")
        result = handle_kb_read(kb_root, "redis-oom-recovery", path="../../etc/passwd")
        assert "error" in result

    def test_read_subfile_for_unknown_skill_returns_error(self, kb_root: Path):
        result = handle_kb_read(kb_root, "nonexistent-skill", path="check.sh")
        assert "error" in result


# ---------------------------------------------------------------------------
# Phase 4: handle_kb_search
# ---------------------------------------------------------------------------


class TestKbSearch:
    def test_search_returns_results(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM Fix")
        result = handle_kb_search(kb_root, query="redis")
        assert "items" in result
        assert "total" in result
        assert "hint" in result

    def test_search_finds_matching_entry(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis Memory OOM")
        result = handle_kb_search(kb_root, query="redis memory")
        ids = [item["id"] for item in result["items"]]
        assert "PT-DB-001" in ids

    def test_search_no_results_returns_empty(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Postgres deadlock")
        result = handle_kb_search(kb_root, query="kubernetes networking")
        assert result["items"] == []
        assert result["total"] == 0

    def test_search_item_structure(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM")
        result = handle_kb_search(kb_root, query="redis")
        if result["items"]:
            item = result["items"][0]
            assert "id" in item
            assert "title" in item
            assert "type" in item
            assert "maturity" in item
            assert "score" in item
            assert "brief" in item

    def test_search_type_filter(self, kb_root: Path):
        _make_entry(kb_root, "PT-DB-001", title="Redis OOM pitfall")
        result = handle_kb_search(kb_root, query="redis", type="pitfall")
        for item in result["items"]:
            assert item["type"] == "pitfall"

    def test_search_limit_respected(self, kb_root: Path):
        for i in range(5):
            _make_entry(kb_root, f"PT-DB-00{i + 1}", title=f"Redis entry {i}")
        result = handle_kb_search(kb_root, query="redis", limit=2)
        assert len(result["items"]) <= 2


# ---------------------------------------------------------------------------
# Phase D: handle_kb_draft
# ---------------------------------------------------------------------------


class TestSanitizeTitle:
    def test_normal_title(self):
        assert _sanitize_title("redis-oom-2026-06-23") == "redis-oom-2026-06-23"

    def test_strips_forward_slash(self):
        assert _sanitize_title("a/b") == "a_b"

    def test_strips_backslash(self):
        assert _sanitize_title("a\\b") == "a_b"

    def test_strips_dotdot(self):
        # ".." → "_", "/" → "_": "../etc/passwd" → "__etc_passwd"
        assert _sanitize_title("../etc/passwd") == "__etc_passwd"

    def test_empty_becomes_untitled(self):
        assert _sanitize_title("") == "untitled"


class TestKbDraft:
    """Tests for handle_kb_draft — pure file write, no LLM."""

    def _make_config(self, username: str = "testuser") -> object:
        from holmes.config import HolmesConfig
        return HolmesConfig(username=username)

    def test_username_not_set_returns_error(self, kb_root: Path, tmp_path: Path):
        cfg = self._make_config(username="")
        result = handle_kb_draft(kb_root, content="test content", title="draft", config=cfg)
        assert "error" in result
        assert "username" in result["error"]
        # No file written
        assert not (kb_root / "_drafts").exists()

    def test_creates_draft_file_with_title(self, kb_root: Path, tmp_path: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="Redis OOM content", title="redis-oom", config=cfg)
        assert "error" not in result
        draft_file = kb_root / "_drafts" / "redis-oom.md"
        assert draft_file.exists()

    def test_returns_saved_and_next_step(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="content", title="test-draft", config=cfg)
        assert result["saved"] == "_drafts/test-draft.md"
        assert result["next_step"] == "holmes import _drafts/test-draft.md"

    def test_frontmatter_contains_author(self, kb_root: Path):
        cfg = self._make_config(username="engineer01")
        handle_kb_draft(kb_root, content="content", title="my-draft", config=cfg)
        text = (kb_root / "_drafts" / "my-draft.md").read_text()
        assert "author: engineer01" in text

    def test_frontmatter_contains_saved_at(self, kb_root: Path):
        cfg = self._make_config()
        handle_kb_draft(kb_root, content="content", title="ts-draft", config=cfg)
        text = (kb_root / "_drafts" / "ts-draft.md").read_text()
        assert "saved_at:" in text

    def test_frontmatter_source_is_mcp_draft(self, kb_root: Path):
        cfg = self._make_config()
        handle_kb_draft(kb_root, content="content", title="src-draft", config=cfg)
        text = (kb_root / "_drafts" / "src-draft.md").read_text()
        assert "source: mcp.draft" in text

    def test_body_contains_content(self, kb_root: Path):
        cfg = self._make_config()
        handle_kb_draft(kb_root, content="## Symptoms\nHigh CPU", title="body-draft", config=cfg)
        text = (kb_root / "_drafts" / "body-draft.md").read_text()
        assert "## Symptoms\nHigh CPU" in text

    def test_no_title_uses_timestamp_filename(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="content", title=None, config=cfg)
        assert result["saved"].startswith("_drafts/")
        filename = result["saved"].replace("_drafts/", "")
        # Timestamp format: YYYY-MM-DD-HHMMSS.md
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}-\d{6}\.md", filename), f"Unexpected filename: {filename}"

    def test_title_with_path_separator_sanitized(self, kb_root: Path):
        cfg = self._make_config()
        result = handle_kb_draft(kb_root, content="content", title="foo/bar", config=cfg)
        assert "error" not in result
        # File should be foo_bar.md
        assert (kb_root / "_drafts" / "foo_bar.md").exists()

    def test_draft_dir_created_if_missing(self, kb_root: Path):
        cfg = self._make_config()
        assert not (kb_root / "_drafts").exists()
        handle_kb_draft(kb_root, content="content", title="new-draft", config=cfg)
        assert (kb_root / "_drafts").is_dir()

    def test_no_llm_called(self, kb_root: Path):
        """handle_kb_draft must not import or call ImportAgentRunner."""
        import holmes.mcp.tools as mcp_tools
        cfg = self._make_config()
        # Verify ImportAgentRunner is not referenced in tools module
        assert not hasattr(mcp_tools, "ImportAgentRunner"), (
            "ImportAgentRunner should not be importable from tools module"
        )
        # And calling handle_kb_draft completes without error
        result = handle_kb_draft(kb_root, content="content", title="no-llm", config=cfg)
        assert "error" not in result
