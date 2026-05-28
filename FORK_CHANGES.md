# Holmes Agent Fork Changes

These changes must be applied to the claude-code fork to create the holmes-agent.
Base: your local `claude-code` fork clone

## T011 — package.json (BR-001)

Change `bin` field:

```diff
-  "bin": {
-    "ccb": "dist/cli-node.js",
-    "ccb-bun": "dist/cli-bun.js",
-    "claude-code-best": "dist/cli-node.js"
-  },
+  "bin": {
+    "holmes": "dist/cli-node.js"
+  },
```

Also update `name` and `description`:

```diff
-  "name": "claude-code-best",
+  "name": "holmes",
-  "description": "Reverse-engineered Anthropic Claude Code CLI ...",
+  "description": "Holmes - AI-powered knowledge-based troubleshooting assistant",
```

## T012 — src/utils/envUtils.ts (BR-004)

Change default config home directory:

```diff
 export const getClaudeConfigHomeDir = memoize(
   (): string => {
     return (
-      process.env.CLAUDE_CONFIG_DIR ?? join(homedir(), '.claude')
+      process.env.CLAUDE_CONFIG_DIR ?? process.env.HOLMES_HOME ?? join(homedir(), '.holmes')
     ).normalize('NFC')
   },
-  () => process.env.CLAUDE_CONFIG_DIR,
+  () => process.env.CLAUDE_CONFIG_DIR ?? process.env.HOLMES_HOME,
 )
```

## T013 — src/main.tsx (BR-002/003)

Find the Commander program definition (`.name(...)` call) and update:

```diff
-program.name('claude-code-best')
+program.name('holmes')
```

Update description and version strings to replace "Claude Code" with "Holmes":

```diff
-  .description('Anthropic Claude Code CLI')
+  .description('Holmes - AI-powered knowledge-based troubleshooting assistant')
```

## T014 — src/entrypoints/cli.tsx (MC-001)

At the very start of the file, after imports, add the config loader:

```typescript
// Load ~/.holmes/config.json and inject into process.env before any module uses them.
// This enables custom LLM providers without setting env vars manually.
import { readFileSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

function loadHolmesConfig(): void {
  const holmesHome = process.env.HOLMES_HOME ?? join(homedir(), '.holmes')
  const configPath = join(holmesHome, 'config.json')
  try {
    const data = JSON.parse(readFileSync(configPath, 'utf-8'))
    if (data.api_key && !process.env.OPENAI_API_KEY) {
      process.env.OPENAI_API_KEY = data.api_key
    }
    if (data.api_base_url && !process.env.OPENAI_BASE_URL) {
      process.env.OPENAI_BASE_URL = data.api_base_url
    }
    if (data.model && !process.env.OPENAI_MODEL) {
      process.env.OPENAI_MODEL = data.model
    }
    if (data.api_key || data.api_base_url) {
      process.env.CLAUDE_CODE_USE_OPENAI = '1'
    }
  } catch {
    // Config file missing or invalid — silently continue.
  }
}

loadHolmesConfig()
```

## T015 — holmes setup (already in kb/holmes/cli.py)

The `holmes setup` command is implemented in `kb/holmes/cli.py`.

## Post-fork: Registering KB tools

After applying the above changes, register KB tools in `src/tools.ts`:

```typescript
import {
  KbReadOverview, KbSearch, KbReadCategoryIndex, KbReadEntry,
  KbExtractAndSave, KbWriteEntry, KbListPending,
} from './tools/kb/index.js'

// Add to the tools array:
KbReadOverview,
KbSearch,
KbReadCategoryIndex,
KbReadEntry,
KbExtractAndSave,
KbWriteEntry,
KbListPending,
```
