# Holmes

> **A self-evolving knowledge base for engineering teams — built from every incident you resolve.**

Holmes is an AI-powered troubleshooting assistant that turns ad-hoc debugging sessions into a structured, continuously improving knowledge base shared across the entire organization. Unlike static wikis or runbooks, Holmes actively manages the full lifecycle of every piece of knowledge — from automatic capture to maturity tracking to decay detection — so the KB stays accurate, trustworthy, and alive.

---

## Two-Repo Architecture

Holmes is split into two repositories that work together:

| Repo | Role |
|------|------|
| **[holmes-kb](https://github.com/buptwz/holmes-kb)** (this repo) | Python KB library — CLI, KB operations, TypeScript tool implementations, documentation |
| **[holmes-agent](https://github.com/buptwz/holmes-agent)** | AI agent TUI — a fork of [claude-code-best](https://github.com/claude-code-best/claude-code) with KB tools registered |

```
holmes-agent (TypeScript / Bun)          holmes-kb (Python)
┌──────────────────────────────┐         ┌──────────────────────────────┐
│  TUI + Agent loop            │         │  holmes CLI                  │
│  7 KB native tools  ─────────┼─────────▶  KB store / validator        │
│  HOLMES.md methodology       │  calls  │  merger / linter / importer  │
│  /holmes-resolve skill       │  CLI    │  git-native KB repo          │
└──────────────────────────────┘         └──────────────────────────────┘
```

**You need both repos for the full experience.** If you only want the KB CLI
(`holmes kb`, `holmes import`, `holmes setup`) without the agent TUI, this repo
is sufficient on its own.

---

## Getting Started with Both Repos

```bash
# 1. Install the KB CLI (this repo)
pip install holmes-kb

# 2. Build and install the agent (holmes-agent repo)
git clone https://github.com/buptwz/holmes-agent.git
cd holmes-agent && bun install && bun run build
ln -sf "$(pwd)/dist/cli-bun.js" ~/.bun/bin/holmes-agent

# 3. Set up a knowledge base
cp -r kb-template ~/holmes-kb
cd ~/holmes-kb && git init && git add . && git commit -m "init KB"

# 4. Configure once
holmes setup \
  --kb-path ~/holmes-kb \
  --model gpt-4o \
  --api-key <your-api-key> \
  --api-base-url https://api.openai.com/v1

# 5. Start troubleshooting
holmes-agent
```

---

## The Problem

Every engineering team rediscovers the same failures. A Redis connection pool exhausts at 2 AM, someone debugs it for three hours, writes a Slack message, and the knowledge evaporates. Six months later, a different engineer hits the same issue and starts from scratch.

Existing solutions fall short:
- **Wiki pages** go stale and are never consulted under pressure
- **Runbooks** are static documents that don't integrate with your debugging workflow
- **Chat history** is unsearchable and unstructured
- **Individual expertise** doesn't transfer when people leave

Holmes solves this by closing the loop: every debugging session automatically contributes to a living knowledge base that the next engineer can query in real time.

---

## How It Works

```
                    ┌─────────────────────────────────────────────┐
                    │              Holmes Agent (TUI)              │
                    │                                              │
  Engineer          │  "Redis connection keeps timing out"         │
  describes ───────>│                                              │
  problem           │  [KbSearch: "Redis timeout"]                 │
                    │  Found: PT-DB-001 Redis Connection Pool      │
                    │  [KbReadEntry: PT-DB-001]                    │
                    │                                              │
                    │  Based on KB entry PT-DB-001:                │
                    │  1. Check redis-cli INFO clients             │
                    │  2. Review maxclients configuration          │
                    │  3. Inspect for connection leaks ...         │
                    └─────────────────────────────────────────────┘
                                          │
                              Problem resolved
                                          │
                                          ▼
                               /holmes-resolve
                                          │
                    ┌─────────────────────────────────────────────┐
                    │          Knowledge Base (Git repo)           │
                    │                                              │
                    │  contributions/pending/                      │
                    │  └── auto-20260526-redis-timeout.md          │
                    │       type: pitfall                          │
                    │       maturity: draft                        │
                    │       ## Symptoms                            │
                    │       ## Root Cause                          │
                    │       ## Resolution   ◄── auto-generated     │
                    └─────────────────────────────────────────────┘
                                          │
                         holmes kb confirm <id>
                         (3-gate validation)
                                          │
                    ┌─────────────────────────────────────────────┐
                    │  pitfall/database/redis-conn-timeout.md      │
                    │  id: PT-DB-003                               │
                    │  maturity: draft → verified → proven         │
                    │  (promotes automatically as more engineers   │
                    │   reference it across sessions)              │
                    └─────────────────────────────────────────────┘
```

---

## Key Features

### Self-Evolving Knowledge Base

Most knowledge bases grow and rot. Holmes grows and improves.

**Automatic capture** — When you tell the agent a problem is resolved, it automatically extracts the full troubleshooting arc (Symptoms / Root Cause / Resolution) and structures it into a KB entry. No forms, no templates, no copy-pasting.

**Usage-driven maturity** — Every entry tracks how often it has been consulted across real troubleshooting sessions. Confidence levels promote automatically:

| Level | Meaning | Promoted when |
|-------|---------|--------------|
| `draft` | Captured, not yet validated by use | — |
| `verified` | Consulted and confirmed in at least 1 session | reference_count ≥ 1 |
| `proven` | Repeatedly validated across multiple sessions | reference_count ≥ 3 |

**Automatic decay** — Knowledge that hasn't been referenced in a long time loses its confidence level automatically: `proven → verified` after 365 days, `verified → draft` after 180 days. The KB reflects what is actually useful today, not what was relevant two years ago.

**Contradiction and duplicate detection** — The linter continuously scans for entries with conflicting content, near-duplicate titles (Jaccard similarity > 85%), and stale pending contributions — flagging them before they mislead anyone.

The result: a KB that gets more reliable as the team uses it, without any maintenance burden.

---

### Full Knowledge Lifecycle Management

Holmes manages knowledge from first capture to retirement across six stages:

```
Capture → Validate → Store → Mature → Monitor → Retire
```

| Stage | Mechanism |
|-------|-----------|
| **Capture** | Auto-extraction from sessions; LLM-powered import from any document |
| **Validate** | 3-gate confirmation: schema check → deduplication → forced human preview |
| **Store** | Plain Markdown + YAML frontmatter in a git repo — no proprietary format |
| **Mature** | Usage-driven promotion (draft → verified → proven) |
| **Monitor** | Periodic lint: decay detection, orphan files, contradiction keywords, index consistency |
| **Retire** | Git-tracked deletion or forced downgrade — full audit trail |

**Three-gate entry validation** ensures nothing enters the official KB without passing:
1. **Schema check** — required frontmatter fields and type-specific sections must exist
2. **Deduplication** — title similarity > 85% against existing entries blocks the entry
3. **Forced preview** — the submitter must read the full content before confirming

---

### Git-Native Team Collaboration

The knowledge base is a plain git repository. Every engineer works on their local clone; Holmes handles the hard part of merging — 5 scenarios, classified and resolved automatically:

| Conflict type | Resolution |
|---------------|-----------|
| Two engineers add different entries | Automatic — keep both |
| Same entry, only reference counts differ | Automatic — take the higher value |
| Same entry, maturity both moving up | Automatic — take the higher level |
| Same entry, non-content fields differ | Automatic — take the newer timestamp |
| Same entry, actual content conflict | Isolated to `conflicts/` for human review |

Only genuine content disagreements require human judgment. Everything else merges without intervention, regardless of team size.

---

## Installation

### Prerequisites

- Python >= 3.11
- git >= 2.30
- An OpenAI-compatible LLM API

### Install

```bash
pip install holmes-kb
```

### Configure

```bash
# Point Holmes at your knowledge base repository
holmes setup \
  --kb-path ~/holmes-kb \
  --model gpt-4o \
  --api-key sk-xxxx \
  --api-base-url https://api.yourprovider.com/v1
```

This writes the KB path to `~/.holmes/settings.json` so the agent always finds it, generates a `HOLMES.md` methodology file in the KB root, and deploys the `/holmes-resolve` skill.

---

## Usage

### Troubleshoot with the Agent

```bash
holmes-agent
```

Describe your problem in natural language. Holmes searches the KB first, reads the most relevant entry, and walks you through the proven resolution steps. If nothing matches, it falls back to general reasoning and clearly marks the response as not backed by KB.

### Knowledge Extraction is Automatic

When you tell the agent the issue is resolved — "that fixed it", "it's working now",
"issue solved" — the agent automatically invokes `/holmes-resolve`, extracts the
full troubleshooting arc (Symptoms / Root Cause / Resolution), and writes a
structured entry to `contributions/pending/`. No command needed.

You can also trigger it manually at any time:
```
/holmes-resolve
```

The only manual step is the quality gate — confirm from your terminal:

```bash
holmes kb pending                     # see what the agent generated
holmes kb pending --show <id>         # read the full entry before confirming
holmes kb confirm <id>                # 3-gate validate → official KB
```

### Import Existing Knowledge

```bash
# LLM classifies and structures any document automatically
holmes import ./incident-report.md

# Override classification if needed
holmes import ./runbook.md --type pitfall --category database

# Preview without writing
holmes import ./doc.md --dry-run
```

### Browse and Search

```bash
holmes kb list                          # all entries
holmes kb list --type pitfall           # by type
holmes kb list --category database      # by category
holmes kb list --query "redis timeout"  # keyword search
holmes kb show PT-DB-001                # full entry content
```

### Sync with the Team

```bash
cd ~/holmes-kb
git add . && git commit -m "feat(pitfall): add Redis connection pool guide"
git pull origin main --rebase

# If conflicts arise, Holmes handles them intelligently
holmes kb merge

# Human review only needed for genuine content conflicts
holmes kb resolve <conflict-id> --keep A   # or --keep B or --manual

git push origin main
```

### Maintain KB Health

```bash
holmes kb lint          # report: stale pending, maturity decay, duplicates, orphans
holmes kb lint --fix    # auto-fix: rebuild indexes, apply maturity decay
holmes kb lint --report           # machine-readable output for CI (JSON to stdout)
```

---

## Knowledge Base Structure

```
knowledge-base/
├── README.md                   # human-maintained overview (~50 lines)
├── index.json                  # machine-readable index (auto-generated)
├── CHANGELOG.md                # contribution log (append-only)
│
├── pitfall/                    # known failure patterns and fixes
│   ├── _index.md               # auto-generated category index
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── model/                      # concept definitions
├── guideline/                  # dos and don'ts
├── process/                    # step-by-step procedures
├── decision/                   # architecture decision records
│
└── contributions/
    ├── pending/                # entries awaiting review
    ├── conflicts/              # content disputes awaiting human resolution
    └── log.md                  # full contribution audit trail
```

Every entry is a Markdown file with YAML frontmatter:

```markdown
---
id: PT-DB-001
type: pitfall
title: Redis Connection Pool Exhausted
maturity: proven
category: database
tags: [redis, connection-pool, timeout]
created_at: 2026-03-15T08:00:00Z
updated_at: 2026-05-20T14:30:00Z
reference_count: 7
last_referenced: 2026-05-20T14:30:00Z
---

## Symptoms

Users report Redis operations timing out. Error logs show:
`ERR max number of clients reached`

## Root Cause

The `maxclients` configuration is set too low for the current workload.
High-traffic periods exhaust the connection pool, causing all new
connection attempts to fail immediately.

## Resolution

1. Check current limit: `redis-cli CONFIG GET maxclients`
2. Increase the limit: `redis-cli CONFIG SET maxclients 10000`
3. Make it permanent: add `maxclients 10000` to `redis.conf`
4. Audit client code for connection leaks (missing `.close()` calls)
5. Consider connection pooling at the application layer
```

Plain Markdown means every entry is human-readable, git-diffable, and reviewer-friendly.

---

## Agent Tools

Holmes Agent gets seven native KB tools — loaded at startup alongside `Read` and `Grep`, without any MCP protocol overhead:

| Tool | Access | Description |
|------|--------|-------------|
| `KbReadOverview` | read | KB README + all category indexes |
| `KbReadCategoryIndex` | read | Single category index |
| `KbReadEntry` | read | Full entry content by ID |
| `KbSearch` | read | Keyword search across titles and tags |
| `KbListPending` | read | Pending entries list |
| `KbWriteEntry` | write | Write content to pending area |
| `KbExtractAndSave` | write | Extract knowledge from session and save to pending |

Write tools trigger the standard agent permission confirmation flow — the engineer explicitly approves every write.

---

## CLI Reference

```
holmes setup               Configure KB path, model, and API credentials
holmes import <file>       Import any document into KB pending area
holmes config show         Display current configuration
holmes config set <k> <v>  Update a configuration value

holmes kb list             List knowledge entries (with filtering and pagination)
holmes kb show <id>        Display full entry content
holmes kb overview         KB README and category indexes
holmes kb pending          List pending entries
holmes kb pending --show   Show full pending entry content
holmes kb confirm <id>     3-gate validate and promote to official KB
holmes kb reject <id>      Discard a pending entry
holmes kb merge            Intelligent git conflict resolution (5 scenarios)
holmes kb resolve <id>     Choose a side for content contradiction conflicts
holmes kb lint             Health check: stale, decay, duplicates, orphans
holmes kb lint --fix       Auto-fix resolvable issues
holmes kb rebuild-index    Rebuild all _index.md and index.json files
```

---

## Observability

Holmes includes built-in telemetry that streams every KB operation to a Grafana dashboard — giving team leads real-time visibility into contribution activity and KB health.

**Admin (one time):**

```bash
cd telemetry/ && docker compose up -d
# Grafana → http://<server>:3000  (admin / holmes)
```

**Each contributor (one time):**

```bash
holmes setup --kb-path ~/holmes-kb \
  --otel-endpoint http://<server>:4318 \
  --contributor alice
```

After that, all KB commands report automatically in the background. See [telemetry/README.md](telemetry/README.md) for the full guide.

---

## Documentation

| Document | Description |
|----------|-------------|
| [OPERATIONS.md](OPERATIONS.md) | Complete operations manual — every command explained with parameters and real-world scenario walkthroughs |
| [telemetry/README.md](telemetry/README.md) | Observability quick start — 5-minute setup for admin and contributors |
| [telemetry/USER_GUIDE.md](telemetry/USER_GUIDE.md) | Full observability user manual — install, event reference, dashboard, custom config, troubleshooting |
| [telemetry/ARCHITECTURE.md](telemetry/ARCHITECTURE.md) | Observability architecture — data flow, buffer design, OTLP format, component details |
| [docs/quickstart.md](docs/quickstart.md) | Get started in 10 minutes |
| [docs/developer-guide.md](docs/developer-guide.md) | Architecture, IPC protocol, and contribution guide |
| [FORK_CHANGES.md](FORK_CHANGES.md) | How to integrate KB tools into a claude-code fork |
| [kb-template/](kb-template/) | Starter knowledge base — clone this as your team's KB repo |

---

## Design Principles

**No magic, no lock-in.** The knowledge base is a directory of Markdown files in a git repository. You can read, edit, search, and version-control every entry with standard tools. Holmes is a workflow accelerator, not a proprietary platform.

**Human in the loop, always.** Agents write to a staging area. Humans confirm. No entry enters the official KB without a human reading it first. The three-gate validation is not optional.

**Quality degrades gracefully.** Entries that aren't referenced decay in maturity. Knowledge that contradicts itself is flagged. The KB represents what is actually useful today, not what was true years ago.

**Collaboration without coordination.** The git-native workflow means engineers work independently. Merges are mostly automatic. Only genuine disagreements require discussion. No shared state, no locks, no central bottleneck.

---

## Contributing

Contributions to Holmes itself follow the standard GitHub flow: fork, branch, PR. The KB tooling is tested with a comprehensive test suite (680+ test cases covering the complete lifecycle from import to merge conflict resolution).

To run the tests:

```bash
cd holmes-kb
pip install -e ".[dev]"
pytest tests/
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
