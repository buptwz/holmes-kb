# Holmes Knowledge Base

This is a structured troubleshooting knowledge base managed by Holmes.
Entries use Markdown + YAML frontmatter and are version-controlled with Git.

## Entry Types

| Type | Directory | Description |
|------|-----------|-------------|
| pitfall | `pitfall/` | Known failures, fault patterns, and troubleshooting steps |
| model | `model/` | Entity definitions and conceptual domain knowledge |
| guideline | `guideline/` | Recommended and prohibited practices |
| process | `process/` | Step-by-step operational procedures |
| decision | `decision/` | Technical choices and architecture rationale |

## Pitfall Subcategories

- `pitfall/network/` — Network, connectivity, DNS, load-balancer issues
- `pitfall/system/` — OS, resource, kernel, hardware issues
- `pitfall/application/` — Application errors, bugs, runtime failures
- `pitfall/database/` — Database, cache, storage layer issues

## Contribution Flow

**Agents never write directly to the official KB.** All writes go through pending:

```bash
# Agent or MCP tool saves new knowledge to pending
holmes kb pending                          # review what's waiting

# Human reviews and confirms
holmes kb confirm <id>                     # 3-gate validate → official KB
                                           # adds first evidence record, maturity → verified

# Agent calls kb_confirm_entry after a KB entry helps resolve an issue
# → writes evidence sidecar, maturity auto-promotes when ≥2 sessions + ≥2 contributors

# Correct a verified/proven entry (never edit directly)
holmes kb write-pending --corrects <id> --content "$(cat corrected.md)"
holmes kb confirm <correction_id>          # saves snapshot → .history/, replaces original

# Commit and share
git add . && git commit -m "Add: PT-NET-001 ..."
git push
git pull --rebase    # evidence sidecar files auto-merge conflict-free
```

## Maturity Model

Maturity is computed automatically from evidence records — never set manually.

| Level | Rule |
|-------|------|
| `draft` | 0 evidence records |
| `verified` | ≥ 1 confirmed resolution |
| `proven` | ≥ 2 distinct sessions **and** ≥ 2 distinct contributors |

Run `holmes kb decay` periodically to demote stale entries (`proven` > 12 months,
`verified` > 6 months). Snapshots are saved to `.history/` before each demotion.

## Management Commands

```bash
# Read
holmes kb overview            # show this README + index summary
holmes kb search <query>      # full-text search
holmes kb show <id>           # read a full entry
holmes kb list                # list all entries
holmes kb history <id>        # list version snapshots

# Write (via pending)
holmes kb pending             # list pending entries
holmes kb confirm <id>        # confirm a pending entry
holmes kb reject <id>         # reject a pending entry

# Governance
holmes kb decay               # demote stale entries
holmes kb decay --dry-run     # preview only
holmes kb archive-orphans     # move evidence-empty drafts to archive
holmes kb check-conflicts     # list contradiction: true entries

# Maintenance
holmes kb lint                # health check
holmes kb rebuild-index       # rebuild index.json and _index.md files
holmes kb merge               # resolve git conflict markers
```
