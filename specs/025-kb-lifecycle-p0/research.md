# Research: Knowledge Lifecycle P0 — Evidence, Maturity, Search

**Feature**: `025-kb-lifecycle-p0` | **Date**: 2026-06-11

## Decision 1: P0-2 已隐式实现 — 无需额外工作

**Decision**: P0-2 (maturity 自动更新) 不需要单独实现。

**Finding**: `kb/holmes/kb/store.py` 中的 `append_evidence()` 已在内部链式调用 maturity 计算：

```python
# store.py lines 289-297
new_all_evidence = all_existing + [evidence_record]
new_maturity = derive_maturity(new_all_evidence)
if new_rank > current_rank:
    post.metadata["maturity"] = new_maturity
    entry_path.write_text(frontmatter.dumps(post), encoding="utf-8")
```

只要 P0-1 正确调用 `append_evidence()`，maturity 自动更新即已完成。P0-2 标记为"随 P0-1 免费获得"。

**Rationale**: 利用现有已测实现，避免重复。

---

## Decision 2: Evidence 写回触发点 — engine.py 内部处理

**Decision**: evidence 写回在 `engine.py` 的 `_InternalStopEvent` handler 中完成，不依赖外部调用方。

**Alternatives considered**:
- **Option A (chosen)**: engine 内部调用 `append_evidence()`，在 `_InternalStopEvent` handler 处，yield `DoneEvent` 之前。`AgentEngine` 已有 `self._kb_root`，无需注入新依赖。
- **Option B**: 调用方（TUI/CLI）监听 `DoneEvent.kb_refs` 后自行调用。问题：调用方需额外处理 kb_root 传递，且每个调用入口都要实现一遍，违反单一职责。

**Rationale**: Engine 已拥有 `_kb_root` 和 session 生命周期，最小化改动，调用方无感知。

---

## Decision 3: session.kb_refs 填充时机 — 工具执行成功后

**Decision**: 在 `_exec_tool()` 成功返回且 `tool_name == "kb_read_entry"` 时，将 `tool_input["entry_id"]` 追加到 `self._session.kb_refs`。

**Finding**:
- `session.py:Session.kb_refs: list[str] = []` 已定义，只是从未被填充
- `engine.py` line 298 已传递 `kb_refs=list(self._session.kb_refs)` 到 `DoneEvent`
- `KbReadEntryTool` 的 `input_schema` 有 `entry_id` 字段，工具名为 `"kb_read_entry"`
- 去重：`session.kb_refs` 追加前检查是否已存在（同一 session 内多次读同一条目只记一次）

**Rationale**: 最小改动，只追踪最有价值的信号（full entry read，而非 overview/index）。

---

## Decision 4: Evidence record contributor 字段 — 使用 session.id 作为默认值

**Decision**: Evidence record 的 `contributor` 字段默认使用 `session.id`（UUID），`date` 使用 UTC today（YYYY-MM-DD）。

**Rationale**:
- `derive_maturity()` 使用 `contributors` 集合来判断 proven 阈值（≥2 distinct contributors）
- 没有用户身份体系时，用 session_id 作为 contributor 保证每次 session 都是唯一 contributor，但 proven 阈值实际上要求两个不同 session 调用
- 这是合理的降级：proven = 至少 2 次不同 session 引用过，即"被多个排障场景验证"
- 未来可通过 config 添加 `contributor_name` 字段，向后兼容

---

## Decision 5: 搜索排序 — (evidence_date DESC, score DESC) 双键排序

**Decision**: `LinearScanBackend.search()` 改为以 `last_evidence_date` 为主键（DESC）、`score` 为次键（DESC）排序。无 evidence 的条目 `last_evidence_date` 为空字符串，自然排在所有有日期的条目之后。

**Alternatives considered**:
- **Option A (chosen)**: 纯字典序比较 ISO 日期字符串，`"" < "2024-..."` 保证无 evidence 排后
- **Option B**: 加权融合 `score * w1 + evidence_freshness_factor * w2`。问题：引入两个调参参数，过度设计
- **Option C**: 只有相同 score 时才用 evidence 排序。问题：弱化 evidence 的信号价值

**Rationale**: 简单、可预期、无超参数。关键词过滤（hits==0 直接排除）保证相关性不受影响。

---

## Decision 6: SearchResult 新增 last_evidence_date 字段

**Decision**: `SearchResult` dataclass 新增 `last_evidence_date: Optional[str] = None` 字段。

**Rationale**:
- 调用方（TUI/CLI）可能需要展示 evidence 日期以帮助用户评估条目新鲜度
- 不新增字段则无法传递此信息给展示层
- 用 `Optional[str]` + 默认值保证向后兼容：现有代码直接实例化 `SearchResult` 时不需要传此字段

---

## Code Paths Summary

### P0-1 改动文件：`agent/holmes/agent/engine.py`

```text
改动 1：_exec_tool 返回后
  if tool_name == "kb_read_entry" and not result.is_error:
    entry_id = tool_input.get("entry_id", "")
    if entry_id and entry_id not in self._session.kb_refs:
        self._session.kb_refs.append(entry_id)

改动 2：_InternalStopEvent handler 中，yield DoneEvent 之前
  if self._kb_root and self._session.kb_refs:
    self._flush_evidence()  # 调用 append_evidence for each entry_id

新增 _flush_evidence() 私有方法：
  from holmes.kb.store import append_evidence
  for entry_id in self._session.kb_refs:
    append_evidence(kb_root, entry_id, {
      "session_id": session.id,
      "contributor": session.id,
      "date": today_iso,
    })
```

### P0-2 无改动（随 P0-1 免费）

### P0-3 改动文件：`kb/holmes/kb/search.py`

```text
改动 1：SearchResult 新增 last_evidence_date: Optional[str] = None
改动 2：scan 循环中，build SearchResult 后调用
  load_evidence(kb_root, entry_id) → get_last_evidence_date(evidence)
改动 3：sort key 改为 lambda r: (r.last_evidence_date or "", r.score)
  注意：两个字段都升序，最终 reverse=True，等价于双键降序
```

---

## Tests Required

| Test | File | What |
|------|------|------|
| test_engine_records_kb_ref | agent/tests/test_engine.py | kb_read_entry 调用后 session.kb_refs 含 entry_id |
| test_engine_flushes_evidence | agent/tests/test_engine.py | session 结束后 append_evidence 被调用 |
| test_engine_dedup_kb_refs | agent/tests/test_engine.py | 同 session 多次读同一条目只记一次 |
| test_search_evidence_ranks_higher | kb/tests/test_search.py | 有 evidence 条目排在同 score 无 evidence 条目前 |
| test_search_no_evidence_falls_back | kb/tests/test_search.py | 全无 evidence 时退回 score 排序 |

## No New External Dependencies

所有改动使用项目内现有模块（`store.py`，`session.py`），stdlib `datetime`。无新 pip 包。
