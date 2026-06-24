"""Tests for Phase 3 per-KP context isolation (US1 perf optimisation)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import frontmatter
import pytest

from holmes.config import HolmesConfig
from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
from holmes.kb.agent.provider.base import LLMProvider, ToolCall
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Minimal mock provider that records calls
# ---------------------------------------------------------------------------

class _RecordingProvider(LLMProvider):
    """Provider that records every complete() call's messages and returns stop=True."""

    def __init__(self):
        self.complete_calls: list[list[Any]] = []  # each entry = messages arg

    def complete(self, messages, system, model, max_tokens, tools):
        self.complete_calls.append(list(messages))
        return True, [], list(messages), {}

    def simple_complete(self, messages, system="", max_tokens=512):
        return ""

    def append_tool_results(self, messages, results):
        return list(messages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DRAFT_TEMPLATE = textwrap.dedent("""\
    ---
    id: {kp_id}
    type: pitfall
    title: {title}
    maturity: draft
    category: database
    tags: []
    created_at: "2026-01-01T00:00:00+00:00"
    updated_at: "2026-01-01T00:00:00+00:00"
    ---

    ## Root Cause

    {cause}

    ## Resolution

    {resolution}
""")


def _make_draft(kp_id: str, title: str, cause: str, resolution: str) -> str:
    return _DRAFT_TEMPLATE.format(
        kp_id=kp_id, title=title, cause=cause, resolution=resolution
    )


# ---------------------------------------------------------------------------
# Test: each LLM call gets isolated context (no sibling draft bleed)
# ---------------------------------------------------------------------------

def test_phase3_each_kp_gets_fresh_messages(tmp_path: Path) -> None:
    """Each KP's LLM loop must start with a fresh messages list.

    Verifies that the messages passed to complete() on KP #2 do not contain
    any draft content from KP #1.
    """
    provider = _RecordingProvider()
    cfg = HolmesConfig(api_key="test-key")

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=provider,
    )

    kp_drafts = {
        "kp-001": _make_draft("kp-001", "Alpha Error", "Alpha cause", "Alpha fix"),
        "kp-002": _make_draft("kp-002", "Beta Error", "Beta cause", "Beta fix"),
        "kp-003": _make_draft("kp-003", "Gamma Error", "Gamma cause", "Gamma fix"),
    }

    report = ImportReport(dry_run=True)
    ctx: dict[str, Any] = {
        "kb_root": tmp_path,
        "dry_run": True,
        "provider": provider,
        "model": cfg.model,
        "report": report,
        "source_hash": "abc123",
        "no_interactive": True,
        "source_text": "Alpha cause. Alpha fix. Beta cause. Beta fix. Gamma cause. Gamma fix.",
        "force_type": "",
        "force": False,
        "kp_drafts": kp_drafts,
    }

    pipeline._run_extraction_loop(
        source_text=ctx["source_text"],
        source_hash="abc123",
        file_path=None,
        ctx=ctx,
        report=report,
    )

    # Should have had exactly 3 separate complete() calls (one per KP).
    assert len(provider.complete_calls) == 3, (
        f"Expected 3 complete() calls (one per KP), got {len(provider.complete_calls)}"
    )

    # Each call should start with exactly one user message (fresh context).
    for i, call_messages in enumerate(provider.complete_calls):
        assert len(call_messages) == 1, (
            f"KP #{i+1}: expected 1 message (fresh context), got {len(call_messages)}"
        )
        assert call_messages[0]["role"] == "user"

    # Each prompt must contain exactly ONE draft block, not multiple.
    # (The source text itself is present in all prompts as reference material;
    #  the isolation guarantee is that sibling DRAFT blocks are absent.)
    for i, call_messages in enumerate(provider.complete_calls):
        prompt = call_messages[0]["content"]
        draft_block_count = prompt.count("--- Draft for kp-")
        assert draft_block_count == 1, (
            f"KP #{i+1} prompt must contain exactly 1 draft block, got {draft_block_count}"
        )

    # KP #2's prompt must NOT contain KP #1's draft block.
    kp2_prompt = provider.complete_calls[1][0]["content"]
    assert "--- Draft for kp-001 ---" not in kp2_prompt, (
        "KP #2 prompt must not contain KP #1's draft block header"
    )
    # KP #3's prompt must NOT contain KP #1 or KP #2 draft blocks.
    kp3_prompt = provider.complete_calls[2][0]["content"]
    assert "--- Draft for kp-001 ---" not in kp3_prompt
    assert "--- Draft for kp-002 ---" not in kp3_prompt


def test_phase3_each_kp_prompt_contains_only_its_draft(tmp_path: Path) -> None:
    """Each per-KP prompt must contain that KP's draft text."""
    provider = _RecordingProvider()
    cfg = HolmesConfig(api_key="test-key")

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=provider,
    )

    kp_drafts = {
        "kp-A": _make_draft("kp-A", "Error A", "Cause A unique", "Fix A unique"),
        "kp-B": _make_draft("kp-B", "Error B", "Cause B unique", "Fix B unique"),
    }

    report = ImportReport(dry_run=True)
    ctx: dict[str, Any] = {
        "kb_root": tmp_path,
        "dry_run": True,
        "provider": provider,
        "model": cfg.model,
        "report": report,
        "source_hash": "def456",
        "no_interactive": True,
        "source_text": "Cause A unique. Fix A unique. Cause B unique. Fix B unique.",
        "force_type": "",
        "force": False,
        "kp_drafts": kp_drafts,
    }

    pipeline._run_extraction_loop(
        source_text=ctx["source_text"],
        source_hash="def456",
        file_path=None,
        ctx=ctx,
        report=report,
    )

    assert len(provider.complete_calls) == 2

    # Each prompt should contain its own KP content.
    for call_messages in provider.complete_calls:
        prompt = call_messages[0]["content"]
        if "kp-A" in prompt:
            assert "Cause A unique" in prompt or "kp-A" in prompt
        elif "kp-B" in prompt:
            assert "Cause B unique" in prompt or "kp-B" in prompt


def test_skip_git_commit_flag(tmp_path: Path) -> None:
    """When skip_git_commit=True the pipeline must not call _git_commit."""
    provider = _RecordingProvider()
    cfg = HolmesConfig(api_key="test-key")

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=False,  # dry_run=False so git commit would normally run
        skip_git_commit=True,
        _provider=provider,
    )

    report = ImportReport(dry_run=False)
    ctx: dict[str, Any] = {
        "kb_root": tmp_path,
        "dry_run": False,
        "provider": provider,
        "model": cfg.model,
        "report": report,
        "source_hash": "xyz789",
        "no_interactive": True,
        "source_text": "test",
        "force_type": "",
        "force": False,
        "kp_drafts": {},
    }

    with patch("holmes.kb.agent.runner.ImportAgentRunner._git_commit") as mock_commit:
        pipeline._run_extraction_loop(
            source_text="test",
            source_hash="xyz789",
            file_path=None,
            ctx=ctx,
            report=report,
        )

    mock_commit.assert_not_called()


def test_no_drafts_fallback_uses_single_loop(tmp_path: Path) -> None:
    """When kp_drafts is empty, a single LLM loop (not per-KP) should run."""
    provider = _RecordingProvider()
    cfg = HolmesConfig(api_key="test-key")

    pipeline = ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        no_interactive=True,
        dry_run=True,
        _provider=provider,
    )

    report = ImportReport(dry_run=True)
    ctx: dict[str, Any] = {
        "kb_root": tmp_path,
        "dry_run": True,
        "provider": provider,
        "model": cfg.model,
        "report": report,
        "source_hash": "empty123",
        "no_interactive": True,
        "source_text": "some text",
        "force_type": "",
        "force": False,
        "kp_drafts": {},  # no drafts
    }

    pipeline._run_extraction_loop(
        source_text="some text",
        source_hash="empty123",
        file_path=None,
        ctx=ctx,
        report=report,
    )

    # Fallback: exactly one complete() call for the whole document.
    assert len(provider.complete_calls) == 1
