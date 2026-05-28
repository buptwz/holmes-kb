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

```
holmes import <file>          # import any document → pending area
holmes kb pending             # review pending entries
holmes kb confirm <id>        # 3-gate validation → official KB
git add . && git commit       # commit to your local repo
git push                      # share with everyone
git pull && holmes kb merge   # incorporate others' changes
```

If `git push` has conflicts, run `git pull`, resolve normally, then
`holmes kb merge` to handle any semantic content contradictions.

## Management Commands

```bash
holmes kb overview            # show this README + index summary
holmes kb search <query>      # full-text search
holmes kb show <id>           # read a full entry
holmes kb list                # list all entries
holmes kb pending             # list pending entries
holmes kb confirm <id>        # confirm (3-gate) a pending entry
holmes kb reject <id>         # reject a pending entry
holmes kb merge               # resolve git conflict markers
holmes kb lint                # health check
holmes kb lint --fix          # auto-fix index mismatches
```
