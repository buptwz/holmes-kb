# Quick Start

Get Holmes running in under 10 minutes.

## Prerequisites

| Dependency | Version | Check |
|------------|---------|-------|
| Python | ≥ 3.11 | `python3 --version` |
| LLM API key (Anthropic or OpenAI-compatible) | — | |

## Step 1: Install

```bash
pip install holmes-kb
```

## Step 2: Create a Knowledge Base

```bash
# Copy the included template as your KB repo
cp -r kb-template ~/holmes-kb
cd ~/holmes-kb && git init && git add . && git commit -m "init KB"
```

Or clone an existing team KB:
```bash
git clone <kb-repo-url> ~/holmes-kb
```

## Step 3: Configure

**Anthropic:**
```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --api-key <your-api-key>
```

**OpenAI / Azure / Ollama:**
```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider openai \
  --model gpt-4o \
  --api-key <your-api-key> \
  --api-base-url https://api.openai.com/v1
```

## Step 4: Expose as MCP Server

```bash
holmes start                   # Default: port 8765, local mode (127.0.0.1, no auth)
holmes start --port 9000       # Custom port
holmes start --mode central    # Shared server (requires: holmes config set mcp_token <token>)
```

MCP client config: `{ "url": "http://localhost:8765" }`

Your MCP-compatible AI agent (Claude, GPT-4o, etc.) can now call `kb_browse`,
`kb_read`, `kb_confirm`, and `kb_draft` directly.

See [mcp-integration.md](mcp-integration.md) for the full tool reference and usage protocol.

## Step 5: Import Existing Knowledge

Import requires a contributor identity — set it once:

```bash
holmes config set username <your-name>
```

```bash
# Single file
holmes import ./incident-report.md

# Batch import a directory
holmes import --dir ./postmortems/

# Preview without writing
holmes import ./incident.md --dry-run
```

## Step 6: Review and Publish Pending Entries

```bash
holmes pending
holmes approve <pending-id>    # mints a permanent ID, e.g. PT-DB-a3f8c2
```

---

## Where to Go Next

| Guide | Description |
|-------|-------------|
| [kb-management.md](kb-management.md) | Day-to-day KB operations: import, confirm, decay, git workflow |
| [mcp-integration.md](mcp-integration.md) | Connecting AI agents via MCP: tools, protocol, examples |
| [reference.md](reference.md) | Complete CLI flag reference for all commands |
| [user-guide.md](user-guide.md#observability-langfuse) | Optional Langfuse tracing for import pipeline |
| [developer-guide.md](developer-guide.md) | Architecture, package structure, adding tools |
