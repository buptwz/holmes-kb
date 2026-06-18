# Implementation Plan: KB 包整合与 Bug 修复

**Branch**: `034-kb-consolidation-bugfix` | **Date**: 2026-06-17 | **Spec**: [spec.md](spec.md)

## Summary

本 feature 完成四项独立任务：

1. **包整合（US1）**：将 `holmes/holmes/kb/`（旧包）的所有调用方迁移到 `kb/holmes/kb/`（新包），主 `pyproject.toml` 增加本地依赖，删除旧包文件
2. **死代码清理（US2）**：删除 IPC 遗留代码（`agent_server.py`、`ipc_server.py`、`agent/tools/kb_read.py`、`kb_write.py`），清理相关 CLI 入口
3. **Bug-4 修复（US3）**：`SkillAdvisor._make_slug()` 支持从 `title` 派生可读 kebab-case slug
4. **Bug-5 修复（US4）**：`EXTRACTOR_SYSTEM_PROMPT` 增加 type→section 对照表，并在 Normalizer 阶段加入一致性检查

---

## Technical Context

**Language/Version**: Python 3.11+

**Primary Files**:
- `holmes/pyproject.toml` — FR-1：增加本地 `holmes-kb` 依赖
- `holmes/holmes/cli.py` — FR-3：所有旧 `holmes.kb.*` import 改为新包路径
- `holmes/holmes/kb/` — 旧包，迁移验证后删除（8 个模块）
- `kb/holmes/kb/merger.py` — 新增 `merge_pending_entry()` 函数（CLI merge 命令所需）
- `kb/holmes/kb/agent/skill_advisor.py` — Bug-4：`_make_slug()` 接受 `title` 参数
- `kb/holmes/kb/agent/phases/extractor.py` — Bug-5：`EXTRACTOR_SYSTEM_PROMPT` 增加 type-section 表
- `kb/holmes/kb/agent/phases/normalizer.py` — Bug-5：type-section 一致性检查
- `holmes/holmes/agent_server.py` — US2 删除
- `holmes/holmes/agent/ipc_server.py` — US2 删除
- `holmes/holmes/agent/tools/kb_read.py` — US2 删除
- `holmes/holmes/agent/tools/kb_write.py` — US2 删除

**Testing**: pytest，现有 `kb/tests/`（733 基线）

**Constraints**:
- 所有现有 `holmes kb *` CLI 命令行为与迁移前一致
- 不修改 `kb/holmes/kb/` 内部逻辑，只做调用方迁移（新增 merge_pending_entry 除外）
- Bug-4 修复只改 `_make_slug()` 签名 + `advise()` 传参，不影响其他接口
- Bug-5 修复不影响 pitfall 条目生成流程

---

## Constitution Check

- [x] 开闭原则：旧包调用方适配新包 API，不修改新包已有实现
- [x] 单一职责：每个修复点独立，不互相耦合
- [x] 渐进式实现：迁移分模块逐步进行，不整体替换
- [x] 验证原则：每个迁移步骤均有现有测试覆盖；Bug-4/5 补充新测试
- [x] 可观测性：CLI 命令行为输出不变，日志路径一致

---

## Root Cause Analysis

### Bug-2 根因（包整合动机）

`holmes/holmes/kb/` 是初始实现。`kb/` 目录后期独立发展为功能完整的新包（含 agent/、skill/、mcp/ 等），但主 `pyproject.toml` 从未更新依赖。`holmes/cli.py` L229 的 `from holmes.kb.agent.runner import ImportAgentRunner` 在 Python 路径上找到的是旧包（无 `agent/` 子包），导致 `ImportError`。

### Bug-4 根因

`SkillAdvisor._make_slug(entry_id: str)` 只接受 `entry_id`。`advise()` 虽然接收 `description` 参数，但仅用于 `_find_similar_skill()` 去重检查，**从未传入 `_make_slug()`**。当 `entry_id` 是 pending ID（如 `pending-20260617-040251-g0ww`）时，slug 变为 `skill-pending20260617040251`，完全不可读。

### Bug-5 根因

`EXTRACTOR_SYSTEM_PROMPT`（`extractor.py` L26-92）展示的 entry 模板仅有一种 section 结构（`## Symptoms / ## Root Cause / ## Resolution`），第 70 行注释 "For pitfall entries: Symptoms, Root Cause, and Resolution sections are mandatory" 但未说明其他 type 的 section 格式。LLM 选择 `type: decision` 时，仍复制 pitfall 的 section 结构，产生格式不合法的条目。

---

## API 迁移对照表（旧包 → 新包）

### store.py

| 旧 API | 新 API | 变化说明 |
|--------|--------|---------|
| `KnowledgeEntry` dataclass | `EntryMeta` dataclass | 字段相同，无 `to_frontmatter_str()` 方法 |
| `get_entry(kb_root, id)` → `KnowledgeEntry` | `read_entry(kb_root, id)` → `Optional[str]` | 返回原始 Markdown 字符串 |
| `list_entries(kb_root, kb_type)` | `list_entries(kb_root, kb_type=...)` → `list[EntryMeta]` | 参数改为 kwargs |
| `write_entry(kb_root, KnowledgeEntry)` | `write_entry(path: Path, content: str)` | 调用方需自行计算路径和序列化 |
| `rebuild_index(kb_root)` → dict | `rebuild_index_files(kb_root)` → None | 函数名变化；返回值不同 |

### pending.py

| 旧 API | 新 API | 变化说明 |
|--------|--------|---------|
| `get_pending(kb_root, id)` → `Optional[tuple[Path, Post]]` | `get_pending(kb_root, id)` → `Optional[str]` | 仅返回原始 Markdown 内容 |
| `list_pending(kb_root)` | `list_pending(kb_root)` | 签名相同 ✓ |
| `reject_pending(kb_root, id, reason)` | `delete_pending(kb_root, id)` | 函数名变化；新版无 reason 参数 |
| `_next_sequential_id(kb_root, type, cat)` | `generate_id(kb_root, type, cat)` | 移至 validator.py，改为公开函数 |
| `_append_log(kb_root, ...)` | `append_log(kb_root, ...)` | 改为公开函数 |

### validator.py

| 旧 API | 新 API | 变化说明 |
|--------|--------|---------|
| `validate_entry(kb_root, content)` → dict | `validate_schema(content, kb_root)` → `ValidationResult` | Gate1：schema 校验 |
| `validation["duplicates"]["similar_entries"]` | `check_duplicate(kb_root, content)` → `DuplicateResult` | Gate2：独立函数 |
| `ValidationError` exception | `ValidationResult.errors` 列表 | 改为值对象 |

### linter.py

| 旧 API | 新 API | 变化说明 |
|--------|--------|---------|
| `lint(kb_root, fix)` → dict | `lint(kb_root, fix)` → `LintReport` | 返回值改为结构化对象 |
| `results["total_entries"]` | `report.total_entries` | 属性访问 |
| `results["warnings"]` | `report.warnings` | 属性访问 |
| `results["errors"]` | `report.errors` | 属性访问 |
| `results["fixes_applied"]` | `report.fixes_applied` | 属性访问 |
| `results["pending_count"]` | `report.pending_count` | 属性访问 |
| `results["conflict_count"]` | `report.conflict_count` | 属性访问 |

### merger.py（需新增函数）

旧 `merge_entry(kb_root, content) → dict` 在新包中无对应实现。新包的 `merger.py` 面向 git conflict 文件，API 不兼容。

**方案**：在新包 `kb/holmes/kb/merger.py` 新增 `merge_pending_entry(kb_root, content) → dict`，使用新包的 `read_entry`、`write_entry`、`write_conflict_entry`、`rebuild_index_files` 实现相同的 5 场景逻辑。

### conflict.py

| 旧 API | 新 API | 变化说明 |
|--------|--------|---------|
| `list_conflicts(kb_root)` → `list[dict]` | `list_conflicts(kb_root)` → `list[ConflictEntry]` | 返回结构化对象 |
| `resolve_conflict(kb_root, conflict_id)` → bool | `resolve_conflict(kb_root, conflict_id, ...)` | 需确认签名 |

### index_builder.py（删除）

`from holmes.kb.index_builder import rebuild_index` → 改为 `from holmes.kb.store import rebuild_index_files`

---

## Project Structure

### Documentation (this feature)

```text
specs/034-kb-consolidation-bugfix/
├── plan.md          ← 本文件
├── spec.md
├── research.md      ← Phase 0 输出
├── data-model.md    ← Phase 1 输出
├── checklists/
│   └── requirements.md
└── tasks.md         ← /speckit-tasks 生成
```

### Source Code (impacted files)

```text
holmes/pyproject.toml                          ← FR-1：新增本地依赖
holmes/holmes/cli.py                           ← FR-3：更新所有 import + CLI 调用

# 旧包（全部删除）
holmes/holmes/kb/__init__.py
holmes/holmes/kb/conflict.py
holmes/holmes/kb/importer.py
holmes/holmes/kb/index_builder.py
holmes/holmes/kb/linter.py
holmes/holmes/kb/merger.py
holmes/holmes/kb/pending.py
holmes/holmes/kb/store.py
holmes/holmes/kb/validator.py

# 死代码（全部删除）
holmes/holmes/agent_server.py
holmes/holmes/agent/ipc_server.py
holmes/holmes/agent/tools/kb_read.py
holmes/holmes/agent/tools/kb_write.py

# 新包（Bug-4/5 修复 + merge 补全）
kb/holmes/kb/agent/skill_advisor.py           ← Bug-4：_make_slug(title)
kb/holmes/kb/agent/phases/extractor.py        ← Bug-5：EXTRACTOR_SYSTEM_PROMPT
kb/holmes/kb/agent/phases/normalizer.py       ← Bug-5：type-section 一致性检查
kb/holmes/kb/merger.py                        ← 新增 merge_pending_entry()
kb/tests/                                     ← Bug-4/5 新测试
```

---

## Phase 0: Research

### R-1：pyproject.toml 本地依赖格式

**结论**：使用 PEP 508 本地路径格式：

```toml
[project]
dependencies = [
    ...
    "holmes-kb @ file:///./kb",
]
```

使用相对路径时需确认 setuptools 版本支持（>=61 已足够）。安装后 `from holmes.kb.agent.runner import ImportAgentRunner` 直接可用。

### R-2：LintReport 字段完整名称

查看 `kb/holmes/kb/linter.py` 中 `LintReport` 的字段定义，确认 CLI 中的属性访问名称（`total_entries`、`pending_count` 等）与结构体字段一致。

### R-3：conflict.py `list_conflicts` 返回字段

新包 `ConflictEntry` dataclass 字段名需确认（旧 CLI 用 `conflict_id` 字段），保证 `kb_resolve` 命令行为不变。

### R-4：entry 文件路径推算规则

`kb_confirm` 命令调用 `write_entry(path, content)` 时需自行构造路径。通过分析 `list_entries` 实现确认路径规则：`kb_root/{type}/{category}/{id}.md`（pitfall）或 `kb_root/{type}/{id}.md`（其他）。

---

## Phase 1: Design & Contracts

### Data Model Changes

**Bug-4：`SkillAdvisor._make_slug()` 签名变更**

```python
# 旧签名
@staticmethod
def _make_slug(entry_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", entry_id.lower())[:20]
    return f"skill-{slug}" if slug else "agent-skill"

# 新签名
@staticmethod
def _make_slug(entry_id: str, title: str = "") -> str:
    """Generate skill slug from title (preferred) or entry_id (fallback)."""
    if title:
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)   # non-alphanum → dash
        slug = slug.strip("-")                       # trim leading/trailing dashes
        slug = re.sub(r"-{2,}", "-", slug)           # collapse consecutive dashes
        slug = slug[:40]                             # max length
        if len(slug) >= 3:
            return slug
    # Fallback: entry_id-based (existing logic)
    slug = re.sub(r"[^a-z0-9]", "", entry_id.lower())[:20]
    return f"skill-{slug}" if slug else "agent-skill"
```

`advise()` 调用处更新：

```python
# Form A（第 161 行附近）
slug = self._make_slug(entry_id, title=description)
```

去重：`advise()` 返回前检查 `kb_root / "skills" / suggested_name` 是否已存在，若存在则追加 `-2`、`-3` 后缀直至不重名。

**Bug-5：EXTRACTOR_SYSTEM_PROMPT type-section 对照表（新增段落）**

在 extractor.py 现有第 70 行 `"For pitfall entries..."` 之后插入：

```
TYPE-SECTION MAPPING — use ONLY the sections listed for the type you select:

  pitfall   → ## Symptoms  |  ## Root Cause  |  ## Resolution
  model     → ## When to Use  |  ## Structure  |  ## Example
  guideline → ## Guideline  |  ## Rationale  |  ## Examples
  process   → ## Purpose  |  ## Steps  |  ## Verification
  decision  → ## Context  |  ## Decision

CRITICAL: body sections MUST match the type you choose.
- type: decision → NO ## Symptoms, ## Root Cause, ## Resolution
- type: pitfall  → NO ## Context, ## Decision
- type: model    → NO ## Symptoms, ## Resolution
When in doubt, choose pitfall — it is the most permissive type.
```

**Bug-5：Normalizer type-section 一致性检查**

在 `normalizer.py` 新增常量和函数：

```python
_TYPE_REQUIRED_SECTIONS: dict[str, set[str]] = {
    "pitfall":   {"Symptoms", "Root Cause", "Resolution"},
    "model":     {"When to Use", "Structure", "Example"},
    "guideline": {"Guideline", "Rationale", "Examples"},
    "process":   {"Purpose", "Steps", "Verification"},
    "decision":  {"Context", "Decision"},
}

_TYPE_FORBIDDEN_SECTIONS: dict[str, set[str]] = {
    "decision": {"Symptoms", "Root Cause", "Resolution"},
    "model":    {"Symptoms", "Root Cause", "Resolution"},
    "guideline":{"Symptoms", "Root Cause", "Resolution"},
    "process":  {"Symptoms", "Root Cause", "Resolution"},
}
```

`normalize()` 中：检测 forbidden sections → 记录 warning，并将 `## Resolution` rename 为 `## Decision`（decision type）；其他类型 forbidden sections 仅记 warning，不自动修改（避免过度自动修正）。

### Interface Contracts

**`merge_pending_entry(kb_root: Path, content: str) -> dict`**（新增到 `kb/holmes/kb/merger.py`）

```python
# 输入
kb_root: Path
content: str  # 原始 Markdown，含 YAML frontmatter

# 输出（与旧 merge_entry 相同格式）
{
    "scenario": "pure_add" | "evidence_append" | "maturity_upgrade"
               | "maturity_conflict" | "content_contradiction",
    "entry_id": "PT-DB-001",        # 大多数场景
    "conflict_id": "conflict-xxx",  # content_contradiction 时
}
```

5 场景判断逻辑与旧版 `merge_entry()` 相同，使用新包 API 实现。

---

## Implementation Approach

### 实现顺序（依赖关系）

```
Step 1: FR-1 — pyproject.toml 新增本地依赖              — 独立
Step 2: FR-4 — 删除死代码（4 个 IPC 文件）               — 独立
Step 3: 新增 merge_pending_entry() 到新包 merger         — 独立（为 Step 4 做准备）
Step 4: FR-3 — 更新 cli.py 的所有 import + 调用适配      — 依赖 Step 1 + Step 3
Step 5: FR-2 — 删除旧包 holmes/holmes/kb/（9 个文件）    — 依赖 Step 4 验证通过
Step 6: FR-5 — 删除 CLI 中 holmes tui/agent start 入口  — 依赖 Step 2
Step 7: Bug-4 — _make_slug(title) + advise() 传参        — 独立
Step 8: Bug-5 — EXTRACTOR_SYSTEM_PROMPT 对照表           — 独立
Step 9: Bug-5 — Normalizer type-section 检查             — 独立
Step 10: 测试 — pytest + 新增 Bug-4/5 测试               — 全部 Steps 完成后
```

### 各步骤要点

**Step 1 — pyproject.toml**：
- `holmes/pyproject.toml` dependencies 列表末尾追加 `"holmes-kb @ file:///./kb"`
- 验证：`pip install -e . && python -c "from holmes.kb.agent.runner import ImportAgentRunner"` 无报错

**Step 2 — 删除死代码**：
- 删除：`holmes/holmes/agent_server.py`、`holmes/holmes/agent/ipc_server.py`、`holmes/holmes/agent/tools/kb_read.py`、`holmes/holmes/agent/tools/kb_write.py`
- 检查 `holmes/holmes/agent/tools/__init__.py`，删除对 kb_read/kb_write 的 import

**Step 3 — merge_pending_entry()**：
- 在 `kb/holmes/kb/merger.py` 末尾新增函数
- 5 场景逻辑使用 `read_entry()`、`write_entry()`、`write_conflict_entry()`、`rebuild_index_files()` 实现

**Step 4 — cli.py import 迁移**：

旧 import 块替换为：

```python
from holmes.kb.linter import lint, LintReport
from holmes.kb.pending import (get_pending, list_pending, delete_pending, append_log)
from holmes.kb.store import read_entry, list_entries, write_entry, rebuild_index_files
from holmes.kb.validator import validate_schema, check_duplicate, generate_id
from holmes.kb.merger import merge_pending_entry
from holmes.kb.conflict import list_conflicts, resolve_conflict
```

逐命令适配：
- `kb_pending_show`：`get_pending()` 返回 `Optional[str]`，直接 `click.echo(content)`
- `kb_confirm`：
  - `get_pending()` → `Optional[str]`；用 `frontmatter.loads(content)` 解析 metadata
  - `validate_entry()` → `validate_schema(content, kb_root)` + `check_duplicate(kb_root, content)`
  - `_next_sequential_id()` → `generate_id(kb_root, kb_type, category)`
  - 构造 entry 路径（pitfall：`kb_root / kb_type / category / f"{new_id}.md"`；其他：`kb_root / kb_type / f"{new_id}.md"`）
  - 更新 content frontmatter 的 id 字段后，`write_entry(entry_path, new_content)`
  - `path.unlink()` → `delete_pending(kb_root, pending_id)`
  - `rebuild_index()` → `rebuild_index_files(kb_root)`
  - `_append_log()` → `append_log()`
- `kb_reject`：`reject_pending()` → `delete_pending()`（reason 可写入 log 行，或省略）
- `kb_merge`：`merge_entry()` → `merge_pending_entry()`
- `kb_lint`：字典访问 → `LintReport` 属性访问；`rebuild_index()` 调用也改名
- `kb_rebuild_index`：`rebuild_index()` → `rebuild_index_files()`；返回 None，改为查询 `len(list_entries(kb_root))` 打印数量
- `kb_show`：`get_entry()` → `read_entry()`；返回原始字符串直接 `click.echo(content)`
- 行内 `from holmes.kb.store import KnowledgeEntry, write_entry` → 删除（不再需要）
- `from holmes.kb.agent.runner import ImportAgentRunner` → 无需改动

**Step 5 — 删除旧包**：
- `rm -rf holmes/holmes/kb/`
- `pytest` 验证无遗漏 import

**Step 6 — CLI 死代码入口**：
- 删除 `cli.py` 中 `holmes tui` 命令实现（依赖已删除的 `agent_server.py`）
- 删除 `holmes agent start` 命令实现（依赖已删除的 `ipc_server.py`）
- 删除 `cli.py` 顶部 docstring 中对应的命令描述行

**Step 7 — Bug-4（skill_advisor.py）**：
- `_make_slug(entry_id, title="")` 新签名（默认空 title，向后兼容 Form B 调用）
- `advise()` 的 Form A 路径（L161）：`slug = self._make_slug(entry_id, title=description)`
- 去重检查：`advise()` 返回前，若 `(kb_root / "skills" / suggested_name).is_dir()`，则追加 `-2`、`-3`

**Step 8 — Bug-5（extractor.py prompt）**：
- 在 `EXTRACTOR_SYSTEM_PROMPT` 第 70 行（"For pitfall entries: ..."）之后插入 TYPE-SECTION MAPPING 对照表段落

**Step 9 — Bug-5（normalizer.py）**：
- 新增 `_TYPE_REQUIRED_SECTIONS` 和 `_TYPE_FORBIDDEN_SECTIONS` 常量
- 在 `normalize()` 中添加 type-section 一致性检查
- decision type 的 `## Resolution` → `## Decision` 自动 rename
- 其他不匹配情况记录 warning，不自动修改

---

## Success Criteria Mapping

| SC | 验证方式 | 关联步骤 |
|----|---------|---------|
| SC-1 `holmes import` 无需 PYTHONPATH | `pip install -e . && holmes import <file>` 成功 | Step 1 + 4 |
| SC-2 现有 CLI 命令行为不变（测试 ≥ 733） | `pytest kb/tests/` 全部通过 | Step 4 + 5 |
| SC-3 Skill 名称无 pending 时间戳 | `holmes import` 后 `skill list` 验证 slug 可读 | Step 7 |
| SC-4 KB 条目 type-section 一致 | 导入多类型文档后 schema 校验通过 | Step 8 + 9 |
| SC-5 IPC 死代码已删除 | `ls holmes/holmes/agent_server.py` 返回不存在 | Step 2 |
