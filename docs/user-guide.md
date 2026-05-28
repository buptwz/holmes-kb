# Holmes User Guide

## Overview

Holmes is an AI-powered troubleshooting agent backed by a shared knowledge base.
It helps you diagnose and resolve technical problems, and automatically captures
solutions for future use.

## TUI Usage

### Starting Holmes

```bash
holmes         # Start TUI with default session
holmes tui     # Explicit form
```

### Chat Interface

Type your problem description and press **Enter** to send.

Holmes will:
1. Search the knowledge base for related patterns
2. Ask clarifying questions if needed
3. Run diagnostic commands (with your confirmation)
4. Propose solutions based on KB knowledge + AI reasoning

### Injecting Files

Prefix a file path with `@` to inject it into the conversation:

```
@/var/log/nginx/error.log
@/etc/nginx/nginx.conf
```

For files > 1MB or > 500 lines, Holmes shows the last 500 lines by default.

### Slash Commands

| Command | Description |
|---------|-------------|
| `/compact` | Compress conversation history to free up context |
| `/remember <text>` | Save a note to your persistent memory |
| `/` | Show available skills list |
| `/<skill-name>` | Execute a skill |

### Session Navigation

| Key | Action |
|-----|--------|
| Ctrl+H | Open session history list |
| Ctrl+K | Open knowledge base browser |
| Ctrl+R | Mark session resolved and extract knowledge |

### Tool Confirmations

When Holmes wants to execute a write operation or shell command, a confirmation
dialog appears:

- **[y]** — Allow the tool to execute
- **[n] or Esc** — Deny (session continues, Holmes adapts)

### Resolving a Session

After successfully troubleshooting a problem:

1. Press **Ctrl+R** to mark the session as resolved
2. Holmes extracts a structured knowledge entry
3. A confirmation dialog shows the entry preview
4. Approve to save it to `contributions/pending/`
5. Review and confirm with `holmes kb confirm <id>`

## CLI Reference

### Config

```bash
holmes config init              # Interactive setup wizard
holmes config show              # View current config
holmes config set model claude-opus-4-5-20251001
```

### Knowledge Import

```bash
holmes import <file>            # Auto-classify and import
holmes import <file> --type pitfall --category network
holmes import <file> --dry-run  # Preview without saving
```

### Knowledge Base Management

```bash
holmes kb pending               # List pending entries
holmes kb pending-show <id>     # View pending entry content
holmes kb confirm <id>          # 3-gate validation + confirm
holmes kb reject <id>           # Discard pending entry
holmes kb merge <id>            # Smart merge (5 scenarios)
holmes kb resolve <conflict-id> # Mark conflict resolved
holmes kb lint                  # Health check
holmes kb lint --fix            # Health check + auto-fix
holmes kb rebuild-index         # Rebuild index files
holmes kb list                  # List all entries
holmes kb list --type pitfall   # Filter by type
holmes kb show <id>             # Show full entry
```

### Session Management

```bash
holmes session list             # All sessions
holmes session list --status resolved
holmes session show <id>        # View session messages
```

## Persistent Memory

Holmes loads two memory files at the start of each session:

1. **`{kb_root}/HOLMES.md`** — Project-specific context (shared, in KB repo)
2. **`~/.holmes/MEMORY.md`** — Your personal preferences (local)

To add to your personal memory from TUI:
```
/remember Always check nginx logs first when debugging web issues
```

To edit project context, edit `{kb_root}/HOLMES.md` directly.

## Knowledge Base Structure

```
{kb_root}/
├── README.md              # Overview (human-maintained, ~50 lines)
├── CHANGELOG.md           # Auto-appended change log
├── index.json             # Machine-readable index (auto-generated)
├── pitfall/               # Fault patterns & troubleshooting steps
│   ├── _index.md
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── model/                 # Entity definitions
├── guideline/             # Best practices
├── process/               # Operational workflows
├── decision/              # Architecture decisions
└── contributions/
    ├── pending/           # Awaiting review
    ├── conflicts/         # Content contradictions
    └── log.md             # All contribution events
```

### Knowledge Entry Format

```markdown
---
id: PT-DB-001
type: pitfall
title: PostgreSQL connection pool exhaustion
maturity: verified
category: database
tags: [postgresql, connection-pool, performance]
created_at: 2026-05-26T10:00:00Z
updated_at: 2026-05-26T10:00:00Z
---

## Symptoms
- Application logs show "connection pool exhausted"
- Database connections at max_connections limit

## Root Cause
Long-running transactions holding connections

## Resolution
1. Check active connections: `SELECT count(*) FROM pg_stat_activity`
2. Kill long-running transactions
3. Adjust pool size in application config
```

### Maturity Levels

| Level | Meaning |
|-------|---------|
| draft | Newly added, untested |
| verified | Tested and confirmed to work |
| proven | Used successfully multiple times |

Entries auto-decay from `proven` to `verified` if not updated in 180 days.

## Git Workflow for Shared KB

```bash
cd ~/holmes-kb
git pull --rebase origin main   # Get latest
# ... add/confirm entries ...
git add .
git commit -m "Add: PT-NET-001 DNS resolution failure pattern"
git push origin main            # Share with team
```

For merge conflicts in Markdown files, use standard git merge tools.
The `contributions/log.md` uses append-only strategy — both sides' lines are kept.
