# M5 — Agent 2：双源知识生成

## 项目与代码库背景

**Holmes KB** 是一个 Python CLI 工具，管理工程团队的 Markdown 知识库。

- 代码库根：`/home/wangzhi/project/projectTmp/holmes/holmes/kb/`
- 配置文件：`~/.holmes/config.json`（api_key / api_base_url / model / username）

## 必读参考文档（实现前全部通读）

### 1. 施工蓝图 — Agent 2 设计（最重要，逐字阅读）
`/home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/blueprint.md`

**必须全部读完的章节**：

- `§ Step 2.5：解析规范化与交叉验证`（全节）
  - **Agent 1 完成后的交互选择**：[1] 编辑 / [2] 跳过 / [3] 稍后，`--no-interactive` 自动选 2
  - **解析规范化**（LLM 宽松解析）：用户自然语言写法识别表（`这步比较复杂` → `complexity: process` 等）
  - **交叉验证**（程序化 + LLM 抽检）：每个 section_heading Grep 原文验证存在；随机抽查节点语义一致性
  - **合并一屏展示**：编辑识别 + 内容验证合并，用户**一次**确认
  - **解析失败**（悬空节点、循环引用）：不进入生成，打印 error，提示修改
  - **--resume 多状态选择**：多个 pending state 时让用户选择

- `§ Step 3：双源知识生成（Agent 2）`（全节）
  - **输入**：规范 DAG JSON（`.dag.json`，通过 `read_dag()` 获取）+ 原始文档（Read / Grep）
  - **Agent 2 设计背景**：与 Agent 1 使用同一 agent loop 框架，但工具集和 harness 约束不同；两 Agent context 完全独立，通过文件系统通信
  - **工具设计**（6 个工具）：
    | 工具 | 用途 |
    |---|---|
    | `Read(file, offset, limit)` | 读原始文档，按段分页 |
    | `Grep(pattern, file)` | 定位 section_heading、分支条件 |
    | `read_dag()` | 读 .dag.json，获取全树结构和 ID 表 |
    | `write_entry(entry_id, content)` | 写 entry 到 `_pending/<category>/`，内置格式校验 |
    | `read_entry(entry_id)` | 读回已写 entry，用于一致性检查和获取子节点标题 |
    | `finalize()` | 结束 loop，触发 lint 校验，生成 ImportReport |
  - **工具约束**：Agent 2 只能写 `_pending/<category>/*.md`，不能修改 DAG 文件或其他文件
  - **四阶段 Loop**：
    - **Phase 1 Study（不写任何 entry）**：`read_dag()` 理解全树结构、节点 ID 表、section_heading；决定 study 策略；读取所有相关 section 内容
    - **Phase 2 顺序生成 process entries（叶节点 → 根方向，拓扑逆序）**：原因：父节点写之前子节点已存在，可 `read_entry(child)` 获取真实标题；每个 process 节点：定位 section → `write_entry`（内置格式校验，失败则修正后重试）
    - **Phase 3 最后写 pitfall root**：`read_entry(child_id)` 获取子节点真实标题和 Steps 首句；pitfall root 路由链接文案来自子节点真实标题，精准对应
    - **Phase 4 Consistency review**：抽查 5~10 个 entry（随机 + section_heading=null 必查）；`read_entry(id)` 检查术语一致性和路由链接；有问题则 `write_entry` 覆盖修正；`finalize()`
  - **规模分层策略（解决大树 context 累积问题）**：
    - ≤ 20 个 process 节点：全局视野模式，Phase 1 一次性读完所有 section，全部内容同时在 context → 术语天然一致
    - \> 20 个 process 节点：分批子 agent 模式，每批 10 节点，每批启动独立 sub-agent（全新 context）；批次间接口：输入 DAG + 本批节点列表 + 已写 entries 的 `{id: 标题}` 摘要表；最后 pitfall root 由独立 sub-agent 生成
  - **Harness 设计**（与 Agent 1 对比）：
    | 项目 | Agent 1 | Agent 2 |
    |---|---|---|
    | 写文件权限 | 只能写 `.dag.md` | 只能写 `_pending/<category>/*.md` |
    | write 格式校验 | N/A | `write_entry` 内置，失败返回 error，agent 修正后重试 |
    | maxTurns | 300 | 50 × process 节点数（上限 1000）|
    | Crash Recovery | 对话历史快照（每 20 turns） | 已写文件天然 checkpoint，restart 跳过已写节点 |
    | 终止方式 | `output_dag()` | `finalize()` |
    | context 隔离 | 独立 | 与 Agent 1 完全独立，仅通过文件通信 |
  - **section 定位策略**：
    ```
    section_heading 存在（标准路径）：
      Grep(section_heading) → 找到起始行 start
      Grep("^#{同级或更高} ", offset=start+1) → 找到结束行 end
      Read(start, end-start) → 提取完整 section（含所有嵌套子标题）

    section_heading = null（prose 文档 fallback）：
      Grep(description 关键词) → 定位相关段落
      找到 → Read 该段落 ±200 行范围
      找不到 → write_entry 时在 frontmatter 标注：
        content_source: description_match_failed
        → 进入 ImportReport.warnings，提示 reviewer 人工核查内容
    ```
  - **System Prompt 结构**（参考蓝图完整范例）：
    ```
    你是 Holmes KB 的知识提取专家（Agent 2）。

    输入：
      DAG 文档（read_dag()）
      原始知识文档（Read / Grep）

    工作流程：
      Phase 1  Study：read_dag() 理解全树，读取所有相关 section 内容
      Phase 2  生成 process entries：从叶节点开始，父节点最后
               每写一个 entry 前，检查已写节点的术语保持一致
      Phase 3  生成 pitfall root：最后写，read_entry 获取子节点真实标题
      Phase 4  Review：抽查一致性，有问题覆盖修正
      finalize()

    关键约束：
      只使用原文中存在的内容，允许重组为结构化格式，不捏造内容
      所有 ID 来自 DAG ID 表，不自行创造 ID
      pitfall root 必须最后写
      写完所有节点再调用 finalize()
      entry 格式严格遵守（见格式约束）
    ```

- `§ Entry ID 预生成`
  - 顺序生成前必须先确定所有 entry 的 ID（否则 `child_entry_ids` / `parent_id` 无法填写）
  - process 节点：`{source-name-slug}-{node-id}-{import-seq}`（例：`hardware-init-failure-N3-001`）
  - pitfall root：`{source-name-slug}-root-{import-seq}`（例：`hardware-init-failure-root-001`）
  - 将完整 ID 表写入 `.dag.json`，Agent 2 通过 `read_dag()` 获取
  - 重试时复用同一 `import-seq`，保证 ID 幂等

- `§ Agent 2 格式约束（System Prompt 硬约束）`
  - pitfall entry 必填 frontmatter：`title, description, type=pitfall, pitfall_structure=tree, kb_status=pending, source_hash, source_file, import_trace_id, child_entry_ids, maturity=draft, decay_status=active, next_decay_check, contributors, tags`
  - pitfall entry 必填 sections：`## Symptoms, ## Root Cause, ## Resolution（含路由链接）`
  - process entry 必填 frontmatter：`title, description, type=process, kb_status=pending, parent_id, child_entry_ids（若有子节点）, source_hash, source_file, import_trace_id, 同上证据字段`
  - process entry 必填 sections：`## Steps（编号步骤，含路由逻辑）`
  - 内容约束：只使用原文 section 中存在的内容；允许叙述文本重组为编号步骤；不补充原文没有的信息；链接格式：`[entry 标题](entry-id)`

- `§ 程序化格式校验（write_entry 内置，写入前触发）`
  - 校验规则：所有必填 frontmatter 字段存在且非空；必需 sections 存在；`child_entry_ids` 中 ID 全部在 DAG ID 表中；`parent_id` 在 DAG ID 表中
  - 校验失败 → `write_entry` 返回 error 描述，agent 修正后重试；重试仍失败 → 进 `ImportReport.errors`，entry 不写入 `_pending/`
  - `content_source: description_match_failed` → 非格式错误，写入 pending 但标注 warning

- `§ Lint 规则`（7 条，import 完成后自动校验，任一失败写入 `ImportReport.errors`）：
  - `parent_id_consistency`：所有 process entry 的 `parent_id` 对应 entry 存在（同批生成中）
  - `child_entry_ids_consistency`：所有 `child_entry_ids` 中 ID 存在（同批生成中）
  - `tree_completeness`：DAG 中每个 `process` 节点都有对应生成 entry；无孤立 entry
  - `no_cycle`：`child_entry_ids` 不形成循环引用
  - `pitfall_has_root`：至少存在一个无 `parent_id` 的 pitfall root；每棵子树能到达至少一个 END
  - `source_file_consistent`：同一批生成的所有 entries 的 `source_file` 和 `source_hash` 一致
  - `evidence_fields_present`：`maturity`、`decay_status`、`next_decay_check`、`contributors` 全部存在
  - lint 失败不阻断 import，但 ImportReport 标记，`holmes kb pending` 展示时显示 ⚠ 警告

- `§ ImportReport 展示格式`：含 ✓ 生成成功数量、⚠ 格式校验失败 entry 列表（retry 命令）、⚠ Lint 警告条数、"下一步"操作提示（`holmes kb pending` + `holmes kb approve <root-id>`）

- `§ 证据初始化（生成时写入 frontmatter）`：
  - `maturity: draft`、`decay_status: active`、`next_decay_check: <today + 180 days>`
  - `contributors: [{user: config.username, role: "initiator", date: today}]`
  - `username` 取自 `~/.holmes/config.json`，未配置时 import 终止

- `§ Pitfall entry（路由骨架）` 和 `§ Process entry（任意复杂节点）`：完整 frontmatter 示例（含注释格式）

- `§ KB Entry 可读性规范 > 3. 关联结构注释`：`child_entry_ids` 每项带标题注释，`parent_id` 带父标题注释，Agent 2 在写入时自动添加

- `§ 生成规则`：simple 节点 inline 写在父 entry 的 Resolution；process 节点独立 entry；生成顺序拓扑逆序

- `§ Step 0 > Entry 状态字段`：`kb_status: pending` 初始值

- `§ 单节点 retry`：`holmes import --retry-entry <node-id>` 重新生成单个失败节点

### 2. 知乎 KB 数据模型
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/kb-data-model.md`

重点章节：
- §2 Entry Frontmatter 字段 — 现有必填/可选字段（`maturity / decay_status / next_decay_check / contributors / tags / related_ids / layer / applicable_phases`）
- §3 Maturity 生命周期 — `draft → verified → proven` 升级路径和条件
- §4 Evidence sidecar — 证据记录结构
- §6 EntryMeta dataclass — store.py 轻量 meta 结构

### 3. 开发者指南
`/home/wangzhi/project/projectTmp/holmes/holmes/docs/developer-guide.md`

了解项目架构和 Python 包结构、sub-agent 调用方式（若使用）、LLM Provider 接口约定。

## 涉及的现有代码（实现前全部通读）

### Agent loop 参考实现
```
kb/holmes/kb/agent/runner.py           # 现有 Python agent loop（ImportAgentRunner）
                                       # 重点：__init__、run()、_run_loop()、工具白名单实现方式
kb/holmes/kb/agent/pipeline.py         # ThreePhaseImportPipeline，了解 pipeline 整体结构
                                       # _run_dag_pipeline()（M3 已建立框架，M5 填充实现）
kb/holmes/kb/agent/tools.py            # 现有工具函数模式（TOOL_DEFINITIONS + TOOL_HANDLERS）
```

### LLM Provider 接口
```
kb/holmes/kb/agent/provider/base.py         # LLMProvider ABC、ToolCall dataclass、_call_with_retry
kb/holmes/kb/agent/provider/openai_provider.py  # OpenAI 实现参考
kb/holmes/kb/agent/provider/factory.py     # create_provider(cfg) 工厂函数
```

### M4 已建立的文件（Agent 2 的前置输入）
```
kb/holmes/kb/agent/dag/
  __init__.py
  schema.py       # DAGNode / DAGEdge / DAGGraph dataclass（M4 已实现）
  formatter.py    # .dag.md ↔ .dag.json 互转（M4 已实现）
  tools1.py       # write_dag / read_dag / output_dag（M4 已实现，M5 参考工具实现模式）
  harness1.py     # Agent 1 harness（M4 已实现，M5 参考 harness 结构）
  prompt1.py      # Agent 1 system prompt（M4 已实现，M5 参考 prompt 结构）
```

### 工具化原语
```
kb/holmes/kb/atomic.py       # atomic_write() — 原子文件写入（write_entry 使用）
kb/holmes/kb/importer.py     # compute_source_hash()（M5 写 entry 时填写 source_hash 字段）
kb/holmes/config.py          # HolmesConfig — username / model / api_key / api_base_url
```

### 相关测试
```
kb/tests/test_agent_runner.py    # 现有 agent loop 测试，理解测试模式
kb/tests/test_pipeline.py        # pipeline 测试
```

### claude-code 设计参考（Agent 实现必读）

Agent 2 与 Agent 1 使用同一 agent loop 框架，但工具集、harness 约束、maxTurns 策略、context 隔离方式均不同。**实现前务必阅读以下 claude-code 文件**，理解设计理念后在 Python 中复现：

```
/home/wangzhi/project/claude-code/src/query.ts
```
**Agent loop 主逻辑**（最重要）。Agent 2 的四阶段 loop（Study → process entries → pitfall root → Consistency review）在同一 messages 数组中积累 context，工具调用模式与 Agent 1 完全相同。重点理解：
- tool_use block → 执行工具 → tool_result block → append to messages 的循环结构
- 如何在同一 loop 内维护跨多轮的"已写 entry 列表"状态（agent 通过 messages 历史记忆）
- 非交互模式（`--no-interactive`）下 loop 的自动推进

```
/home/wangzhi/project/claude-code/src/Tool.ts
```
**工具接口定义**。Agent 2 的 6 个工具（`read_dag / write_entry / read_entry / finalize / Read / Grep`）均按此接口实现。重点理解：
- `write_entry` 的内置格式校验在工具 `call()` 方法内实现，校验失败直接在 tool_result 中返回 error（agent 感知到并修正，不抛异常）
- `finalize()` 工具调用触发 lint + ImportReport 生成，loop 在 harness 层检测到 finalize 调用后终止

```
/home/wangzhi/project/claude-code/src/constants/prompts.ts
```
**System Prompt 结构工程**。Agent 2 的 system prompt（`prompt2.py`）参考此文件的分块组织方式：
- 角色 → 输入说明 → 四阶段工作流 → 关键约束（内容只用原文 / ID 只用 DAG ID 表 / pitfall root 最后写） → 格式硬约束（frontmatter 必填字段列表、section 必须存在）
- 格式约束作为单独 section 放在 prompt 末尾，使 agent 在写 entry 前回顾

```
/home/wangzhi/project/claude-code/src/constants/tools.ts
```
**工具白名单**。Agent 2 只允许 6 个工具（不能写 DAG 文件，不能修改其他文件）。白名单拒绝机制与 Agent 1 完全相同，复用 `harness1.py` 的实现模式。

```
/home/wangzhi/project/claude-code/src/query/tokenBudget.ts
```
**Turn 预算控制**。Agent 2 的 maxTurns = `50 × process 节点数（上限 1000）`，比 Agent 1 的 300 更动态。理解 BudgetTracker 模式后，在 `harness2.py` 中实现动态计算 maxTurns 的逻辑。

```
/home/wangzhi/project/claude-code/src/utils/model/agent.ts
```
**分批子 agent 模式**（>20 process 节点时）。理解 claude-code 中子 agent 的启动方式（独立 context、独立 messages 数组、通过参数传递跨批次信息）。Agent 2 的分批模式：每批 10 节点启动独立 sub-agent，通过 `{id: 标题}` 摘要表传递术语上下文。

**核心借鉴点**（Python 实现中必须体现）：

| claude-code 设计 | M5 Python 实现对应 |
|---|---|
| messages 数组 append tool_use + tool_result | `harness2.py` 中的 messages 管理 |
| 工具 `call()` 返回 error（不抛异常） | `write_entry` 格式校验失败 → tool_result error |
| 终止工具（finalize）触发 loop 退出 | harness 检测到 `finalize` 调用 → 退出 loop |
| prompt 分块结构（角色/流程/约束/格式） | `prompt2.py` 四段式结构 |
| 动态 maxTurns | `harness2.py` 根据节点数计算 maxTurns |
| 子 agent 独立 context | >20 节点时每批独立 sub-agent，新 messages 数组 |
| 已写文件 = 天然 checkpoint | restart 时扫描 `_pending/` 跳过已写节点 |

## 前置依赖

- **M4**（必须先完成）：M4 生成的 `.dag.md` / `.dag.json` 是 M5 的输入，M4 建立的 `dag/` 目录结构和 `schema.py` / `formatter.py` 是 M5 的依赖
- **M6a** 可以并行开发：M5 的 `write_entry` 最终调用 M6a 的 `write_pending()`；若 M6a 未完成，先用直接文件写入占位

## 新建文件结构

```
kb/holmes/kb/agent/dag/
  step25.py       # Step 2.5：宽松解析 + 交叉验证 + 合并展示 + 用户确认
  id_gen.py       # Entry ID 预生成：遍历 DAG 节点，分配 ID 表，写入 .dag.json
  tools2.py       # Agent 2 专属工具：read_dag / write_entry（内置格式校验）/ read_entry / finalize
  harness2.py     # Agent 2 harness：工具集执行、maxTurns、写文件权限约束、Crash Recovery（已写文件作 checkpoint）
  prompt2.py      # Agent 2 system prompt（四阶段说明、格式约束、section 定位策略说明）
  lint.py         # 7 条 lint 规则（finalize 触发）
  report.py       # ImportReport：生成 + 终端打印（含 retry 命令提示和"下一步"操作）
```

## 关键设计要点（均来自蓝图，实现时严格遵守）

### Step 2.5 宽松解析（LLM 单次调用）
```python
# 识别用户常见自然语言写法：
"这步比较复杂"       → complexity: process
"如果修复失败跳到N7" → edge: → N7, condition: 修复失败
新增节点没给 ID      → 自动分配 ID
section 写成"第三节" → 标 uncertain，展示给用户
删掉🔧但没改 complexity → uncertain，展示给用户
```

### Entry ID 格式
```
process 节点：{source-name-slug}-{node-id}-{import-seq}
  例：hardware-init-failure-N3-001
pitfall root：{source-name-slug}-root-{import-seq}
  例：hardware-init-failure-root-001
import-seq 重试时复用同一值（幂等性）
```

### write_entry 内置格式校验（写入前触发）
```
✓ 所有必填 frontmatter 字段存在且非空
✓ 必需 sections 存在（pitfall: Symptoms/Root Cause/Resolution；process: Steps）
✓ child_entry_ids 中的 ID 全部在 DAG ID 表中
✓ parent_id 在 DAG ID 表中

校验失败 → 返回 error，agent 修正后重试
重试仍失败 → 进 ImportReport.errors，不写入 pending
```

### Crash Recovery（Agent 2）
Agent 2 不做对话历史快照。已写文件本身就是天然 checkpoint：重启时读取 `_pending/<category>/` 下已有文件，跳过已生成的节点，只重试未完成的节点。

### child_entry_ids 标题注释（KB 可读性规范）
```yaml
child_entry_ids:
  - hardware-init-firmware-repair-001   # 固件修复流程
  - hardware-init-memory-diag-001       # 内存诊断流程
parent_id: hardware-init-failure-root-001  # 硬件初始化失败
```
Agent 2 在写入时必须先通过 `read_entry(child_id)` 获取子节点已生成的 title，再添加注释。

## 验收条件

- [ ] Step 2.5 合并展示编辑识别 + 内容验证，用户一次确认
- [ ] 解析失败（悬空节点 / 循环引用）：打印 error，不进入 Agent 2
- [ ] `--no-interactive` 自动跳过编辑（选 2），Step 2.5 仍执行解析和验证，最终确认自动接受
- [ ] Entry ID 预生成：所有 ID 在生成开始前确定，写入 `.dag.json`，重试时 ID 幂等
- [ ] Agent 2 生成顺序为拓扑逆序（叶节点 → 父节点 → pitfall root）
- [ ] `write_entry` 格式校验：失败返回 error，重试仍失败进 errors 列表，不写入 pending
- [ ] `section_heading=null` 且 Grep 失败：frontmatter 标注 `content_source: description_match_failed`，进 warnings
- [ ] 所有生成 entry 写入 `_pending/<category>/`（目录按 category 分级）
- [ ] `finalize()` 触发 7 条 lint，任一失败写入 `ImportReport.errors`（lint 失败不阻断，但 pending 展示 ⚠）
- [ ] ImportReport 末尾固定展示"下一步：`holmes kb pending` / `holmes kb approve <root-id>`"
- [ ] `holmes import --retry-entry <node-id>` 单独重新生成指定节点（复用同一 import-seq）
- [ ] pitfall entry frontmatter 包含全部必填字段（含 `contributors` / `import_trace_id` / `child_entry_ids` 注释）
- [ ] process entry frontmatter 包含全部必填字段（含 `parent_id` 注释 / `child_entry_ids` 注释）
- [ ] ≤ 20 个 process 节点：全局视野模式（单 Agent loop）
- [ ] \> 20 个 process 节点：分批子 agent 模式（每批 10 节点）
- [ ] maxTurns = 50 × process 节点数（上限 1000）
- [ ] Agent 1 和 Agent 2 conversation context 完全独立（仅通过 .dag.json 文件系统通信）

## 执行步骤

```bash
cd /home/wangzhi/project/projectTmp/holmes/holmes/specs/037-dag-import-pipeline/modules/M5-agent2/
/speckit-specify
/speckit-plan
/speckit-tasks
/speckit-implement
/speckit-analyze
```

**实现前务必**：完整读完蓝图 `§ Step 2.5`、`§ Step 3`（含四阶段 Loop、规模分层、Harness、section 定位策略、System Prompt 结构、格式约束）、`§ Lint 规则`、`§ ImportReport`、`§ Entry ID 预生成`、`§ 证据初始化`、`§ KB Entry 可读性规范 §3`，并对照 pitfall/process entry 完整 frontmatter 示例确保字段完备。再读完 `runner.py` 理解现有 Python agent loop 结构，参考 M4 的 `harness1.py` / `prompt1.py` 建立 Agent 2 的等价结构。
