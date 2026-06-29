# 038 — Agent 2 Context 优化：per-node 隔离方案

## 背景

当前 Agent 2 有两条路径：
- `≤30 process 节点`：`_build_initial_messages` 把**完整源文档**塞进初始消息 → `_run_loop` 单循环生成全部 entries → context 线性膨胀
- `>30 process 节点`：`_run_batch_mode` 每批 10 节点独立 context，`title_summary` 传递一致性信息 → context 隔离

**现状问题**：≤30 节点路径中，每轮 turn 的 context 随已写 entry 数量线性增长。5 个节点写完后 context 达 ~6K tokens，其中 60-70% 是已无用的历史 tool result。

## 设计目标

统一两条路径为 **per-node 隔离模式**：每个 process 节点在独立的短对话中生成，context 恒定 ~2K tokens，通过结构化上下文注入保持语义一致性。

## 核心设计

### 执行顺序

```
1. Process 节点（叶节点 → 根方向，拓扑逆序）
   每个节点独立 context，写完收集 brief
2. Pitfall root（最后）
   独立 context，注入全部 process entries 的 brief
3. Consistency review（可选，最后一轮）
   独立 context，随机抽查 + 修正
```

这与现有 batch mode 的 `process → root` 顺序完全一致（`harness2.py:340`）。

### 每个节点的 context 构成

```
┌─────────────────────────────────────────────────────┐
│ System prompt (AGENT2_NODE_PROMPT)        ~400 tok  │  ← 新的精简版 prompt
├─────────────────────────────────────────────────────┤
│ User message:                                       │
│   ① DAG 概览（ASCII 树 + 节点列表）       ~200 tok  │  ← 从现有 dag.md 概览提取
│   ② Entry ID 映射表                       ~100 tok  │  ← 已有 entry_ids_table
│   ③ 已写 entries brief                  ~50/entry  │  ← 新增：{id, title, step_count}
│   ④ Root entry 全文（如已生成）            ~400 tok  │  ← 仅 root，因为 root 最后写所以 process 阶段无此项
│   ⑤ 源文档段落（line_range 切片）        ~300 tok  │  ← 用 line_range 精确切割
│   ⑥ 当前节点任务指令                      ~100 tok  │  ← 节点 ID、entry_id、node_type、children
├─────────────────────────────────────────────────────┤
│ 合计初始 context                        ~1200 tok  │
│ + 对话 turns (~3-5 轮/节点)             ~800 tok   │
│ = 峰值 context                          ~2000 tok  │  恒定，不随节点数增长
└─────────────────────────────────────────────────────┘
```

**对比当前方案**：
- 第 1 个节点：~3000 → ~1200 tokens（降 60%）
- 第 5 个节点：~7500 → ~1500 tokens（降 80%）
- 第 10 个节点：~12000 → ~1700 tokens（降 86%）

### Brief 结构

每个节点写完后，从 `write_entry` 的返回值和 `ctx["written_entries"]` 中提取 brief：

```python
@dataclass
class EntryBrief:
    entry_id: str       # "gpu-init-failure-N2-001"
    node_id: str        # "N2"
    title: str          # "固件修复排查步骤"
    step_count: int     # 5
    has_children: bool  # True
```

序列化为 context 注入（每条 ~50 tokens）：

```
已生成的 entries：
- N2 → gpu-init-failure-N2-001: "固件修复排查步骤"（5步，有子节点）
- N3 → gpu-init-failure-N3-001: "硬件更换排查步骤"（3步，叶节点）
```

### Pitfall root 生成

Root 最后生成，此时所有 process entries 已完成。Root context：

```
① DAG 概览
② Entry ID 映射表
③ 全部 process entries brief（不是全文，是 brief）
④ 源文档全文（root 需要写 Symptoms/Root Cause，需要全局视角）
⑤ 任务指令："生成 pitfall root，entry_id 为 xxx"
```

Root 仍然通过 `read_entry()` 工具获取子节点的真实 title（现有逻辑不变）。

### Consistency review

最后一个独立 context，注入：
- 全部 brief 列表
- 指令：随机抽查 3-5 个 entry，用 `read_entry()` 读取并检查术语一致性
- 有问题则 `write_entry()` 覆盖修正

## 影响范围

### 需要修改的文件

| 文件 | 改动 | 说明 |
|------|------|------|
| `harness2.py` | **主要改动** | 新增 `_run_per_node_mode()`，修改 `run()` 的分支逻辑 |
| `harness2.py` | 新增方法 | `_build_node_messages()`、`_collect_brief()` |
| `harness2.py` | 删除/弃用 | `_build_initial_messages()` 不再使用（≤30 路径去掉） |
| `prompt2.py` | 新增 | `AGENT2_NODE_PROMPT`（per-node 精简版 system prompt） |
| `prompt2.py` | 保留 | `AGENT2_SYSTEM_PROMPT` 保留给 consistency review 阶段 |

### 不需要改动的文件

| 文件 | 原因 |
|------|------|
| `tools2.py` | 工具定义和 handler 不变（write_entry, read_entry, finalize 接口不变） |
| `harness1.py` | Agent 1 不受影响 |
| `__init__.py` | `run_agent2()` 入口签名不变 |
| `id_gen.py` | entry ID 预生成逻辑不变 |
| `report2.py` | 报告打印不变 |

### 向后兼容

- `run_agent2()` 公开接口签名不变
- crash recovery 不受影响（`_scan_written_node_ids()` 走磁盘扫描）
- `retry_nodes` 参数天然兼容（只对指定 node 运行 per-node 循环）
- batch mode（>30 节点）可以保留或统一为 per-node，优先统一

## 详细实现

### 1. `_run_per_node_mode()` 方法

```python
def _run_per_node_mode(
    self,
    process_nodes: list[dict],
    written_node_ids: set[str],
    source_text: str,
    ctx: dict[str, Any],
    report: ImportReport,
) -> None:
    """Per-node isolated context mode — replaces single-loop for all cases."""
    source_lines = source_text.splitlines()
    briefs: list[dict] = []   # collected after each node

    # --- Phase 1: Process nodes (topological reverse) ---
    # 拓扑逆序：子节点先于父节点
    ordered_nodes = self._topological_reverse(process_nodes)

    for node in ordered_nodes:
        node_id = node["id"]
        if node_id in written_node_ids:
            continue

        entry_id = self.entry_ids.get(node_id, "")
        report.phase_traces.append(f"Agent2: generating {node_id} → {entry_id}")

        # Build per-node context
        node_messages = self._build_node_messages(
            node=node,
            source_lines=source_lines,
            briefs=briefs,
        )

        # Run short loop (max 15 turns per node)
        max_turns_node = 15
        ctx["_terminate"] = False
        try:
            self._run_loop(node_messages, ctx, max_turns_node)
        except MaxTurnsExceededError:
            report.warnings.append(f"Node {node_id} exceeded {max_turns_node} turns")

        # Collect brief from written_entries
        brief = self._collect_brief(ctx, node_id, entry_id)
        if brief:
            briefs.append(brief)

    # --- Phase 2: Pitfall root ---
    root_entry_id = self.entry_ids.get("root", "")
    if root_entry_id and "root" not in written_node_ids:
        report.phase_traces.append("Agent2: generating pitfall root")
        ctx["_terminate"] = False
        root_messages = self._build_root_messages(
            source_text=source_text,
            briefs=briefs,
        )
        try:
            self._run_loop(root_messages, ctx, 15)
        except MaxTurnsExceededError:
            report.warnings.append("Pitfall root exceeded max turns")

    # --- Phase 3: Consistency review (optional) ---
    if len(briefs) >= 2:
        ctx["_terminate"] = False
        review_messages = self._build_review_messages(briefs)
        try:
            self._run_loop(review_messages, ctx, 10)
        except MaxTurnsExceededError:
            pass  # review is best-effort
```

### 2. `_build_node_messages()` 方法

```python
def _build_node_messages(
    self,
    node: dict,
    source_lines: list[str],
    briefs: list[dict],
) -> list[Any]:
    """Build isolated context for a single process node."""

    # ① DAG 概览
    dag_overview = self._format_dag_overview()  # 从 self.dag_json 生成 ASCII 树

    # ② Entry ID 映射
    entry_ids_table = "\n".join(
        f"  {nid}: {eid}" for nid, eid in self.entry_ids.items()
    )

    # ③ 已写 entries brief
    brief_text = "\n".join(
        f"  - {b['node_id']} → {b['entry_id']}: \"{b['title']}\"（{b['step_count']}步）"
        for b in briefs
    ) or "  (尚无已生成的 entries)"

    # ④ 源文档段落（line_range 切片）
    lr = node.get("line_range")
    if lr and len(lr) == 2:
        start, end = lr
        # 扩展 ±5 行以提供上下文
        safe_start = max(0, start - 5)
        safe_end = min(len(source_lines), end + 5)
        segment = "\n".join(source_lines[safe_start:safe_end])
        source_info = f"源文档段落（行 {safe_start+1}-{safe_end}）：\n{segment}"
    else:
        heading = node.get("section_heading", "")
        source_info = (
            f"请用 Grep(\"{heading}\", \"{self.source_file}\") 定位，"
            f"然后用 Read 提取该 section 内容。"
        )

    # ⑤ 节点任务指令
    node_id = node["id"]
    entry_id = self.entry_ids.get(node_id, "")
    children_info = ""
    children_ids = node.get("children", [])
    if children_ids:
        children_lines = []
        for c in children_ids:
            target = c.get("target", "")
            cond = c.get("condition", "")
            c_eid = self.entry_ids.get(target, target)
            children_lines.append(f"    {cond} → {target} ({c_eid})")
        children_info = "  子节点跳转：\n" + "\n".join(children_lines)

    task = (
        f"请为以下节点生成 process entry：\n"
        f"  node_id: {node_id}\n"
        f"  entry_id: {entry_id}\n"
        f"  description: {node.get('description', '')}\n"
        f"  node_type: {node.get('node_type', '')}\n"
        f"  parent_id: {self.entry_ids.get(node.get('parent_id', ''), 'null')}\n"
        f"{children_info}\n\n"
        f"source_hash: {self.source_hash}\n"
        f"source_file: {self.source_file}\n"
    )

    content = (
        f"DAG 概览：\n{dag_overview}\n\n"
        f"entry_ids 表：\n{entry_ids_table}\n\n"
        f"已生成 entries：\n{brief_text}\n\n"
        f"{source_info}\n\n"
        f"{task}\n"
        f"生成完成后调用 finalize()。"
    )
    return [{"role": "user", "content": content}]
```

### 3. `_collect_brief()` 方法

```python
def _collect_brief(
    self, ctx: dict, node_id: str, entry_id: str
) -> Optional[dict]:
    """Extract brief summary from the most recently written entry."""
    for entry in reversed(ctx.get("written_entries", [])):
        if entry.get("entry_id") == entry_id:
            fm = entry.get("frontmatter", {})
            body = entry.get("body", "")
            step_count = len(re.findall(r"^\d+\.\s+", body, re.MULTILINE))
            return {
                "node_id": node_id,
                "entry_id": entry_id,
                "title": str(fm.get("title", entry_id)),
                "step_count": step_count,
                "has_children": bool(fm.get("child_entry_ids")),
            }
    return None
```

### 4. `AGENT2_NODE_PROMPT`（精简版 system prompt）

```python
AGENT2_NODE_PROMPT = """\
你是 Holmes KB 知识提取专家。你的任务是为排查树中的**一个 process 节点**生成 KB entry。

## 输入

user message 中包含：
- DAG 概览（全树结构）
- entry_id 映射表
- 已生成 entries 的摘要（标题和步骤数）
- 源文档段落（当前节点的相关内容）
- 当前节点的元信息（node_id, entry_id, node_type, parent_id, children）

## 工作流程

1. 阅读 user message 中的源文档段落
2. 如有子节点且已生成 → 调用 read_entry(child_id) 获取真实 title
3. 调用 write_entry(entry_id, content) 生成 entry
4. 校验失败则修正后重试
5. 调用 finalize()

## 格式约束

（此处复用现有 prompt2.py 中的 Process entry frontmatter 和 Steps 格式部分，不重复）
"""
```

### 5. `run()` 方法修改

```python
def run(self, source_text: str = "", retry_nodes=None) -> ImportReport:
    # ... 前面不变（username 校验、load dag_json、process_nodes、written_node_ids）...

    # 统一使用 per-node 模式（删除 if process_count > 30 分支）
    self._run_per_node_mode(
        process_nodes=effective_nodes,
        written_node_ids=written_node_ids,
        source_text=source_text,
        ctx=ctx,
        report=report,
    )

    # ... 后面不变（collect results、lint、report）...
```

## 测试计划

### 单元测试（确定性）

| ID | 测试内容 | 验证点 |
|----|---------|--------|
| T1 | `_build_node_messages` 输出包含 DAG 概览 | assert "N1" in content |
| T2 | `_build_node_messages` 包含 source segment（有 line_range） | assert source_lines[start:end] in content |
| T3 | `_build_node_messages` 无 line_range 时给出 Grep 指令 | assert "Grep" in content |
| T4 | `_build_node_messages` 包含 brief | assert "已生成" in content |
| T5 | `_collect_brief` 正确提取 title 和 step_count | mock written_entries |
| T6 | `_collect_brief` 无匹配返回 None | empty written_entries |
| T7 | `_topological_reverse` 叶节点在前 | N3 before N2 |
| T8 | `_build_root_messages` 包含全部 brief | assert all entry_ids in content |
| T9 | context 大小恒定性：5 节点后 messages[0] 长度 < 3000 chars | measure len |

### LLM 集成测试（@llm）

| ID | 测试内容 | 验证点 |
|----|---------|--------|
| L1 | DOC-01 per-node 模式生成完整 entries | 命令保真、结构完整 |
| L2 | 术语一致性：所有 entries 使用相同术语 | 检查 "nvidia-smi" 不出现 "显卡驱动" 等替代词 |
| L3 | 交叉引用一致性：parent_id/child_entry_ids 正确 | 遍历验证无断链 |
| L4 | per-node vs 旧单 loop 质量对比（同一文档） | 命令保真率 ≥ 旧方案 |

## 风险和回退

| 风险 | 概率 | 回退方案 |
|------|------|---------|
| per-node 模式下模型不调用 finalize() | 中 | `_run_loop` 结束后检查，未 finalize 则自动调用 |
| source segment 切割不完整（line_range 不精确） | 低 | ±5 行扩展 + fallback 到 Grep 定位 |
| consistency review 增加总耗时 | 低 | review 是 best-effort，超时直接跳过 |
| 旧 batch mode (>30) 路径被移除后回归 | 低 | per-node 天然覆盖 >30 场景（逐个处理） |
