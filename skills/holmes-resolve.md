# /holmes-resolve

> ⚠️ 本文件属于旧版自建 agent 体系的引导资产，当前产品形态为 MCP server（见 docs/mcp-integration.md），本文件保留作示例。

Use this skill when the user confirms that a technical issue has been successfully resolved.

## Purpose

Extract the troubleshooting knowledge from the current session and save it to the
knowledge base pending area. This ensures the solution is available for future users
who encounter the same or similar issues.

## Execution Steps

1. **Summarize the session** — Identify the key elements from this conversation:
   - **Symptoms**: What the user observed (error messages, unexpected behavior, performance degradation)
   - **Root Cause**: What caused the issue (configuration, code bug, resource exhaustion, etc.)
   - **Resolution**: The exact steps taken to fix it

2. **Choose entry type and category**:
   - Type is almost always `pitfall` for troubleshooting sessions
   - Category for pitfall: `network` | `system` | `application` | `database`

3. **Build the KB entry** in Markdown with YAML frontmatter:
   ```markdown
   ---
   type: pitfall
   title: <concise title describing the problem>
   maturity: draft
   category: <network|system|application|database>
   tags: [<relevant-tag-1>, <relevant-tag-2>]
   created_at: ""
   updated_at: ""
   ---

   ## Symptoms
   <what the user observed>

   ## Root Cause
   <why it happened>

   ## Resolution
   <exact steps to fix, numbered if multiple>
   ```

4. **Call KbExtractAndSave** with the complete entry content.

5. **Report the result**:
   ```
   ✓ Knowledge saved to pending area
   Pending ID: <pending_id>

   To promote to the official knowledge base:
     holmes kb confirm <pending_id>
   ```

## Notes

- Only run this skill when the user explicitly confirms the issue is resolved.
- If the resolution is uncertain or experimental, set `maturity: draft` (it is by default).
- You may also call this skill if the user says phrases like "that fixed it", "it's working now",
  "issue resolved", or "let's save this".
