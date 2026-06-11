<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at specs/027-kb-mcp-server/plan.md
<!-- SPECKIT END -->

## detect-commands Usage Constraint

When calling `holmes kb skill detect-commands` (or `detect_commands()` programmatically),
pass **only the actionable steps section content** of a KB entry, not the full entry text.

This section may be headed `## Resolution`, `## Steps`, or one of the supported Chinese
equivalents: `## 解决方案`, `## 解决步骤`, `## 解决`, `## 恢复步骤`, `## 恢复`,
`## 诊断步骤`, `## 操作步骤`, `## 修复步骤`, `## 修复`, `## 处理步骤`, `## 处理方案`.

`detect_commands()` extracts commands from two sources:
1. Lines in shell-family triple-backtick code blocks (`\`\`\`bash`, `\`\`\`sh`, `\`\`\`sql`, etc.)
2. Explicit `$ command` patterns in prose text

Code block content is **trusted as-is** (language declaration is authoritative).
Passing sections that contain code blocks with non-command content (e.g., YAML examples,
nginx config snippets in the ## Root Cause section) may produce false positives.

**Correct usage**:
```bash
# Extract only the Resolution section before passing to detect-commands
holmes kb skill detect-commands --content "$(awk '/^## Resolution/,/^##/' entry.md | tail -n +2)"
```

**Incorrect usage**:
```bash
# Do NOT pass full entry content — code blocks in other sections may be detected
holmes kb skill detect-commands --content "$(cat entry.md)"
```
