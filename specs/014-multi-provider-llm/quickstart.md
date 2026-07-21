# Quickstart: Multi-Provider LLM Configuration

**Feature**: 014-multi-provider-llm
**Date**: 2026-06-08

---

## Scenario 1: First-time setup with Anthropic provider

```bash
# Configure with Anthropic (default provider)
holmes setup --kb-path ~/holmes-kb --provider anthropic --api-key sk-ant-xxxx --model claude-3-5-sonnet-20241022

# Import a document
echo "Redis OOM: maxmemory policy evicts keys mid-transaction.\nFix: set maxmemory-policy to noeviction for transactional workloads." > /tmp/redis-oom.md
holmes import /tmp/redis-oom.md

# Expected: KB entry created, no provider-related errors
```

---

## Scenario 2: Setup with OpenAI provider

```bash
# Configure with OpenAI
holmes setup --kb-path ~/holmes-kb --provider openai --api-key sk-xxxx --model gpt-4o

# Import a document
holmes import /tmp/redis-oom.md

# Expected: import completes, KB entry created via OpenAI API
```

---

## Scenario 3: Azure OpenAI endpoint

```bash
# Configure with Azure OpenAI (custom base URL)
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --api-key <azure-key> \
  --api-base-url https://my-resource.openai.azure.com/ \
  --model gpt-4o

holmes import /tmp/redis-oom.md
# Expected: all LLM calls route to Azure endpoint
```

---

## Scenario 4: Local Ollama (no API key)

```bash
# Start Ollama locally first: ollama serve
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --api-key ollama \
  --api-base-url http://localhost:11434/v1 \
  --model llama3.1:8b-instruct-q4_K_M

holmes import /tmp/redis-oom.md
# Expected: import agent communicates with local Ollama endpoint
```

---

## Scenario 5: Switch from Anthropic to OpenAI

```bash
# Currently configured as anthropic
cat ~/.holmes/config.json | grep provider   # "provider": "anthropic"

# Switch to OpenAI
holmes setup --kb-path ~/holmes-kb --provider openai --api-key sk-xxxx --model gpt-4o

cat ~/.holmes/config.json | grep provider   # "provider": "openai"

# Next import uses OpenAI
holmes import /tmp/redis-oom.md
```

---

## Scenario 6: Error message shows provider name

```bash
# Configure with wrong key for provider
holmes setup --kb-path ~/holmes-kb --provider anthropic --api-key sk-WRONG_KEY --model claude-3-5-sonnet-20241022

holmes import /tmp/redis-oom.md
# Expected error output contains "provider: anthropic"
# Error: LLM authentication failed (provider: anthropic).
# Run 'holmes setup --provider anthropic --api-key <KEY>' to reconfigure.
```

---

## Integration Test Matrix

| Test case | Provider | api_base_url | Expected result |
|-----------|----------|-------------|----------------|
| T1: Valid Anthropic | anthropic | (empty) | Import succeeds |
| T2: Valid OpenAI | openai | (empty) | Import succeeds |
| T3: Azure endpoint | openai | custom URL | Import succeeds, traffic to custom URL |
| T4: Bad key, anthropic | anthropic | (empty) | Error mentions "anthropic" |
| T5: Bad key, openai | openai | (empty) | Error mentions "openai" |
| T6: No config | (none) | — | "LLM not configured" message |
| T7: Switch providers | anthropic→openai | — | Second import uses openai |
| T8: Backward compat | (no provider field in config) | — | Defaults to anthropic, import succeeds |
