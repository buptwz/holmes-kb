# Implementation Plan: Knowledge Lifecycle P0 — Evidence, Maturity, Search

**Branch**: `025-kb-lifecycle-p0` | **Date**: 2026-06-11 | **Spec**: [spec.md](spec.md)

## Summary

打通知识生命周期三个 P0 缺失环节：(1) agent 读取 KB 条目后自动写回 evidence；(2) evidence 写入后自动更新 maturity（随 P0-1 免费，`append_evidence()` 已内置此逻辑）；(3) 搜索结果按 evidence 最新日期为主键排序。三项改动合计修改 2 个文件，新增约 40 行代码，无新外部依赖。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: openai, frontmatter, pydantic（均为现有依赖，无新增）

**Storage**: 文件系统（KB Markdown + JSON sidecar evidence 文件）

**Testing**: pytest，现有测试套件 731+ tests

**Target Platform**: Linux CLI

**Project Type**: library/cli（两个子项目：`agent/`，`kb/`）

**Performance Goals**: `_flush_evidence()` 写入数量通常 1-5 个条目，每次写入 <10ms，总开销 <50ms，对 session 结束延迟无感知影响

**Constraints**: 不引入新外部依赖；不破坏 SearchResult dataclass 的现有调用方（新增字段有默认值）

**Scale/Scope**: 单 session 读取条目通常 1-10 个，O(n) 写入可接受

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | ✅ | `SearchResult` 新增可选字段，不改变现有 API；`append_evidence()` 无改动，只是新增调用点 |
| 依赖倒置 | ✅ | engine 通过 `store.append_evidence` 接口操作 KB，不直接操作文件 |
| 单一职责 | ✅ | engine 负责 agent 生命周期（记录 ref + 触发写回），store 负责 evidence+maturity，search 负责排序 |
| 接口隔离 | ✅ | 无新接口，复用现有函数 |
| 迪米特法则 | ✅ | engine 只调用 `store.append_evidence()`，不了解 sidecar 文件格式 |
| 里氏替换 | ✅ | `LinearScanBackend` 仍满足 `SearchBackend` 接口约定 |
| 合成复用 | ✅ | 复用 `append_evidence`、`load_evidence`、`get_last_evidence_date` |
| 验证原则 | ✅ | 每个 P0 对应独立测试 |
| 可观测性 | ✅ | `_flush_evidence()` 写入 logger.info；搜索排序结果可从结果顺序验证 |
| 渐进式实现 | ✅ | 最小改动，不引入抽象层 |

## Project Structure

### Documentation (this feature)

```text
specs/025-kb-lifecycle-p0/
├── plan.md              ← 本文件
├── spec.md
├── research.md
└── tasks.md             ← speckit-tasks 生成
```

### Source Code (affected files)

```text
agent/holmes/agent/
└── engine.py            # _exec_tool 后追踪 kb_refs；_flush_evidence() 新方法

kb/holmes/kb/
└── search.py            # SearchResult.last_evidence_date 字段；排序键更新

agent/tests/
└── test_engine.py       # 新增 P0-1 evidence 写回测试

kb/tests/
└── test_search.py       # 新增 P0-3 evidence 排序测试
```

## Phase 0: Research

已完成，见 [research.md](research.md)。关键决策：

- P0-2 随 P0-1 免费（`append_evidence()` 已内置 maturity 链式更新）
- Evidence 写回在 engine 内部处理（`_InternalStopEvent` handler 中，yield DoneEvent 前）
- `contributor` 默认使用 `session.id`（UUID），保证每次会话独立计数
- 搜索排序：`(last_evidence_date DESC, score DESC)` 双键，空日期自然排最后

## Phase 1: Design & Implementation

### US1 — Evidence 写回（FR-001, FR-002, FR-003）

**改动：`agent/holmes/agent/engine.py`**

1. 在 `chat()` 的工具执行成功路径中（`result = await self._exec_tool(...)` 之后），判断 `tool_name == "kb_read_entry"` 且 `status != "error"`：
   ```python
   if tool_name == "kb_read_entry" and not result.is_error:
       entry_id = tool_input.get("entry_id", "")
       if entry_id and entry_id not in self._session.kb_refs:
           self._session.kb_refs.append(entry_id)
   ```

2. 新增 `_flush_evidence()` 私有方法，在 `_InternalStopEvent` handler 中 yield DoneEvent 之前调用：
   ```python
   def _flush_evidence(self) -> None:
       if not self._kb_root or not self._session.kb_refs:
           return
       from datetime import date
       from holmes.kb.store import append_evidence
       today = date.today().isoformat()
       for entry_id in self._session.kb_refs:
           record = {
               "session_id": self._session.id,
               "contributor": self._session.id,
               "date": today,
           }
           try:
               appended = append_evidence(self._kb_root, entry_id, record)
               logger.info(
                   "Evidence flush: entry=%s session=%s appended=%s",
                   entry_id, self._session.id, appended,
               )
           except Exception:
               logger.exception("Failed to flush evidence for entry %s", entry_id)
   ```

### US2 — Maturity 自动更新（FR-004, FR-005）

**无额外改动**。`append_evidence()` 已包含完整 maturity 链式更新逻辑（store.py lines 289-297）。US1 完成后 US2 自动生效。

### US3 — 搜索按 evidence 新鲜度排序（FR-006, FR-007）

**改动：`kb/holmes/kb/search.py`**

1. `SearchResult` 新增字段：
   ```python
   last_evidence_date: Optional[str] = None
   ```

2. `LinearScanBackend.search()` scan 循环中，构建 `SearchResult` 时同时加载 evidence：
   ```python
   from holmes.kb.store import load_evidence, get_last_evidence_date

   # 在 results.append() 前：
   evidence = load_evidence(self._kb_root, str(meta.get("id", md_file.stem)))
   led = get_last_evidence_date(evidence)

   results.append(SearchResult(
       ...  # 现有字段
       last_evidence_date=led,
   ))
   ```

3. 排序键更新（line 123 附近）：
   ```python
   # 旧：
   results.sort(key=lambda r: r.score, reverse=True)
   # 新：
   results.sort(key=lambda r: (r.last_evidence_date or "", r.score), reverse=True)
   ```

### 测试要求

**`agent/tests/test_engine.py`**：
- `test_engine_records_kb_ref_on_successful_read`：mock `_exec_tool` 成功执行 `kb_read_entry`，断言 `session.kb_refs` 含 `entry_id`
- `test_engine_does_not_record_kb_ref_on_error`：`_exec_tool` 返回 `is_error=True`，断言 `session.kb_refs` 为空
- `test_engine_deduplicates_kb_refs`：同一 entry_id 读取两次，`session.kb_refs` 只含一条
- `test_engine_flushes_evidence_on_done`：session 结束时断言 `append_evidence` 被调用（mock store）

**`kb/tests/test_search.py`**：
- `test_search_ranks_evidence_entry_higher`：两条同关键词条目，一条有近期 evidence，一条无；断言有 evidence 的排前
- `test_search_no_evidence_falls_back_to_score`：全无 evidence 时结果顺序与 score 一致

## Agent Context Update

CLAUDE.md 的 plan 引用更新为：`specs/025-kb-lifecycle-p0/plan.md`
