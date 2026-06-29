# Data Model: M5 — Agent 2 双源知识生成

**Date**: 2026-06-24

## Extended .dag.json Schema

在 M4 的 `.dag.json` 结构基础上追加 `entry_ids` 字段（id_gen.py 写入）：

```json
{
  "title": "硬件初始化失败",
  "source_file": "hardware-init-failure.md",
  "generated": "2026-06-24",
  "nodes": [...],
  "entry_ids": {
    "N1": "hardware-init-failure-N1-001",
    "N3": "hardware-init-failure-N3-001",
    "N7": "hardware-init-failure-N7-001",
    "root": "hardware-init-failure-root-001"
  },
  "import_seq": "001"
}
```

**Fields**:
- `entry_ids`: `dict[str, str]` — node_id → entry_id 映射；`"root"` 键为 pitfall root entry ID
- `import_seq`: `str` — 3 位序号字符串（`"001"`, `"002"`, ...）；重试时保持不变（幂等）

---

## Pitfall Entry Frontmatter

```yaml
---
title: 硬件初始化失败 — 排查路由
description: 设备上电后无法完成初始化，涵盖固件异常、内存故障、启动序列问题三条排查路径。
type: pitfall
category: hardware
pitfall_structure: tree
kb_status: pending
source_file: hardware-init-failure.md
source_hash: abc123def456789a
import_trace_id: hardware-init-failure
child_entry_ids:
  - hardware-init-failure-N3-001   # 固件修复流程
  - hardware-init-failure-N7-001   # 硬件更换流程
parent_id: null
maturity: draft
decay_status: active
next_decay_check: "2026-12-21"
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-24"}
tags: [hardware, initialization, firmware, memory]
---
```

**Validation rules** (write_entry 内置校验):
- All fields above MUST be present and non-empty (except parent_id which is null for root)
- `type` MUST be `pitfall`
- `kb_status` MUST be `pending`
- `pitfall_structure` MUST be `tree`
- `child_entry_ids` item IDs MUST all exist in `entry_ids` table
- Body MUST contain: `## Symptoms`, `## Root Cause`, `## Resolution`

---

## Process Entry Frontmatter

```yaml
---
title: 固件修复流程
description: 检测固件版本并通过 API 执行修复，根据修复结果路由到成功路径或硬件更换路径。
type: process
category: hardware
kb_status: pending
source_file: hardware-init-failure.md
source_hash: abc123def456789a
import_trace_id: hardware-init-failure
parent_id: hardware-init-failure-root-001   # 硬件初始化失败 — 排查路由
child_entry_ids:
  - hardware-init-failure-N7-001   # 硬件更换流程
maturity: draft
decay_status: active
next_decay_check: "2026-12-21"
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-24"}
tags: [hardware, firmware, repair]
---
```

**Validation rules** (write_entry 内置校验):
- All above fields MUST be present and non-empty
- `type` MUST be `process`
- `parent_id` MUST exist in `entry_ids` table
- `child_entry_ids` item IDs (if present) MUST all exist in `entry_ids` table
- Body MUST contain: `## Steps`

---

## Agent 2 Tool Context (ctx)

```python
ctx = {
    "state_dir": Path,        # kb_root / "_import-state"
    "source_hash": str,       # 16-char SHA-256 prefix
    "source_file": str,       # relative path of source doc
    "source_text": str,       # full untruncated source document
    "kb_root": Path,          # KB root directory
    "dry_run": bool,
    "dag_json": dict,         # parsed .dag.json including entry_ids
    "entry_ids": dict,        # node_id → entry_id mapping (from dag_json)
    "pending_root": Path,     # kb_root / "_pending"
    "category": str,          # inferred from Agent 2 during Study phase
    "failed_entries": list,   # list of (node_id, error_reason) for report
    "written_entries": list,  # list of (entry_id, title) for report
    "_terminate": bool,       # set True by finalize() tool
}
```

---

## Step 2.5 Parse Result

```python
@dataclass
class ParseResult:
    recognized_edits: list[str]    # human-readable descriptions of recognized changes
    uncertain_items: list[str]     # items needing user clarification (displayed as ⚠)
    validation_errors: list[str]   # structural errors (dangling nodes, cycles) — block Agent 2
    validation_warnings: list[str] # content warnings (section not found in source) — non-blocking
    dag_graph: Optional[DAGGraph]  # re-parsed graph after normalization (None if structural error)
```

---

## Lint Result

```python
@dataclass
class LintResult:
    rule: str       # e.g., "parent_id_consistency"
    passed: bool
    message: str    # human-readable detail (empty if passed)
```

7 rules: `parent_id_consistency`, `child_entry_ids_consistency`, `tree_completeness`,
`no_cycle`, `pitfall_has_root`, `source_file_consistent`, `evidence_fields_present`

---

## ID Generation

```
source_name_slug: file stem → kebab-case  (e.g., "hardware-init-failure")
node_id: DAGNode.id  (e.g., "N3")
import_seq: zero-padded 3-digit counter  (e.g., "001")

process entry ID:  {source_name_slug}-{node_id}-{import_seq}
pitfall root ID:   {source_name_slug}-root-{import_seq}

Examples:
  hardware-init-failure-N3-001   (process)
  hardware-init-failure-root-001 (pitfall root)
```

**Seq allocation**:
1. Read existing `import_seq` from `.dag.json` if present → reuse (idempotent on retry)
2. Otherwise scan `_import-state/*.dag.json` for max existing seq → increment
3. Default to `"001"` if no prior imports
