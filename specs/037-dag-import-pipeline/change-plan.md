# 037 Design-Gaps 改动执行计划

> 本文档供执行者（cheaper model）逐步执行。每个 STEP 独立可测试。
> 执行完每个 STEP 后运行 `cd /home/wangzhi/project/projectTmp/holmes/holmes && python -m pytest kb/tests/test_dag_schema.py kb/tests/test_dag_formatter.py kb/tests/test_dag_tools1.py -x -q` 确认不 break。
> 所有文件路径相对于 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/holmes/kb/agent/dag/`，测试文件路径相对于 `/home/wangzhi/project/projectTmp/holmes/holmes/kb/tests/`。

---

## STEP 1: schema.py — 扩展 NodeType enum + 新增 line_range 字段

### 1.1 修改 NodeType enum（第 20-26 行）

**当前代码：**
```python
class NodeType(str, Enum):
    """Semantic type of a DAG node — hint for Agent 2 generation."""

    human_observation = "human_observation"
    api_call = "api_call"
    decision = "decision"
    action = "action"
```

**改为：**
```python
class NodeType(str, Enum):
    """Semantic type of a DAG node — drives behavior tags in KB entries.

    5 types (original 'action' split into remote_action + physical_action):
      - human_observation: must be done by human on-site (eyes/ears/hands)
      - api_call: remote command/API to retrieve information (read-only)
      - remote_action: remote command/API to change system state
      - physical_action: physical manipulation of hardware
      - decision: choose branch based on prior results
    """

    human_observation = "human_observation"
    api_call = "api_call"
    remote_action = "remote_action"
    physical_action = "physical_action"
    decision = "decision"
```

**注意：删除 `action = "action"`，新增 `remote_action` 和 `physical_action`。**

### 1.2 DAGNode 新增 line_range 字段（第 57-77 行）

**当前 DAGNode dataclass：**
```python
@dataclass
class DAGNode:
    id: str
    description: str
    node_type: NodeType
    complexity: Complexity
    section_heading: Optional[str] = None
    is_end: bool = False
    children: list[DAGEdge] = field(default_factory=list)
```

**改为（在 `section_heading` 之后新增 `line_range`）：**
```python
@dataclass
class DAGNode:
    id: str
    description: str
    node_type: NodeType
    complexity: Complexity
    section_heading: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None
    is_end: bool = False
    children: list[DAGEdge] = field(default_factory=list)
```

**同时更新 DAGNode 的 docstring**，在 `section_heading` 行之后加一行：
```
        line_range: Source document line range [start, end] for Agent 2 to locate content.
```

### 1.3 验证

运行 `python -m pytest kb/tests/test_dag_schema.py -x -q`。预期部分测试失败（因为测试中使用了 `NodeType.action`），这在 STEP 9 中统一修复。先确认 import 不报错：
```bash
python -c "from holmes.kb.agent.dag.schema import NodeType, DAGNode; print(list(NodeType))"
```
预期输出包含 5 个成员，无 `action`。

---

## STEP 2: formatter.py — 序列化/反序列化支持 line_range + 新 node_type

### 2.1 dag_to_json 增加 line_range 序列化（第 303-329 行）

在 `dag_to_json` 函数中，节点序列化字典中（第 315 行 `"section_heading"` 之后）增加：
```python
                "line_range": n.line_range,
```

完整的节点 dict 变为：
```python
            {
                "id": n.id,
                "description": n.description,
                "node_type": n.node_type.value,
                "complexity": n.complexity.value,
                "section_heading": n.section_heading,
                "line_range": n.line_range,
                "is_end": n.is_end,
                "children": [...]
            }
```

### 2.2 dag_from_json 增加 line_range 反序列化（第 332-369 行）

在 `dag_from_json` 函数中，构造 DAGNode 时（第 353 行附近），增加 `line_range` 参数：

**当前：**
```python
        nodes.append(
            DAGNode(
                id=nd["id"],
                description=nd.get("description", ""),
                node_type=nt,
                complexity=cx,
                section_heading=nd.get("section_heading"),
                is_end=nd.get("is_end", False),
                children=children,
            )
        )
```

**改为：**
```python
        # Parse line_range: JSON stores as [start, end] list or null.
        lr = nd.get("line_range")
        line_range = tuple(lr) if isinstance(lr, list) and len(lr) == 2 else None

        nodes.append(
            DAGNode(
                id=nd["id"],
                description=nd.get("description", ""),
                node_type=nt,
                complexity=cx,
                section_heading=nd.get("section_heading"),
                line_range=line_range,
                is_end=nd.get("is_end", False),
                children=children,
            )
        )
```

### 2.3 dag_from_json 中 NodeType fallback 值修改（第 346-348 行）

**当前：**
```python
        try:
            nt = NodeType(nd.get("node_type", "action"))
        except ValueError:
            nt = NodeType.action
```

**改为：**
```python
        raw_nt = nd.get("node_type", "decision")
        # Backward compat: old "action" maps to remote_action.
        if raw_nt == "action":
            raw_nt = "remote_action"
        try:
            nt = NodeType(raw_nt)
        except ValueError:
            nt = NodeType.decision
```

### 2.4 _parse_node_block 中 NodeType fallback 值修改（第 255-260 行）

**当前：**
```python
    node_type_m = _RE_NODE_TYPE.search(block_text)
    node_type_val = node_type_m.group(1).strip().lower() if node_type_m else "action"
    try:
        node_type = NodeType(node_type_val)
    except ValueError:
        node_type = NodeType.action
```

**改为：**
```python
    node_type_m = _RE_NODE_TYPE.search(block_text)
    node_type_val = node_type_m.group(1).strip().lower() if node_type_m else "decision"
    # Backward compat: old "action" maps to remote_action.
    if node_type_val == "action":
        node_type_val = "remote_action"
    try:
        node_type = NodeType(node_type_val)
    except ValueError:
        node_type = NodeType.decision
```

### 2.5 _parse_node_block 增加 line_range 解析（第 262-264 行之后）

在解析 `section_heading` 之后、`is_end` 之前，增加 line_range 解析：

```python
    # line_range (optional)
    lr_m = re.search(r"^line_range:\s*\[(\d+)\s*,\s*(\d+)\]", block_text, re.MULTILINE)
    line_range = (int(lr_m.group(1)), int(lr_m.group(2))) if lr_m else None
```

然后在 `_parse_node_block` 返回的 DAGNode 构造中增加 `line_range=line_range`：

**当前：**
```python
    return DAGNode(
        id=node_id,
        description=description,
        node_type=node_type,
        complexity=complexity,
        section_heading=section_heading,
        is_end=is_end,
        children=children,
    )
```

**改为：**
```python
    return DAGNode(
        id=node_id,
        description=description,
        node_type=node_type,
        complexity=complexity,
        section_heading=section_heading,
        line_range=line_range,
        is_end=is_end,
        children=children,
    )
```

### 2.6 _node_to_block 输出 line_range（第 94-112 行）

在 `_node_to_block` 中，`section_heading` 输出行之后（第 102 行），增加 line_range 输出：

**当前：**
```python
    if node.section_heading:
        lines.append(f'section_heading: "{node.section_heading}"')
    lines.append("")
```

**改为：**
```python
    if node.section_heading:
        lines.append(f'section_heading: "{node.section_heading}"')
    if node.line_range:
        lines.append(f"line_range: [{node.line_range[0]}, {node.line_range[1]}]")
    lines.append("")
```

### 2.7 _build_ascii_tree 增加行为标签（第 115-150 行）

在 `_build_ascii_tree` 中，每个节点描述前增加 node_type 缩写标签。

**新增映射常量**（在 `_build_ascii_tree` 函数之前）：

```python
_NODE_TYPE_TAG: dict[str, str] = {
    "human_observation": "[observe]",
    "api_call": "[api]",
    "remote_action": "[remote]",
    "physical_action": "[physical]",
    "decision": "[decide]",
}
```

**修改 `_render` 函数内部**（第 132-134 行）：

**当前：**
```python
        icon = " 🔧" if node.complexity == Complexity.process else ""
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{node.description}{icon}")
```

**改为：**
```python
        icon = " 🔧" if node.complexity == Complexity.process else ""
        tag = _NODE_TYPE_TAG.get(node.node_type.value, "")
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{tag} {node.description}{icon}")
```

### 2.8 验证

```bash
python -c "from holmes.kb.agent.dag.formatter import dag_to_json, dag_from_json; print('OK')"
```

---

## STEP 3: tools1.py — output_dag 增加 node_type 校验

### 3.1 _validate_dag 增加 node_type 合法性检查（在 Rule 5 之后）

在 `_validate_dag` 函数中（第 210 行 `return ""` 之前），增加 Rule 6：

```python
    # Rule 6: node_type must be one of the 5 valid types
    valid_types = {nt.value for nt in NodeType}
    for n in graph.nodes:
        if n.node_type.value not in valid_types:
            return (
                f"节点 {n.id} 的 node_type '{n.node_type.value}' 不合法。"
                f"必须是以下之一：{', '.join(sorted(valid_types))}"
            )
```

**注意：因为 NodeType 是 enum，理论上不会出现非法值（构造时就会报错），但这里是防御性校验。**

### 3.2 _validate_dag 修改 Rule 4 增加 line_range 作为可选项

**当前 Rule 4（第 188-197 行）：**
```python
    # Rule 4: All process nodes have section_heading or non-empty description
    for n in graph.nodes:
        if n.complexity == Complexity.process:
            has_heading = bool(n.section_heading and n.section_heading.strip())
            has_desc = bool(n.description and n.description.strip())
            if not has_heading and not has_desc:
                return (
                    f"Process 节点 {n.id} 既无 section_heading 也无有效 description。"
                    f"请添加 section_heading 或完善 description，供 Agent 2 定位原文内容。"
                )
```

**改为：**
```python
    # Rule 4: All process nodes have line_range OR section_heading OR non-empty description
    for n in graph.nodes:
        if n.complexity == Complexity.process:
            has_lr = bool(n.line_range)
            has_heading = bool(n.section_heading and n.section_heading.strip())
            has_desc = bool(n.description and n.description.strip())
            if not has_lr and not has_heading and not has_desc:
                return (
                    f"Process 节点 {n.id} 既无 line_range 也无 section_heading 也无有效 description。"
                    f"请添加 line_range 或 section_heading 或完善 description，供 Agent 2 定位原文内容。"
                )
```

### 3.3 在 tools1.py 顶部确保 import NodeType

确认文件顶部的 import 中已包含 `NodeType`。当前 tools1.py 应该已经通过 formatter 间接使用，但如果没有直接 import，需要加上：

```python
from holmes.kb.agent.dag.schema import NodeType, Complexity
```

如果已存在类似 import，无需改动。

### 3.4 增加 node_type 合理性 warning（可选，不阻断）

在 `tool_output_dag` 函数中（`_validate_dag` 调用之后、返回结果之前），增加 warning 检查：

找到 `tool_output_dag` 函数中 validation 通过后的代码段（大约在 `_validate_dag` 返回空字符串之后），增加：

```python
    # Non-blocking node_type reasonableness warnings.
    _PHYSICAL_KEYWORDS = {"拔", "插", "断电", "更换", "拆", "装", "按下", "unplug", "replace", "remove", "insert"}
    _QUERY_KEYWORDS = {"查询", "检查", "读取", "查看", "获取", "query", "check", "read", "inspect", "get"}
    warnings: list[str] = []
    for n in graph.nodes:
        desc_lower = n.description.lower() if n.description else ""
        if any(kw in desc_lower for kw in _PHYSICAL_KEYWORDS):
            if n.node_type != NodeType.physical_action:
                warnings.append(
                    f"⚠ 节点 {n.id} 描述含物理操作关键词但 node_type={n.node_type.value}，建议确认是否应为 physical_action"
                )
        if any(kw in desc_lower for kw in _QUERY_KEYWORDS):
            if n.node_type == NodeType.remote_action:
                warnings.append(
                    f"⚠ 节点 {n.id} 描述含查询关键词但 node_type=remote_action，建议确认是否应为 api_call"
                )
```

将 warnings 加入返回结果字典中：
```python
    result = {
        "_terminate": True,
        "success": True,
        "nodes": len(graph.nodes),
        "process_nodes": process_count,
        "dag_json_path": dag_json_path.name,
    }
    if warnings:
        result["node_type_warnings"] = warnings
    return result
```

---

## STEP 4: prompt1.py — Agent 1 system prompt 重写 node_type + line_range

### 4.1 修改节点格式规范段落（第 157-173 行）

**当前（第 157-173 行）：**
```
## 节点格式规范

每个节点必须包含：
- `### [ID] — [描述]`  例：`### N3 — 固件修复流程`
- `complexity: simple | process`
- `node_type: human_observation | api_call | decision | action`
- 出边列表：`- [条件] → **[目标ID]**`
- 终止节点：`- END`（或 `- [条件] → END`）

process 节点附加：
- `section_heading: "### 原文标题"`  （如果原文有对应标题）

node_type 选择指南：
- human_observation: 用户/工程师直接观测某个状态（看日志、观察指示灯）
- api_call: 调用接口/工具获取信息或执行操作
- decision: 基于已有信息做判断/选择
- action: 执行某个操作步骤
```

**改为：**
```
## 节点格式规范

每个节点必须包含：
- `### [ID] — [描述]`  例：`### N3 — 固件修复流程`
- `complexity: simple | process`
- `node_type: human_observation | api_call | remote_action | physical_action | decision`
- `line_range: [起始行, 结束行]` — 你在 Read 时看到这段内容的原文行号范围
- 出边列表：`- [条件] → **[目标ID]**`
- 终止节点：`- END`（或 `- [条件] → END`）

process 节点附加：
- `section_heading: "### 原文标题"`  （如果原文有对应标题）

### node_type 分类标准（5 种）

核心判断："这个步骤需不需要人在设备旁边？"

**human_observation** — 必须人在现场用感官获取信息
  判断依据：结果只能通过人的眼睛/耳朵/手获取，没有任何远程接口可以替代
  例：观察 LED 颜色、听风扇声音、触摸散热片、目视检查物理连接

**api_call** — 通过命令行或 API 远程获取信息（只读，不改变系统状态）
  判断依据：执行命令/调用接口获取状态或诊断数据
  例：nvidia-smi、dmesg、lspci、REST API 查询、读日志文件

**remote_action** — 通过命令行或 API 远程改变系统状态
  判断依据：执行命令/调用接口修改系统（重启、安装、配置）
  例：systemctl restart、固件刷写、修改配置文件、创建工单

**physical_action** — 需要人物理操作硬件
  判断依据：涉及触摸、移动、连接或更换物理组件
  例：拔插 GPU 卡、断电上电、更换部件、按物理重置按钮

**decision** — 基于已收集信息选择分支
  判断依据：不执行操作，只根据前面步骤结果选路径
  例：根据错误码查表、根据版本号决定升级路径

### line_range 要求

每个节点必须记录 line_range — 你在 Read 时看到这段内容的原文行号范围 [起始行, 结束行]。
这是 Agent 2 定位原文的最可靠锚点。即使有 section_heading，也必须同时记录 line_range。
```

### 4.2 修改阶段 2 初稿模板中的 node_type 行（第 86 行）

**当前：**
```
node_type: human_observation | api_call | decision | action
```

**改为：**
```
node_type: human_observation | api_call | remote_action | physical_action | decision
line_range: [起始行, 结束行]
```

### 4.3 修改阶段 1 中的关键判断描述（第 42 行）

**当前：**
```
- 每个节点：一句话描述 + complexity（simple/process）+ node_type + section_heading（如果有标题）
```

**改为：**
```
- 每个节点：一句话描述 + complexity（simple/process）+ node_type + line_range + section_heading（如果有标题）
```

### 4.4 修改自我检查清单（第 111-116 行）

**当前（5 项）：**
```
- [ ] 每条分支都追踪到了 END 或另一个节点
- [ ] 没有悬空节点（所有引用的节点都已定义）
- [ ] 文档的主要 section / 段落都读过了
- [ ] 每个 process 节点有 section_heading 或足够的 description
- [ ] 没有未解决的 [?] 标记（如果有，回原文查，或删掉）
```

**改为（7 项）：**
```
- [ ] 每条分支都追踪到了 END 或另一个节点
- [ ] 没有悬空节点（所有引用的节点都已定义）
- [ ] 文档的主要 section / 段落都读过了
- [ ] 每个 process 节点有 line_range 或 section_heading 或足够的 description
- [ ] 每个节点都有 line_range（你 Read 时看到该内容的行号范围）
- [ ] 每个节点的 node_type 符合 5 种分类标准
- [ ] 没有未解决的 [?] 标记（如果有，回原文查，或删掉）
```

---

## STEP 5: prompt2.py — Agent 2 system prompt 增加英文行为标签 + 内容质量约束

### 5.1 修改 section 定位策略（第 44-60 行）

**当前：**
```
## section 定位策略

**section_heading 存在（标准路径）**：
```
Grep(section_heading, source_file) → 找到起始行 start
Grep("^#{同级或更高} ", source_file, offset=start+1) → 找到结束行 end
Read(source_file, offset=start, limit=end-start) → 提取完整 section（含嵌套子标题）
```

**section_heading = null（prose 文档 fallback）**：
```
Grep(description 关键词, source_file) → 定位相关段落
找到 → Read 该段落 ±200 行范围
找不到 → write_entry 时在 frontmatter 标注：
  content_source: description_match_failed
  （进入 ImportReport.warnings，提示 reviewer 人工核查）
```
```

**改为：**
```
## 原文定位策略（按优先级执行）

**优先级 1：line_range（DAG 中记录的行号范围）**
```
Read(source_file, offset=line_range[0], limit=line_range[1]-line_range[0]) → 直接提取
```
最精准，对 prose 文档（无标题）尤其重要。

**优先级 2：section_heading（标题锚点）**
line_range 不存在或内容明显不匹配时 fallback。
```
Grep(section_heading, source_file) → 找到起始行 start
Grep("^#{同级或更高} ", source_file, offset=start+1) → 找到结束行 end
Read(source_file, offset=start, limit=end-start) → 提取完整 section（含嵌套子标题）
```

**优先级 3：description 关键词 Grep**
section_heading 也为 null 时 fallback。
```
Grep(description 关键词, source_file) → 定位相关段落
找到 → Read 该段落 ±200 行范围
```

**全部失败**：write_entry 时在 frontmatter 标注 `content_source: match_failed`（进入 warnings）
```

### 5.2 修改 Steps 格式示例（第 128-141 行）

**当前：**
```python
### Steps 格式
```markdown
## Steps

1. **[接口调用]** 执行诊断命令
   `POST /api/diagnostic/memory {"mode": "full"}`

2. **[人工观测]** 查看输出结果

3. 根据结果路由：
   - 结果 A → 参考 [子步骤标题](child-entry-id)
   - 结果 B → 参考 [另一子步骤标题](another-child-entry-id)
   - 处理完成 → 结束
```
```

**改为：**
```python
### Steps 格式

每个 Step 开头必须标注行为标签，来自 DAG 节点的 node_type：

| Tag | node_type | 含义 |
|---|---|---|
| [api] | api_call | 远程获取信息（只读） |
| [remote] | remote_action | 远程改变系统状态 |
| [physical] | physical_action | 物理操作硬件 |
| [observe] | human_observation | 需要人在现场观测 |
| [decide] | decision | 根据已有信息判断 |

```markdown
## Steps

1. **[api]** 执行诊断命令
   `POST /api/diagnostic/memory {"mode": "full"}`
   预期输出：JSON 格式，包含 status 和 code 字段

2. **[observe]** 观察设备面板状态指示灯

3. **[decide]** 根据诊断输出判断：
   - 输出 status=pass → 正常，END
   - 输出 code=E01 → 参考 [E01 修复](child-entry-id)
   - 输出 code=E02 → 参考 [E02 修复](another-child-entry-id)
```

**Steps 内容质量约束**：
1. 行为标签：每步开头必须标注 **[api]** / **[remote]** / **[physical]** / **[observe]** / **[decide]**
2. 可执行性：[api] 和 [remote] 步骤必须包含完整可执行的命令或 API 调用（逐字来自原文，不编造）
3. 判断条件：[decide] 步骤必须给出明确条件和对应路径
4. 预期输出：[api] 步骤如果原文有预期输出，必须写出来
5. 路由链接：有子分支的步骤使用 [标题](entry-id) 格式
```

### 5.3 修改关键约束中的 content_source 值（第 57-59 行）

将 `content_source: description_match_failed` 改为 `content_source: match_failed`。

---

## STEP 6: tools2.py — write_entry 增加内容质量 warning

### 6.1 在 _validate_process 函数末尾增加内容质量检查

在 `_validate_process` 函数中（第 296-333 行），现有 `return ""` 之前，**不修改现有逻辑**，新增一个 warning 收集函数。

**方案**：修改 `_validate_entry` 的返回值，增加 warnings 列表。但这会影响调用方。

**更简单的方案**：在 `tool_write_entry` 函数中，validation 通过后增加内容 warning 检查，将 warnings 追加到返回结果中。

找到 `tool_write_entry` 函数中 `_validate_entry` 调用的位置。在 validation 通过（error 为空字符串）之后、写入文件之前（或之后），增加：

```python
    # Content quality warnings (non-blocking — entry is still written).
    content_warnings: list[str] = []
    if entry_type == "process" and "## Steps" in body:
        steps_section = body.split("## Steps", 1)[1] if "## Steps" in body else ""
        # Check: steps with [api] or [remote] should have code blocks or backtick commands.
        import re as _re
        api_remote_steps = _re.findall(
            r"\*\*\[(api|remote)\]\*\*(.+?)(?=\n\d+\.\s|\n##|\Z)",
            steps_section, _re.DOTALL,
        )
        for tag, step_body in api_remote_steps:
            if "`" not in step_body and "```" not in step_body:
                content_warnings.append(
                    f"[{tag}] step missing executable command (no code block found)"
                )
        # Check: steps should have behavior tags.
        step_lines = _re.findall(r"^\d+\.\s+(.+)", steps_section, _re.MULTILINE)
        for step_line in step_lines:
            if not _re.search(r"\*\*\[(api|remote|physical|observe|decide)\]\*\*", step_line):
                content_warnings.append(
                    f"Step missing behavior tag: {step_line[:60]}..."
                )
```

然后在返回的 result dict 中追加：
```python
    if content_warnings:
        result["content_warnings"] = content_warnings
```

---

## STEP 7: step25.py — 交叉验证增加 line_range 验证 + node_type 抽检

### 7.1 _run_section_validation 增加 line_range 验证（第 229-250 行）

**当前函数只检查 section_heading**。修改为先检查 line_range，再 fallback 到 section_heading：

**当前：**
```python
def _run_section_validation(
    graph: DAGGraph,
    source_text: str,
    result: ParseResult,
) -> None:
    source_lines = source_text.splitlines()
    for node in graph.nodes:
        if node.complexity != Complexity.process:
            continue
        if not node.section_heading:
            continue  # null heading handled by Agent 2 fallback
        heading = node.section_heading.strip()
        found = any(heading.lower() in line.lower() for line in source_lines)
        if not found:
            result.validation_warnings.append(
                f"{node.id} 的 section \"{heading}\" 在原文中找不到"
            )
```

**改为：**
```python
def _run_section_validation(
    graph: DAGGraph,
    source_text: str,
    result: ParseResult,
) -> None:
    source_lines = source_text.splitlines()
    total_lines = len(source_lines)
    for node in graph.nodes:
        if node.complexity != Complexity.process:
            continue

        # Priority 1: Validate line_range is within bounds.
        if node.line_range:
            start, end = node.line_range
            if start < 0 or end > total_lines or start >= end:
                result.validation_warnings.append(
                    f"{node.id} 的 line_range [{start}, {end}] 超出原文范围（共 {total_lines} 行）"
                )
            continue  # line_range exists, skip section_heading check

        # Priority 2: Validate section_heading.
        if not node.section_heading:
            continue  # no line_range and no heading — Agent 2 fallback
        heading = node.section_heading.strip()
        found = any(heading.lower() in line.lower() for line in source_lines)
        if not found:
            result.validation_warnings.append(
                f"{node.id} 的 section \"{heading}\" 在原文中找不到"
            )
```

### 7.2 display_complexity_tips 更新阈值（第 200-221 行）

**当前：**
```python
    if parse_result.total_count > 20:
        tips.append("链路较长（>20 个节点），建议分阶段组织文档")
    if parse_result.process_count > 10:
        tips.append(f"将生成较多 entries（{parse_result.process_count} process），建议 review 关联关系")
    ...
        if depth > 4:
            tips.append(f"嵌套较深（深度 {depth}），agent 导航可能受影响")
```

**改为：**
```python
    if parse_result.total_count > 30:
        tips.append("链路较长（>30 个节点），建议分阶段组织文档")
    if parse_result.process_count > 15:
        tips.append(f"将生成较多 entries（{parse_result.process_count} process），建议 review 关联关系")
    ...
        if depth > 5:
            tips.append(f"嵌套较深（深度 {depth}），agent 导航可能受影响")
```

---

## STEP 8: harness2.py — 分批阈值改为 30

### 8.1 修改分批阈值（第 184 行）

**当前：**
```python
        if process_count > 20 and not retry_nodes:
```

**改为：**
```python
        if process_count > 30 and not retry_nodes:
```

### 8.2 修改文件顶部注释（第 7 行）

**当前：**
```python
  - Batch sub-agent mode when process_count > 20 (each batch of 10 nodes)
```

**改为：**
```python
  - Batch sub-agent mode when process_count > 30 (each batch of 10 nodes)
```

---

## STEP 9: 测试文件 — 全部 `NodeType.action` 替换

### 9.1 全局替换规则

在以下测试文件中执行替换：

| 文件 | 替换 |
|---|---|
| `test_dag_schema.py` | `NodeType.action` → `NodeType.remote_action`，`"action"` → `"remote_action"` |
| `test_dag_formatter.py` | `NodeType.action` → `NodeType.remote_action`，`node_type: action` → `node_type: remote_action` |
| `test_dag_tools1.py` | `NodeType.action` → `NodeType.remote_action`，`node_type: action` → `node_type: remote_action` |
| `test_dag_harness1.py` | `NodeType.action` → `NodeType.remote_action` |
| `test_dag_pipeline.py` | `NodeType.action` → `NodeType.remote_action` |
| `test_e2e_dag_pipeline.py` | 搜索并替换所有 `NodeType.action` 和 `"action"` 相关引用 |

**具体操作**：对每个文件执行全局查找替换：
1. `NodeType.action` → `NodeType.remote_action`
2. `node_type: action` → `node_type: remote_action`（在字符串字面量中）
3. `assert NodeType.action.value == "action"` → `assert NodeType.remote_action.value == "remote_action"`

### 9.2 test_dag_schema.py 特殊处理

第 26 行有直接的 enum 值测试：
```python
    assert NodeType.action.value == "action"
```

**改为：**
```python
    assert NodeType.remote_action.value == "remote_action"
    assert NodeType.physical_action.value == "physical_action"
```

同时确认测试中检查 enum 成员数量的地方，如果有 `len(NodeType) == 4` 之类的断言，改为 5。

### 9.3 验证全部测试

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes
python -m pytest kb/tests/test_dag_schema.py kb/tests/test_dag_formatter.py kb/tests/test_dag_tools1.py kb/tests/test_dag_harness1.py kb/tests/test_dag_pipeline.py -x -q
```

如有失败，根据错误信息修复。常见问题：
- 字符串中的 `"action"` 未替换 → 改为 `"remote_action"`
- 构造 DAGNode 时传了 `NodeType.action` → 改为 `NodeType.remote_action`

---

## STEP 10: 最终全量测试

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes
python -m pytest kb/tests/ -x -q
```

确认无新增失败。已有的 45 个 pre-existing failures 不算。

---

## 文件改动汇总

| 文件 | STEP | 改动内容 |
|---|---|---|
| `schema.py` | 1 | NodeType 4→5, DAGNode +line_range |
| `formatter.py` | 2 | JSON 序列化/反序列化 +line_range, 解析器 fallback action→remote_action, 树标签 |
| `tools1.py` | 3 | output_dag +node_type 校验 +line_range Rule4, +reasonableness warnings |
| `prompt1.py` | 4 | node_type 5 种分类标准, line_range 要求, checklist 更新 |
| `prompt2.py` | 5 | 英文行为标签, 定位优先级链, 内容质量约束 |
| `tools2.py` | 6 | write_entry +内容质量 warning |
| `step25.py` | 7 | line_range 验证, 阈值更新 |
| `harness2.py` | 8 | 分批阈值 20→30 |
| `test_dag_*.py` (6 files) | 9 | action → remote_action 全局替换 |
