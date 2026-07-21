# Research: Multi-Provider LLM Configuration

**Feature**: 014-multi-provider-llm
**Date**: 2026-06-08

---

## Decision 1: Provider Abstraction Strategy

**Decision**: Introduce a `LLMProvider` abstract base class in a new `kb/agent/provider/` package, with concrete `AnthropicProvider` and `OpenAIProvider` implementations. A `factory.py` module creates the correct provider from `HolmesConfig`.

**Rationale**: The Anthropic SDK and OpenAI SDK differ in three areas — request format (tool definitions), response parsing (tool call extraction), and message-building (tool results). Isolating these differences behind a provider interface satisfies the Open/Closed and Single Responsibility principles: `runner.py` and `tools.py` call a stable interface without branching on provider type.

**Alternatives considered**:
- In-place branching in `runner.py` (`if cfg.provider == "anthropic": ... else: ...`): rejected because it scatters provider logic across the codebase and makes adding future providers invasive.
- Separate runner implementations per provider: rejected as heavy duplication; all tool dispatch and gate logic is shared.

---

## Decision 2: LLMProvider Interface Design

**Decision**: The interface exposes two methods:
1. `complete(messages, system, model, max_tokens, tools) -> (stop: bool, tool_calls: list[ToolCall], messages: list)` — runs one completion step and appends the assistant turn to messages.
2. `simple_complete(messages) -> str` — lightweight non-tool call used by `compare_root_cause` and `verify_content` in `tools.py`.

**Rationale**: `runner.py`'s tool-use loop needs `complete()` only; `tools.py`'s verification sub-calls need `simple_complete()` only. Keeping them separate avoids forcing tool-definition awareness onto simple text completions.

**Alternatives considered**:
- Single `complete()` method with optional tools: introduces nullable overloads and ambiguity; rejected.

---

## Decision 3: Tool Definition Format

**Decision**: `TOOL_DEFINITIONS` in `tools.py` remains in Anthropic format (using `input_schema`). `OpenAIProvider` converts it internally to OpenAI format (`{"type": "function", "function": {"name": ..., "parameters": ...}}`), swapping `input_schema` → `parameters`.

**Rationale**: Anthropic format is already the source of truth. Converting at the provider boundary (not at definition time) means tool authors write once and both providers stay in sync automatically.

---

## Decision 4: Message Format Normalization

**Decision**: The `messages` list passed through the loop uses a "canonical" format. Each provider converts to its own wire format on the way in and appends responses in canonical format on the way out:
- Assistant turns: `{"role": "assistant", "content": ...}` (Anthropic format; OpenAI uses the same role key).
- Tool results (Anthropic): appended as `{"role": "user", "content": [{"type": "tool_result", "tool_use_id": id, "content": text}]}`.
- Tool results (OpenAI): appended as separate `{"role": "tool", "tool_call_id": id, "content": text}` messages.

The provider's `append_tool_results()` helper handles this difference so `runner.py` remains format-agnostic.

**Rationale**: The Anthropic format is used as canonical because it is already the baseline. The OpenAI provider translates the system prompt and initial messages on first call.

---

## Decision 5: Config Field Addition

**Decision**: Add `provider: str = "anthropic"` to `HolmesConfig`. When deserialising from a config file that lacks this field, the default `"anthropic"` ensures backward compatibility.

**Rationale**: Zero-migration approach — existing users' config files continue to work without modification; new field only matters when explicitly set.

---

## Decision 6: `holmes setup` CLI Extension

**Decision**: Add `--provider` option to `holmes setup` with choices `anthropic` and `openai`, defaulting to `anthropic`. The help text explains which providers are supported.

**Rationale**: Minimal change to the existing setup command; no new subcommand required. The `--provider` flag is optional so existing `holmes setup` invocations remain valid.

---

## Decision 7: Error Message Enhancement

**Decision**: All authentication and connectivity error messages in `cli.py` already reference "ANTHROPIC_API_KEY". After this change, the messages will use `cfg.provider` dynamically (e.g., "configured provider: anthropic" or "configured provider: openai"). The error prefix format becomes:
```
Error: LLM authentication failed (provider: {provider}).
Run 'holmes setup --provider {provider} --api-key <KEY>' to reconfigure.
```

**Rationale**: Users can instantly identify key-type mismatches without reading documentation.

---

## Existing Code Affected

| File | Change Required |
|------|----------------|
| `kb/holmes/config.py` | Add `provider` field to `HolmesConfig` |
| `kb/holmes/cli.py` | Add `--provider` to `setup_cmd`; update error messages |
| `kb/holmes/kb/agent/runner.py` | Replace `anthropic.Anthropic(...)` with `create_provider(cfg)`; refactor loop to use provider interface |
| `kb/holmes/kb/agent/tools.py` | Replace `client.messages.create` in `compare_root_cause` and `verify_content` with `provider.simple_complete()` |
| `kb/holmes/kb/agent/provider/` | New package (4 files: `__init__.py`, `base.py`, `anthropic_provider.py`, `openai_provider.py`, `factory.py`) |
| `kb/tests/test_integration.py` | Update mocks and add OpenAI provider test cases |

---

## Dependencies

- `anthropic` SDK: already installed
- `openai` SDK: add to `pyproject.toml` / `requirements.txt` if not already present

**Verify**: `pip show openai` to confirm availability in the environment.
