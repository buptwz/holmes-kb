# /holmes-search

Use this skill to proactively search the knowledge base for entries relevant to
the user's current issue or question.

## Purpose

Quickly find and present KB entries that match the user's troubleshooting context.
Useful when the user wants an explicit KB search rather than waiting for Holmes
to search automatically.

## Execution Steps

1. **Extract keywords** from the user's message or the current conversation context.
   - Focus on: error names, service names, symptoms, technology stack keywords.

2. **Call KbSearch** with the extracted keywords:
   ```
   KbSearch({ query: "<keywords>", limit: 5 })
   ```

3. **If results found** — present them clearly:
   ```
   Found N KB entries matching "<keywords>":

   1. [PT-DB-001] Redis Connection Pool Exhaustion (pitfall/database, verified)
      "Connection refused when load spikes above..."

   2. [PT-NET-003] DNS Resolution Timeout (pitfall/network, proven)
      "Intermittent failures resolving internal service names..."
   ```
   Then ask: "Would you like me to read the full content of any of these entries?"

4. **If no results found** — say so clearly and offer to reason from general knowledge:
   ```
   No matching KB entries found for "<keywords>".
   I can still help based on general knowledge — what's the specific error you're seeing?
   ```

5. **On follow-up** — if the user wants to read a full entry, call KbReadEntry with the entry ID.

## Usage

The user can invoke this skill explicitly:
- `/holmes-search Redis timeout`
- `/holmes-search kubernetes pod CrashLoopBackOff`
- `/holmes-search MySQL replication lag`
