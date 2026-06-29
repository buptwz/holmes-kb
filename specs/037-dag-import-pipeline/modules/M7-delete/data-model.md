# Data Model: KB Soft Delete (M7)

**Phase 1 output** | 2026-06-24

## Entities

### EntryFile (existing)

Markdown file with YAML frontmatter. Relevant fields for M7:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Entry identifier |
| `type` | string | yes | `pitfall / process / model / guideline / decision` |
| `category` | string | yes | Directory group (e.g., `hardware`) |
| `parent_id` | string | no | Set for process sub-entries; absent on root nodes |
| `child_entry_ids` | list[string] | no | IDs of child process entries; present on pitfall roots |
| `pitfall_structure` | string | no | `tree` (new DAG format) or `flat` / absent (legacy) |

### TrashRecord (new concept, not persisted)

In-memory structure representing one pending move operation:

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | string | Entry ID being moved |
| `src_path` | Path | Current location of the file |
| `dst_path` | Path | Target path in `_trash/` (may include timestamp suffix) |
| `warning` | str | Non-empty if file not found (skip case) |

## State Transitions

```
Entry State Machine:
  [confirmed: type/category/id.md]  ──delete──►  [trashed: _trash/type/category/id.md]
  [pending: _pending/type/category/id.md]  ──delete──►  [trashed: _trash/type/category/id.md]
  [trashed: _trash/type/category/id.md]  ──git checkout──►  [restored to original location]
```

## Directory Layout (M7 additions)

```
kb_root/
  pitfall/
    hardware/
      gpu-init-failure.md       ← confirmed entry
  _pending/
    process/
      hardware/
        gpu-check-001.md        ← pending entry
  _trash/                       ← NEW (created on first deletion)
    pitfall/
      hardware/
        gpu-init-failure.md     ← soft-deleted confirmed entry
    process/
      hardware/
        gpu-check-001.md        ← soft-deleted pending entry
```

## move_to_trash() Logic Flow

```
move_to_trash(kb_root, entry_id, cascade=True)
  │
  ├─ find_entry(kb_root, entry_id)  →  src_path (or FileNotFoundError)
  │
  ├─ Read frontmatter: type, category, parent_id, pitfall_structure, child_entry_ids
  │
  ├─ is_cascade_root = (
  │     type == "pitfall"
  │     AND parent_id is None
  │     AND pitfall_structure == "tree"
  │     AND child_entry_ids is non-empty
  │     AND cascade == True
  │   )
  │
  ├─ if is_cascade_root:
  │     ids_to_move = collect_tree(kb_root, entry_id)   [root + all descendants]
  │   else:
  │     ids_to_move = [entry_id]
  │
  ├─ for each id in ids_to_move:
  │     src = find_entry(kb_root, id)  OR _find_pending_entry(kb_root, id)
  │     if src is None: log warning, skip
  │     fm = read frontmatter from src
  │     type = fm["type"], category = fm["category"]
  │     dst_dir = kb_root / "_trash" / type / category
  │     dst_dir.mkdir(parents=True, exist_ok=True)
  │     dst = dst_dir / src.name
  │     if dst.exists():
  │         dst = dst_dir / f"{src.stem}-{timestamp}{src.suffix}"
  │     shutil.move(str(src), str(dst))
  │     moved.append(str(dst))
  │
  └─ return moved
```
