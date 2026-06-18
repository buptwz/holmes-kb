# Research: Import Pipeline v2 Report Bug Fixes

## Decision 1: CommandCandidate.line — root cause confirmed

**Decision**: Use `cmd.line` wherever `detect_commands()` results are used as strings.

**Rationale**: `detect_commands()` in `kb/holmes/kb/skill/manager.py` returns `list[CommandCandidate]`, not `list[str]`. `CommandCandidate` is a dataclass with a `.line: str` attribute. Feature 018 added two code sites that iterate these objects and pass them to `re.findall(pattern, cmd)` — which expects a string. The same objects were also assigned directly to `tool_input["resolution_commands"]` and `create_skill_for_entry ctx["resolution_commands"]`, both of which downstream code serializes as strings.

**Affected sites** (all in `runner.py`):
1. `_dispatch_tool()` line ~207: `tool_input["resolution_commands"] = det_cmds` → `[c.line for c in det_cmds]`
2. `_dispatch_tool()` line ~210: `_PARAM_RE_DISPATCH.findall(cmd)` → `findall(cmd.line)`
3. `_run_skill_and_curation()` line ~366: `_PARAM_RE.findall(cmd)` → `findall(cmd.line)`
4. `_run_skill_and_curation()` line ~382: `"resolution_commands": extracted_commands` → `[c.line for c in extracted_commands]`

**Alternatives considered**: Modify `detect_commands()` to return `list[str]`. Rejected — `CommandCandidate` carries metadata (confidence, source position) used elsewhere; stripping it here would be a broader change with regression risk.

---

## Decision 2: force_type enforcement in write_kb_entry

**Decision**: Add `force_type` to the shared pipeline `ctx` dict and apply it inside `write_kb_entry` before writing.

**Rationale**: Feature 018 applied `force_type` only to the Phase 2 Extractor draft. Phase 3 runs a full LLM tool-use loop where the LLM calls `write_kb_entry` with its own independently-chosen type. The `write_kb_entry` function receives `ctx` (which contains the pipeline-level force_type) but never read it.

**Fix**: In `pipeline.py`, add `"force_type": self.force_type or ""` to `ctx`. In `tools.py` `write_kb_entry`, after parsing frontmatter, apply `post.metadata["type"] = force_type` and `post.metadata["suggested_type"] = force_type` when `ctx.get("force_type")` is non-empty.

**Alternatives considered**: Re-parse and overwrite the content after `write_pending()`. Rejected — modifying file after write is a race condition and adds a file I/O round trip.

---

## Decision 3: D-5 dedup enforcement inside write_kb_entry

**Decision**: Call `_find_entry_by_hash(kb_root, source_hash)` directly inside `write_kb_entry` before writing, and return early with `{"duplicate": True}` if a match is found.

**Rationale**: The existing `check_source_hash` tool exists and works, but the LLM agent may skip calling it. In the v2 test with `--no-interactive`, the LLM called `write_kb_entry` directly without first calling `check_source_hash`, resulting in 3 identical pending entries for 3 identical imports. Making dedup deterministic inside the write function is the only reliable approach.

**The `force` parameter**: `write_kb_entry` already has a `force: bool` parameter that bypasses the pending duplicate check. This same flag will be used to bypass the new hash dedup check.

**Alternatives considered**: Change the system prompt to require `check_source_hash` before `write_kb_entry`. Rejected — LLM instruction compliance is unreliable; the v2 report demonstrates this failure mode.

---

## Decision 4: E-12 — track evaluated entries to prevent fallback bypass

**Decision**: Add `self._skill_evaluated_entries: set[str]` to `ImportAgentRunner.__init__`. In `_dispatch_tool`, when `name == "create_skill_for_entry"`, add `tool_input["entry_id"]` to this set before the gate check. In `_finalize_skill_generation`, skip `pending_id` entries already in the set.

**Rationale**: `_finalize_skill_generation` is a deterministic fallback for when the LLM doesn't call `evaluate_skill`. When the LLM *does* call `create_skill_for_entry` and the user declines, the fallback should not re-process the same entry. Tracking by `entry_id` is the most direct approach.

**Edge case**: The `entry_id` passed to `create_skill_for_entry` may be a `pending_id` (e.g., `pending-20260609-XXXX.md`). The `_created_entry_contents` dict uses `pending_id` as key. Since `_finalize_skill_generation` iterates `_created_entry_contents.items()`, using `pending_id` as the key in both places ensures correct lookup.

**Alternatives considered**: Track by skill name. Rejected — skill name is derived from advisor, not always the same between tool-loop and fallback evaluation.

---

## Decision 5: E-11 — pass entry title as description to advisor.advise()

**Decision**: In `_finalize_skill_generation`, extract `post.metadata.get("title")` from the entry content and pass it as `description=title` to `_run_skill_and_curation`. Add `description=None` parameter to `_run_skill_and_curation` and forward it to `advisor.advise()`.

**Rationale**: `SkillAdvisor._find_similar_skill()` uses Jaccard token overlap on the `description` argument to detect near-duplicate skills. When the fallback calls `advisor.advise(entry_id, resolution_text, kb_root)` without `description`, `_find_similar_skill` is never called and the LINK path is never taken, allowing duplicate skills to accumulate.

**Why title works as proxy**: The entry title (e.g., "Nginx upstream 配置错误端口导致 502") is a concise summary of the skill's purpose. Jaccard overlap between two Nginx-related titles will be high; overlap between a Nginx title and an unrelated K8s title will be low.

**Alternatives considered**: Use `resolution_text` directly for similarity. Rejected — resolution text is long and verbose, reducing Jaccard precision. Title is compact and topic-representative.

---

## Decision 6: KB data fixes

**PT-DB-002.md**: Remove the first (Redis) section block; retain the HikariCP section which has actual kubectl commands and matches the `skill_refs` field. Update title to reflect HikariCP content.

**PT-DB-005.md**: Remove `body_additions:` and `additional_context:` keys from frontmatter. The existing markdown body (Symptoms/Root Cause/Resolution from line 39 onward) is the canonical content. The `body_additions` content describes a different incident (PgBouncer/payment-service) that was incorrectly merged into the frontmatter.

**Test files**: Delete `PT-DB-TEST2.md` and `PT-NET-TEST.md` from the committed KB.
