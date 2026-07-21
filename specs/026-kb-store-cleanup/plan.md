# Implementation Plan: KB Store Internal Cleanup

**Branch**: `026-kb-store-cleanup` | **Date**: 2026-06-11 | **Spec**: [spec.md](spec.md)

## Summary

三项内部清理改动：(1) 删除 `update_references()` 死函数（48 行，零调用方）；(2) 删除 `EntryMeta.last_referenced` / `reference_count` 孤立字段；(3) 将 `LinearScanBackend.search()` 中 O(n×m) 的 per-entry `load_evidence()` 调用替换为一次性 `_build_evidence_date_index()` 扫描。改动仅涉及 `kb/holmes/kb/store.py` 和 `kb/holmes/kb/search.py`，无新外部依赖，无行为变化。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: frontmatter, pathlib（均为现有依赖，无新增）

**Storage**: 文件系统（KB Markdown + JSON sidecar evidence 文件）

**Testing**: pytest，现有测试套件 ~737 tests

**Target Platform**: Linux CLI

**Project Type**: library（`kb/` 子项目）

**Performance Goals**: `_build_evidence_date_index()` 一次性扫描 `contributions/evidence/*/`，O(m) I/O，m = evidence sidecar 目录数（通常 < 100）

**Constraints**: 不改变任何对外 API；`SearchResult.last_evidence_date` 字段保留（feature 025 添加）；`append_evidence()` 不修改

**Scale/Scope**: store.py 净减少 ≥50 行；search.py 净改动约 +10/-5 行

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 单一职责 | ✅ | `append_evidence()` 成为唯一的 maturity lifecycle 入口 |
| 开闭原则 | ✅ | 外部接口不变；仅删除内部死代码 |
| 里氏替换 | ✅ | `LinearScanBackend` 仍满足 `SearchBackend` 接口，行为不变 |
| 依赖倒置 | ✅ | search 通过 `load_evidence` 接口操作 evidence，index helper 封装细节 |
| 迪米特法则 | ✅ | `_build_evidence_date_index` 是私有 helper，不暴露实现 |
| 验证原则 | ✅ | 每项改动对应现有或新增测试验证 |
| 可观测性 | ✅ | 删除代码，无新 observability 需求 |
| 渐进式实现 | ✅ | 三个 US 顺序独立，可逐一验证 |

## Project Structure

### Documentation (this feature)

```text
specs/026-kb-store-cleanup/
├── plan.md              ← 本文件
├── spec.md
├── research.md
└── tasks.md             ← speckit-tasks 生成
```

### Source Code (affected files)

```text
kb/holmes/kb/
├── store.py             # 删除 update_references()；删除 EntryMeta 孤立字段
└── search.py            # 新增 _build_evidence_date_index()；替换 search() 内 load_evidence 调用
```

### Tests (affected)

```text
kb/tests/
├── test_store.py        # 删除对 update_references() 的直接测试（如有）；删除孤立字段断言
└── test_search.py       # 现有两个测试必须无修改通过；可新增 index-scan 验证测试
```

## Implementation Approach

### US1: Remove update_references()

1. 确认 `update_references()` 在 `store.py` 中的行范围（lines 348–394）
2. 检查 `datetime.timezone` 是否只被 `update_references()` 使用 — 若是，从 import 中删除
3. 删除函数体和 docstring
4. 运行 `grep -r "update_references" .` 确认零残留
5. 运行 `python -m pytest kb/ -q`

### US2: Remove Orphaned EntryMeta Fields

1. 从 `EntryMeta` dataclass 删除 `last_referenced: str = ""` 和 `reference_count: int = 0`
2. 从 `list_entries()` 中删除对应的 `last_referenced=...` 和 `reference_count=...` 行
3. 检查 `test_store.py` 是否有直接断言这两个字段 — 若有则删除对应测试行
4. 运行 `python -m pytest kb/ -q`

### US3: Fix Search Evidence Loading

新增私有函数 `_build_evidence_date_index(kb_root: Path) -> dict[str, str]`：
- 扫描 `kb_root / "contributions/evidence/"` 目录（若不存在则返回空 dict）
- 对每个子目录（= entry_id），遍历 `*.json` 文件，取最大 date 字符串
- 返回 `{entry_id: max_date}` dict

修改 `LinearScanBackend.search()`:
- 在 scan loop 前调用 `_build_evidence_date_index(self._kb_root)`
- 在 loop 内，将 `load_evidence()` + `get_last_evidence_date()` 调用替换为 `date_index.get(entry_id_str)`
- 移除 `from holmes.kb.store import get_last_evidence_date, load_evidence` import（若不再使用）

## research.md

无需独立 research 文件——所有技术决策基于现有代码阅读，无外部依赖、无架构分歧。关键确认：
- `update_references()` 调用方确认为零：`grep -r "update_references" kb/ agent/ tui/` → 0 结果
- `last_referenced` 读取路径确认：仅 `list_entries()` 从 frontmatter 读取；无其他代码路径消费此字段
- `decay._get_reference_date()` fallback 链：`evidence → last_referenced → updated_at`（读取 entry 对象的 frontmatter，不依赖 `EntryMeta`）
