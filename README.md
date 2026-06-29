# Holmes

> **A self-evolving knowledge base for engineering teams — built from every incident you resolve.**

Holmes is an AI-powered troubleshooting assistant that turns debugging sessions into a shared, living knowledge base. It integrates with any MCP-compatible AI agent or runs as a standalone CLI. Every confirmed resolution automatically hardens into structured knowledge that the next engineer can query in seconds.

---

## The Problem

Every engineering team rediscovers the same failures. A Redis connection pool exhausts at 2 AM, someone debugs it for three hours, posts a Slack message, and the knowledge evaporates. Six months later a different engineer starts from scratch.

Static wikis go stale. Runbooks aren't consulted under pressure. Chat history is unsearchable. Holmes closes the loop.

---

## How It Works

```
Engineer describes a problem
        │
        ▼
  Agent searches KB ──► Found: PT-DB-001 "Redis Connection Pool Exhaustion"
        │
        ▼
  Agent reads entry, walks through resolution steps
        │
        ▼
  Problem resolved ──► Agent calls kb_confirm_entry (evidence written)
                        maturity: draft → verified → proven
                        (auto-promotes as more engineers confirm it)

  No matching entry? ──► Agent saves new entry to pending
                          holmes kb approve <id>   ← human reviews and publishes
```

Evidence is **always explicit** — reading an entry does not record evidence. Only a deliberate confirmation call does. This keeps maturity scores meaningful.

---

## Architecture

Holmes is two Python packages in one repo, installed together via a single command:

```
kb/          Python KB package — store, validator, import pipeline, MCP server
holmes/      Python CLI package — agent session loop, KB management commands
```

Both are installed with `pip install -e .` from the `holmes/` directory. The `kb` package is a dependency of the main package.

```
┌─────────────────────────────────────┐
│  holmes (CLI)                        │
│                                      │
│  holmes import <doc> ← LLM pipeline │
│  holmes kb ...       ← KB ops       │
│  holmes start        ← MCP server   │
└──────────────────┬──────────────────┘
                   │
                   ▼
     Knowledge Base (git repo)
     plain Markdown + YAML frontmatter
     contributions/evidence/  ← sidecar files, conflict-free git merges
```

**MCP server** (`holmes start`) exposes the KB as a standard MCP endpoint so any MCP-compatible AI agent — Claude, GPT-4o, or your own — can query and contribute knowledge with zero custom integration:

| MCP Tool | What it does |
|----------|-------------|
| `kb_overview` | KB structure: entry counts, skill count, categories, top tags, session_id |
| `kb_list` | Paginated entries or skills with previews |
| `kb_search` | Full-text keyword search across entries, ranked by relevance |
| `kb_read` | Full content of an entry or skill (SKILL.md) — unified routing by ID format |
| `kb_confirm` | Write evidence for a confirmed resolution (idempotent per session) |
| `kb_submit` | Submit natural-language description; processed by import pipeline into a pending entry |

---

## Quick Start

### 1. Install

```bash
# Clone the repo and install both packages
git clone <repo-url> && cd holmes
pip install -e .
```

Or install only the KB/MCP server package:
```bash
pip install holmes-kb
```

### 2. Set Up a Knowledge Base

```bash
# Use the included template
cp -r kb-template ~/holmes-kb
cd ~/holmes-kb && git init && git add . && git commit -m "init KB"
```

### 3. Configure

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --api-key <your-api-key>
```

Supports Anthropic and any OpenAI-compatible endpoint (OpenAI, Azure, Ollama, etc.).

### 4. Use

**Troubleshoot interactively:**
```bash
holmes "Redis connections timing out under load"
```

**Expose as MCP server (for Claude, GPT-4o, or any MCP client):**
```bash
holmes start                   # port 8765
holmes start --port 9000       # custom port
# MCP client config: { "url": "http://localhost:8765" }
```

**Import existing runbooks or incident reports:**
```bash
holmes import ./incident-report.md
holmes import --dir ./postmortems/
```

**Review and publish pending entries:**
```bash
holmes kb pending
holmes kb approve <id>
```

---

## Knowledge Base Structure

Plain Markdown files in a git repo — no proprietary format, no database.

```
~/holmes-kb/
├── pitfall/           # fault patterns and fixes
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── process/           # step-by-step diagnostic procedures (part of pitfall trees)
├── model/             # concept definitions
├── guideline/         # best practices
├── decision/          # architecture decisions
├── skills/            # reusable agent instruction packages (auto-generated)
├── _pending/          # awaiting human review (import pipeline output)
│   ├── pitfall/<category>/
│   └── process/<category>/
├── _import-state/     # Agent 1 DAG files (.dag.json) — import progress checkpoints
└── contributions/
    ├── evidence/       # per-session sidecar files (conflict-free git merges)
    └── archive/        # retired drafts
```

**Entry format:**

```markdown
---
id: PT-DB-001
type: pitfall
title: Redis Connection Pool Exhausted
maturity: proven
category: database
tags: [redis, connection-pool, timeout]
created_at: 2026-03-15T08:00:00Z
---

## Symptoms
Users report Redis operations timing out. Logs show: `ERR max number of clients reached`

## Root Cause
`maxclients` is set too low for current workload.

## Resolution
1. Check limit: `redis-cli CONFIG GET maxclients`
2. Increase: `redis-cli CONFIG SET maxclients 10000`
3. Make permanent: add `maxclients 10000` to `redis.conf`
```

**Maturity is evidence-driven, never set manually:**

| Level | Rule |
|-------|------|
| `draft` | 0 evidence records |
| `verified` | ≥ 1 confirmed resolution |
| `proven` | ≥ 2 distinct sessions **and** ≥ 2 distinct contributors |

Evidence decays over time: `proven` after 12 months without use drops to `verified`; `verified` after 6 months drops to `draft`. Run `holmes kb decay` to apply.

---

## Key Capabilities

- **AI import pipeline** — `holmes import` uses a two-agent DAG pipeline for fault-diagnosis documents: Agent 1 extracts a structured decision tree, Agent 2 generates tree-linked pitfall + process entries; other document types use the classic single-pass pipeline
- **Tree-structured pitfall entries** — pitfall documents import as a navigable tree: one pitfall root entry (symptoms → root cause → resolution routing) linked to multiple process entries (step-by-step diagnostics), with `child_entry_ids` enabling depth-first navigation
- **3-gate confirmation** — pending entries pass schema validation, deduplication check, and forced human preview before entering the official KB
- **Git-native collaboration** — evidence sidecars are individual JSON files; file additions never conflict, so concurrent confirmations from different engineers merge automatically
- **Automatic decay** — stale knowledge loses maturity, preventing the KB from becoming a graveyard of outdated entries
- **Skill generation** — import pipeline auto-creates agent instruction skills (SKILL.md) when a Resolution section has ≥ 3 command steps; skills serve as reusable agent instruction packages, not shell scripts

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/quickstart.md](docs/quickstart.md) | End-to-end setup in 10 minutes |
| [docs/kb-management.md](docs/kb-management.md) | Day-to-day KB operations: import, confirm, decay, git workflow |
| [docs/mcp-integration.md](docs/mcp-integration.md) | Connecting AI agents via MCP: tools, protocol, examples |
| [docs/reference.md](docs/reference.md) | Complete CLI flag reference for all commands |
| [docs/developer-guide.md](docs/developer-guide.md) | Architecture, package structure, adding tools |
| [docs/technical-debt.md](docs/technical-debt.md) | Known gaps and planned improvements |
| [docs/kb-data-model.md](docs/kb-data-model.md) | Authoritative KB data model: entry fields, maturity rules, evidence format, skill structure |
| [kb-template/](kb-template/) | Starter KB — copy this as your team's repo |

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
