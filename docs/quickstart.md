# Quick Start — Holmes KB

Get from zero to your first KB-backed troubleshooting session in under 10 minutes.

## Prerequisites

- Python >= 3.11
- git >= 2.30
- An OpenAI-compatible API (key + base URL)

## 1. Install

```bash
pip install holmes-kb
```

## 2. Clone or create a knowledge base

```bash
# Option A: use your team's existing KB
git clone <your-kb-repo-url> ~/holmes-kb

# Option B: start fresh from the included template
cp -r kb-template ~/holmes-kb
cd ~/holmes-kb && git init && git add . && git commit -m "init KB"
```

## 3. Configure (one-time)

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --model gpt-4o \
  --api-key <your-api-key> \
  --api-base-url https://api.openai.com/v1
```

## 4. Start troubleshooting

```bash
holmes-agent
```

Describe your problem. The agent searches the KB, reads the best match, and gives
you step-by-step resolution from proven team knowledge.

## 5. Save what you learned (automatic)

When you tell the agent the issue is resolved — "that fixed it", "it's working now" —
the agent **automatically** extracts the session knowledge and saves a structured entry
to `contributions/pending/`. No command needed.

You can also trigger it manually at any time:
```
/holmes-resolve
```

The only manual step is the quality gate — confirm from your terminal:

```bash
holmes kb pending                     # see what the agent generated
holmes kb pending --show <pending-id> # read the full entry before confirming
holmes kb confirm <pending-id>        # 3-gate validate → official KB
```

## Next steps

For the complete command reference, all options, real-world scenario walkthroughs,
and multi-person collaboration guide, see **[OPERATIONS.md](../OPERATIONS.md)**.
