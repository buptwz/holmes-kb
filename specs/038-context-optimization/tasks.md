# 038 — Agent 2 Context 优化：任务清单

> 详细设计方案见 [plan.md](./plan.md)
> 预估总工作量：3-4 人天（含测试）

---

## 任务依赖关系

```
T1 ──┐
T2 ──┤
T3 ──┼──→ T5 ──→ T6 ──→ T7 ──→ T8 ──→ T9
T4 ──┘
```

- T1-T4 可并行，无依赖
- T5 依赖 T1-T4 全部完成
- T6-T9 串行

---

## T1: 新增 `EntryBrief` 数据结构和 `_collect_brief()` 方法

**文件**: `kb/holmes/kb/agent/dag/harness2.py`

**内容**:
1. 新增 `EntryBrief` dataclass（字段：`entry_id`, `node_id`, `title`, `step_count`, `has_children`）
2. 实现 `_collect_brief(self, ctx, node_id, entry_id) -> Optional[dict]`
   - 从 `ctx["written_entries"]` 反向遍历查找匹配 entry
   - 用正则 `r"^\d+\.\s+"` 统计步骤数
   - 返回 brief dict 或 None

**验收标准**:
- [ ] `_collect_brief` 有匹配时返回正确的 title 和 step_count
- [ ] `_collect_brief` 无匹配时返回 None
- [ ] 单元测试 T5、T6 通过（见 plan.md 测试计划）

---

## T2: 新增 `AGENT2_NODE_PROMPT` 精简版 system prompt

**文件**: `kb/holmes/kb/agent/dag/prompt2.py`

**内容**:
1. 新增 `AGENT2_NODE_PROMPT` 常量
2. 内容参考 plan.md §4，核心要素：
   - 角色定义：单节点生成专家
   - 输入说明：user message 中的 5 部分内容
   - 工作流程：读段落 → 读子节点 → write_entry → finalize
   - 格式约束：从现有 `AGENT2_SYSTEM_PROMPT` 中提取 process entry frontmatter 和 Steps 格式部分
3. 保留原 `AGENT2_SYSTEM_PROMPT`（给 consistency review 用）

**验收标准**:
- [ ] `AGENT2_NODE_PROMPT` 可正常 import
- [ ] 包含 write_entry/finalize 调用指引
- [ ] 包含 process entry 格式约束（frontmatter 字段 + Steps 格式）
- [ ] 总长度控制在 ~400 tokens（约 600 汉字）

---

## T3: 实现 `_build_node_messages()` 方法

**文件**: `kb/holmes/kb/agent/dag/harness2.py`

**内容**:
1. 实现 `_build_node_messages(self, node, source_lines, briefs) -> list[dict]`
2. 组装 5 部分 context：
   - ① DAG 概览：复用 `_format_dag_overview()`（如不存在，需新增一个从 `self.dag_json` 生成 ASCII 树的辅助方法）
   - ② Entry ID 映射表：遍历 `self.entry_ids`
   - ③ 已写 entries brief：从 `briefs` 参数格式化
   - ④ 源文档段落：用 `node["line_range"]` 切片 `source_lines`，±5 行扩展；无 line_range 时给 Grep fallback 指令
   - ⑤ 节点任务指令：node_id、entry_id、description、node_type、parent_id、children 跳转条件
3. 返回 `[{"role": "user", "content": content}]`

**验收标准**:
- [ ] 输出包含 DAG 概览（含节点 ID）
- [ ] 有 line_range 时包含源文档 segment
- [ ] 无 line_range 时包含 Grep 指令
- [ ] 包含 brief 信息
- [ ] 单元测试 T1-T4、T9 通过

---

## T4: 实现 `_build_root_messages()` 和 `_build_review_messages()`

**文件**: `kb/holmes/kb/agent/dag/harness2.py`

**内容**:

### `_build_root_messages(self, source_text, briefs) -> list[dict]`
1. context 组成：DAG 概览 + entry_ids + **全部** process entries brief + **源文档全文** + 任务指令
2. 任务指令："生成 pitfall root entry，entry_id 为 {root_entry_id}"
3. 使用 `AGENT2_NODE_PROMPT` 或 `AGENT2_SYSTEM_PROMPT` 作为 system prompt（推荐前者，增加 root 特定指令）

### `_build_review_messages(self, briefs) -> list[dict]`
1. context 组成：全部 brief 列表 + 指令
2. 指令："随机抽查 3-5 个 entry，用 read_entry() 读取，检查术语一致性和交叉引用，有问题则 write_entry() 覆盖修正"
3. 使用 `AGENT2_SYSTEM_PROMPT` 作为 system prompt

**验收标准**:
- [ ] `_build_root_messages` 包含全部 brief 和源文档全文
- [ ] `_build_review_messages` 包含 brief 列表和抽查指令
- [ ] 单元测试 T8 通过

---

## T5: 实现 `_run_per_node_mode()` 主流程

**文件**: `kb/holmes/kb/agent/dag/harness2.py`

**依赖**: T1、T2、T3、T4

**内容**:
1. 实现 `_run_per_node_mode(self, process_nodes, written_node_ids, source_text, ctx, report)`
2. 三阶段流程：
   - Phase 1: 拓扑逆序遍历 process 节点，每个节点调用 `_build_node_messages` → `_run_loop`（max 15 turns）→ `_collect_brief`
   - Phase 2: 生成 pitfall root，调用 `_build_root_messages` → `_run_loop`
   - Phase 3: consistency review（≥2 entries 时），调用 `_build_review_messages` → `_run_loop`（max 10 turns）
3. 需要新增 `_topological_reverse(nodes)` 辅助方法（叶节点优先）
4. 每阶段前重置 `ctx["_terminate"] = False`
5. `MaxTurnsExceededError` 捕获并记录 warning

**注意**:
- `_run_loop()` 的 system prompt 传入方式：检查现有 `_run_loop` 签名，可能需要增加 `system_prompt` 参数，或在 messages 列表首位插入 `{"role": "system", "content": ...}`
- 拓扑逆序算法：遍历 nodes 的 children 依赖构建 DAG，然后做拓扑排序再 reverse

**验收标准**:
- [ ] Process 节点按拓扑逆序执行（子节点先于父节点）
- [ ] 已写节点（`written_node_ids`）被跳过
- [ ] Pitfall root 最后生成
- [ ] 每个节点的 context 独立（不复用前一个节点的 messages）
- [ ] 单元测试 T7 通过

---

## T6: 修改 `run()` 统一执行路径

**文件**: `kb/holmes/kb/agent/dag/harness2.py`

**依赖**: T5

**内容**:
1. 在 `run()` 方法中，删除 `if process_count > 30` 分支判断
2. 统一调用 `_run_per_node_mode()` 替代原来的两条路径：
   - 删除/弃用 `_build_initial_messages()` + 单循环 `_run_loop()` 路径
   - 保留或删除 `_run_batch_mode()` — 推荐删除，因为 per-node 已覆盖
3. 保留 `retry_nodes` 参数支持：过滤 `effective_nodes` 时只保留指定节点

**验收标准**:
- [ ] `run()` 不再有 `>30` 分支
- [ ] 旧的 `_build_initial_messages()` 路径不再被调用
- [ ] `retry_nodes` 仍能正常工作
- [ ] 现有 `run_agent2()` 公开接口签名不变

---

## T7: 单元测试

**文件**: `kb/tests/test_harness2_context.py`（新建）

**依赖**: T6

**内容**:
实现 plan.md 中的 9 个单元测试：

| ID | 测试方法名 | 验证点 |
|----|-----------|--------|
| T1 | `test_build_node_messages_contains_dag` | output 包含 DAG 节点 ID |
| T2 | `test_build_node_messages_source_segment` | 有 line_range 时包含对应源文本行 |
| T3 | `test_build_node_messages_grep_fallback` | 无 line_range 时包含 "Grep" |
| T4 | `test_build_node_messages_contains_brief` | 包含已生成 entries 摘要 |
| T5 | `test_collect_brief_extracts_correctly` | mock written_entries，验证返回 title/step_count |
| T6 | `test_collect_brief_returns_none` | empty written_entries → None |
| T7 | `test_topological_reverse_leaves_first` | 叶节点排在父节点前面 |
| T8 | `test_build_root_messages_has_all_briefs` | 所有 entry_id 出现在 root messages 中 |
| T9 | `test_context_size_constant` | 5 节点后 messages[0] content < 3000 chars |

**验收标准**:
- [ ] 9 个单元测试全部通过
- [ ] 不依赖 LLM API（纯 mock/确定性）
- [ ] `pytest kb/tests/test_harness2_context.py -v` 全绿

---

## T8: LLM 集成测试

**文件**: `kb/tests/test_e2e_llm.py`（在现有文件追加）

**依赖**: T7

**内容**:
新增 4 个 `@pytest.mark.llm` 测试：

| ID | 测试方法名 | 验证点 |
|----|-----------|--------|
| L1 | `test_per_node_generates_complete_entries` | DOC-01 文档 per-node 模式生成完整 entries，命令保真 |
| L2 | `test_per_node_terminology_consistency` | 所有 entries 术语一致（如 "nvidia-smi" 不被替换为 "显卡驱动"） |
| L3 | `test_per_node_cross_reference_integrity` | parent_id/child_entry_ids 无断链 |
| L4 | `test_per_node_context_efficiency` | 记录每个节点的 input tokens，验证不随节点数增长 |

**验收标准**:
- [ ] 4 个 LLM 测试通过（允许 xfail 标记不稳定的）
- [ ] L4 验证 context 恒定性：最后一个节点的 input tokens ≤ 第一个节点的 1.5x

---

## T9: 清理和文档

**依赖**: T8

**内容**:
1. 删除不再使用的方法：`_build_initial_messages()`、`_run_batch_mode()`、`_build_batch_messages()`（如确认无其他调用方）
2. 更新 `prompt2.py` 中的注释，说明 `AGENT2_SYSTEM_PROMPT` 仅用于 review 阶段
3. 如有 CHANGELOG 或 release notes，记录此优化

**验收标准**:
- [ ] 无 dead code 残留
- [ ] `grep -r "_build_initial_messages\|_run_batch_mode" kb/` 无结果
- [ ] 全量测试通过：`pytest kb/tests/ -v`
