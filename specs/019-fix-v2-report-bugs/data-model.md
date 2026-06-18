# Data Model: Import Pipeline v2 Report Bug Fixes

## Changed Entities

### write_kb_entry Return Value (tools.py)

The return dict now includes an optional `duplicate` flag:

```python
# New: when source_hash already exists in KB or pending
{
    "pending_id": str,      # existing entry ID (not None)
    "dry_run": False,
    "action": "Skipped: duplicate source hash already in KB ({existing_id})",
    "duplicate": True,      # NEW field — signals skip without error
}

# Unchanged: successful write
{
    "pending_id": str,
    "dry_run": False,
    "action": "Created entry: {title}",
}
```

**Downstream impact**: `_maybe_post_process` in `runner.py` checks `result.get("pending_id")` before recording `_created_entry_contents`. When `duplicate=True`, `pending_id` is the existing entry — code must not overwrite `_created_entry_contents` with an empty string for this case.

### ImportAgentRunner State (runner.py)

New instance field:

```python
self._skill_evaluated_entries: set[str] = set()
# Key: pending_id (str) — entries for which create_skill_for_entry was called in tool loop
# Lifecycle: populated in _dispatch_tool; read in _finalize_skill_generation; reset per run()
```

### Pipeline ctx dict (pipeline.py)

New key added to the shared context:

```python
ctx["force_type"] = self.force_type or ""   # str, empty string means "no override"
```

Consumed by: `write_kb_entry` in `tools.py`.

### _run_skill_and_curation Signature (runner.py)

```python
# Before
def _run_skill_and_curation(self, entry_id, resolution_text, category, report):

# After
def _run_skill_and_curation(self, entry_id, resolution_text, category, report, description=None):
```

`description` is forwarded to `SkillAdvisor.advise()` for `_find_similar_skill()`.
