# Research: Holmes KB Autonomous Import Agent

**Feature**: `013-kb-skill-evolution` | **Date**: 2026-06-07

---

## R-001: Anthropic SDK Tool-Use Agent Loop (Python)

**Decision**: Use `anthropic` Python SDK with `client.messages.create(tools=[...])` in a `while True` loop that processes `tool_use` blocks and returns `tool_result` blocks until `stop_reason == "end_turn"`.

**Rationale**: The Anthropic tool-use API is purpose-built for agentic loops. Each iteration: send messages → receive response → if `tool_use` blocks present, execute tools and append results → continue loop. This is simpler than the OpenAI function-calling pattern and directly supported by the SDK.

**Pattern**:
```python
from anthropic import Anthropic

client = Anthropic(api_key=api_key, base_url=base_url)
messages = [{"role": "user", "content": prompt}]

while True:
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=tool_defs,
        messages=messages,
    )
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        break

    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            result = execute_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

    if not tool_results:
        break

    messages.append({"role": "user", "content": tool_results})
```

**Alternatives considered**:
- OpenAI function-calling: rejected — existing openai SDK is for config/model compat only; Anthropic tool-use is better aligned with spec Assumption
- LangChain agent: rejected — unnecessary heavy dependency, violates 渐进式实现原则
- Custom recursive function: rejected — Anthropic SDK loop is simpler and well-tested

---

## R-002: Source Hash (Idempotency Key)

**Decision**: Compute `source_hash = hashlib.sha256(content.encode()).hexdigest()[:16]`.

**Rationale**: SHA-256 truncated to 16 hex chars (64-bit) gives near-zero collision probability for KB scale (thousands of entries). Python `hashlib` is stdlib — no extra dependency. Hash is stored in `source_hash` frontmatter field. On import, scan existing KB entries for matching `source_hash` before calling LLM.

**Pattern**:
```python
import hashlib

def compute_source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
```

**Alternatives considered**:
- MD5: rejected — deprecated, collision concerns
- Full SHA-256 (64 chars): rejected — verbose in frontmatter, 16 chars is sufficient
- File path hash: rejected — same content from different paths must deduplicate (spec US3.3)

---

## R-003: Atomic File Write (temp + os.replace)

**Decision**: Write to a `.tmp` file in the same directory, then call `os.replace(tmp, target)` for atomic rename.

**Rationale**: `os.replace()` is atomic on POSIX (single filesystem). A crash mid-write leaves the `.tmp` file, not a half-written target. The target is either old or new — never corrupt. This satisfies SC-006 exactly.

**Pattern**:
```python
import os
import tempfile
from pathlib import Path

def atomic_write(path: Path, content: str) -> None:
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
```

**Alternatives considered**:
- Direct `path.write_text()`: rejected — not atomic; partial writes possible on crash
- `shutil.move()`: rejected — not guaranteed atomic across filesystems

---

## R-004: Git Commit from Python

**Decision**: Use `subprocess.run(["git", "commit", "-m", msg, "--"], capture_output=True, cwd=kb_root)` after all file writes succeed.

**Rationale**: `subprocess.run` is stdlib and the simplest way to invoke git. Check return code; if non-zero (e.g., nothing to commit), treat as non-fatal. Use `--` to separate flags from paths.

**Pattern**:
```python
import subprocess

def git_commit(kb_root: Path, message: str) -> bool:
    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=kb_root, capture_output=True
    )
    if result.returncode != 0:
        return False
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=kb_root, capture_output=True
    )
    return result.returncode == 0
```

**Alternatives considered**:
- `gitpython` library: rejected — extra dependency; subprocess is sufficient
- Skipping git commit: rejected — spec FR-017 requires it as rollback mechanism

---

## R-005: LLM Semantic Deduplication (No Vector DB)

**Decision**: Use a separate LLM call (within the agent tool-use loop) to compare a new entry's root cause description against candidate existing entries. Return `same_root_cause: bool` and `confidence: float`.

**Rationale**: LLM semantic judgment is more accurate than keyword Jaccard for root-cause comparison (resolves spec Q3). The agent retrieves candidate entries by category (narrowing the comparison set) and asks the LLM to evaluate semantic equivalence. No vector DB means no new infrastructure.

**Prompt design**:
```
You are comparing two knowledge base entries to determine if they describe the same root cause.

Entry A (new):
{new_entry_summary}

Entry B (existing):
{existing_entry_summary}

Answer with JSON: {"same_root_cause": true/false, "confidence": 0.0-1.0, "reason": "..."}
Same root cause means: the fundamental technical problem is identical, even if symptoms or
resolution steps differ. Different root cause means: independent technical problems.
```

**Alternatives considered**:
- Keyword Jaccard similarity: rejected — poor accuracy for technical content (same symptom, different root cause)
- Sentence-transformers embedding cosine: rejected — requires vector DB infrastructure, violates Assumptions
- Title string match only: rejected — misses paraphrasing, different languages

---

## R-006: Self-Verification Pass

**Decision**: After agent generates a draft KB entry, make a second LLM call with both the source text and the draft, asking the agent to identify any field whose content lacks a corresponding source text fragment. Fields flagged as unsupported are cleared.

**Rationale**: The spec requires US2 — no LLM hallucination in key fields. A verification pass with explicit source-tracing instruction catches invented content before write.

**Prompt design**:
```
You are a knowledge base quality verifier.

SOURCE TEXT:
{source_text}

DRAFT ENTRY (YAML frontmatter + Markdown body):
{draft_content}

For each field in the draft, verify it has textual support in the SOURCE TEXT.
Return JSON: {
  "verified_fields": ["title", "root_cause", ...],
  "unsupported_fields": [{"field": "root_cause", "reason": "not mentioned in source"}],
  "confidence": 0.0-1.0
}
```

**Alternatives considered**:
- Single-pass generation with strict prompt: rejected — LLMs still hallucinate; two-pass is more reliable
- Human review only: rejected — defeats the "autonomous" goal

---

## R-007: Skill Generation Criteria

**Decision**: Agent evaluates three criteria:
1. Resolution has ≥3 distinct command steps → "Recommended"
2. Any `{parameter}` placeholder detected → "Recommended"
3. Existing skill already covers these commands (`skill_refs` or detect_commands scan) → "Link" (not create)

If all three fail → "Skip" (report suggestion only). Uncertain → "Skip" with suggestion in report (spec FR-011).

**Pattern**: Use existing `detect_commands()` in `skill/manager.py` on the Resolution section, then count distinct steps and check for `{...}` placeholder regex.

**Alternatives considered**:
- Always generate skill: rejected — skill bloat, violates spec
- LLM-based judgment: considered — but criteria are rule-based and deterministic; rule-based is simpler and more predictable (渐进式实现原则)

---

## R-008: Incremental Skill Curation Metrics

**Decision**: Three curation finding types, each with a deterministic check:

| Type | Detection | Threshold |
|------|-----------|-----------|
| `merge_candidate` | Jaccard similarity of SKILL.md description word sets | >0.6 (configurable) |
| `oversized` | Body character count of SKILL.md | >3,000 chars |
| `update_candidate` | `patch_count == 0` AND linked KB entry `updated_at > skill created_at` | n/a |

Merge candidates additionally confirmed by LLM semantic judgment before being promoted from "possible" to "candidate" in the report.

**Alternatives considered**:
- Full LLM scan of all skills: rejected — expensive and slow for large skill libraries
- Time-based archiving: explicitly rejected per user feedback (stale != unused recently)

---

## R-009: SkillUsageRecord Sidecar

**Decision**: Store `.skill_usage.json` in the skill directory alongside `SKILL.md`. JSON schema:

```json
{
  "created_at": "ISO-8601",
  "agent_created": true,
  "use_count": 0,
  "last_used_at": null,
  "patch_count": 0,
  "last_patched_at": null,
  "absorbed_into": null
}
```

Atomic write (R-003) on every update. File is optional — if absent, all values default to 0/null.

**Alternatives considered**:
- Central JSON registry: rejected — per-skill sidecar avoids central lock contention and makes skill deletion clean
- SQLite: rejected — over-engineered for file-based KB

---

## R-010: Interactive Confirmation UX

**Decision**: Use Click's `click.prompt()` and `click.confirm()` for interactive gates. Gate triggers: classification confidence < 0.7, dedup ambiguity, skill generation recommendation. `--no-interactive` flag sets a `no_interactive=True` parameter that bypasses all gates and logs decisions to ImportReport.

**Alternatives considered**:
- Rich terminal UI: rejected — unnecessary dependency
- Always interactive: rejected — headless/CI use case blocked
