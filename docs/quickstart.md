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
holmes start                   # Default: port 8765
holmes start --port 9000       # Custom port
```

MCP client config: `{ "url": "http://localhost:8765" }`

Your MCP-compatible AI agent (Claude, GPT-4o, etc.) can now call `kb_overview`,
`kb_list`, `kb_read`, `kb_confirm`, and `kb_submit` directly.

See [mcp-integration.md](mcp-integration.md) for the full tool reference and usage protocol.

## Step 5: Import Existing Knowledge

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
holmes kb pending
holmes kb confirm <id>
```

---

## Where to Go Next

| Guide | Description |
|-------|-------------|
| [kb-management.md](kb-management.md) | Day-to-day KB operations: import, confirm, decay, git workflow |
| [mcp-integration.md](mcp-integration.md) | Connecting AI agents via MCP: tools, protocol, examples |
| [reference.md](reference.md) | Complete CLI flag reference for all commands |
| [developer-guide.md](developer-guide.md) | Architecture, IPC protocol, adding tools |
