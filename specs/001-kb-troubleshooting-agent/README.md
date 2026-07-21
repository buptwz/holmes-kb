# Holmes

> **Knowledge-driven troubleshooting, built for engineering teams.**

Holmes is an AI-powered troubleshooting assistant that learns from every incident your team resolves. It turns ad-hoc debugging sessions into a structured, searchable, and continuously improving knowledge base — shared across the entire organization.

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

### Structured Knowledge, Automatically

When you finish a debugging session, `/holmes-resolve` extracts the full troubleshooting arc — symptoms, root cause, and resolution — and structures it into a KB entry. No manual formatting, no templates to fill.

### Three-Gate Entry Validation

Every piece of knowledge passes three checks before entering the official KB:

1. **Schema validation** — required fields and sections must exist
2. **Deduplication** — Jaccard similarity check against existing entries (>85% blocks entry)
3. **Forced preview** — you must read the full content before confirming

This prevents low-quality or duplicate entries from polluting the knowledge base.

### Maturity Model

Knowledge is not binary. Entries evolve through three maturity levels:

| Level | Meaning | Promotion Condition |
|-------|---------|---------------------|
| `draft` | Newly added, unverified | — |
| `verified` | Referenced in at least 1 session | reference_count >= 1 |
| `proven` | Validated repeatedly across sessions | reference_count >= 3 |

Entries that haven't been referenced in a long time automatically decay (proven → verified after 365 days, verified → draft after 180 days), keeping the KB honest about what is actually current.

### Git-Native Collaboration

The knowledge base is a plain git repository. Holmes handles the complex part — intelligent conflict resolution for 5 distinct merge scenarios:

| Scenario | Resolution |
|----------|-----------|
| Two engineers add different entries | Automatic — keep both |
| Same entry, different reference counts | Automatic — take the higher value |
| Same entry, maturity both upgrading | Automatic — take the higher maturity |
| Same entry, non-content field differs | Automatic — take the newer timestamp |
| Same entry, actual content conflict | Isolated to `conflicts/` for human review |

Only genuine content disagreements require human judgment. Everything else merges automatically.

### LLM-Powered Import

Already have a collection of runbooks, incident reports, or engineering docs? `holmes import` passes any document through an LLM and produces a properly structured KB entry. No manual work required.

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

### Save What You Learned

```
/holmes-resolve
```

Run this at the end of any session. Holmes extracts the troubleshooting arc and queues it for review.

```bash
# Review what was extracted
holmes kb pending
holmes kb pending --show <id>

# Run 3-gate validation and confirm entry
holmes kb confirm <id>
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
holmes kb resolve <conflict-id> --side A   # or --side B or --manual

git push origin main
```

### Maintain KB Health

```bash
holmes kb lint          # report: stale pending, maturity decay, duplicates, orphans
holmes kb lint --fix    # auto-fix: rebuild indexes, apply maturity decay
holmes kb lint --report report.json   # machine-readable output for CI
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

## Design Principles

**No magic, no lock-in.** The knowledge base is a directory of Markdown files in a git repository. You can read, edit, search, and version-control every entry with standard tools. Holmes is a workflow accelerator, not a proprietary platform.

**Human in the loop, always.** Agents write to a staging area. Humans confirm. No entry enters the official KB without a human reading it first. The three-gate validation is not optional.

**Quality degrades gracefully.** Entries that aren't referenced decay in maturity. Knowledge that contradicts itself is flagged. The KB represents what is actually useful today, not what was true years ago.

**Collaboration without coordination.** The git-native workflow means engineers work independently. Merges are mostly automatic. Only genuine disagreements require discussion. No shared state, no locks, no central bottleneck.

---

## Contributing

Contributions to Holmes itself follow the standard GitHub flow: fork, branch, PR. The KB tooling is tested with a full functional test suite (65 test cases covering the complete lifecycle from import to merge conflict resolution).

To run the tests:

```bash
cd holmes-kb
pip install -e ".[dev]"
pytest tests/
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
