# CLI Contract: Multi-Provider LLM Configuration

**Feature**: 014-multi-provider-llm
**Date**: 2026-06-08

---

## Command: `holmes setup` (extended)

### Signature

```
holmes setup
  --kb-path   TEXT   (required) Local path to the cloned KB repository
  --model     TEXT   (default: gpt-4o) Model identifier
  --api-key   TEXT   (default: "")    API key for the provider
  --api-base-url TEXT (default: "")   Base URL for OpenAI-compatible API
  --provider  [anthropic|openai]      (default: anthropic) LLM provider type
```

### Behaviour Contract

| Condition | Expected output | Exit code |
|-----------|----------------|-----------|
| `--provider anthropic` with valid args | Saves config, prints `✓ Config saved` | 0 |
| `--provider openai` with valid args | Saves config with `provider=openai`, prints `✓ Config saved` | 0 |
| `--provider` omitted | Defaults to `anthropic`, saves config | 0 |
| `--provider` with unknown value | Click error: `Invalid value for '--provider': 'X' is not one of 'anthropic', 'openai'` | 2 |

### Persistence

After a successful `holmes setup`:
- `~/.holmes/config.json` contains `"provider": "<value>"` alongside existing fields.
- Re-running with a different `--provider` overwrites the previous `provider` value.

---

## Command: `holmes import` (error messages)

### Error: No API Key / Authentication Failure

```
Error: LLM authentication failed (provider: {provider}).
Run 'holmes setup --provider {provider} --api-key <KEY>' to reconfigure.
EXIT: 1
```

Where `{provider}` is the value of `cfg.provider` from the current configuration.

### Error: No Configuration

```
Error: LLM not configured.
Run 'holmes setup --kb-path <PATH> --provider <anthropic|openai> --api-key <KEY>'
EXIT: 1
```

### Error: Dry-run with no type and no LLM (unchanged)

```
No LLM configured. To preview without LLM, provide --type (e.g. --type pitfall).
To configure LLM: holmes setup --provider <anthropic|openai> --api-key <KEY>
EXIT: 0
```

---

## Provider Interface Contract

### `LLMProvider.complete()`

| Input | Type | Description |
|-------|------|-------------|
| messages | list | Current message history |
| system | str | System prompt |
| model | str | Model identifier |
| max_tokens | int | Max tokens for response |
| tools | list[dict] | Tool definitions in Anthropic `input_schema` format |

| Output | Type | Description |
|--------|------|-------------|
| stop | bool | `True` if no more tool calls; loop should exit |
| tool_calls | list[ToolCall] | Parsed tool calls from the response |
| messages | list | Updated messages with assistant turn appended |

**Guarantee**: If `stop=True`, `tool_calls` is empty. If `tool_calls` is non-empty, `stop=False`.

### `LLMProvider.simple_complete()`

| Input | Type | Description |
|-------|------|-------------|
| messages | list | `[{"role": "user", "content": system_and_user_combined}]` |

| Output | Type | Description |
|--------|------|-------------|
| text | str | Raw text from the LLM response |

**Guarantee**: Never returns an empty string; raises `ProviderError` on failure.

### `LLMProvider.append_tool_results()`

| Input | Type | Description |
|-------|------|-------------|
| messages | list | Current message history |
| results | list[tuple[str, str]] | `[(tool_use_id, json_content), ...]` |

| Output | Type | Description |
|--------|------|-------------|
| messages | list | Updated messages with tool results appended in provider format |
