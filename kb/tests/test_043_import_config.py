"""Tests for import tunables in ~/.holmes/config.json (read_chunk_chars / direct_mode_char_limit).

Resolution: HolmesConfig value (>0) wins; 0/absent falls back to the code
defaults (READ_CHUNK_CHARS / DIRECT_MODE_CHAR_LIMIT).
"""

from __future__ import annotations

from holmes.config import HolmesConfig
from holmes.kb.agent.doc_access import READ_CHUNK_CHARS
from holmes.kb.agent.phases.summarizer import DIRECT_MODE_CHAR_LIMIT, SummarizerAgent


class TestHolmesConfigFields:
    def test_defaults_are_zero_meaning_unset(self) -> None:
        cfg = HolmesConfig()
        assert cfg.read_chunk_chars == 0
        assert cfg.direct_mode_char_limit == 0

    def test_from_dict_parses_ints(self) -> None:
        cfg = HolmesConfig.from_dict({"read_chunk_chars": 30000, "direct_mode_char_limit": "12000"})
        assert cfg.read_chunk_chars == 30000
        assert cfg.direct_mode_char_limit == 12000

    def test_from_dict_missing_keys(self) -> None:
        cfg = HolmesConfig.from_dict({})
        assert cfg.read_chunk_chars == 0
        assert cfg.direct_mode_char_limit == 0

    def test_roundtrip(self) -> None:
        cfg = HolmesConfig(read_chunk_chars=25000)
        assert HolmesConfig.from_dict(cfg.to_dict()).read_chunk_chars == 25000


class _StubProvider:
    """Minimal provider stub: records the first user message, returns JSON."""

    def __init__(self) -> None:
        self.user_messages: list[str] = []

    def complete(self, messages, system, tools, max_tokens, **kw):  # noqa: ANN001
        self.user_messages.append(str(messages[0].get("content")))
        return ("end_turn", [], messages + [{"role": "assistant", "content": "{}"}], {})

    def simple_complete(self, prompt, max_tokens=4096):  # noqa: ANN002
        return "{}"


class TestSummarizerResolution:
    def test_configured_chunk_used_in_tool_loop_prompt(self) -> None:
        provider = _StubProvider()
        agent = SummarizerAgent(provider=provider, model="test", read_chunk_chars=9000)  # type: ignore[arg-type]
        doc = "# T\n" + ("步骤内容。\n" * 4000)  # ~20K chars > default direct limit
        agent.run(doc, suggested_type="pitfall", ctx={})
        assert provider.user_messages, "provider was never called"
        assert "end_char=9000" in provider.user_messages[0]

    def test_zero_falls_back_to_default(self) -> None:
        agent = SummarizerAgent(provider=None, model="test", read_chunk_chars=0)  # type: ignore[arg-type]
        assert agent._read_chunk_chars == READ_CHUNK_CHARS
        assert agent._direct_mode_char_limit == DIRECT_MODE_CHAR_LIMIT

    def test_non_int_truthy_falls_back_to_default(self) -> None:
        # Regression: eval tests build the pipeline with a MagicMock cfg;
        # a truthy non-int must not reach the `total_chars <= limit` comparison.
        from unittest.mock import MagicMock

        agent = SummarizerAgent(
            provider=None, model="test",  # type: ignore[arg-type]
            read_chunk_chars=MagicMock(), direct_mode_char_limit=MagicMock(),
        )
        assert agent._read_chunk_chars == READ_CHUNK_CHARS
        assert agent._direct_mode_char_limit == DIRECT_MODE_CHAR_LIMIT

    def test_configured_direct_limit(self) -> None:
        agent = SummarizerAgent(provider=None, model="test", direct_mode_char_limit=12000)  # type: ignore[arg-type]
        assert agent._direct_mode_char_limit == 12000
