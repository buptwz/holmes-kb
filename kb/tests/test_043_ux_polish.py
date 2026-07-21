"""Tests for pre-release UX polish (spec 043):

empty-KB guide note, batch approve --all, approve git nudge,
image-reference survival note, holmes sync error path.
"""

from __future__ import annotations

from pathlib import Path

import frontmatter
from click.testing import CliRunner

from holmes.cli import cli
from holmes.config import HolmesConfig
from holmes.kb.pending import write_pending
from holmes.mcp.tools import handle_kb_browse


def _pending(kb: Path, title: str) -> str:
    return write_pending(kb, (
        f"---\ntype: pitfall\ntitle: {title}\ncategory: hardware\ntags: [a,b]\n---\n\n"
        "## Symptoms\nx\n\n## Root Cause\ny\n\n## Resolution\nz\n"
    ), source="auto")


class TestEmptyKbGuide:
    def test_empty_kb_gets_onboarding_note(self, tmp_path: Path) -> None:
        result = handle_kb_browse(tmp_path)
        assert "EMPTY" in result["guide"]
        assert "holmes import" in result["guide"]

    def test_non_empty_kb_no_note(self, tmp_path: Path) -> None:
        entry_dir = tmp_path / "pitfall" / "hardware"
        entry_dir.mkdir(parents=True)
        (entry_dir / "PT-HW-aaaaaa.md").write_text(
            "---\nid: PT-HW-aaaaaa\ntype: pitfall\ntitle: T\nmaturity: draft\n"
            "category: hardware\ntags: [a]\ncreated_at: '2024-01-01'\nupdated_at: '2024-01-01'\n"
            "---\n\n## Symptoms\nx\n\n## Root Cause\ny\n\n## Resolution\nz\n",
            encoding="utf-8",
        )
        result = handle_kb_browse(tmp_path)
        assert "EMPTY" not in result["guide"]


class TestBatchApprove:
    def test_approve_all(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        _pending(tmp_path, "条目一")
        _pending(tmp_path, "条目二")
        result = CliRunner().invoke(
            cli, ["--kb-path", str(tmp_path), "approve", "--all", "--skip-dedup"],
        )
        assert result.exit_code == 0, result.output
        assert "批量 approve 2 条" in result.output
        assert "2 成功, 0 失败" in result.output
        remaining = list((tmp_path / "contributions" / "pending").glob("*.md"))
        assert remaining == []
        confirmed = list((tmp_path / "pitfall" / "hardware").glob("PT-*.md"))
        assert len(confirmed) == 2

    def test_approve_all_empty(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["--kb-path", str(tmp_path), "approve", "--all", "--skip-dedup"],
        )
        assert result.exit_code == 0
        assert "No pending entries" in result.output

    def test_approve_without_id_errors(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["--kb-path", str(tmp_path), "approve"])
        assert result.exit_code == 1
        assert "entry ID" in result.output


class TestApproveGitNudge:
    def test_nudge_shown_when_git_repo(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        pid = _pending(tmp_path, "条目")
        result = CliRunner().invoke(
            cli, ["--kb-path", str(tmp_path), "approve", pid, "--no-interactive", "--skip-dedup"],
        )
        assert result.exit_code == 0, result.output
        assert "共享给团队" in result.output


class TestImageNote:
    def test_dropped_images_noted_in_entry(self, tmp_path: Path) -> None:
        from holmes.kb.agent.pipeline import ImportPipeline

        class _P:
            def __init__(self, r): self._r = list(r); self.calls = 0
            def complete(self, messages, system, model, max_tokens, tools=None):  # noqa: ANN001
                item = self._r[min(self.calls, len(self._r) - 1)]
                self.calls += 1
                return True, [], list(messages) + [{"role": "assistant", "content": str(item)}], {}
            def simple_complete(self, messages, system="", max_tokens=512):  # noqa: ANN001
                item = self._r[min(self.calls, len(self._r) - 1)]
                self.calls += 1
                return str(item)
            def append_tool_results(self, m, r):  # noqa: ANN001
                return m

        doc = (
            "# 眼图抖动排查\n\n## 现象\n眼图闭合。\n\n"
            "![眼图截图](./eye.png)\n\n## 排查\n1. [api:read] `dmesg`\n"
            + "内容行。\n" * 30
        )
        provider = _P([
            '{"doc_type":"incident","suggested_type":"pitfall","language":"zh",'
            '"is_multi_topic":false,"topic_boundaries":[],"branch_count":1,"reason":"i"}',
            '{"brief":"x","key_facts":["f1","f2"],"commands":[],"symptoms":["s1","s2"],'
            '"resolution_branches":[],"outline":[{"section":"Symptoms","description":"s"}],'
            '"steps":[],"decision_tree":""}',
            "---\ntype: pitfall\ntitle: 眼图抖动\ncategory: hardware\ntags: [a,b]\n---\n\n"
            "## Symptoms\n眼图闭合\n\n## Root Cause\n信号问题\n\n## Resolution\n1. dmesg\n",
        ])
        pipeline = ImportPipeline(
            kb_root=tmp_path, cfg=HolmesConfig(model="test"),
            no_interactive=True, _provider=provider,
        )
        report = pipeline.run(doc, file_path=None)
        assert not report.errors, report.errors
        pending = list((tmp_path / "contributions" / "pending").glob("*.md"))
        assert pending
        content = pending[0].read_text(encoding="utf-8")
        assert "📷" in content and "eye" not in content.split("📷")[0] or "📷" in content


class TestSync:
    def test_sync_not_a_git_repo(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(cli, ["--kb-path", str(tmp_path), "sync"])
        assert result.exit_code == 1
        assert "not a git repository" in result.output
