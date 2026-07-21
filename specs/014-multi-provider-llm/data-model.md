# Data Model: Multi-Provider LLM Configuration

**Feature**: 014-multi-provider-llm
**Date**: 2026-06-08

---

## Entity 1: HolmesConfig (extended)

Existing entity; `provider` field added.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| kb_path | str | `""` | Local path to the KB repository |
| model | str | `"gpt-4o"` | LLM model identifier |
| api_base_url | str | `""` | Custom base URL (empty = provider default) |
| api_key | str | `""` | API key for the chosen provider |
| log_level | str | `"WARNING"` | Logging verbosity |
| max_tokens | int | `4096` | Max tokens per completion |
| **provider** | **str** | **`"anthropic"`** | **Provider type: `"anthropic"` or `"openai"`** |

**Validation rules**:
- `provider` must be one of `{"anthropic", "openai"}`. Values not in this set are rejected at setup time with a user-friendly error.
- If `provider` is absent from the serialised config, deserialisation defaults to `"anthropic"` (backward compatibility).

---

## Entity 2: ToolCall

Normalised representation of a single tool call returned by the LLM, provider-agnostic.

| Field | Type | Description |
|-------|------|-------------|
| id | str | Provider-issued tool call identifier (used to correlate results) |
| name | str | Tool name (e.g., `"write_kb_entry"`) |
| input | dict[str, Any] | Parsed JSON arguments from the LLM |

---

## Entity 3: LLMProvider (interface)

Abstract interface satisfied by `AnthropicProvider` and `OpenAIProvider`.

| Method | Signature | Description |
|--------|-----------|-------------|
| complete | `(messages, system, model, max_tokens, tools) -> (stop, tool_calls, messages)` | One step of the tool-use loop |
| simple_complete | `(messages) -> str` | Single-turn text completion (no tools) |
| append_tool_results | `(messages, results) -> messages` | Append tool results in provider wire format |

---

## Entity 4: AnthropicProvider

Implements `LLMProvider` using the Anthropic SDK.

| Attribute | Source |
|-----------|--------|
| `_client` | `anthropic.Anthropic(api_key, base_url)` |
| `_model` | `cfg.model` |

Wire-format specifics:
- Tool definitions: passed as-is (Anthropic `input_schema` format).
- Tool results: appended as `{"role": "user", "content": [{"type": "tool_result", ...}]}`.
- Stop condition: `response.stop_reason == "end_turn"`.

---

## Entity 5: OpenAIProvider

Implements `LLMProvider` using the OpenAI SDK (compatible with OpenAI, Azure, Ollama, etc.).

| Attribute | Source |
|-----------|--------|
| `_client` | `openai.OpenAI(api_key, base_url)` |
| `_model` | `cfg.model` |

Wire-format specifics:
- Tool definitions: converted from Anthropic `input_schema` format to OpenAI `{"type": "function", "function": {"parameters": ...}}` format on every call.
- System prompt: prepended as `{"role": "system", "content": system}` to the messages list.
- Tool results: appended as separate `{"role": "tool", "tool_call_id": id, "content": text}` messages.
- Stop condition: `response.choices[0].finish_reason in {"stop", None}` with no tool calls.

---

## Entity 6: ProviderFactory

Stateless factory function `create_provider(cfg: HolmesConfig) -> LLMProvider`.

| Input | Output |
|-------|--------|
| `cfg.provider == "anthropic"` | `AnthropicProvider(cfg)` |
| `cfg.provider == "openai"` | `OpenAIProvider(cfg)` |
| unknown value | raises `ValueError` with descriptive message |

---

## State Transitions: Provider Configuration

```
[No config file]
       │ holmes setup --provider anthropic --api-key KEY
       ▼
[provider=anthropic, api_key=KEY]
       │ holmes setup --provider openai --api-key NEW_KEY
       ▼
[provider=openai, api_key=NEW_KEY]
       │ holmes setup --provider anthropic --api-key ORIG_KEY
       ▼
[provider=anthropic, api_key=ORIG_KEY]
```

Switching providers overwrites the entire config (no merge). Users must re-supply all fields when switching.

---

## File Layout (new files)

```text
kb/holmes/kb/agent/provider/
├── __init__.py          # exports: LLMProvider, ToolCall, create_provider
├── base.py              # LLMProvider ABC + ToolCall dataclass
├── anthropic_provider.py
├── openai_provider.py
└── factory.py           # create_provider(cfg) -> LLMProvider
```
