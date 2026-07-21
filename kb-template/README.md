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

## Entry IDs

- **Permanent IDs** are minted at approve time with a random suffix: `PT-DB-a3f8c2`
  (type prefix + category abbreviation + 6 lowercase hex). They are not sequential.
- **Pending entries** carry temporary IDs like `pending-20260720-153000-ab1f`; after
  approval the temporary ID is kept in the entry's `former_id` field.

## Contribution Flow

**Agents never write directly to the official KB.** All writes go through drafts/pending:

```bash
# Agent saves a raw draft via the kb_draft MCP tool → _drafts/
holmes drafts                              # list drafts waiting to be imported
holmes import _drafts/<file>               # structure into contributions/pending/

# Human reviews and publishes
holmes pending                             # review what's waiting
holmes pending --show <pending-id>         # read full content
holmes approve <pending-id>                # dedup gate → mint permanent ID → publish

# Agent calls kb_confirm after a KB entry helps resolve an issue
# → writes evidence sidecar, maturity auto-promotes when ≥2 sessions + ≥2 contributors

# Correct a verified/proven entry — submit a correction proposal, then confirm
holmes write-pending --corrects PT-DB-a3f8c2 --file corrected.md
holmes confirm <pending-id>                # saves snapshot → .history/, replaces original

# Commit and share
git add . && git commit -m "Add: PT-NET-9c2d51 ..."
git push
git pull --rebase    # evidence sidecar files auto-merge conflict-free
```

Derived files stay out of git: `index.json` and `*/_index.md` are git-ignored and rebuilt
locally (`holmes rebuild-index`, on server start, after approve). `contributions/log.md`
is union-merged on pull.

## Maturity Model

Maturity is derived from evidence records at read time — never set manually
(the frontmatter field is only a cache).

| Level | Rule |
|-------|------|
| `draft` | 0 solved evidence records |
| `verified` | ≥ 1 confirmed resolution |
| `proven` | ≥ 2 distinct sessions **and** ≥ 2 distinct contributors |

Run `holmes decay` periodically to demote stale entries (`proven` > 12 months,
`verified` > 6 months). Snapshots are saved to `.history/` and a system `decayed`
evidence record is written before each demotion.

## Management Commands

All commands are top-level (`holmes <cmd>`); the legacy `holmes kb <cmd>` form still
works as a hidden alias for one version cycle.

```bash
# Read
holmes list                # list all entries
holmes show <id>           # read a full entry
holmes search <query>      # full-text search
holmes overview            # README + entry count

# Write (via pending)
holmes pending             # list pending entries
holmes pending --show <id> # show full pending entry content
holmes approve <id>        # publish a pending entry (mints permanent ID)
holmes confirm <id>        # 3-gate confirm (hand-written / correction proposals)
holmes reject <id>         # reject a pending entry

# Merge & conflict resolution
holmes merge               # resolve git conflicts (log union, index rebuild, isolate contradictions)
holmes resolve <id> --keep A|B   # resolve a conflict by choosing a side

# Maintenance
holmes lint                # health check
holmes doctor              # full self-diagnostic (--fix to auto-repair)
holmes decay               # maturity decay check
holmes rebuild-index       # rebuild index.json and _index.md files
```
