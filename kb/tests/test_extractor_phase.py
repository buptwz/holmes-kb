"""Unit tests for ExtractorAgent — Phase 2 context isolation (T021)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.phases.extractor import ExtractorAgent
from holmes.kb.agent.provider.base import LLMProvider, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_with_transcripts() -> tuple[LLMProvider, list[list[Any]]]:
    """Return a provider that records all messages per complete() call sequence.

    Each ExtractorAgent.run() invocation gets its own call sequence.
    Returns (provider, all_message_snapshots) where each element records
    the messages at the start of each complete() call.
    """
    provider = MagicMock(spec=LLMProvider)
    # List of (messages_at_call_time, response) tuples
    all_calls: list[tuple[list[Any], Any]] = []
    responses = [
        # First extractor: reads section and returns draft
        (False, [ToolCall(id="tc1", name="read_document_range", input={"start_char": 0, "end_char": 200})]),
        (True, []),  # stop after tool call
        # Second extractor: reads section and returns draft
        (False, [ToolCall(id="tc2", name="read_document_range", input={"start_char": 200, "end_char": 400})]),
        (True, []),  # stop after tool call
    ]
    call_idx = [0]

    def _complete(messages, system, model, max_tokens, tools):
        idx = call_idx[0]
        if idx >= len(responses):
            all_calls.append((list(messages), None))
            return True, [], messages, {}
        stop, tcs = responses[idx]
        all_calls.append((list(messages), (stop, tcs)))
        call_idx[0] += 1
        updated = messages + [{"role": "assistant", "content": f"step-{idx}"}]
        return stop, tcs, updated

    def _append_tool_results(messages, results):
        tool_results = [{"role": "tool", "tool_use_id": tid, "content": c} for tid, c in results]
        return messages + tool_results

    provider.complete.side_effect = _complete
    provider.append_tool_results.side_effect = _append_tool_results
    return provider, all_calls


def _make_simple_provider(draft_text: str = "---\ntype: pitfall\ntitle: Test\n---\n\n## Resolution\nFix it.") -> LLMProvider:
    """Provider that always returns a final text response (no tools)."""
    provider = MagicMock(spec=LLMProvider)
    call_count = [0]

    def _complete(messages, system, model, max_tokens, tools):
        call_count[0] += 1
        updated = messages + [{"role": "assistant", "content": draft_text}]
        return True, [], updated, {}

    provider.complete.side_effect = _complete
    provider.append_tool_results.side_effect = lambda msgs, results: msgs
    return provider


def _make_kp(kp_id: str, start: int, end: int, description: str = "test") -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id,
        description=description,
        section_start=start,
        section_end=end,
    )


# ---------------------------------------------------------------------------
# Context Isolation Tests
# ---------------------------------------------------------------------------


class TestExtractorContextIsolation:
    """Verify that each ExtractorAgent.run() starts with a fresh messages list."""

    SOURCE = "A" * 200 + "B" * 200

    def test_fresh_messages_each_run(self):
        """Each call to ExtractorAgent.run() starts with messages = [user_message].

        The user message for KP-2 must NOT contain any tool results from KP-1.
        """
        provider, all_calls = _make_provider_with_transcripts()
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}

        kp1 = _make_kp("kp-1", 0, 200, "Redis issue in section A")
        kp2 = _make_kp("kp-2", 200, 400, "MySQL issue in section B")

        # Run extractor for KP-1
        agent.run(kp1, km, ctx)
        # Record the messages length after KP-1
        kp1_call_count = provider.complete.call_count

        # Run extractor for KP-2 — messages must start fresh
        agent.run(kp2, km, ctx)

        # The first complete() call for KP-2 should have only 1 message (the user message)
        # and NOT contain any messages from KP-1's conversation.
        # We can verify this by checking the messages passed to complete() after KP-1 ran.
        # The all_calls list shows messages at each complete() invocation.

        # KP-2's first complete() call is at index 2 (after KP-1 used calls 0 and 1)
        if len(all_calls) >= 3:
            kp2_first_messages = all_calls[2][0]
            # KP-2 starts with exactly 1 message (the user prompt for kp-2)
            assert len(kp2_first_messages) == 1, (
                f"KP-2 started with {len(kp2_first_messages)} messages, expected 1 (fresh context). "
                f"Messages: {kp2_first_messages}"
            )

    def test_no_cross_contamination_in_tool_results(self):
        """Tool results from KP-1 must not appear in KP-2's message history."""
        provider, all_calls = _make_provider_with_transcripts()
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}

        kp1 = _make_kp("kp-1", 0, 200, "Redis")
        kp2 = _make_kp("kp-2", 200, 400, "MySQL")

        agent.run(kp1, km, ctx)
        agent.run(kp2, km, ctx)

        # Collect all messages that KP-2's run() passed to complete()
        if len(all_calls) >= 3:
            kp2_messages = all_calls[2][0]
            for msg in kp2_messages:
                # No message in KP-2's initial context should reference KP-1's tool ID
                content = str(msg.get("content", ""))
                assert "tc1" not in content, (
                    f"KP-2 messages contain reference to KP-1 tool call 'tc1': {content}"
                )

    def test_kp_description_in_user_prompt(self):
        """The user message for each KP must mention that KP's details."""
        provider = _make_simple_provider()
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": "x" * 500}

        kp = _make_kp("kp-42", 0, 250, "Redis connection pool exhausted")
        agent.run(kp, km, ctx)

        # Check the first complete() call's messages
        first_call = provider.complete.call_args_list[0]
        messages = first_call[1]["messages"] if first_call[1] else first_call[0][0]
        user_msg = messages[0]["content"]

        assert "kp-42" in user_msg
        assert "Redis connection pool exhausted" in user_msg
        assert "0" in user_msg and "250" in user_msg  # section offsets


# ---------------------------------------------------------------------------
# Return Value Tests
# ---------------------------------------------------------------------------


class TestExtractorReturnValue:
    SOURCE = "This is a test document about Redis OOM issues in production."

    def test_returns_string(self):
        """ExtractorAgent.run() returns a string."""
        provider = _make_simple_provider("---\ntype: pitfall\ntitle: Test\n---")
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}
        kp = _make_kp("kp-1", 0, len(self.SOURCE))
        result = agent.run(kp, km, ctx)
        assert isinstance(result, str)

    def test_returns_draft_from_last_assistant_message(self):
        """The draft returned is the content of the last assistant message."""
        draft = "---\ntype: pitfall\ntitle: Redis OOM\n---\n\n## Resolution\nRestart Redis."
        provider = _make_simple_provider(draft)
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}
        kp = _make_kp("kp-1", 0, len(self.SOURCE))
        result = agent.run(kp, km, ctx)
        assert result == draft

    def test_returns_empty_on_no_assistant_message(self):
        """Returns empty string if no assistant message was produced."""
        provider = MagicMock(spec=LLMProvider)
        provider.complete.return_value = (True, [], [])  # messages stays empty
        provider.append_tool_results.return_value = []
        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}
        kp = _make_kp("kp-1", 0, len(self.SOURCE))
        result = agent.run(kp, km, ctx)
        assert result == ""

    def test_doc_access_tool_calls_handled(self):
        """Tool calls to read_document_range are executed and results appended."""
        call_seq = [
            (False, [ToolCall(id="t1", name="read_document_range", input={"start_char": 0, "end_char": 30})]),
            (True, []),
        ]
        idx = [0]

        provider = MagicMock(spec=LLMProvider)

        def _complete(messages, system, model, max_tokens, tools):
            i = idx[0]
            idx[0] += 1
            if i >= len(call_seq):
                return True, [], messages + [{"role": "assistant", "content": "draft"}], {}
            stop, tcs = call_seq[i]
            updated = messages + [{"role": "assistant", "content": f"step{i}"}]
            return stop, tcs, updated

        provider.complete.side_effect = _complete
        provider.append_tool_results.side_effect = (
            lambda msgs, results: msgs + [{"role": "tool", "content": str(results)}]
        )

        agent = ExtractorAgent(provider=provider, model="test-model")
        km = KnowledgeMap()
        ctx = {"source_text": self.SOURCE}
        kp = _make_kp("kp-1", 0, len(self.SOURCE))

        agent.run(kp, km, ctx)

        # append_tool_results should have been called with the read_document_range result
        assert provider.append_tool_results.called


# ---------------------------------------------------------------------------
# D-1: _validate_and_repair_draft Tests
# ---------------------------------------------------------------------------


class TestValidateAndRepairDraft:
    """Tests for ExtractorAgent._validate_and_repair_draft() (D-1 fix)."""

    def test_valid_draft_returns_unchanged(self):
        """A properly formatted draft passes through unchanged."""
        draft = "---\ntype: pitfall\ntitle: Redis OOM\n---\n\n## Resolution\nFix it."
        repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)
        assert repaired == draft
        assert warning is None

    def test_empty_draft_returns_error(self):
        """Empty draft returns ('', error_message)."""
        repaired, warning = ExtractorAgent._validate_and_repair_draft("")
        assert repaired == ""
        assert warning is not None and len(warning) > 0

    def test_no_delimiter_returns_error(self):
        """Draft with no '---' at all is unrecoverable."""
        repaired, warning = ExtractorAgent._validate_and_repair_draft(
            "Here is the entry:\ntype: pitfall\ntitle: test"
        )
        assert repaired == ""
        assert warning is not None

    def test_prose_preamble_stripped(self):
        """Prose before the first '---' is stripped and draft becomes valid."""
        draft_with_preamble = (
            "Here is the KB entry:\n"
            "---\ntype: pitfall\ntitle: Redis OOM\n---\n\n## Resolution\nFix it."
        )
        repaired, warning = ExtractorAgent._validate_and_repair_draft(draft_with_preamble)
        assert repaired.startswith("---")
        assert "Here is the KB entry" not in repaired
        assert warning is not None  # repair was performed

    def test_missing_closing_delimiter_repaired(self):
        """Draft missing closing '---' gets it appended and becomes parseable."""
        draft_no_close = "---\ntype: pitfall\ntitle: Redis OOM\n\n## Resolution\nFix it."
        repaired, warning = ExtractorAgent._validate_and_repair_draft(draft_no_close)
        # After repair it must be parseable
        import frontmatter as _fm
        post = _fm.loads(repaired)
        assert post.metadata.get("type") == "pitfall"
        assert warning is not None  # repair note present

    def test_repaired_draft_is_parseable(self):
        """Repaired draft always passes frontmatter.loads() without exception."""
        drafts = [
            "---\ntype: pitfall\ntitle: Test\n---",
            "Here is:\n---\ntype: model\ntitle: T2\n---\nbody",
            "---\ntype: process\ntitle: T3\n",  # missing closing ---
        ]
        import frontmatter as _fm
        for d in drafts:
            repaired, _ = ExtractorAgent._validate_and_repair_draft(d)
            if repaired:
                _fm.loads(repaired)  # must not raise


# ---------------------------------------------------------------------------
# D-2: EXTRACTOR_SYSTEM_PROMPT verbatim instruction Tests
# ---------------------------------------------------------------------------


class TestExtractorSystemPromptVerbatim:
    """Verify EXTRACTOR_SYSTEM_PROMPT contains the verbatim-copy instruction (D-2)."""

    def test_prompt_contains_verbatim_instruction(self):
        """EXTRACTOR_SYSTEM_PROMPT must instruct the LLM to copy commands VERBATIM."""
        from holmes.kb.agent.phases.extractor import EXTRACTOR_SYSTEM_PROMPT
        assert "VERBATIM" in EXTRACTOR_SYSTEM_PROMPT or "verbatim" in EXTRACTOR_SYSTEM_PROMPT.lower()

    def test_prompt_instructs_resolution_section(self):
        """EXTRACTOR_SYSTEM_PROMPT must specifically mention ## Resolution for verbatim copy."""
        from holmes.kb.agent.phases.extractor import EXTRACTOR_SYSTEM_PROMPT
        assert "## Resolution" in EXTRACTOR_SYSTEM_PROMPT or "Resolution" in EXTRACTOR_SYSTEM_PROMPT

    def test_prompt_does_not_say_paraphrase_commands(self):
        """EXTRACTOR_SYSTEM_PROMPT must not tell LLM to paraphrase commands."""
        from holmes.kb.agent.phases.extractor import EXTRACTOR_SYSTEM_PROMPT
        # Should explicitly forbid paraphrasing commands
        lower = EXTRACTOR_SYSTEM_PROMPT.lower()
        # The prompt should say NOT to paraphrase
        assert "not paraphrase" in lower or "do not paraphrase" in lower or "not summarize" in lower


# ---------------------------------------------------------------------------
# T004 (021): resolution_commands {PARAM} → $PARAM conversion in runner dispatch
# ---------------------------------------------------------------------------


class TestRunnerParamConversion:
    """021 T004: runner.py converts {PARAM} placeholders to $PARAM in resolution_commands."""

    def test_param_placeholders_converted_to_dollar_syntax(self, tmp_path):
        """Given detect_commands returns line with {PARAM}, runner writes $PARAM to tool_input."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")

        cmd_candidate = MagicMock()
        cmd_candidate.line = "kubectl rollout restart deployment/{APP_NAME} -n {NAMESPACE}"

        captured_inputs = []

        def _capture_handler(_ctx, tool_input):
            captured_inputs.append(dict(tool_input))
            return {"created": True, "linked": True, "action": "created", "skill_dir": str(tmp_path)}

        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        # Inject a real entry into _created_entry_contents so the dispatch block triggers.
        runner._created_entry_contents["PT-TEST-001"] = (
            "---\ntitle: Test\ntype: pitfall\n---\n"
            "## Resolution\nkubectl rollout restart deployment/{APP_NAME} -n {NAMESPACE}\n"
        )

        with (
            patch("holmes.kb.skill.manager.detect_commands", return_value=[cmd_candidate]),
            patch.object(runner, "_gate_skill_create", return_value=True),
            patch("holmes.kb.agent.runner.TOOL_HANDLERS", {"create_skill_for_entry": _capture_handler}),
        ):
            runner._dispatch_tool(
                "create_skill_for_entry",
                {
                    "name": "deploy-restart",
                    "entry_id": "PT-TEST-001",
                    "description": "Restart deployment",
                    "resolution_commands": ["kubectl rollout restart deployment/{APP_NAME} -n {NAMESPACE}"],
                },
                {"report": MagicMock()},
            )

        assert len(captured_inputs) == 1
        cmds = captured_inputs[0]["resolution_commands"]
        # {APP_NAME} and {NAMESPACE} must become $APP_NAME and $NAMESPACE
        assert all("{" not in cmd for cmd in cmds), f"Braces still present: {cmds}"
        assert any("$APP_NAME" in cmd for cmd in cmds), f"$APP_NAME not found: {cmds}"
        assert any("$NAMESPACE" in cmd for cmd in cmds), f"$NAMESPACE not found: {cmds}"

    def test_commands_without_params_unchanged(self, tmp_path):
        """Commands without {PARAM} placeholders are not modified."""
        from unittest.mock import MagicMock, patch

        from holmes.config import HolmesConfig
        from holmes.kb.agent.runner import ImportAgentRunner

        kb_root = tmp_path / "kb"
        for d in ("pitfall/database", "contributions/pending", "skills"):
            (kb_root / d).mkdir(parents=True, exist_ok=True)

        cfg = HolmesConfig(kb_path=str(kb_root), model="test-model", api_key="key")

        cmd_candidate = MagicMock()
        cmd_candidate.line = "systemctl restart redis"

        captured_inputs = []

        def _capture_handler(_ctx, tool_input):
            captured_inputs.append(dict(tool_input))
            return {"created": True, "linked": True, "action": "created", "skill_dir": str(tmp_path)}

        with patch("holmes.kb.agent.runner.create_provider", return_value=MagicMock()):
            runner = ImportAgentRunner(kb_root=kb_root, cfg=cfg, no_interactive=True)

        runner._created_entry_contents["PT-TEST-002"] = (
            "---\ntitle: Test\ntype: pitfall\n---\n"
            "## Resolution\nsystemctl restart redis\n"
        )

        with (
            patch("holmes.kb.skill.manager.detect_commands", return_value=[cmd_candidate]),
            patch.object(runner, "_gate_skill_create", return_value=True),
            patch("holmes.kb.agent.runner.TOOL_HANDLERS", {"create_skill_for_entry": _capture_handler}),
        ):
            runner._dispatch_tool(
                "create_skill_for_entry",
                {
                    "name": "redis-restart",
                    "entry_id": "PT-TEST-002",
                    "description": "Restart Redis",
                    "resolution_commands": ["systemctl restart redis"],
                },
                {"report": MagicMock()},
            )

        assert len(captured_inputs) == 1
        cmds = captured_inputs[0]["resolution_commands"]
        assert cmds == ["systemctl restart redis"]


class TestExtractorPromptCodeBlockConstraint:
    """QA-18 (023): Extractor system prompt must instruct LLM that code blocks
    in ## Resolution contain only executable commands, not bare descriptive text."""

    def _get_system_prompt(self) -> str:
        from holmes.kb.agent.phases import extractor as ext_mod
        return ext_mod.EXTRACTOR_SYSTEM_PROMPT

    def test_prompt_requires_executable_only_in_code_blocks(self):
        """Prompt must state that code blocks contain ONLY executable bash commands."""
        prompt = self._get_system_prompt()
        assert "ONLY executable bash commands" in prompt or "only executable" in prompt.lower(), (
            "Extractor prompt must require code blocks contain only executable commands"
        )

    def test_prompt_forbids_bare_text_in_code_blocks(self):
        """Prompt must explicitly forbid bare descriptive text inside code blocks."""
        prompt = self._get_system_prompt()
        assert "bare" in prompt.lower() or "never" in prompt.lower(), (
            "Extractor prompt must forbid bare text inside code blocks"
        )

    def test_create_skill_schema_requires_executable_commands_only(self):
        """create_skill_for_entry resolution_commands schema must forbid non-command text."""
        from holmes.kb.agent import tools as tools_mod
        schema_desc = ""
        for tool_def in tools_mod.TOOL_DEFINITIONS:
            if tool_def.get("name") == "create_skill_for_entry":
                props = tool_def.get("input_schema", {}).get("properties", {})
                schema_desc = props.get("resolution_commands", {}).get("description", "")
                break
        assert "executable" in schema_desc.lower(), (
            "create_skill_for_entry resolution_commands schema must say 'executable'"
        )
        assert "plain text" in schema_desc.lower() or "do not" in schema_desc.lower(), (
            "create_skill_for_entry schema must forbid non-command text"
        )
