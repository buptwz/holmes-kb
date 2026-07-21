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
  Agent browses KB ──► Found: PT-DB-a3f8c2 "Redis Connection Pool Exhaustion"
        │
        ▼
  Agent reads entry, walks through resolution steps
        │                              (kb_read(full) records reference → resets decay timer)
        ▼
  Problem resolved ──► Agent calls kb_confirm(outcome="solved")
                        maturity: draft → verified → proven
                        (auto-promotes as more engineers confirm it)

  No matching entry? ──► Agent saves draft via kb_draft
                          holmes import _drafts/<file> → holmes approve <id>
                          ← human reviews and publishes
```

**Evidence lifecycle**: reading an entry (full) records a lightweight reference that keeps the entry alive in decay checks. A `kb_confirm` in the same session upgrades that record to `solved`/`not_solved`. Maturity is derived from the evidence records at read time — only `solved` outcomes promote it.

---

## Architecture

Holmes is two Python packages in one repo; only the KB package ships the `holmes` command:

```
kb/          Python KB package — store, validator, import pipeline, CLI, MCP server
             (declares the `holmes` script: holmes.cli:cli)
agent/       Legacy agent package — its script is `holmes-agent` (no `holmes` conflict)
```

Both are installed with `pip install -e .` from the repo root. The `kb` package provides the `holmes` CLI entry point and is a dependency of the main package.

```
┌─────────────────────────────────────┐
│  holmes (CLI)                        │
│                                      │
│  holmes import <doc> ← LLM pipeline │
│  holmes approve ...  ← KB ops       │
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
| `kb_browse` | Directory-style browsing: type → category → entries, with pagination and applicability filters |
| `kb_read` | Progressive disclosure: summary (default) or full content; section/branch navigation |
| `kb_confirm` | Record usage feedback: `solved` (promotes maturity) or `not_solved` (neutral) |
| `kb_draft` | Save a draft document without LLM processing |

Two deployment modes: `holmes start --mode local` (default — loopback bind, no auth, git-config identity) or `--mode central` (shared server — bearer token auth via `holmes config set mcp_token`, `contributor` parameter enforced on writes).

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

**Expose as MCP server (for Claude, GPT-4o, or any MCP client):**
```bash
holmes start                   # port 8765, local mode (loopback, no auth)
holmes start --port 9000       # custom port
holmes start --mode central    # shared server: token auth, contributor enforced
# MCP client config: { "url": "http://localhost:8765" }
```

**Import existing runbooks or incident reports:**
```bash
holmes config set username <your-name>     # required once before importing
holmes import ./incident-report.md           # one document = one KB entry
holmes import --dir ./postmortems/           # batch import a directory
holmes import ./incident-report.md --dry-run # preview without writing
holmes import ./incident-report.md --no-interactive  # skip confirmation gates
```

**Review and publish pending entries:**
```bash
holmes pending                  # list all pending entries
holmes approve <pending-id>     # review + publish; mints a permanent ID (e.g. PT-DB-a3f8c2)
holmes delete <id>              # soft-delete (moves to _trash/, recoverable via git)
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
├── process/           # step-by-step procedures
├── model/             # concept definitions
├── guideline/         # best practices
├── decision/          # architecture decisions
├── skills/            # reusable agent instruction packages
├── _drafts/           # agent-saved drafts (kb_draft)
└── contributions/
    ├── evidence/       # per-session sidecar files (conflict-free git merges)
    ├── pending/        # entries awaiting human review (import pipeline output)
    └── archive/        # retired stale drafts
```

`index.json` and `*/_index.md` are derived files — rebuilt locally (`holmes rebuild-index`, on server start, after approve) and git-ignored. `contributions/log.md` is union-merged on pull.

**Entry format:**

```markdown
---
id: PT-DB-a3f8c2
type: pitfall
title: Redis Connection Pool Exhausted
maturity: proven
category: database
tags: [redis, connection-pool, timeout]
brief: Redis maxclients too low causes connection timeout under load
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

**Maturity is evidence-driven, never set manually.** It is derived from the evidence sidecar records at read time; the frontmatter field is only a cache, recalibrated by `holmes rebuild-index`:

| Level | Rule |
|-------|------|
| `draft` | 0 solved evidence records |
| `verified` | ≥ 1 confirmed resolution (`kb_confirm(solved)`) |
| `proven` | ≥ 2 distinct sessions **and** ≥ 2 distinct contributors |

**Automatic lifecycle:**

| Event | Action |
|-------|--------|
| `proven` entry unreferenced for 12 months | Decays to `verified` |
| `verified` entry unreferenced for 6 months | Decays to `draft` |
| `draft` entry age > 30 days + unreferenced > 3 months | Archived (moved out of active index) |
| `kb_read(full)` called | Records lightweight reference (resets decay timer) |
| `kb_confirm(solved)` called | Records evidence (triggers maturity promotion) |

Decay is event-sourced: `holmes decay` writes a system `decayed` evidence record per demotion, so the derived maturity follows the demotion permanently. Run `holmes doctor` to detect lifecycle issues — it also checks **entry hygiene** (behavior-tag mistags and `applies_to` placeholder noise left by older pipeline versions, auto-repaired with `--fix`) and surfaces entries with **not_solved feedback** whose content may be wrong. To fix wrong content, submit a corrected version with `holmes write-pending --corrects <id>` and approve it — the old entry is deprecated automatically.

---

## Key Capabilities

- **One-document-one-entry import** — `holmes import` uses a three-phase LLM pipeline (Classifier → Summarizer → Generator) to convert any document into a single structured KB entry
- **Progressive disclosure** — `kb_read` returns a structured summary by default; agents drill into full content, specific sections, or individual resolution branches on demand
- **Evidence-driven lifecycle** — entries automatically promote (via `kb_confirm`) and decay (via time-based rules), preventing the KB from becoming a graveyard of outdated knowledge
- **Git-native collaboration** — evidence sidecars are individual JSON files; file additions never conflict, so concurrent confirmations from different engineers merge automatically
- **Deterministic LLM pipeline** — `temperature=0` for all LLM calls; validate → feedback → retry loop on every LLM output (inspired by claude-code agent loop)
- **Direct mode optimization** — documents under 8K chars skip the tool-use loop, reducing Summarizer from 3-7 LLM round trips to 1

---

## Import Pipeline

One document = one KB entry. Three LLM phases:

```
Source doc → Classifier (type + language detection)
                │
                ▼
          Summarizer (structured extraction: key_facts, commands, symptoms, branches)
                │
                ▼
          Type Inference (deterministic: override Classifier based on extracted content)
                │
                ▼
          Generator (format summary into KB Markdown with YAML frontmatter)
                │
                ▼
          Normalizer + Fidelity Check (validate → feedback → retry, max 2 retries)
                │
                ▼
          contributions/pending/  (awaiting human review — holmes approve)
```

### Import Options

```bash
holmes import <file>                   # auto-detect type
holmes import <file> --type pitfall    # force document type (skip Classifier)
holmes import <file> --dry-run         # preview: run Classifier only, no writes
holmes import <file> --no-interactive  # suppress all confirmation prompts
holmes import <file> --force           # skip duplicate check
holmes import --dir ./docs/            # batch import all files in a directory
```

### Stability

- **No hangs**: all API calls have a 120s timeout with automatic retry (2 retries on timeout/connection/5xx errors)
- **Verbatim fidelity**: shell commands, API endpoints, URLs, error codes, and file paths are copied character-for-character from source documents — never paraphrased
- **Turn limits**: all LLM loops have hard turn caps to prevent infinite loops
- **Fallback extraction**: if Summarizer LLM fails completely, regex-based extraction ensures the pipeline never dies

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/scenarios.md](docs/scenarios.md) | **Start here** — scenario-first cookbook (中文): setup, import, troubleshooting, corrections, git collaboration, central deployment |
| [docs/quickstart.md](docs/quickstart.md) | End-to-end setup in 10 minutes |
| [docs/kb-management.md](docs/kb-management.md) | Day-to-day KB operations: import, confirm, decay, git workflow |
| [docs/mcp-integration.md](docs/mcp-integration.md) | Connecting AI agents via MCP: tools, protocol, examples |
| [docs/reference.md](docs/reference.md) | Complete CLI flag reference for all commands |
| [docs/developer-guide.md](docs/developer-guide.md) | Architecture, package structure, adding tools |
| [docs/technical-debt.md](docs/technical-debt.md) | Known gaps and planned improvements |
| [docs/kb-data-model.md](docs/kb-data-model.md) | Authoritative KB data model: entry fields, maturity rules, evidence format |
| [kb-template/](kb-template/) | Starter KB — copy this as your team's repo |

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
