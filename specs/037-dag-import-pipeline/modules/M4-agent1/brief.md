# M4 — Agent 1：DAG 提取

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图 — Agent 1 设计（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ Step 2：DAG 提取（Agent 1）`（全节）
  - **工具设计**：5 个工具的职责、参数、返回值（Read/Grep/write_dag/read_dag/output_dag）
  - **三阶段 Agent Loop**：
    - 阶段 1 通读：目标、典型 Read/Grep 操作序列、禁止项（不调用 write_dag）
    - 阶段 2 初稿：一次性写三个 section，允许标 [?]
    - 阶段 3 Review：read_dag → 回原文核实 → write_dag 修正，2~3 轮；调用 output_dag 前必须过自我检查清单
  - **Harness 设计**：工具白名单机制、output_dag 校验 5 条规则、Crash Recovery（每 20 turns 序列化 messages 写 session.json）、maxTurns=300
  - **能力边界与特殊情况处理**：
    - 隐性分支（两层兜底：用户 review + Step 2.5 抽检）
    - section_heading=null fallback
    - 多 root 场景（multi_incident，允许多个根节点）
    - 循环引用处理（output_dag 返回 error → agent 主动打断，标记 back_edge）
  - **System Prompt 结构**：`角色 → 阶段说明 → 工具说明 → 禁止项 → 终止条件`（完整 prompt 范例在蓝图中，直接参考）

- `§ DAG 节点 schema（.dag.json internal 格式）`
  - node_type 枚举（human_observation/api_call/decision/action）
  - complexity 枚举（simple/process）
  - section_heading、children（condition/target）字段

- `§ DAG 文档格式（.dag.md）`
  - 三个 section 的格式规范：文档摘要 / 排查树概览（ASCII 树形图，🔧标记）/ 节点详情
  - node_type / complexity / section_heading 字段在 .dag.md 中的写法
  - 用户编辑原则（宽松格式）

- `§ Step 2.5 > Agent 1 完成后的交互选择`
  - [1] 编辑 / [2] 跳过 / [3] 稍后 三选一菜单
  - --no-interactive 自动选 2

- `§ 状态存储（git 追踪）`
  - `_import-state/<hash>.dag.md` / `.dag.json` / `.session.json` 三文件职责

- `§ 核心数据模型`（Agent 1 提取的基础概念）
  - pitfall entry = 整棵排查树的路由骨架
  - **两种节点复杂度**（Agent 1 必须为每个节点正确判断）：
    | 节点类型 | 判断依据 | 在 .dag.md 中的处理 |
    |---|---|---|
    | `simple` | 1~2 步操作，无需展开 | inline 写在父 entry Resolution，不生成独立 entry |
    | `process` | 步骤多、有具体操作命令、有子分支 | 独立 process entry，标 🔧 |
  - process 节点可以出现在树的**任意位置**（不限于叶子节点）；执行完可继续路由到下一节点
  - **node_type 枚举**（4 种）：`human_observation / api_call / decision / action`

- `§ --no-interactive 模式`（全节）
  - `holmes import doc.md --no-interactive`：显式跳过用户确认
  - `holmes import --dir ./docs/`：**隐含 `--no-interactive`**（批量导入无法逐文档等待交互）
  - Agent 1 完成后自动选 [2]（跳过编辑，直接进 Step 2.5）
  - Step 2.5 仍然运行（parse + validate），但最终确认自动接受
  - ImportReport 记录 "DAG 未经用户确认"
  - `--dir` 批量导入时：所有文档一次性跑完，全部进入 pending 空间，由 reviewer 事后批量 approve

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

了解现有 KB 文件系统布局（§1），理解 Agent 1 输出写到哪个目录。

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构和 Python 包结构。

## 涉及的现有代码（实现前全部通读）

### Agent loop 参考实现
```
kb/holmes/kb/agent/runner.py           # 现有 Python agent loop（ImportAgentRunner）
                                       # 重点：__init__、run()、_run_loop()、工具白名单实现方式
kb/holmes/kb/agent/pipeline.py         # ThreePhaseImportPipeline，了解 pipeline 整体结构
kb/holmes/kb/agent/tools.py            # 现有工具函数模式（TOOL_DEFINITIONS + TOOL_HANDLERS）
```

### LLM Provider 接口
```
kb/holmes/kb/agent/provider/base.py         # LLMProvider ABC、ToolCall dataclass、_call_with_retry
kb/holmes/kb/agent/provider/openai_provider.py  # OpenAI 实现参考
kb/holmes/kb/agent/provider/factory.py     # create_provider(cfg) 工厂函数
```

### 工具化原语
```
kb/holmes/kb/atomic.py                 # atomic_write() — 原子文件写入
kb/holmes/kb/importer.py              # compute_source_hash() — SHA-256 前 16 位
```

### 路由入口（M3 建立的框架）
```
kb/holmes/kb/agent/pipeline.py        # _run_dag_pipeline() 框架（M3 已建立，M4 填充）
```

### CLI 参数
```
kb/holmes/cli.py                       # holmes import --resume / --skip-edit / --no-interactive 参数
```

### 相关测试
```
kb/tests/test_agent_runner.py          # 现有 agent loop 测试，理解测试模式
kb/tests/test_pipeline.py             # pipeline 测试
```

### claude-code 设计参考（Agent 实现必读）

Agent 1 的 harness 直接借鉴 claude-code 的 agent loop 设计哲学。**实现前务必阅读以下文件**，理解设计理念，在 Python 实现中复现同等结构：

```
/home/wangzhi/project/claude-code/src/query.ts
```
**Agent loop 主逻辑**（最重要）。理解以下设计：
- 每轮循环：发送 messages → 收到 response → 解析 tool_use block → 执行工具 → append tool_result → 检查终止条件 → 下一轮
- tool_use / tool_result 在 messages 数组中的结构（对应 Python 实现中 messages 的 append 逻辑）
- turn 计数机制（对应 maxTurns=300 的实现方式）
- 非交互模式下的行为控制

```
/home/wangzhi/project/claude-code/src/Tool.ts
```
**工具接口定义**。理解：
- 工具的标准结构（name、description、inputSchema、call 方法）
- 工具执行结果的返回格式（对应 `write_dag` / `read_dag` / `output_dag` 的实现模式）
- 工具调用失败时的 error 返回格式（对应白名单拒绝时返回 `{"error": "tool not allowed"}`）

```
/home/wangzhi/project/claude-code/src/constants/prompts.ts
```
**System Prompt 结构工程**。理解：
- prompt 按 section 分块组织（角色 → 上下文 → 工具说明 → 禁止项 → 终止条件）
- 不同 section 独立维护，便于迭代
- prompt 内容与代码逻辑分离（对应 `prompt1.py` 的职责）

```
/home/wangzhi/project/claude-code/src/constants/tools.ts
```
**工具白名单机制**。理解：
- CORE_TOOLS 列表如何定义哪些工具允许被 LLM 调用
- 非白名单工具调用被拦截、返回 error 的实现方式
- 对应 Agent 1 的 5 个工具白名单（Read/Grep/write_dag/read_dag/output_dag）

```
/home/wangzhi/project/claude-code/src/query/tokenBudget.ts
```
**Turn 预算控制**。理解：
- BudgetTracker 追踪 turn 计数
- 检测"diminishing returns"（连续多轮无实质进展）时主动停止
- 对应 maxTurns=300 的实现，以及超出时的报错退出行为

```
/home/wangzhi/project/claude-code/src/query/stopHooks.ts
```
**Loop 终止条件**。理解：
- 何时退出 agent loop（收到终止信号、maxTurns 超出、output_dag 校验通过）
- 与 `output_dag()` 作为唯一终止方式的对应关系

**核心借鉴点**（Python 实现中必须体现）：

| claude-code 设计 | M4 Python 实现对应 |
|---|---|
| `messages` 数组 append tool_use + tool_result | `_run_loop()` 中的 messages 管理 |
| 工具白名单 + 拒绝返回 error | `harness1.py` 中 `_execute_tool()` 白名单检查 |
| `systemPromptSection()` 分块结构 | `prompt1.py` 三阶段 section 组织 |
| turn 计数 + maxTurns 强制停止 | `harness1.py` turn counter，超出则 raise |
| messages 数组序列化为快照 | `session.json` crash recovery（每 20 turns） |

## 本模块目标

实现 Agent 1 的完整 harness：

1. **领域专属工具**：`write_dag` / `read_dag` / `output_dag`
2. **Harness 约束**：工具白名单（只允许 5 个工具）、maxTurns=300、output_dag 校验、Crash Recovery
3. **三阶段 System Prompt**：通读 → 初稿 → Review，完整规范见蓝图 § Step 2 > System Prompt 结构
4. **交互菜单**：[1/2/3] 三选一，--no-interactive 自动选 2
5. **--resume 支持**：从 session.json 恢复 messages，继续 loop

## 前置依赖

- **M3**（必须先完成）：pipeline.py 中 `_run_dag_pipeline()` 框架已建立，M4 填充其实现

## 新建文件结构

```
kb/holmes/kb/agent/dag/
  __init__.py
  schema.py       # DAGNode / DAGEdge / DAGGraph dataclass（含 node_type/complexity/section_heading）
  tools1.py       # write_dag / read_dag / output_dag 实现（包含 output_dag 校验逻辑）
  harness1.py     # Agent 1 harness：工具白名单执行、maxTurns、crash recovery 快照
  prompt1.py      # Agent 1 system prompt（三阶段说明、工具说明、禁止项、终止 checklist）
  formatter.py    # .dag.md（三 section 人类可读格式）↔ .dag.json（内部 DAGGraph）互转
```

## 关键设计要点（均来自蓝图，实现时严格遵守）

### 工具白名单
只允许调用 `Read / Grep / write_dag / read_dag / output_dag`。harness 在执行工具前检查名称，不在白名单则直接返回 `{"error": "tool not allowed"}` 给 agent，不执行。

### output_dag 校验（5 条规则，任一失败返回 error）
```
✓ 至少存在一个根节点（无 parent 的节点）
✓ 所有边的目标节点在节点列表中存在（无悬空边）
✓ 无循环引用
✓ 所有 process 节点有 section_heading 或 description 非空
✓ 每个节点至少有一条出边，或显式标记为 END
```

### Crash Recovery
每 20 turns 将完整 messages 数组 JSON 序列化写入 `_import-state/<hash>.session.json`（覆盖写入）。`--resume` 时读取此文件，恢复 conversation context，继续 loop，不从头开始。

### 循环引用处理
`output_dag` 检测到循环引用时：返回 error + 循环路径描述（如 "N3 → N8 → N3"）。System prompt 规定 agent 处理方式：选一条回路边标记为 back_edge，在节点 description 中注明，再次调用 output_dag。

### .dag.md 格式（三 section）
```markdown
# 排查树：<title>
> source: <source_file>
> generated: <date>
> 说明：可直接编辑后运行 holmes import --resume

## 文档摘要
<核心问题、主要症状、覆盖场景>

## 排查树概览
<ASCII 树形图，🔧 标记 process 节点>

## 节点详情
### N1 — <描述>
complexity: simple | process
node_type: human_observation | api_call | decision | action
section_heading: "### <原文标题>"  # 可省略
- <条件> → **N2**
```

### System Prompt 结构（参考蓝图完整版本）
```
角色：Holmes KB import pipeline 排查树提取专家（Agent 1）
阶段说明：三阶段详细说明（通读/初稿/Review），含每阶段目标和典型操作
工具说明：5 个工具的用途和约束
禁止项：不在通读阶段调用 write_dag；不补充文档没有的分支；不在 checklist 完成前 output_dag
终止条件：output_dag 校验通过后 loop 终止
```

## 验收条件

- [ ] Agent 1 只能调用 5 个白名单工具，其他调用返回拒绝 error
- [ ] `output_dag` 调用触发 5 条校验，任一失败返回 error，agent 修正后重试
- [ ] 校验通过后生成 `_import-state/<hash>.dag.md`（三 section 人类可读格式）
- [ ] 同时生成 `_import-state/<hash>.dag.json`（完整 DAGGraph 内部格式）
- [ ] 每 20 turns 写入 `<hash>.session.json` crash recovery 快照
- [ ] `holmes import --resume` 从快照恢复，继续 loop，不从头开始
- [ ] Agent 1 完成后展示 [1/2/3] 交互菜单
- [ ] `--no-interactive` 自动选 [2]，直接进 Step 2.5
- [ ] 循环引用：output_dag 返回 error，system prompt 引导 agent 打断（back_edge）
- [ ] 多 root 场景：output_dag 允许多个根节点（multi_incident 文档合法）
- [ ] maxTurns=300 超出后报错退出

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M4-agent1/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ Step 2` 全节（含 System Prompt 范例）、`§ DAG 节点 schema`、`§ DAG 文档格式`，再读完 `runner.py` 理解现有 Python agent loop 结构，然后再动手。
