# Research: M5 — Agent 2 双源知识生成

**Date**: 2026-06-24

## Decision 1: Agent 2 工具集复用 tools1.py 的 Read/Grep

**Decision**: `tools2.py` 直接 `from holmes.kb.agent.dag.tools1 import tool_read, tool_grep` 复用现有实现，不重新实现。

**Rationale**: `tool_read` 和 `tool_grep` 已经实现文件路径解析（`_resolve_file`），支持 in-memory source text 和文件系统路径，完全满足 Agent 2 的需求。Agent 2 的 ctx 包含 `source_file`, `source_text`, `kb_root`，与 tools1 的 ctx 接口兼容。

**Alternatives considered**: 重新实现 Read/Grep — 无收益，增加代码重复。

---

## Decision 2: write_entry 内置格式校验在工具层实现

**Decision**: 格式校验逻辑完全在 `tool_write_entry()` 函数内实现，校验失败返回 `{"error": "..."}` dict（不抛异常），校验通过才调用 `atomic_write()`。

**Rationale**: 与 Agent 1 的 `tool_output_dag()` 设计完全一致（也是返回 error dict）。`tool_write_entry` 的调用者（`harness2._execute_tool`）统一处理返回值，agent 通过 tool_result 感知错误并修正重试。

**Alternatives considered**: 在 harness 层校验 — 违反工具封装原则；抛异常 — 导致 loop 中断而非 agent 感知修正。

---

## Decision 3: Entry ID 写入 .dag.json 的 entry_ids 字段

**Decision**: `id_gen.py` 读取 `.dag.json`，为每个 process 节点和 pitfall root 分配 ID，将结果写入同一文件的顶层 `entry_ids` 字段（`dict[node_id, entry_id]` + `"root"` 键）。Agent 2 通过 `read_dag()` 读取此字段。

**Rationale**: `.dag.json` 已是 agent 之间的通信载体，entry_ids 作为其扩展字段自然。避免引入额外文件。`dag_to_json()` 不修改（结构性修改风险），而是在 JSON 中追加 `entry_ids` 字段（JSON merge）。

**Import-seq**: 从 `_import-state/` 目录扫描现有 `.dag.json` 文件，取最大 seq 号加 1；如果没有则从 `001` 开始。重试时读取已存在的 entry_ids 字段，不重新生成（幂等）。

**Alternatives considered**: 单独 `.entry-ids.json` 文件 — 增加文件数量，不必要。

---

## Decision 4: Step 2.5 解析规范化使用单次 LLM 调用

**Decision**: `step25.py` 使用 `provider.complete()` 单次调用，将用户编辑后的 `.dag.md` 内容和原始文档（前 3000 字符）作为输入，输出 JSON 格式的识别结果（`recognized_edits`, `uncertain_items`, `validation_results`）。

**Rationale**: 与 blueprint 一致（"LLM 单次调用"）。单次调用足以处理自然语言识别任务，且成本可控。

**LLM 失败处理**: LLM 调用失败时，跳过解析规范化（仅做程序化 Grep 验证），在展示界面标注"解析未完成，仅展示验证结果"。

---

## Decision 5: 分批子 agent 使用独立 messages 数组

**Decision**: >20 process 节点时，`harness2.py` 对每批 10 节点调用 `_run_batch_agent(batch_nodes, title_summary)` — 该函数创建全新的 `messages=[]` 列表（独立 context），用同一个 `provider` 实例发 LLM 请求。

**Rationale**: 与 brief.md 和 blueprint 一致（"每批启动独立 sub-agent（全新 context）"）。Python 中通过新列表实现 context 隔离，不需要新进程。

**Alternatives considered**: 多进程/多线程 — 引入复杂性，不必要；通过系统消息清除 context — 不够干净。

---

## Decision 6: Crash Recovery 通过已写文件 checkpoint

**Decision**: `harness2.py` 在启动时扫描 `_pending/` 下已存在的以本次 `import-seq` 结尾的文件，构建"已写节点 ID 集合"，在生成循环中跳过已写节点。不做 session.json 快照。

**Rationale**: 与 blueprint 一致（"已写文件天然 checkpoint"）。实现比 session.json 更简单，文件本身就是最新状态。

---

## Decision 7: write_entry 写文件路径

**Decision**: `write_entry(entry_id, content)` 从 content 的 frontmatter 解析 `type` 和 `category`（Agent 2 写入时必须包含），路径为 `_pending/<type>/<category>/<entry_id>.md`。

**Category 推断**: Agent 2 在 Phase 1 Study 时从文档内容推断 category（如 `hardware`, `network`），并在 `write_entry` 的 content frontmatter 中包含 `category` 字段（必填字段之一）。

**文件名**: `<entry_id>.md`（entry_id 已是 slug 格式）。

---

## Decision 8: --retry-entry 实现方式

**Decision**: CLI 新增 `--retry-entry <node-id>` flag。调用时：
1. 读取已有 `.dag.json`（需要 `--source <file>` 或 `--resume` 找到对应 hash）
2. 读取 `entry_ids` 中该节点对应的 entry_id
3. 启动独立 Agent 2 loop，只传入该单个节点（`retry_nodes=[node_id]`）
4. 已有文件作为 checkpoint，其他节点不重新生成

**Rationale**: 最小改动，复用 harness2 的完整逻辑，只是节点集合变为单个节点。

---

## Decision 9: report2.py vs 复用现有 ImportReport

**Decision**: 新增 `report2.py` 提供 `print_agent2_report(report, dag_title, root_ids)` 函数，接收现有 `ImportReport` 对象并格式化打印 Agent 2 专用的展示格式（含分隔线、树信息、retry 命令、下一步提示）。不修改 `ImportReport` dataclass。

**Rationale**: 现有 `ImportReport.format_summary()` 是单行格式，不适合 Agent 2 的多行展示需求。新函数不破坏现有接口。
