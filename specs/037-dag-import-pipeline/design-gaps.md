# 037 设计薄弱环节优化方案

> 基于 spec.md 评审，针对已识别的设计薄弱点提出优化方案。
> 核心目标：**给有经验的硬件工程师提效** — 排查知识准确沉淀，agent 读到后能自主执行远程步骤、只在需要人工观测时停下来问用户。

---

## 架构前提（评审中确认）

Holmes 不拥有 agent。Holmes 通过 MCP 暴露知识库，外部 agent（Claude Code 或任何 MCP 客户端）：
1. 通过 `kb_search` / `kb_read` 读取排查知识
2. 用 agent 自身能力（Bash、HTTP 调用等）执行远程步骤
3. 自行决定何时问用户、何时自动执行

**因此 KB entry 的内容质量 = 产品价值的上限。** entry 写得好，任何有能力的 agent 都能高效引导排查；entry 写得差（命令不完整、步骤模糊、节点类型标错），再强的 agent 也帮不了用户。

---

## Gap 1：node_type 准确率保障

### 问题

node_type 决定 agent 行为（5 种，原 spec 的 `action` 拆分为 `physical_action` + `remote_action`）：
- `human_observation` → agent 必须问用户（如：观察 LED 颜色、听风扇声音）
- `api_call` → agent 可以自己执行（如：`nvidia-smi --gpu-reset`、`curl POST /api/diag`）
- `remote_action` → agent 可以自己执行的操作（如：重启服务、刷固件、修改配置文件）
- `physical_action` → agent 必须告知用户去做（如：拔出 GPU 卡、重新插拔电源线、更换部件）
- `decision` → agent 根据已有信息自行判断下一步

**`api_call` vs `remote_action` 区别**：`api_call` 是获取信息（查状态、跑诊断），`remote_action` 是改变状态（重启、安装、修改配置）。两者 agent 都可以自动执行，区分是为了语义清晰。

当前 spec 把 node_type 只作为 Agent 1 填写的一个字段，没有判断标准、没有校验、.dag.md 中也不显性展示。如果标错：
- `physical_action`（拔 GPU 卡）误标为 `api_call` → agent 会尝试自动执行物理操作，产生误导
- `api_call`（跑诊断命令）误标为 `human_observation` → agent 本可以自动跑，却停下来问用户，失去提效价值

### 优化方案

#### 1.1 Agent 1 System Prompt 增加 node_type 判断标准

在 Agent 1 的 system prompt（M4 prompt.py）中，增加明确的分类标准和典型例子：

```
node_type classification (5 types):

human_observation — must be performed by a human on-site using their senses
  Criterion: the result can ONLY be obtained through human eyes/ears/hands; no remote interface exists
  Examples:
    - Observe LED indicator color (red/green/off)
    - Listen for fan rotation or abnormal noise
    - Touch heatsink to assess temperature
    - Visually inspect physical connections for looseness
    - Read physical error codes on device panel

api_call — can be performed remotely via CLI command or API call to RETRIEVE information
  Criterion: executes a command/API to get status or diagnostic data; does not change system state
  Examples:
    - Run nvidia-smi, dmesg, lspci for diagnostics
    - Call REST API to query device status
    - Execute dcgmi diag for self-test
    - Read log files (cat /var/log/...)
    - Query ticket system API for status

remote_action — can be performed remotely via CLI command or API call to CHANGE system state
  Criterion: executes a command/API that modifies the system (restart, install, configure)
  Examples:
    - Restart a service: systemctl restart nvidia-persistenced
    - Flash firmware: nvidia-smi --gpu-reset
    - Modify configuration files
    - Create a ticket: dcctl ticket create ...
    - Install/upgrade software packages

physical_action — requires a human to physically manipulate hardware
  Criterion: involves touching, moving, connecting, or replacing physical components
  Examples:
    - Unplug and re-seat GPU card
    - Power off and disconnect power cable
    - Replace faulty hardware component
    - Press physical reset button
    - Re-seat memory DIMMs

decision — choose the next path based on already-collected information
  Criterion: no action needed; just evaluate prior results and select a branch
  Examples:
    - Based on nvidia-smi output, determine if it's a driver or hardware issue
    - Look up error code in table to select fix procedure
    - Based on firmware version, decide upgrade path
```

#### 1.2 .dag.md 树形概览中显性展示 node_type

当前 .dag.md 的树形概览只用 `🔧` 标记 process 节点。改为同时标注 node_type：

**当前**：
```
硬件初始化失败
├── 指示灯不亮
│   ├── 电源线松动 → 重新插紧（simple）
│   └── 电源线正常 → 电源适配器更换 🔧
├── 指示灯红色闪烁 → 固件修复流程 🔧
```

**优化后**：
```
硬件初始化失败
├── [observe] 指示灯不亮
│   ├── [physical] 电源线松动 → 重新插紧（simple）
│   └── [physical] 电源线正常 → 电源适配器更换 🔧
├── [observe] 指示灯红色闪烁 → 固件修复流程 🔧
│   ├── [remote] 执行固件重置命令 🔧
│   └── [physical] 修复失败 → 硬件更换 🔧
└── [api] 运行内存诊断 🔧
    ├── [decide] 输出正常 → END
    └── [decide] 输出 E01 → E01 修复 🔧
```

标记映射（英文缩写，agent 无需 CLAUDE.md 也能理解语义）：

| Tag | node_type | Agent behavior |
|---|---|---|
| `[observe]` | human_observation | Must ask user |
| `[api]` | api_call | Agent auto-executes (read-only) |
| `[remote]` | remote_action | Agent auto-executes (state-changing) |
| `[physical]` | physical_action | Must tell user to do it |
| `[decide]` | decision | Agent decides based on prior results |

用户 review .dag.md 时一眼就能看出哪些节点 agent 会自动执行、哪些会停下来问，发现标错的概率大幅提升。

#### 1.3 节点详情中增加 node_type

.dag.md 的节点详情 section 已有 `node_type` 字段，无需改动。确保与树形概览一致即可。

#### 1.4 output_dag 增加 node_type 合理性校验

在 Agent 1 的 `output_dag` 校验中，增加一条软校验（warning，不阻断）：

```
⚠ Node N7 (硬件更换流程): description contains physical keywords ("拔出""插入""断电")
  but node_type is remote_action. Should this be physical_action?
⚠ Node N12 (查询设备状态): description suggests read-only query
  but node_type is remote_action. Should this be api_call?
```

这不是阻断性校验，而是提醒 Agent 1 再看一眼。关键词检测规则：
- 物理关键词（拔/插/断电/更换/拆/装/按下按钮）出现在 non-physical 节点 → warning
- 查询/检查/读取 关键词出现在 remote_action 节点 → 可能应为 api_call

#### 1.5 Step 2.5 交叉验证增加 node_type 抽检

在 Step 2.5 的 LLM 抽检中，增加 node_type 维度：

```
抽检内容（现有）：分支条件与原文语义一致性
抽检内容（新增）：node_type 与节点描述/原文内容是否一致
  例：节点描述"观察 LED 颜色"但标为 api_call → ⚠ should be human_observation
  例：节点描述"拔出故障 GPU 卡"但标为 remote_action → ⚠ should be physical_action
  例：节点描述"重启 nvidia-persistenced"但标为 api_call → ⚠ should be remote_action
```

---

## Gap 2：KB Entry 内容质量 — 让任何 agent 都能读懂并执行

### 问题

Holmes 不控制 agent，但 agent 能否高效排查完全取决于 entry 内容写得好不好。当前 spec 定义了 entry 的格式约束（必须有 ## Steps、## Resolution 等），但没有定义 **内容质量标准** — 即 Steps 里每一步应该写到什么程度。

一个写得差的 process entry：
```markdown
## Steps
1. 检查驱动版本
2. 如果版本不对就升级
3. 重启验证
```

一个写得好的 process entry：
```markdown
## Steps
1. **[api]** 查询当前 GPU 驱动版本
   `nvidia-smi --query-gpu=driver_version --format=csv,noheader`

2. **[decide]** 对比版本号：
   - >= 535.129.03 → 驱动版本正常，返回上层继续排查
   - < 535.129.03 → 需要升级，继续下一步

3. **[remote]** 下载并安装目标版本驱动
   ```bash
   wget https://us.download.nvidia.com/tesla/535.129.03/NVIDIA-Linux-x86_64-535.129.03.run
   chmod +x NVIDIA-Linux-x86_64-535.129.03.run
   sudo ./NVIDIA-Linux-x86_64-535.129.03.run --silent
   ```

4. **[remote]** 重启 nvidia-persistenced 并验证
   ```bash
   sudo systemctl restart nvidia-persistenced
   nvidia-smi
   ```
   预期输出：显示 GPU 信息和驱动版本 535.129.03

5. **[decide]** 根据验证结果：
   - nvidia-smi 正常显示 → 问题解决，END
   - 仍然报错 → 参考 [驱动安装失败排查](gpu-driver-install-failure-001)
```

差别在于：
- 每步标注了行为类型（`[api]`/`[remote]`/`[physical]`/`[observe]`/`[decide]`）
- 命令完整可执行（不是"升级驱动"而是具体的 wget + install 命令）
- 判断条件明确（不是"版本不对"而是 ">= 535.129.03"）
- 预期输出清晰（agent 可以对比实际输出判断是否成功）

### 优化方案

#### 2.1 Agent 2 System Prompt 增加内容质量标准

在 Agent 2 的 system prompt（M5 prompt2.py）中，增加每步写法的硬约束：

```
Every Step must satisfy:

1. Behavior tag: prefix each step with **[api]** / **[remote]** / **[physical]** / **[observe]** / **[decide]**
   This tag comes from the DAG node's node_type and must be consistent.

2. Executability:
   - [api] and [remote] steps MUST include a complete, executable command or API call
     ✓ `nvidia-smi --query-gpu=driver_version --format=csv,noheader`
     ✗ "check driver version" (not executable)
   - Commands must come verbatim from the source document; do not fabricate commands
   - If the source only has a description without a concrete command, write the description
     and append [command not in source]

3. Decision criteria:
   - [decide] steps MUST specify explicit conditions and corresponding paths
     ✓ "output status=pass → memory OK; output code=E01 → see [E01 Fix](...)"
     ✗ "decide next step based on result" (vague)

4. Expected output (optional but recommended):
   - [api] steps: if the source document provides expected output, include it
   - This helps the agent automatically determine if the command succeeded

5. Routing links:
   - Every step with sub-branches must use [title](entry-id) link format
   - Link text must come from the target entry's actual title (read_entry before write_entry)
```

#### 2.2 write_entry 格式校验增加内容质量检查

在 Agent 2 的 `write_entry` 校验中，增加内容级检查（warning，不阻断写入）：

```
Content quality checks (written to pending, but flagged as warning):
  ⚠ Step 2 tagged [api] but contains no code block or command → "missing executable command"
  ⚠ Step 4 tagged [remote] but contains no code block or command → "missing executable command"
  ⚠ Step 5 has branches but contains no [...](entry-id) link → "missing routing link"
```

这些 warning 进入 ImportReport.warnings，提示 reviewer 关注。

#### 2.3 CLAUDE.md 中增加 KB 使用指引

Holmes 不控制 agent，但可以通过 CLAUDE.md（agent 启动时加载）给 agent 提示如何使用 KB：

```markdown
## Using the Troubleshooting Knowledge Base

When users describe hardware problems:
1. Use kb_search to find relevant pitfall entries
2. Use kb_read to read the pitfall entry's Resolution for the troubleshooting tree
3. Follow routing links to drill into process sub-entries
4. Each process entry's Steps are tagged with behavior hints:
   - **[api]** — You can execute this command directly (read-only query/diagnostic)
   - **[remote]** — You can execute this command directly (changes system state)
   - **[observe]** — You MUST ask the user; this requires on-site human observation
   - **[physical]** — You MUST tell the user to do this; it requires physical manipulation
   - **[decide]** — Evaluate prior results yourself and choose the correct branch
5. When you hit a branch, select the path matching actual output/user feedback,
   then kb_read the corresponding child entry to continue
```

这段指引是 Holmes 能影响 agent 行为的唯一渠道。英文标签的好处是 agent 不需要 CLAUDE.md 也能猜到语义（`[physical]`、`[observe]` 对任何 LLM 都是自解释的），CLAUDE.md 只是加强确定性。

---

## Gap 3：规模可行性（当前目标 ≤30 process 节点）

### 问题

30 个 process 节点级别的排查树，文档长度约数千到一万字。风险集中在内容定位准确性和 review 效率。

### 优化方案

#### 3.1 Agent 1 增加 line_range 记录

Agent 1 提取 DAG 时，每个节点除了 `section_heading`，还记录 `line_range`：

```json
{
  "id": "N3",
  "description": "运行内存诊断工具",
  "node_type": "api_call",
  "complexity": "process",
  "section_heading": "### 内存诊断步骤",
  "line_range": [156, 203],
  "children": [...]
}
```

`line_range` 是 Agent 1 在通读阶段 Read 到该内容时记录的原文行号范围。

**作用**：
- Agent 2 定位原文内容时，`line_range` 是第一优先级锚点，比 `section_heading` Grep 更精准
- 特别是 prose 文档（无标题），`line_range` 是唯一可靠的定位方式
- `section_heading` 保留作为备选和人类可读锚点

**Agent 2 定位策略变更**：
```
line_range 存在 → Read(line_range[0], line_range[1] - line_range[0]) → 直接提取
line_range 不存在或内容不匹配 → fallback 到 section_heading Grep
section_heading 也不存在 → fallback 到 description 关键词 Grep
全部失败 → content_source: match_failed
```

#### 3.2 .dag.md 按一级分支分区

排查树概览按根节点的一级分支分区，每段标注节点数，帮助用户分段 review：

```
## 排查树概览

### 分支 1：电源相关（8 个节点）
├── [observe] 指示灯不亮
│   ├── [physical] 电源线松动 → 重新插紧（simple）
│   └── [physical] 电源线正常 → 电源适配器更换 🔧
└── [observe] 指示灯红色闪烁 → 固件修复流程 🔧
    └── ...

### 分支 2：启动序列相关（12 个节点）
├── [api] 检查启动日志 🔧
│   ├── ...
```

30 节点以内的树，分 3-5 个分支段，每段 5-10 个节点，review 可行。

#### 3.3 分批子 agent 策略（后续迭代）

spec 中 >20 process 节点的分批子 agent 策略保留设计，但当前不实现。M4/M5 的 Agent 2 只实现"全局视野模式"（一个 agent 生成所有 entries）。待有真实大规模文档后再验证分批策略的必要性和细节。

---

## Gap 4：section_heading 定位脆弱性

### 问题

Agent 2 靠 `section_heading` 定位原文内容。但硬件排查文档经常：
- 没有规范标题（纯文字描述）
- 同一个操作散布在文档多处
- 标题有微小差异（"内存诊断" vs "### 内存诊断步骤"）

### 优化方案

已在 Gap 3 的 3.1 中通过 `line_range` 解决。这是最直接的方案——Agent 1 在通读文档时天然知道每段内容的位置，直接记录行号比事后用标题 Grep 可靠得多。

**补充**：Agent 1 的 system prompt 中增加要求：

```
每个节点必须记录 line_range（你在阅读时看到这段内容的行号范围）。
这是 Agent 2 定位原文的最可靠锚点。
即使有 section_heading，也必须同时记录 line_range。
```

---

## 已确认的设计决策

### D1：action 拆分为 physical_action + remote_action（已确认）

原 spec 的 4 种 node_type 扩展为 5 种。拆分理由：

- **安全红线**：`physical_action` 是硬标签，agent 看到就不会尝试自动执行
- **连续自动执行不中断**：`api_call → remote_action → api_call` 序列中 agent 一口气跑完，不需要在 `action` 处暂停分析是否可以自己做
- **分类负担低**："需不需要人在现场"是清晰的物理标准，Agent 1 判断容易

### D2：标注格式使用英文（已确认）

`[api]` / `[remote]` / `[physical]` / `[observe]` / `[decide]`

英文标签对任何 LLM 都自解释（`[physical]` 不需要额外说明就知道是物理操作），降低对 CLAUDE.md 的依赖。CLAUDE.md 只是加强确定性，不是必须的。

### D3：先保证 30 节点规模（已确认）

- M4/M5 实现目标：可靠支持 ≤30 个 process 节点
- 分批子 agent 策略（>20 节点分批）保留在设计中，但实现优先级降低
- 分批策略作为后续迭代（有真实大规模文档后再验证和实现）

---

## 优化方案与模块的对应关系

| 优化项 | 影响模块 | 改动量 |
|---|---|---|
| 1.1 node_type 判断标准 | M4 prompt.py | 小（prompt 增加内容） |
| 1.2 .dag.md 树形概览展示 node_type | M4 tools.py、prompt.py | 小（格式变更） |
| 1.4 output_dag node_type 校验 | M4 agent1.py | 小（增加 1 条校验） |
| 1.5 Step 2.5 node_type 抽检 | M5 step25.py | 小（抽检维度扩展） |
| 2.1 Agent 2 内容质量标准 | M5 prompt2.py | 中（prompt 重写 Steps 约束） |
| 2.2 write_entry 内容检查 | M5 tools2.py | 小（增加 warning 检查） |
| 2.3 CLAUDE.md KB 使用指引 | 非代码，文档维护 | 小 |
| 3.1 line_range 记录 | M4 schema.py、prompt.py；M5 agent2.py | 中（DAG schema 扩展） |
| 3.2 .dag.md 分区 review | M4 prompt.py | 小（格式建议） |
| 4.1 Agent 2 定位策略变更 | M5 agent2.py、prompt2.py | 中（定位优先级链变更） |

总体改动集中在 M4 和 M5 的 prompt 和校验逻辑，不影响其他模块。

---

## 对 spec.md 的变更摘要

本文档确认后，需要同步修改 spec.md 的以下章节：

1. **DAG 节点 schema** — `node_type` 从 4 种扩展为 5 种（拆分 action → physical_action + remote_action）
2. **DAG 节点 schema** — 新增 `line_range: [start, end]` 字段
3. **.dag.md 格式** — 树形概览增加 `[observe]`/`[api]`/`[remote]`/`[physical]`/`[decide]` 标签
4. **Agent 2 格式约束** — Steps 每步必须有行为标签；`[api]`/`[remote]` 步骤必须有可执行命令
5. **规模策略** — 当前目标 ≤30 process 节点；分批子 agent 策略为后续迭代
