# Data Model: M6a — Pending/Approve 基础流程

## 状态机

```
          write_pending()
[content]  ─────────────▶  kb_status: pending
                           _pending/<category>/<id>.md

          approve_entry()
 pending  ─────────────▶  kb_status: active
                           <category>/<id>.md

          deprecate_entry()
  active  ─────────────▶  kb_status: deprecated
                           <category>/<id>.md  (原地修改)
```

## 目录布局

```
<kb_root>/
├── pitfall/               ← confirmed entries（active 或 deprecated）
│   ├── _index.md          ← category index（可选，approve 后更新）
│   └── hw-init-001.md
├── hardware/              ← category 目录（approve 时自动创建）
│   └── hw-init-002.md
├── _pending/              ← 新格式 pending 空间
│   ├── hardware/
│   │   └── hw-init-002.md
│   └── network/
│       └── dns-001.md
└── contributions/
    └── pending/           ← 旧格式（兼容保留）
        └── pending-xxx.md
```

## EntryMeta（现有 dataclass，M1 已扩展）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | entry 唯一 ID |
| `type` | str | pitfall/process/model/guideline/decision |
| `title` | str | 人类可读标题 |
| `maturity` | str | draft/verified/proven |
| `category` | Optional[str] | 所属 category |
| `kb_status` | str | **active**/pending/deprecated |
| `parent_id` | Optional[str] | process sub-entry 的父节点 |
| `file_path` | str | 绝对文件路径 |

> M6a 新增：`find_entries_by_source_file` 返回 `list[EntryMeta]`，其中含 `source_file` 字段（从 frontmatter 读取，存入 `file_path` 指向的文件中）

## Frontmatter 字段（M6a 相关）

```yaml
---
id: hw-init-002
title: 硬件初始化失败 — 固件修复流程
type: pitfall
category: hardware
kb_status: pending        # pending → active → deprecated
source_file: docs/hardware/hw-troubleshooting.md
source_hash: a3f1b2c4d5e6f7a8
import_trace_id: hw-troubleshooting
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-24"}
maturity: draft
decay_status: active
---
```

### 字段状态转换规则

| 操作 | 修改字段 | 移动文件 |
|------|----------|----------|
| `write_pending` | `kb_status=pending` | 写入 `_pending/<cat>/` |
| `approve_entry` | `kb_status=active` | `_pending/<cat>/` → `<cat>/` |
| `deprecate_entry` | `kb_status=deprecated` | 不移动（in-place） |

## 函数接口

```python
# store.py 新增

def write_pending(kb_root: Path, entry_id: str, content: str, category: str) -> Path:
    """写入 _pending/<category>/<entry_id>.md，返回文件路径。"""

def find_entries_by_source_file(kb_root: Path, source_file: str) -> list[EntryMeta]:
    """返回所有空间中 source_file 匹配的 entries（pending + confirmed）。"""

def approve_entry(kb_root: Path, entry_id: str) -> Path:
    """将 pending entry 移入 confirmed 空间，kb_status 改为 active，返回新路径。"""

def deprecate_entry(kb_root: Path, entry_id: str) -> bool:
    """in-place 将 confirmed entry 的 kb_status 改为 deprecated，返回是否成功。"""
```

## 冲突检测数据流

```
approve <id>
  │
  ├─ read pending entry → 取 source_file
  ├─ find_entries_by_source_file(kb_root, source_file, space="pending")
  │      → 过滤掉 <id> 本身 → old_pending_list
  ├─ find_entries_by_source_file(kb_root, source_file, space="confirmed")
  │      → 只取 kb_status=active → old_confirmed_list
  │
  └─ 用户确认后：
       for e in old_pending: delete _pending/<cat>/<e.id>.md
       for e in old_confirmed: deprecate_entry(kb_root, e.id)
       approve_entry(kb_root, id)
       rebuild_index_files(kb_root)  ← 若 index 存在
```
