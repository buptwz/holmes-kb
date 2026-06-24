# Spec 037 — DAG-Based Import Pipeline for Pitfall Entries

## Background

现有 import pipeline（Reader → Extractor → Phase 3）对于复杂排查链路的提取质量不稳定：
- LLM 单次提取容易丢失分支和隐性知识
- 生成的 KB entry 结构扁平，agent 难以导航复杂决策树
- 无法处理文档更新和多人协作场景

## Design Principles

1. **一个文档 = 一个问题 = 一棵排查树**：引导用户每个文档只写一个排查链路
2. **人工背书的质量保证**：LLM 提取草稿，工程师确认，生成有人工背书的知识
3. **层次化知识结构**：全貌优先，层层递进，agent 按需深入
4. **状态在 git 里**：所有 import 状态随 KB git 同步，支持多人协作

---

## 适用范围

本流程**仅适用于 pitfall 类型**的文档（故障排查链路）。

Classifier 识别到 `single_incident` 或 `multi_incident` 时走本流程。
其他文档类型（`runbook / guideline / model / decision`）继续走现有 Reader → Extractor 流程，不变。

---

## 核心数据模型

### Pitfall = 整棵排查树

**Pitfall entry 是整个排查链路的树形骨架**，包含所有决策节点和路由逻辑。

树中每个节点有两种复杂度：

| 节点类型 | 描述 | KB 处理方式 |
|---|---|---|
| `simple` | 简单判断或一句话操作，不需要展开 | inline 写在父 entry 的 Resolution 里 |
| `process` | 步骤复杂，需要详细描述；执行完后可能还有子分支 | 生成独立 process entry，父 entry 链接到它 |

**关键：process 节点可以出现在树的任意位置，不限于叶子节点。** 一个 process 节点执行完后，可以继续路由到下一个节点（simple 或 process），形成任意深度的嵌套结构。

### 示例结构

```
pitfall entry（路由骨架）
  │
  ├─ [simple] 检查电源指示灯颜色
  │     → 红色  → [process entry: 固件修复流程]
  │                    → 修复成功 → 结束
  │                    → 修复失败 → [process entry: 硬件更换流程]
  │     → 不亮  → [simple] 检查电源线连接
  │                    → 松动  → [process entry: 电源线重连步骤]
  │                    → 正常  → [process entry: 电源适配器更换步骤]
  │     → 绿色  → [simple] 检查启动日志
  │                    → POST 失败 → [process entry: POST 诊断流程]
  │
  └─ [process entry: 内存诊断工具运行步骤]（复杂操作，执行后继续分支）
        → 输出正常   → [simple] 继续下一项检查
        → 输出 E01   → [process entry: E01 错误修复]
        → 输出 E02   → [process entry: E02 错误修复]
```

---

## 整体流程

```
holmes import doc.md
       │
       ├─ [Step 0] 去重与更新检测
       │      → 完全重复？跳过
       │      → 文档更新？走更新流程
       │      → 全新文档？走首次导入流程
       │
       ├─ [Step 1] Classifier
       │      → 非 pitfall 类型？切换到现有 pipeline
       │      → pitfall 类型？继续
       │
       │  ┌─────────────────────────────────────────────────┐
       │  │  [Step 2] Agent 1：DAG 提取（全自动，无交互）   │
       │  │    工具：Read + Grep +                         │
       │  │          write_dag + read_dag + output_dag     │
       │  │    三阶段：通读 → 初稿 → 多轮 review           │
       │  │    Harness：工具白名单 + maxTurns + 快照恢复   │
       │  │    → 输出 _import-state/<hash>.dag.md          │
       │  │    → 提示用户编辑或 --skip-edit               │
       │  └─────────────────────────────────────────────────┘
       │
       │       [用户离线编辑 .dag.md（可选）]
       │
       ├─ holmes import --resume
       │
       │  ┌─────────────────────────────────────────────────┐
       │  │  [Step 2.5] 解析规范化 + 交叉验证               │
       │  │    LLM 宽松解析用户编辑内容 → 规范 DAG JSON    │
       │  │    展示"我的理解"→ 用户确认或修正               │
       │  │    程序化 + LLM 抽检：DAG 与原文是否一致        │
       │  │    → "共 M 个节点，将生成 K 个 entries，开始？" │
       │  └─────────────────────────────────────────────────┘
       │
       │  ┌─────────────────────────────────────────────────┐
       │  │  [Step 3] Agent 2：双源生成（全自动）           │
       │  │    读规范 DAG + 原始文档                        │
       │  │    顺序生成（叶→根），pitfall root 最后写       │
       │  │    每个 entry 即时格式校验                      │
       │  │                                                 │
       └─ │  [Step 4] 写入 pending，等待 approve           │
          └─────────────────────────────────────────────────┘
```

**两个 Agent 的分工**：
- Agent 1 全自动提取结构，尽量减少人的等待；人的工作是离线编辑 .dag.md
- Agent 2 全自动生成知识文档，人只需在开始前做一次最终确认

---

## Step 0：去重与更新检测

### 检测逻辑

```
1. 计算 source_hash = hash(文档内容)

2. 同时搜索 pending 空间和 confirmed 空间中 source_hash 匹配的 entry
   → 找到（任意空间）：完全重复，跳过

3. 搜索 pending 空间和 confirmed 空间中 source_file（路径）匹配的 entry
   → 找到 + hash 不同：文档有更新，走更新流程（见下方）
   → 未找到：全新文档，走首次导入流程
```

### 更新流程：每次 import 全量重新生成，新旧物理隔离

不做 in-place 更新。每次 import 生成全新 ID 的 entries，新旧两套物理上完全独立。
旧 entries 的替换通过 **pending 空间清理** 和 **confirmed 空间 deprecate** 两个时机处理。

```
→ 加载旧 DAG（_import-state/<old_hash>.dag.json）
→ 对新文档重新提取 DAG
→ 展示 DAG 变更概要（新增/删除/修改的节点和边）
→ 用户确认（支持多轮补充修正）
→ 生成全新 ID 的 entries，写入 pending
→ 同时触发「pending 空间清理」（见下方）
```

### Pending 空间清理（import 时触发）

新 import 写入 pending 之前，检查 pending 空间中是否存在同 `source_file` 的旧 pending entries：

```
检测到同文档的旧 pending entries（2024-03-01 导入，未审核）：
  - hardware-init-failure-001 (pending)
  - hardware-init-memory-diag-001 (pending)
  - hardware-init-firmware-repair-001 (pending)
是否取消旧 pending，用本次新 import 替换？[Y/n]

→ Y：从 _pending/ 直接移除旧 entries（未审核草稿，不走 _trash/），继续写入新 entries
→ n：新旧 pending 并存，reviewer 在 approve 时自行选择保留哪套
```

### Confirmed 空间替换（approve 时触发）

approve 新 entries 时，检查 confirmed 空间中是否存在同 `source_file` 的 active entries：

```
approve 后将替代以下 confirmed entries：
  - hardware-init-failure-001 (confirmed, 2024-01-15)
  - hardware-init-memory-diag-001 (confirmed)
  - hardware-init-firmware-repair-001 (confirmed)
标记为 deprecated？[Y/n]

→ Y：旧 entries 的 kb_status 改为 deprecated，新 entries 变为 active
→ n：新旧同时 active（暂时保留两套，由管理员后续处理）
```

### 三层并存场景（最复杂）

同一文档同时存在三层：

```
confirmed 空间：hardware-init-failure-001（1月 import，已 approve）
pending 空间：  hardware-init-failure-002（2月 import，未 approve）
pending 空间：  hardware-init-failure-003（3月 import，刚生成）
```

approve hardware-init-failure-003 时：
1. 取消 pending 中的 002（同 source_file 的旧 pending）
2. deprecate confirmed 中的 001
3. 003 变为 active

一次 approve 操作清理两层旧数据。

### Entry 状态字段

Frontmatter 新增 `kb_status` 字段（区别于知乎模型的 `decay_status`，两者语义不同）：

```yaml
kb_status: active       # 当前有效，参与 agent 检索
kb_status: deprecated   # 已被新版本替代，不参与检索
kb_status: pending      # 待审核（存在 _pending/ 目录中）
```

- `kb_status`：KB 管理工作流状态（import → approve → deprecate）
- `decay_status`（知乎模型原有字段）：知识质量生命周期，由证据积累和衰减机制驱动，与 `kb_status` 正交

Agent 搜索时只返回 `kb_status: active` 的 entries。

### 不同文档但内容相似（语义重复）

`source_file` 不同、内容相似的情况（如两位工程师各自写了同一问题的排查文档），系统不自动处理。
由 **git 仓库管理员** 通过 git PR review / issue 等协作机制介入，手动 deprecate 冗余 entries。

### 状态存储（git 追踪）

```
KB repo/
  _import-state/
    <source_hash>.dag.md       ← Agent 1 输出，用户可编辑
    <source_hash>.dag.json     ← Step 2.5 解析规范化后生成，程序内部格式，随 git 同步
    <source_hash>.session.json ← Agent 1 crash recovery 快照（每 20 turns 覆盖写入）
```

生成失败重试时，直接从已确认的 DAG 继续，跳过提取和确认。

---

## Step 1：Classifier

单次 LLM 调用，判断文档类型：

- `single_incident` → 走 DAG 流程
- `multi_incident` → 走 DAG 流程 + 输出 warning："建议拆分为独立文档分别导入"
- `runbook / guideline / model / decision` → 切换到现有 pipeline
- `non_kb` → 跳过

---

## Step 2：DAG 提取（Agent 1）

**职责**：自主探索源文档，提取排查树结构，输出可供用户 review 的 .dag.md。全程无需用户参与，适用于所有文档类型（有无标题结构均可）。

### 工具设计

| 工具 | 类型 | 用途 |
|---|---|---|
| `Read(file, offset, limit)` | Claude Code 基础工具 | 按需读取任意片段，有界 |
| `Grep(pattern, file)` | Claude Code 基础工具 | 扫标题、定位分支条件、追踪关键词 |
| `write_dag(content)` | 领域专属 | 写入 / 覆盖整个 .dag.md（可多次调用） |
| `read_dag()` | 领域专属 | 读回当前 .dag.md，供 agent 自查 |
| `output_dag()` | 领域专属 | 无参数，validate .dag.md → 生成 .dag.json，终止 loop |

**工具约束**：Agent 1 只有这 5 个工具，物理上无法写 entry、无法修改 KB。

### 三阶段 Agent Loop

Agent 1 按固定三个阶段工作，system prompt 明确规定每个阶段的行为。

#### 阶段 1：通读理解（不调用 write_dag）

```
目标：在写任何输出之前，充分理解文档全貌

典型操作：
  Grep("^#{1,6} ")          ← 如果有标题，先扫结构
  Read(0, 500)              ← 读开头，理解背景和核心问题
  Read(N, 500)              ← 追踪感兴趣的 section
  Grep("如果|→|fail|error") ← 定位分支条件
  Read(M, 300)              ← 读分支附近的上下文
  ...（直到对整棵树有清晰认识）

禁止：此阶段不调用 write_dag
```

#### 阶段 2：写初稿（第一次 write_dag）

```
目标：将理解转化为完整的 .dag.md 初稿

write_dag("""
# 排查树：[title]
## 文档摘要
...
## 排查树概览
[ASCII 树形图]
## 节点详情
[结构化节点定义]
""")

三个 section 一次性写入，允许有不确定的地方（标 [?]）
```

#### 阶段 3：多轮 Review（2~3 轮，可再次 write_dag）

```
目标：核实遗漏、修正错误，直到自己确信 DAG 完整准确

每轮操作：
  read_dag()                ← 看当前 DAG 状态
  Grep / Read               ← 回原文核实有疑问的地方
  write_dag(updated)        ← 有修改则覆盖写入，无修改跳过

自我检查清单（调用 output_dag 前必须过）：
  □ 每条分支都追踪到了 END 或另一个节点
  □ 没有只有入边没有出边的节点（悬空）
  □ 文档的主要 section / 段落都读过了
  □ 每个 process 节点有 section_heading 或足够的描述

output_dag()   ← 提交，harness validate，终止 loop
```

### Harness 设计

**工具白名单**：只允许上表 5 个工具，拒绝其他调用。

**output_dag 校验**（调用时触发，失败则返回 error，agent 必须修正）：
```
✓ 至少存在一个根节点（无 parent 的节点）
✓ 所有边的目标节点在节点列表中存在
✓ 无循环引用
✓ 所有 process 节点有 section_heading 或 description 非空
✓ 每个节点至少有一条出边，或显式标记为 END
```

**Crash Recovery**：每 20 turns 将完整对话历史（messages 数组）序列化写入 `_import-state/<hash>.session.json`。中断后从快照恢复，继续 loop，不从头开始。

**maxTurns = 300**：适用所有文档类型，无需区分。

### 能力边界与特殊情况处理

#### 已知能力边界：隐性分支

Agent 1 能可靠识别文档中**显式**的分支条件（"如果...则..."、箭头、条件关键词）。**隐性分支**（通过叙述语气暗示的条件，如"对于固件版本低于 2.1 的设备，需要额外步骤..."）可能在通读阶段识别，也可能遗漏。

这是已知的能力边界，不是设计缺陷。两层兜底机制：
1. 用户 review .dag.md 的树形图（缺失的分支在视觉上通常很明显）
2. Step 2.5 交叉验证的 LLM 抽检会尝试识别

#### section_heading 为 null 时的 fallback

prose 文档中，process 节点可能没有对应的标题（section_heading = null）。Agent 2 的 fallback 策略：

```
section_heading 存在 → Grep 定位，Read 提取 section 内容（标准路径）
section_heading = null：
  → 用节点 description 作为 Grep pattern，在原文中搜索相关段落
  → 找到 → 读取该段落附近内容（±200 行）
  → 找不到 → frontmatter 标注 `content_source: description_match_failed`，进入 ImportReport.warnings
```

#### 多 root 场景（multi_incident 文档）

Classifier 判断 `multi_incident` 时 warning 建议拆分，但流程不阻断。Agent 1 可能产生多个不相连的子树（多个根节点），这是**允许的合法输出**。

output_dag 校验规则调整：
```
✓ 至少存在一个根节点（无 parent）      ← 不要求唯一
✓ 每个根节点都能到达至少一个 END       ← 每棵子树自洽
```

Agent 2 为每个根节点各生成一个 pitfall entry，ImportReport 说明生成了 N 棵独立排查树。

#### 循环引用处理

文档中可能存在回路逻辑（"步骤 3 失败则回到步骤 1"）。output_dag 检测到循环引用时，不让 agent 无限 retry，而是要求 agent **主动打断**：

```
output_dag 返回错误："检测到循环引用：N3 → N8 → N3"

Agent 处理方式（system prompt 中明确）：
  选择一条回路边标记为 back_edge（通常是"返回"语义的那条）
  back_edge 不作为 DAG 的结构边，改为在节点 description 中注明
  例：N3 的 description 补充"若失败可重试，回到 N8"
  write_dag(修正后内容) → 再次 output_dag
```

### System Prompt 结构

参考 Claude Code prompt.ts 风格：角色 → 阶段说明 → 工具说明 → 禁止项 → 终止条件。

```
你是 Holmes KB import pipeline 的排查树提取专家（Agent 1）。

你的工作分三个阶段：
  阶段 1 通读：充分读完文档，理解核心问题和所有分支，再开始写。
  阶段 2 初稿：调用 write_dag，写出完整的三个 section。
  阶段 3 Review：read_dag → 回原文核实 → write_dag 修正，重复 2~3 轮。

工具说明：
  Read / Grep：探索原文，随时可用
  write_dag：写 .dag.md，可多次调用（后一次覆盖前一次）
  read_dag：看当前 .dag.md，用于 review
  output_dag：唯一的结束方式，调用后 loop 终止

你只提取结构，不写具体操作步骤：
  节点 = 一句话描述 + complexity + section_heading + node_type
  边   = 触发条件 + 目标节点
  具体步骤由 Agent 2 负责，你不需要写

禁止项：
  不要在通读阶段调用 write_dag
  不要补充文档里没有的分支
  不要在自我检查清单完成前调用 output_dag

调用 output_dag 前，确认：
  □ 每条分支都追踪到了 END 或另一个节点
  □ 没有悬空节点
  □ 文档主要内容都读过了
```

### DAG 节点 schema（.dag.json internal 格式）

```json
{
  "id": "N3",
  "description": "运行内存诊断工具",
  "node_type": "api_call",
  "complexity": "process",
  "section_heading": "### 内存诊断步骤",
  "children": [
    {"condition": "输出正常",  "target": "N4"},
    {"condition": "输出 E01", "target": "N7"},
    {"condition": "输出 E02", "target": "N9"}
  ]
}
```

**`complexity` 字段**：

| 值 | 判断依据 | 处理方式 |
|---|---|---|
| `simple` | 1~2 步，无需展开 | inline 写在父 entry 的 Resolution |
| `process` | 步骤多、有具体操作命令、需要独立描述 | 生成独立 process entry |

**`node_type` 字段**（Agent 2 生成时的行为提示，以及 agent 运行时导航提示）：

| 值 | 含义 |
|---|---|
| `human_observation` | 用户观测物理信号 |
| `api_call` | 调用接口 |
| `decision` | 基于已知信息判断 |
| `action` | 执行操作 |

**`section_heading` 字段**：Agent 2 用此字段定位原文 section：
1. `Grep(section_heading)` → 找到起始行号 `start`
2. `Grep("^#{同级或更高} ", offset=start+1)` → 找到下一同级标题行号 `end`（含所有嵌套子标题）
3. `Read(start, end-start)` → 提取完整 section 内容

`section_heading` 为 null 时，Agent 2 依靠节点 `description` 定位相关内容（prose 文档场景）。

---

## DAG 文档格式（.dag.md）

Agent 1 完成后输出 `_import-state/<source_hash>.dag.md`，是人可读、可编辑的 DAG 摘要文件，包含三个渐进式 section。

### 格式规范

```markdown
# 排查树：硬件初始化失败

> source: hardware-init-failure.md
> generated: 2026-06-23
> 说明：可直接编辑任意内容后运行 holmes import --resume
>       不需要修改则运行 holmes import --resume --skip-edit

---

## 文档摘要

核心问题：设备上电后无法完成初始化流程
主要症状：电源指示灯异常、系统无响应、启动序列中断
覆盖场景：固件异常、内存故障、电源故障、启动序列问题

---

## 排查树概览

硬件初始化失败
├── 指示灯不亮
│   ├── 电源线松动 → 重新插紧（simple）
│   └── 电源线正常 → 电源适配器更换 🔧
├── 指示灯红色闪烁 → 固件修复流程 🔧
│   ├── 修复成功 → END
│   └── 修复失败 → 硬件更换流程 🔧
└── 指示灯绿色，有启动尝试 → 内存诊断流程 🔧
    ├── 输出正常 → END
    ├── 输出 E01 → E01错误修复 🔧
    └── 输出 E02 → E02错误修复 🔧

---

## 节点详情

### N1 — 检查电源指示灯
complexity: simple
node_type: human_observation

- 不亮 → **N2**
- 红色闪烁 → **N3** 🔧
- 绿色有启动尝试 → **N5** 🔧

---

### N3 — 固件修复流程
complexity: process
node_type: action
section_heading: "### 固件修复步骤"

- 修复成功 → END
- 修复失败 → **N7** 🔧

---

### N7 — 硬件更换流程
complexity: process
node_type: action
section_heading: "### 硬件更换"

- 更换完成 → END
```

**三个 section 的作用**：

| Section | 作用 |
|---|---|
| 文档摘要 | 让用户快速确认 Agent 1 理解了正确的问题 |
| 排查树概览 | 树形图，用户一眼看出分支是否完整，是最有价值的 review 界面 |
| 节点详情 | 机器可解析的结构化数据，驱动 Agent 2 生成 |

**格式约定**：
- `🔧` = process 节点，将生成独立 KB entry
- 无 `🔧` = simple 节点，inline 写在父 entry 的 Resolution
- `section` 字段：Agent 2 定位原文内容的锚点；无此字段则用节点描述定位
- `END` = 终止节点，无出口

### 用户编辑原则

文件设计为**宽松格式**，用户可以用自然语言修改任意内容：
- 修改节点描述、分支条件、complexity、section 引用
- 增删节点（无需分配 ID，用描述即可）
- 直接在树形图上标注缺失的分支（Step 2.5 的解析会识别）

`--resume` 时 LLM 宽松解析重新理解用户编辑的内容，用户不需要严格遵守格式。

---

## Step 2.5：解析规范化与交叉验证

### Agent 1 完成后的交互选择（同一 session）

Agent 1 完成后**不退出**，直接在同一 session 里展示选项，避免用户需要记住并手动运行第二条命令：

```
DAG 已提取（47 个节点，12 个 process 节点）。
已保存到 _import-state/hardware-init-failure.dag.md

选择：
  [1] 现在编辑（打开编辑器，完成后按 Enter 继续）
  [2] 不需要编辑，直接生成
  [3] 稍后处理（退出后运行 holmes import --resume）

选择 [1/2/3]:
```

选 1 或 2：继续在当前 session 执行 Step 2.5。
选 3：退出，状态保存在 `_import-state/`，用户稍后 `holmes import --resume` 接续。

`--no-interactive` 模式下自动选 2，无需用户操作。

---

### 解析规范化 + 交叉验证（合并为一屏）

用户编辑完成（或选择跳过）后，系统执行解析和验证，**结果合并在一屏展示**，只需一次用户确认：

**解析规范化**（LLM 宽松解析用户编辑内容）：

处理用户常见的自然语言写法：

| 用户写法 | 系统识别 |
|---|---|
| `这步比较复杂` | `complexity: process` |
| `如果修复失败的话跳到N7` | edge: → N7, condition: 修复失败 |
| 新增节点没给 ID | 自动分配 ID |
| section 写成"第三节那里" | 打 uncertain，展示给用户 |
| 删掉🔧但没改 complexity | uncertain，展示给用户 |

**交叉验证**（程序化 + LLM 抽检）：
- 程序化：每个 section 字段 Grep 原文验证存在；无环检测
- LLM 抽检：随机抽 min(10, 节点总数) 个节点，对比分支条件与原文语义一致性

**合并展示，一次确认**：

```
解析 + 验证完成：

  编辑识别：
    ✓ 新增节点 N12（电源适配器故障），complexity=process
    ✓ N3 分支条件改为"降级处理"
    ⚠ 不确定：N_新 的 section 引用"第三节"，是哪个标题？

  内容验证：
    ⚠ N12 的 section "### 超时处理" 在原文中找不到
    ✓ 其余 46 个节点结构验证通过

  共 47 个节点，将生成 13 个 entries（1 pitfall + 12 process）。

确认并开始生成？[Y / 需要修改]
```

**解析失败**（结构性错误）时，不进入生成，报错并提示修改：

```
解析失败，无法继续：
  ✗ N7 的分支目标 N15 不存在（可能删了 N15 但没更新 N7 的出口）
  ✗ 发现循环引用：N3 → N8 → N3

请修改 .dag.md 后选择 [1] 重新编辑，或运行 holmes import --resume
```

---

### --resume 多状态选择

`holmes import --resume` 若存在多个 pending state：

```
找到 2 个待处理的 import：
  [1] hardware-init-failure.md（2026-06-22，47 节点）
  [2] network-timeout.md（2026-06-21，23 节点）
选择: _
```

---

## Step 3：双源知识生成（Agent 2）

### 输入

- **规范 DAG JSON**（`_import-state/<hash>.dag.json`）：决定生成什么、结构是什么、每个 process 节点的 section_heading
- **原始文档**：每个 process 节点的详细内容来源（通过 Grep + Read 按 section_heading 提取）

### Agent 2 设计

Agent 2 与 Agent 1 使用同一 agent loop 框架，但工具集和 harness 约束不同。**两个 Agent 的 conversation context 完全独立**，通过文件系统通信（Agent 1 写 .dag.md/.dag.json，Agent 2 读取并生成 entries）。

#### 工具

| 工具 | 类型 | 用途 |
|---|---|---|
| `Read(file, offset, limit)` | Claude Code 基础工具 | 读原始文档 |
| `Grep(pattern, file)` | Claude Code 基础工具 | 定位原文内容 |
| `read_dag()` | 领域专属 | 读 .dag.json，获取全树结构和 ID 表 |
| `write_entry(entry_id, content)` | 领域专属 | 写一个 entry 到 `_pending/<type>/<category>/`，内置格式校验 |
| `read_entry(entry_id)` | 领域专属 | 读回已写 entry，用于一致性检查 |
| `finalize()` | 领域专属 | 结束 loop，触发 lint 校验，生成 ImportReport |

**工具约束**：Agent 2 只能写 `_pending/<type>/<category>/*.md`，不能修改 DAG 文件或其他文件。

#### 四阶段 Loop

**Phase 1：Study（不写任何 entry）**

```
read_dag()                          ← 理解全树结构、节点 ID 表、section_heading
决定采用哪种 study 策略（见下文）
读取所有相关 section 内容
```

**Phase 2：顺序生成 process entries（叶节点 → 根方向）**

```
生成顺序：拓扑逆序（叶节点先于父节点）
原因：父节点写之前，子节点已存在，可 read_entry(child) 获取真实标题

每个 process 节点：
  read_entry(sibling) if needed     ← 检查已写节点的术语，保持一致
  定位 section 内容（见 section 定位策略）
  write_entry(id, content)          ← 内置格式校验，失败则修正后重试
```

**Phase 3：最后写 pitfall root**

```
read_entry(child_id) for each direct child  ← 获取子节点的真实标题和 Steps 首句
write_entry(root_id, pitfall_content)
  → Resolution 的路由链接文案来自子节点真实标题，精准对应
```

**Phase 4：Consistency review**

```
抽查 5~10 个 entry（随机 + 有 section_heading=null 的必查）
read_entry(id)，检查：
  术语是否一致（和已写的兄弟节点对比）
  路由链接是否对应目标 entry 的真实标题
有问题 → write_entry 覆盖修正
finalize()
```

#### 规模分层策略（解决大树 context 累积问题）

```
≤ 20 个 process 节点：全局视野模式
  Phase 1 一次性读完所有 section 内容
  全部内容同时在 context → 术语天然一致
  顺序写 entry，无需 read_entry 也能保持一致

> 20 个 process 节点：分批子 agent 模式
  每批 10 个节点，每批启动一个独立 sub-agent（全新 context）
  批次间接口：
    输入：DAG + 本批节点列表 + 已写 entries 的 {id: 标题} 摘要表
    摘要表替代共享 context，传递跨批次的术语信息
  最后的 pitfall root 由独立 sub-agent 生成，输入已写的所有 entry 标题
```

#### Harness 设计

| 项目 | Agent 1 | Agent 2 |
|---|---|---|
| 写文件权限 | 只能写 `.dag.md` | 只能写 `_pending/<type>/<category>/*.md` |
| write 格式校验 | N/A | `write_entry` 内置，失败返回 error，agent 修正后重试 |
| maxTurns | 300 | 50 × process 节点数（上限 1000）|
| Crash Recovery | 对话历史快照（每 20 turns） | 已写文件天然 checkpoint，restart 跳过已写节点 |
| 终止方式 | `output_dag()` | `finalize()` |
| context 隔离 | 独立 | 与 Agent 1 完全独立，仅通过文件通信 |

#### section 定位策略

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

#### System Prompt 结构

```
你是 Holmes KB 的知识提取专家（Agent 2）。

输入：
  DAG 文档（read_dag()）
  原始知识文档（Read / Grep）

任务：按 DAG 结构生成 KB entries

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

**单节点 retry**：`holmes import --retry-entry <node-id>` 重新生成单个失败的节点，不影响其他 entries。

### 输出

```
1 个 pitfall entry（整棵树的路由骨架）
+ 每个 process 节点对应 1 个 process entry
```

process 节点可嵌套，因此 process entry 可以链接到其他 process entries，形成任意深度的层次结构。

### Pitfall entry（路由骨架）

```markdown
---
title: 硬件初始化失败
description: 设备上电后无法完成初始化，涵盖固件异常、内存故障、启动序列问题三条排查路径。
type: pitfall
pitfall_structure: tree
kb_status: pending
source_file: hardware-init-failure.md
source_hash: abc123
import_trace_id: hardware-init-failure
child_entry_ids:
  - hardware-init-firmware-repair-001   # 固件修复流程
  - hardware-init-memory-diag-001       # 内存诊断流程
  - hardware-init-post-diag-001         # POST 诊断流程
maturity: draft
decay_status: active
next_decay_check: 2026-12-19
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-22"}
tags: [hardware, initialization, firmware, memory]
---

## Symptoms
设备上电后无法完成初始化。

## Root Cause
可能原因：固件异常 / 内存故障 / 启动序列问题 / 电源故障

## Resolution

**第一步：观察电源指示灯状态（人工观测）**

- 指示灯不亮 → 检查电源线连接是否松动
  - 松动 → 重新插紧，重新上电
  - 正常 → 参考 [电源适配器更换步骤](hardware-init-power-adapter-001)
- 指示灯红色闪烁 → 参考 [固件修复流程](hardware-init-firmware-repair-001)
- 指示灯绿色，系统无响应 → 参考 [系统挂起排查](hardware-init-system-hang-001)
- 指示灯绿色，有启动尝试 → 参考 [内存诊断流程](hardware-init-memory-diag-001)
```

**Pitfall entry 只包含路由逻辑**，complex 节点用链接指向对应 process entry。Simple 节点 inline 描述。

### Process entry（任意复杂节点）

```markdown
---
title: 硬件初始化失败 — 内存诊断流程
description: 通过接口调用内存诊断工具，根据输出结果路由到对应的错误修复流程。
type: process
kb_status: pending
source_file: hardware-init-failure.md
source_hash: abc123
import_trace_id: hardware-init-failure
parent_id: hardware-init-failure-root-001  # 硬件初始化失败
child_entry_ids:
  - hardware-init-e01-repair-001           # E01 错误修复流程
  - hardware-init-e02-repair-001           # E02 错误修复流程
maturity: draft
decay_status: active
next_decay_check: 2026-12-19
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-22"}
tags: [hardware, memory, diagnostics]
---

## Steps

1. **[接口调用]** 执行内存诊断工具
   `POST /api/diagnostic/memory {"mode": "full"}`

2. **[人工观测]** 等待工具运行完成（约 3 分钟），观察输出结果

3. 根据输出判断：
   - 输出 `{"status": "pass"}` → 内存正常，返回上层继续排查
   - 输出 `{"status": "fail", "code": "E01"}` → 参考 [E01 错误修复](hardware-init-e01-repair-001)
   - 输出 `{"status": "fail", "code": "E02"}` → 参考 [E02 错误修复](hardware-init-e02-repair-001)
```

**Process entry 只使用原文 section 中存在的内容，允许重新组织为 Steps 结构，不补充原文没有的信息。** 原文通常是叙述式散文，LLM 将其重组为编号步骤列表，但每一步的内容必须有原文依据。

### 生成规则

- **Simple 节点**：inline 写在父 entry 的 Resolution，不生成独立 entry
- **Process 节点**：独立 process entry，内容从 `section_heading` 锚定的 section 提取（含所有嵌套子标题）
- **Process 节点有子分支**：该 process entry 的 Steps 末尾包含路由逻辑，链接到子 process entries
- **生成顺序**：叶节点 → 父节点 → pitfall root（拓扑逆序），保证写 parent 时 children 已存在可被 read_entry
- **规模策略**：≤20 process 节点全局视野模式；>20 节点分批子 agent，通过标题摘要表传递术语上下文

### Agent 2 格式约束（System Prompt 硬约束）

```
pitfall entry 必须包含：
  frontmatter: title, description, type=pitfall, pitfall_structure=tree, kb_status=pending,
               source_hash, source_file, import_trace_id, child_entry_ids, maturity=draft,
               decay_status=active, next_decay_check, contributors, tags
  sections: ## Symptoms, ## Root Cause, ## Resolution（含路由链接）

process entry 必须包含：
  frontmatter: title, description, type=process, kb_status=pending, parent_id,
               child_entry_ids（若有子节点），source_hash, source_file,
               import_trace_id, 同上证据字段
  sections: ## Steps（编号步骤，含路由逻辑）

内容约束：
  只使用原文 section 中存在的内容
  允许将叙述文本重组为编号步骤
  不补充原文没有的信息
  链接格式：[entry 标题](entry-id)
```

### 程序化格式校验（write_entry 内置，写入前触发）

```
✓ 所有必填 frontmatter 字段存在且非空
✓ 必需 sections 存在（pitfall: ## Symptoms/Root Cause/Resolution；process: ## Steps）
✓ child_entry_ids 中的 ID 全部在 DAG ID 表中
✓ parent_id 在 DAG ID 表中

校验失败 → write_entry 返回 error 描述，agent 修正后重试
           重试仍失败 → 进入 ImportReport.errors，entry 不写入 _pending/<type>/<category>/
           可用 holmes import --retry-entry <node-id> 单独重试

content_source 标注（非格式错误，写入 pending 但标注警告）：
  section_heading=null 且 Grep 定位失败 → frontmatter 写入：
    content_source: description_match_failed
  进入 ImportReport.warnings，提示 reviewer 核查该 entry 内容准确性
```

### 证据初始化（生成时写入 frontmatter）

每个生成的 entry（pitfall 和 process）在写入 pending 时自动填写以下字段，不依赖人工填写：

```
maturity:          draft               # 初始值，知乎模型定义
decay_status:      active              # 初始值，知乎模型定义
next_decay_check:  <today + 180 days>  # draft 级别衰减周期，知乎模型定义
contributors:
  - user: <config.username>    # 取自 ~/.holmes/config.json 的 username 字段
    role: initiator
    date: <today>
tags:              <由生成 agent 从文档内容推断>
source_references:
  - type: document
    path: <source_file>
    hash: <source_hash>
```

**`maturity` 升级路径**（知乎模型）：
- `draft` → `verified`：有工程师验证（`contributors` 新增 verifier）
- `verified` → `proven`：在生产环境有 confirmed case 记录

**`decay_status` 触发**（知乎模型）：
- `next_decay_check` 到期 + 无新 contributor 记录 → 提示 decay review
- decay review 后可升级 `next_decay_check` 或降级 `maturity`

### Entry ID 预生成

顺序生成前必须先确定所有 entry 的 ID，否则 `child_entry_ids` / `parent_id` 无法填写。

```
生成开始前：
  遍历 DAG 所有节点
  为每个 process 节点分配 ID：{source-name-slug}-{node-id}-{import-seq}
    例：hardware-init-failure-N3-001
  pitfall root ID：{source-name-slug}-root-{import-seq}
    例：hardware-init-failure-root-001
  将完整 ID 表写入 .dag.json，Agent 2 通过 read_dag() 获取

每个生成任务（叶→根顺序）：
  从 ID 表中取自身 ID 和子节点 ID
  填写 parent_id / child_entry_ids
  生成 entry 内容
```

重试时复用同一 `import-seq`，保证 ID 幂等。

### Process Sub-entry 可见性规则

Process sub-entries 是 pitfall 树的内部节点，不属于顶层 KB 条目，默认不出现在列表视图：

| 命令 | 默认行为 | 说明 |
|---|---|---|
| `holmes kb list` | **不显示** process sub-entries | 只显示 pitfall root 和顶层 entries |
| `holmes kb search` | **不显示** process sub-entries | 搜索范围限于 pitfall roots |
| `holmes kb show <process-id>` | **正常显示** | 明确指定 ID 时可查看，展示 `[sub-entry of: <parent_id>]` 标签 |
| `holmes kb list --all-types` | **显示** | 用于管理员 review，展示全部 entry 类型 |
| `holmes kb pending` | **按树形分组显示** | pitfall root 为组标题，sub-entries 缩进显示 |

**理由**：agent 通过 pitfall root 进入，按 `child_entry_ids` 链接递归深入，不需要直接搜索 sub-entries。用户直接 `holmes kb list` 时看到的是可以独立成为诊断起点的 entries，而非中间节点。

### Frontmatter 新增字段

本次新增字段，以及与知乎模型原有字段的关系：

| 字段 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `kb_status` | string | 本次新增 | KB 管理工作流状态（pending/active/deprecated） |
| `source_file` | string | 本次新增 | 相对于 KB root 的源文档路径，用于更新检测，随 git 同步 |
| `source_hash` | string | 本次新增 | 文档内容 hash，用于去重检测 |
| `child_entry_ids` | list | 本次新增 | 树结构子节点 ID 列表（区别于知乎的 `related_ids` 语义关联） |
| `parent_id` | string | 本次新增 | 父 entry ID（process entry 指向 pitfall 或上层 process） |
| `pitfall_structure` | string | 本次新增 | `tree`（新式路由骨架）/ `flat`（旧式自包含，兼容旧 entries） |
| `description` | string | 本次新增 | 1-2 句话的 entry 摘要，Agent 2 从 DAG 节点 description 生成，不得为空 |
| `import_trace_id` | string | 本次新增 | 源文档 trace_id（= 文件名 stem），用于日志关联；见可观测性章节 |
| `maturity` | string | 知乎模型原有 | 初始值 `draft`，随证据积累升级为 verified/proven |
| `decay_status` | string | 知乎模型原有 | 初始值 `active` |
| `next_decay_check` | string | 知乎模型原有 | 初始值 `today + 180days`（draft 级别衰减周期） |
| `tags` | list | 知乎模型原有 | 由生成 agent 从文档内容推断，写入 frontmatter |
| `contributors` | list | 知乎模型原有 | 初始值：执行 import 的用户，role=initiator；`user` 取自 `config.username` |
| `related_ids` | list | 知乎模型原有 | 语义关联 entry（与 `child_entry_ids` 不同，不表示树结构） |

**`child_entry_ids` vs `related_ids` 区别**：`child_entry_ids` 是树形导航的结构链接（pitfall → process → sub-process）；`related_ids` 是知乎模型的语义关联（如 pitfall 关联某个 guideline）。两者共存，含义不同。

**`layer` / `applicable_phases`**：知乎模型原有字段。实现前需对照当前 KB entries 确认是否已使用；若已使用，生成 entries 时需同步写入。

### Lint 规则（import 完成后自动校验）

每次 import 写入 pending 后，自动运行以下完整性检查，任何失败写入 ImportReport.errors：

| 规则 | 检查内容 |
|---|---|
| `parent_id_consistency` | 所有 process entry 的 `parent_id` 对应的 entry 存在（同一批生成中） |
| `child_entry_ids_consistency` | 所有 `child_entry_ids` 中的 ID 存在（同一批生成中） |
| `tree_completeness` | DAG 中每个 `process` 节点都有对应的生成 entry；无孤立 entry |
| `no_cycle` | `child_entry_ids` 不形成循环引用 |
| `pitfall_has_root` | 至少存在一个无 `parent_id` 的 pitfall root；每棵子树都能到达至少一个 END |
| `source_file_consistent` | 同一批生成的所有 entries 的 `source_file` 和 `source_hash` 一致 |
| `evidence_fields_present` | `maturity`、`decay_status`、`next_decay_check`、`contributors` 全部存在 |

lint 失败不阻断 import，但 ImportReport 会标记，`holmes kb pending` 展示时显示 ⚠ 警告。

### ImportReport 展示格式

Agent 2 完成后在终端打印 ImportReport，让用户清楚知道发生了什么、下一步做什么：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Import 完成：hardware-init-failure.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

排查树：硬件初始化失败（2 棵独立子树）   ← multi_incident 场景时标注
  pitfall root: hardware-init-failure-root-001
  pitfall root: hardware-power-issue-root-001

✓ 生成成功  11 个 entries
  1 pitfall root + 10 process entries
  写入 _pending/<type>/<category>/

⚠ 格式校验失败  2 个 entries（未写入 pending）
  - N7（固件修复流程）：缺少 ## Steps section
  - N12（电源适配器更换）：section_heading 在原文找不到，内容为空
  重试：holmes import --retry-entry N7
       holmes import --retry-entry N12

⚠ Lint 警告  1 条（已写入 pending，但有问题）
  - tree_completeness：DAG 中 N9 节点无对应生成 entry

下一步：
  审核 pending entries：holmes kb pending
  approve 并发布：holmes kb approve hardware-init-failure-root-001
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**字段说明**：
- 多 root 时明确列出每棵树的 root ID
- 格式校验失败的 entry 不写入 pending，给出 retry 命令
- Lint 警告的 entry 已写入 pending 但标注问题
- 最后固定展示"下一步"操作，消除用户困惑

---

## 知乎知识库建模兼容性

本 spec 设计完全兼容知乎知识库建模标准（https://zhuanlan.zhihu.com/p/2032094280060252204）。以下说明新增元素与知乎模型的关系：

### Process sub-entry 作为 process 类型的扩展

知乎模型中 `process` 类型用于描述复杂操作流程。本 spec 的 process sub-entry 是知乎 `process` 类型的**使用实例**，不是新类型。区别在于：

- 知乎模型 process：顶层知识条目，独立成文
- 本 spec process sub-entry：隶属于某棵 pitfall 树，通过 `parent_id` 链接，**可见性受限**

这是知乎模型 process 类型在树形排查链路场景中的具体化，无需修改知乎模型定义。

### pitfall_structure 字段

`pitfall_structure: tree` 是本 spec 新增字段，用于向后兼容：
- 旧 pitfall entries（扁平结构，无子节点）：`pitfall_structure: flat`（或缺省，视为 flat）
- 新 pitfall entries（树形路由骨架）：`pitfall_structure: tree`

两种 pitfall 共存，agent 通过此字段选择不同的导航策略（flat → 直接读 Resolution；tree → 按 `child_entry_ids` 递归导航）。

### kb_status vs decay_status

两个字段语义正交，不替代知乎模型的 `decay_status`：

| 字段 | 来源 | 语义 | 驱动因素 |
|---|---|---|---|
| `kb_status` | 本 spec 新增 | import 工作流状态 | import/approve/deprecate 操作 |
| `decay_status` | 知乎模型 | 知识质量生命周期 | 证据积累、时间衰减机制 |

### child_entry_ids vs related_ids

两个字段语义不同，均来自知乎模型的不同维度：

| 字段 | 语义 | 导航方向 |
|---|---|---|
| `child_entry_ids` | 树结构子节点（结构关系） | 从父 pitfall/process 进入子 process |
| `related_ids` | 语义关联（内容相关性） | 跨类型跨树关联，如 pitfall 关联某 guideline |

---

## Step 4：写入 Pending 与 Approve 流程

### 写入 Pending

所有生成的 entries 写入 `_pending/<type>/<category>/`，等待 approve。结构与确认空间（`<type>/<category>/`）镜像对称：pitfall root 写入 `_pending/pitfall/<category>/`，process sub-entries 写入 `_pending/process/<category>/`。

```
_pending/
  pitfall/
    hardware/
      hardware-init-failure-002.md              ← pitfall 根节点（新 ID）
  process/
    hardware/
      hardware-init-firmware-repair-002.md      ← process
      hardware-init-memory-diag-002.md          ← process
      hardware-init-e01-repair-002.md           ← process（内存诊断的子节点）
      hardware-init-e02-repair-002.md           ← process（内存诊断的子节点）
      hardware-init-post-diag-002.md            ← process
```

每次 import 生成全新 ID 的 entries，与历史版本物理隔离。

### Approve 流程

```
holmes kb approve hardware-init-failure-002

Step 1：Pending 空间检查
  → 检测同 source_file 的其他 pending entries（来自其他用户或之前的 import）
  → 若存在：提示 reviewer 选择保留哪套 pending，取消其余

Step 2：Confirmed 空间检查
  → 检测同 source_file 的 active confirmed entries
  → 若存在：提示 deprecate 旧 entries

Step 3：原子执行
  → 取消选中的旧 pending entries
  → 将旧 confirmed entries 的 kb_status 改为 deprecated
  → 将本次 pending entries 移入 confirmed，kb_status 改为 active
  → 整棵树（pitfall + 所有关联 process entries）作为整体一次性处理

Step 4：更新 KB 目录索引
  → 更新 category index（该 pitfall 所属 category 的索引文件）
  → 若旧版本 entries 被 deprecated，从索引中移除旧 ID，写入新 ID
  → 确保 `holmes kb list` / `kb overview` 能立即反映新 entry
```

### Approve 时的提示示例

```
准备 approve: hardware-init-failure-002（及其 5 个关联 entries）

[pending 空间] 发现同文档的旧 pending entries：
  - hardware-init-failure-001（2月 import，未审核）及其 4 个关联 entries
  取消旧 pending？[Y/n] → Y

[confirmed 空间] 发现同文档的 active entries：
  - hardware-init-failure-000（1月 import，已 approve）及其 3 个关联 entries
  标记为 deprecated？[Y/n] → Y

执行：取消 5 个旧 pending + deprecate 4 个旧 confirmed + approve 6 个新 entries
确认？[Y/n] → Y
```

---

## Agent 运行时导航

```
用户：我的设备上电后无法初始化
  → Agent 搜索 KB → 找到 pitfall: 硬件初始化失败
  → 读 Resolution → "请观察电源指示灯颜色？"
  → 用户：红色闪烁
  → Agent 按 pitfall root 的 child_entry_ids 找到：固件修复流程
  → 读 process entry，按步骤引导用户
  → 某步骤执行后有子分支
  → Agent 检索子 process entry，继续引导
```

每次 agent 只处理一个 entry，复杂度可控。层次越深，每个 entry 越聚焦。

---

## 复杂度自评估

DAG 确认完成后计算：

| 指标 | 阈值 | 提示 |
|---|---|---|
| 总节点数 | > 20 | "链路较长，建议分阶段组织文档" |
| 最大嵌套深度 | > 4 | "嵌套较深，agent 导航可能受影响" |
| process 节点数 | > 10 | "将生成较多 entries，建议 review 关联关系" |

提示不阻断流程，仅作用户参考。

---

## 与现有 Pipeline 的关系

```
现有流程（保留，用于非 pitfall 类型）：
  Classifier → Reader → Extractor → Normalizer → Phase 3 → Pending

新流程（pitfall 类型）：
  Classifier → 去重检测 → Agent 1（DAG 提取）→ DAG 确认 → Agent 2（双源生成）→ Pending
```

两条流程共用：Classifier、Pending/Approve 机制、Git commit 机制、ImportReport 结构。

---

## 多人协作

所有 import 状态均在 git 追踪的 KB repo 中：
- `source_file`、`source_hash`、`kb_status` 在 entry frontmatter → 随 git pull/push 同步
- `_import-state/<hash>.dag.json` → 随 git 同步，任何人可断点续传
- Pending approve → 并发导入的最终安全网，两人并发导入同一文档时，approve 时统一处理

**不同文档描述同一问题（语义重复）**：不在 import pipeline 中自动处理，由 git 仓库管理员通过 git 协作机制介入，手动 deprecate 冗余 entries。

---

## --no-interactive 模式

```bash
holmes import doc.md --no-interactive   # 显式跳过确认
holmes import --dir ./docs/             # --dir 隐含 --no-interactive
```

- Agent 1 完成后自动选择 [2]（跳过编辑，直接进入 Step 2.5）
- Step 2.5 仍然运行（parse + validate），但最终确认"确认并开始生成？"自动接受
- import report 记录 "DAG 未经用户确认"
- 生成的 entries 写入 pending，仍需人工 approve

`--dir` 批量导入时无法逐文档等待用户交互，因此自动隐含 `--no-interactive`。所有文档一次性跑完，全部进入 pending 空间，由 reviewer 事后批量 approve。

---

## CLI 兼容性

本次改造对所有现有 CLI 命令**向后兼容**，无破坏性改动，无新增命令。

| 命令 | 兼容性 | 说明 |
|---|---|---|
| `holmes config set username <name>` | 新增 | 设置 import 时写入 `contributors[].user` 的用户名；未配置时 import 命令报错提示 |
| `holmes import <file>` | 兼容 | pitfall 类型走两 Agent 流程；其他类型流程不变 |
| `holmes import --dir <dir>` | 兼容 | 自动隐含 `--no-interactive`，全部入 pending |
| `holmes import --dry-run` | 兼容 | 流程不变，不写入任何 entry |
| `holmes import --type pitfall` | 新增 | 强制走 pitfall DAG pipeline，跳过 Classifier 判断 |
| `holmes import --force` | 兼容 | 跳过去重检测，强制重新生成 |
| `holmes import --resume` | 新增 | 从已有 .dag.md 继续（解析规范化 → 交叉验证 → Agent 2） |
| `holmes import --resume --skip-edit` | 新增 | 跳过用户编辑，直接进解析规范化 |
| `holmes import --retry-entry <id>` | 新增 | 重新生成单个格式校验失败的 entry |
| `holmes kb pending` | 兼容 | pitfall 类型按树形分组展示（root + 关联 process entries） |
| `holmes kb approve <id>` | 兼容 | pitfall 类型新增 pending/confirmed 空间冲突提示 |
| `holmes kb delete <id>` | 新增 | 删除单个非根 entry 仅删自身；pitfall 根节点默认级联整棵树（含所有 process sub-entries）一起移入 `_trash/` |
| `holmes kb list` / `holmes kb search` | 兼容 | 默认只显示 active；`--all` flag 可包含 deprecated |
| `holmes kb list --all-types` | 新增 | 显示包含 process sub-entries 在内的全部 entry 类型，用于管理员 review |
| `holmes kb show <id>` | 兼容 | 展示 `kb_status`、`parent_id`、`child_entry_ids` 字段；process sub-entry 显示 `[sub-entry of: <parent_id>]` 标签 |
| `holmes kb drafts` | 新增 | 列出 `_drafts/` 下待 import 的草稿文件，含保存时间和来源（mcp.draft） |
| `holmes log list` | 新增 | 列出所有 trace 的最后事件摘要（import / draft / mcp session） |
| `holmes log show <trace_id>` | 新增 | 展示某条 trace 的完整 span 树；支持 `--json`、`--since <date>` |

**`holmes kb delete` 行为**：
- 所有 entry（pending 或 confirmed）→ 移入 `_trash/` 目录，不硬删除
- pitfall 根节点 → 默认级联整棵树（根节点 + 全部 process sub-entries）一起移入 `_trash/`；加 `--no-cascade` 可只删根节点本身
- 非根 entry（单个 process sub-entry）→ 只移自身，不影响其他节点
- `_trash/` 随 git 追踪，可随时恢复；定期清理由管理员手动执行

**无需新增 `holmes kb deprecate` 命令**：旧版本 entries 在 approve 流程中自动 deprecate；不同文档描述同一问题的语义重复，由 git 仓库管理员通过不 merge 来处理。

---

## 多人协作流程的普适性

**pending → approve → git PR 的协作模型适用于所有知识类型**，不只是 pitfall。

```
所有类型统一流程：
  holmes import <doc>   → 生成 pending entries（各类型走各自的生成 pipeline）
  holmes kb approve     → 移入 confirmed，处理冲突
  git push + PR         → 管理员 review → merge = 正式生效
  holmes kb delete      → 删除错误或过时的条目
```

差异只在生成阶段：
- **pitfall 类型**：DAG 子 Agent + 人机交互 + 双源生成（本 spec 重点）
- **其他类型**：现有 Reader → Extractor pipeline，无 DAG 步骤

pending/approve/delete/git PR 这一套对所有类型完全一致。

---

## KB Entry 可读性规范

**设计原则**：KB entry 是一份独立的文档，用户无需 CLI 也能理解其内容和关联结构。当 import pipeline 产生偏差时，用户可以直接编辑 `.md` 文件作为最终兜底。为此，每个 entry 必须满足以下可读性要求。

### 1. 标题规范

entry 文件名和 `title` 字段必须是自解释的人类可读标题，不得用 ID 或编码作为标题。

**要求**：
- `title` 字段：描述具体问题或流程，不超过 40 个字
- 文件名（slug）：与 title 对应的英文 kebab-case，例如 `gpu-init-failure-firmware-fix.md`
- pitfall entry：标题格式建议 `<症状描述> — <诊断方向>`，例如 `GPU 初始化失败 — 固件修复流程`
- process entry：标题格式建议 `<操作目标> 排查步骤`，例如 `驱动版本不匹配排查步骤`

**反例**：
```yaml
title: entry_abc123          # ❌ 无法理解
title: 硬件问题               # ❌ 过于宽泛
```

**正例**：
```yaml
title: GPU 初始化失败 — 固件修复流程   # ✅ 自解释
title: PCIe 带宽不足排查步骤          # ✅ 清晰
```

### 2. 必填元信息字段

所有 entry 的 frontmatter 必须包含以下元信息字段，以便用户无需 CLI 也能了解条目来源、时效和责任人：

```yaml
---
title: GPU 初始化失败 — 固件修复流程
type: pitfall
category: hardware
kb_status: pending

# 人类可读描述（1-2 句话，说明这个条目是关于什么的）
description: >
  GPU 在系统启动时报 init failure，通常由固件版本不兼容或 PCIe 配置错误引起。
  本条目覆盖固件升级和配置重置两条修复路径。

# 来源追溯
source_file: docs/hardware/gpu-troubleshooting.md   # 相对于 KB root 的路径
source_hash: sha256:a3f1...
import_trace_id: gpu-troubleshooting

# 贡献者（user 取自 config.username；人工编辑后可追加 verifier）
contributors:
  - {user: "wangzhi", role: "initiator", date: "2026-06-23"}
---
```

**字段说明**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `description` | string | 1-2 句话的条目摘要，必填，自解释 |
| `source_file` | string | 相对于 KB root 的源文档路径（如 `docs/hardware/gpu-troubleshooting.md`），用于更新检测 |
| `source_hash` | string | 原始文档 sha256 前缀，用于检测内容变更 |
| `import_trace_id` | string | 源文档文件名 stem，用于日志关联 |
| `contributors` | list | 贡献者列表；pipeline 写入 `{user: config.username, role: "initiator", date: today}`；人工编辑后可追加 verifier |

### 3. 关联结构注释

`child_entry_ids` 和 `parent_id` 字段必须附带人类可读的标题注释，使用户无需 CLI 即可理解树形结构。

**格式**：
```yaml
# pitfall 根节点示例
parent_id: null
child_entry_ids:
  - gpu-init-failure-driver-check       # 驱动版本检查流程
  - gpu-init-failure-firmware-update    # 固件升级流程
  - gpu-init-failure-pcie-reset         # PCIe 配置重置流程

# process sub-entry 示例
parent_id: gpu-init-failure-firmware-fix  # GPU 初始化失败 — 固件修复流程
child_entry_ids: []
```

**注释格式规则**：
- `child_entry_ids` 每项：`- <entry-id>  # <entry title>`
- `parent_id`：`parent_id: <entry-id>  # <parent title>`（若为 null 则不加注释）
- import pipeline（Agent 2）负责在写入时自动添加注释
- 用户手动编辑时，更新注释是 best-effort（pipeline 不强制校验注释准确性）

### 4. 目录结构与文件共置

相关 entry 应放在同一目录下，使用户浏览文件系统时能直观看到关联关系。

**目录结构**：
```
kb/
  pitfall/
    hardware/
      gpu-init-failure-firmware-fix.md     # pitfall 根节点
    network/
      dns-resolution-failure.md
      ...
  process/
    hardware/
      gpu-init-failure-driver-check.md     # process sub-entry
      gpu-init-failure-firmware-update.md  # process sub-entry
      gpu-init-failure-pcie-reset.md       # process sub-entry
  _pending/
    pitfall/
      hardware/
        gpu-overheat-diagnosis.md          # 待 approve（pitfall 根节点）
    process/
      hardware/
        gpu-overheat-driver-reset.md       # 待 approve（process 子节点）
  _trash/
    pitfall/
      hardware/
        old-gpu-issue.md                   # 已删除，可恢复
  _drafts/
    redis-oom-2026-06-24.md               # MCP kb_draft 保存，待 holmes import
    _imported/
      nginx-timeout-2026-06-20.md         # 已 import 的草稿，归档保留
  _import-state/
    <hash>.dag.md                          # Agent 1 输出，用户可编辑
    <hash>.dag.json                        # 程序内部规范格式
    <hash>.session.json                    # crash recovery 快照
```

**规则**：
- pitfall root entry 存放在 `pitfall/<category>/`；process sub-entries 存放在 `process/<category>/`；同一棵树通过相同的 `category` 值保持逻辑关联
- pending entries 存放在 `_pending/<type>/<category>/`（镜像确认空间结构），approve 后移入 `<type>/<category>/`
- 已删除的 entries 移入 `_trash/<type>/<category>/`（不硬删除，保留 type 层与原空间一致），保留 git 可追溯性
- MCP `kb_draft` 保存的草稿存放在 `_drafts/`，`holmes import` 处理后移入 `_drafts/_imported/`
- `_pending/`、`_trash/`、`_drafts/` 目录各有 `README.md` 说明其用途

### 5. import pipeline 的可读性职责

Agent 2 在生成 entry 时必须：
1. 根据 DAG 节点的 `description` 字段生成有意义的 `title` 和文件名 slug
2. 将 DAG 节点的 `description` 作为 entry 的 `description` 字段写入 frontmatter（不得为空）
3. 写入 `contributors: [{user: config.username, role: "initiator", date: today}]`
4. 写入 `import_trace_id`（取源文档文件名 stem）
5. 写入 `child_entry_ids` 和 `parent_id` 时附带标题注释（需先 `read_entry` 获取子节点已生成的 title）

---

## 可观测性与日志

### 设计原则

Holmes 的可观测对象是**文档**：一份源文档从导入到上线的完整生命周期是一条完整的追踪链路。所有 CLI 操作（import、approve、delete、re-import）都归属于某份源文档，因此以文档为粒度组织日志和 trace_id。

### TraceId

**格式**：取源文档文件名 stem，例如：

```
gpu-troubleshooting.md  →  trace_id: gpu-troubleshooting
```

不同路径下存在同名文件时，追加 source_hash 前缀消歧：`gpu-troubleshooting-a3f1`。

**存储**：
- 首次 import 时生成，写入 `_import-state/<hash>.dag.json`（crash recovery 状态文件）
- 同时写入每个生成 entry 的 frontmatter：`import_trace_id: gpu-troubleshooting`
- `holmes kb approve/delete <entry-id>` 时从 entry 的 `source_file` 字段派生 trace_id，不需要用户手动传入

**`--resume` 行为**：从状态文件读取原始 trace_id，继续在同一 trace 下追加事件（不生成新 trace_id）。

### Span 结构

每次 import 的事件按以下层级记录：

```
trace: gpu-troubleshooting
  span: agent1.read          Phase 1 通读
  span: agent1.draft         Phase 2 初稿（首次 write_dag）
  span: agent1.review[1]     第 1 轮 review
  span: agent1.review[N]     第 N 轮 review（直到 output_dag）
  span: step25.parse         DAG 解析规范化
  span: step25.validate      交叉验证
  span: agent2.node[<id>]    生成单个 process entry（每节点一个 span）
  span: agent2.root          生成 pitfall root entry
  span: lint                 import 完成后 lint 校验
  span: kb.approve           approve 操作（每次调用一个 span）
  span: kb.delete            delete 操作
```

每个 span 记录：`started_at`、`duration_ms`、`llm_calls`（该 span 内 LLM 调用次数）、`tokens`（输入+输出）、`result`（ok / error / warning）、`detail`（可选补充信息）。

### 日志格式与存储

日志写入 `~/.holmes/logs/`，两种并行格式：

```
~/.holmes/logs/
  2026-06-23.log      # 人类可读，带 trace_id 前缀，适合直接 cat/grep
  2026-06-23.jsonl    # JSON Lines，适合工具消费（jq、grep 过滤）
```

**JSON Lines 格式**（每行一个事件）：

```json
{"ts":"2026-06-23T14:30:00Z","trace":"gpu-troubleshooting","span":"agent1.draft","level":"INFO","msg":"write_dag","nodes":8,"duration_ms":42100}
{"ts":"2026-06-23T14:35:00Z","trace":"gpu-troubleshooting","span":"agent2.node[N3]","level":"INFO","msg":"write_entry ok","entry_id":"gpu-init-firmware-001","tokens":1240,"duration_ms":8300}
{"ts":"2026-06-23T14:36:00Z","trace":"gpu-troubleshooting","span":"lint","level":"WARN","msg":"content_source: description_match_failed","node_id":"N5"}
{"ts":"2026-06-23T15:10:00Z","trace":"gpu-troubleshooting","span":"kb.approve","level":"INFO","msg":"approved","entry_id":"gpu-init-failure-root-001","user":"wangzhi"}
```

**日志滚动**：按天滚动，保留 30 天，超期自动删除。

### CLI 查询接口

```bash
holmes log list                              # 列出所有 trace 的最后事件摘要（import / draft / mcp session）
holmes log show <trace_id>                   # 展示某条 trace 的完整 span 树（人类可读）
holmes log show <trace_id> --json            # 原始 JSON Lines 输出
holmes log show <trace_id> --since <date>    # 只显示指定日期之后的事件
holmes import <file> --verbose               # 实时将 span 级日志打印到 terminal（默认只打印 INFO 级摘要）
```

`holmes log show` 示例输出：

```
trace: gpu-troubleshooting  (gpu-troubleshooting.md)

2026-06-23 14:30:00  [import #1]
  agent1.read      42s   turns=4
  agent1.draft     38s   nodes=8
  agent1.review[1] 21s   corrections=3
  agent1.review[2] 18s   corrections=1  ← output_dag called
  step25.parse     2s    ok
  step25.validate  3s    ok
  agent2.node[N1]  8s    entry=gpu-init-driver-check-001
  agent2.node[N2]  9s    entry=gpu-init-firmware-001
  agent2.node[N3]  11s   entry=gpu-init-pcie-reset-001   WARN: description_match_failed
  agent2.root      10s   entry=gpu-init-failure-root-001
  lint             1s    ok  created=4 warnings=1

2026-06-23 15:10:00  [kb.approve]
  kb.approve       0s    entry=gpu-init-failure-root-001  user=wangzhi
  kb.approve       0s    entry=gpu-init-firmware-001      user=wangzhi

2026-07-01 09:00:00  [import #2  re-import]
  agent1.read      35s   turns=3
  ...
```

### 未配置 username 时的行为

import 命令在执行任何操作前检查 `config.username`。若未配置：
1. 写一条 `level: ERROR, msg: "config.username not set, run: holmes config set username <name>"` 的日志（trace_id 照常生成）
2. 终止 import 并打印同样的错误提示

---

## MCP 接口

### 定位

MCP 是 agent 访问知识库的**读通道**。Holmes 要求知识质量由人工审阅保障，因此知识的结构化、审阅、approve 全在 CLI 侧完成，MCP 内部**不运行任何 LLM**。

```
agent (via MCP)
  ├── 读知识库      → kb_overview / kb_list / kb_search / kb_read
  ├── 记录证据      → kb_confirm（写使用记录，不生成知识）
  └── 保存草稿      → kb_draft（捕获现场文档，等待人工 import）

人工 CLI
  └── holmes import _drafts/<file>   → DAG pipeline → approve → 知识上线
```

### 工具清单

| 工具 | 类型 | 说明 |
|---|---|---|
| `kb_overview` | 读 | KB 结构概览：各类型数量、分类、高频 tag |
| `kb_list` | 读 | 按 type/category 浏览 entry 列表（默认只返回 active，不含 sub-entries） |
| `kb_search` | 读 | 关键词搜索（默认只返回 active pitfall roots） |
| `kb_read` | 读 | 按 ID 读取 entry 完整内容；pitfall entry 额外返回 `children` 树导航字段 |
| `kb_confirm` | 写（证据） | 记录"此 entry 帮助解决了当前问题"；写证据记录，触发 maturity 升级 |
| `kb_draft` | 写（草稿） | 将现场文档保存到 `_drafts/`；不运行 LLM，不生成结构化 entry |

**`kb_submit` 已删除**：原有的 MCP 内联 import pipeline 与"质量由人工保障"原则冲突，改为 `kb_draft` + 人工 `holmes import`。

### kb_read 树形导航

读取有 `child_entry_ids` 的 pitfall entry 时，返回结构化 `children` 字段，agent 无需解析 frontmatter：

```json
{
  "id": "gpu-init-failure-root-001",
  "type": "pitfall",
  "content": "...",
  "children": [
    {"id": "gpu-init-driver-check-001",    "title": "驱动版本检查流程"},
    {"id": "gpu-init-firmware-update-001", "title": "固件升级流程"},
    {"id": "gpu-init-pcie-reset-001",      "title": "PCIe 配置重置流程"}
  ]
}
```

agent 沿 `children` 递归调用 `kb_read` 即可完成树形导航，不需要理解 entry ID 格式或 frontmatter 结构。

### kb_draft 草稿保存

agent 在排查结束后调用 `kb_draft`，将现场信息整理成自然语言文档保存：

```python
kb_draft(
    content="...",    # 包含症状、根因、解决过程的完整描述
    title="redis-oom-2026-06-23",  # 可选，默认用时间戳生成文件名
)
```

- 调用前检查 `config.username`，未配置则返回错误：`"config.username not set, run: holmes config set username <name>"`
- 文件保存到 `_drafts/<title>.md`，frontmatter 写入 `author: config.username` 和保存时间戳，不做任何 LLM 处理
- 写一条日志事件：`mcp.draft`，trace_id = 文件名
- 返回给 agent：
  ```
  草稿已保存：_drafts/redis-oom-2026-06-23.md
  运行以下命令正式导入：
    holmes import _drafts/redis-oom-2026-06-23.md
  ```

### Draft 生命周期

```
kb_draft 调用
  → _drafts/<name>.md 创建
  → 日志记录 mcp.draft 事件
  → holmes kb drafts 可见

holmes import _drafts/<name>.md
  → DAG pipeline（Agent 1 + 用户确认 + Agent 2）
  → entries 写入 pending
  → _drafts/<name>.md 移入 _drafts/_imported/（不硬删除）
  → 日志记录 draft.imported，trace_id 连续
```

**`holmes kb drafts` 命令**：列出所有待 import 的草稿：

```
_drafts/ (2 pending)
  redis-oom-2026-06-23.md       8 天前  [via mcp.draft]
  nginx-timeout-2026-06-20.md  11 天前  [via mcp.draft]

运行 holmes import _drafts/<file> 正式导入。
```

### MCP 日志记录

MCP 所有工具调用均写入日志，trace_id 分两类：

**读操作 / kb_confirm — session trace**

`kb_overview` 生成的 `session_id` 作为 trace_id（前缀 `session-`），同一 agent 会话的所有操作归在一条 trace 下：

```json
{"ts":"2026-06-24T10:00:00Z","trace":"session-a3f1","span":"mcp.kb_overview","level":"INFO","duration_ms":30}
{"ts":"2026-06-24T10:00:05Z","trace":"session-a3f1","span":"mcp.kb_search","level":"INFO","query":"redis oom","results":3,"duration_ms":45}
{"ts":"2026-06-24T10:00:12Z","trace":"session-a3f1","span":"mcp.kb_read","level":"INFO","entry_id":"gpu-init-failure-root-001","duration_ms":12}
{"ts":"2026-06-24T10:00:18Z","trace":"session-a3f1","span":"mcp.kb_read","level":"INFO","entry_id":"gpu-init-firmware-update-001","duration_ms":10}
{"ts":"2026-06-24T10:05:00Z","trace":"session-a3f1","span":"mcp.kb_confirm","level":"INFO","entry_id":"gpu-init-firmware-update-001","promoted":false}
```

**kb_draft — 文档 trace**

draft 文件名作为 trace_id，与后续 `holmes import` 共享同一 trace，形成完整闭环：

```json
{"ts":"2026-06-24T10:06:00Z","trace":"redis-oom-2026-06-24","span":"mcp.draft","level":"INFO","file":"_drafts/redis-oom-2026-06-24.md","session":"session-a3f1"}
```

`session` 字段记录草稿来自哪个 MCP 会话，便于回溯。

**`holmes log list` 统一展示三类 trace：**

```
gpu-troubleshooting        import   2026-06-23  created=7  approved
redis-oom-2026-06-24       draft    2026-06-24  pending import
session-a3f1               mcp      2026-06-24  read=4 confirmed=1 draft=1
```

**`holmes log show session-a3f1`** 示例：

```
trace: session-a3f1  (mcp session)

2026-06-24 10:00:00
  mcp.kb_overview   0s
  mcp.kb_search     0s   query="redis oom"  results=3
  mcp.kb_read       0s   entry=gpu-init-failure-root-001
  mcp.kb_read       0s   entry=gpu-init-firmware-update-001
  mcp.kb_confirm    0s   entry=gpu-init-firmware-update-001  promoted=false
  mcp.draft         0s   → redis-oom-2026-06-24  (run: holmes import _drafts/redis-oom-2026-06-24.md)
```

### Store 层适配（对 MCP 透明）

以下改动在 `store.py` 统一实现，MCP 工具签名不变，旧格式 entry（`PT-DB-001`）与新格式（`gpu-init-failure-root-001`）自动兼容：

| 改动 | 实现位置 | 说明 |
|---|---|---|
| ID 格式无关化 | `store.find_entry(id)` | 文件系统查找替代正则匹配，任何 ID 格式自动兼容 |
| `kb_status` 过滤 | `list_entries(kb_status="active")` | 默认只返回 active entry，过滤 pending/deprecated |
| sub-entry 可见性 | `list_entries(exclude_sub_entries=True)` | 默认过滤有 `parent_id` 的 process sub-entries |
| 树导航 hint | `read_entry()` 返回值 | 有 `child_entry_ids` 时附加结构化 `children` 字段 |
| contributor 来源 | `HolmesConfig.username` | 使用 `config.username`，未配置时报错 |

---

## 实现模块

本 spec 按以下模块分步实现，每个模块独立 PR，可单独测试。

### 模块适用范围总览

| 模块 | 适用范围 | 说明 |
|---|---|---|
| M1 | **全局** | 所有 entry 类型共用的字段和过滤机制 |
| M2 | **全局** | 所有类型的 import 去重逻辑 |
| M3 | **pitfall 专用** | Classifier 路由 + `--type pitfall` flag |
| M4 | **pitfall 专用** | DAG 提取子 Agent，只用于 pitfall |
| M5 | **pitfall 专用** | 双源知识生成，只用于 pitfall |
| M6a | **全局** | import 时 source_file 冲突检测 + 基础 approve 流程 |
| M6b | **pitfall 专用** | 树级联 approve/deprecate（整棵树原子操作） |
| M7 | **全局** | kb delete 适用于所有 entry 类型 |
| M8 | **全局** | 可观测性与日志：trace_id、span 记录、日志滚动、holmes log 命令 |
| M9 | **全局** | MCP 接口：store 层适配、kb_draft 工具、holmes kb drafts 命令 |

**全局模块**（M1、M2、M6a、M7、M8、M9）不依赖 pitfall pipeline，实现后对所有类型立即生效。
**pitfall 专用模块**（M3、M4、M5、M6b）在全局模块完成后依次实现。

---

### M1 — 基础字段与过滤 `[全局]`

**范围**：
- entry frontmatter 新增全局字段：`kb_status`、`source_file`、`source_hash`、`description`、`import_trace_id`
- 旧 entry 缺 `kb_status` 字段时默认视为 `active`（向后兼容）
- `holmes kb list` / `holmes kb search` 默认只返回 `kb_status: active` 的 entries，加 `--all` flag 包含 deprecated
- `holmes kb list` 默认不显示 `type: process` 且有 `parent_id` 的 sub-entries（见可见性规则）
- store 层适配（对 MCP 透明）：ID 格式无关化、`kb_status` 过滤、sub-entry 可见性过滤、`children` 树导航字段

**依赖**：无（其他模块都依赖它）

---

### M2 — Step 0：去重与更新检测 `[全局]`

**范围**：
- import 时计算 `source_hash = hash(文档内容)`
- 同时搜索 pending + confirmed 空间
  - 找到匹配 `source_hash` → 完全重复，跳过
  - 找到匹配 `source_file` 但 hash 不同 → 文档有更新，走更新流程
  - 未找到 → 全新文档
- `--force` flag 跳过此检测

**依赖**：M1

---

### M3 — `--type` flag 与 Classifier 路由 `[pitfall 专用]`

**范围**：
- `holmes import --type pitfall` 强制走 pitfall DAG pipeline，跳过 Classifier
- Classifier 识别到 `single_incident` / `multi_incident` 时也路由到新 pipeline
- 其他类型继续走现有 Reader → Extractor pipeline

**依赖**：无（独立小模块）

---

### M4 — Agent 1：DAG 提取 `[pitfall 专用]`

**范围**：
- 领域专属工具实现：`write_dag(content)`、`read_dag()`、`output_dag()`
- Harness 实现：
  - 工具白名单（只允许 5 个工具：Read / Grep / write_dag / read_dag / output_dag）
  - maxTurns = 300（适用所有文档类型，无需区分）
  - `output_dag` 校验：根节点存在、无悬空边、无环、process 节点有 section_heading 或描述
  - Crash Recovery：每 20 turns 将 messages 序列化写入 `_import-state/<hash>.session.json`；`--resume` 时从快照恢复继续
- System prompt：三阶段说明（通读 → 初稿 → review）、工具说明、禁止项、终止 checklist
- 全自动，不与用户交互；`--skip-edit` / `--no-interactive` 下完成后直接进 Step 2.5
- 输出：`_import-state/<hash>.dag.md`（渐进式三 section 格式）

**适用范围**：所有文档类型（有无标题结构均可），不需要区分模式

**依赖**：M3

**实现参考**：`/home/wangzhi/project/claude-code` — 工具接口（buildTool）、agent loop（query.ts）、sub-agent 上下文隔离（runAgent.ts）、prompt 写法（prompt.ts）

---

### M5 — Agent 2：双源知识生成 `[pitfall 专用]`

**范围**：
- Step 2.5 实现：LLM 解析规范化 + 交叉验证合并为一屏（见 Step 2.5）
- Agent 2 实现（独立 context，与 Agent 1 完全隔离）：
  - 工具：`read_dag` / `write_entry`（内置格式校验）/ `read_entry` / `finalize`
  - Entry ID 预生成（遍历 DAG 节点，分配所有 ID）
  - 四阶段 loop：Study → 顺序生成 process entries（叶节点→根方向）→ 最后写 pitfall root → Consistency review
  - 规模分层：≤20 节点全局视野；>20 节点分批子 agent + 标题摘要表
  - section_heading=null fallback：Grep description 定位，失败则标注 `content_source: description_match_failed` 进 warnings
  - 证据字段自动初始化（maturity/decay_status/next_decay_check/contributors/tags）
  - 单节点 retry：`holmes import --retry-entry <node-id>`
  - 所有 entries 写入 `_pending/<type>/<category>/`，finalize 触发 lint + 生成 ImportReport

**依赖**：M4

---

### M6a — Pending/Approve 基础流程 `[全局]`

**范围**：
- Import 时新 pending 写入前，检测同 `source_file` 的旧 pending entries → 提示是否取消（适用所有类型）
- `holmes kb approve <id>`：
  - 检测同 `source_file` 的旧 pending entries → 提示清理
  - 检测同 `source_file` 的 active confirmed entries → 提示 deprecate 旧版本
  - 单个 entry 的原子操作（移入 confirmed、更新 kb_status）
  - approve 后更新 category index

**依赖**：M1、M2

---

### M6b — Pending/Approve 树级联 `[pitfall 专用]`

**范围**：
- `holmes kb approve <pitfall-root-id>`：级联处理整棵树（pitfall root + 所有关联 process entries）
- 整棵树作为整体一次性 approve，不允许部分 approve
- 级联检测：旧 pending 树 / 旧 confirmed 树同步清理
- `holmes kb pending` 按树形分组展示（root 为标题，sub-entries 缩进）

**依赖**：M6a、M5

---

### M7 — `holmes kb delete`（垃圾箱） `[全局]`

**范围**：
- `holmes kb delete <id>`：将 entry 文件 mv 到 `_trash/<type>/<category>/` 目录，不硬删除（适用所有类型）
- pitfall 根节点默认级联整棵树移入 `_trash/`；加 `--no-cascade` 只删根节点自身
- 非根 entry 只移自身，不影响其他节点
- `_trash/` git 追踪，误删可通过 git 恢复

**依赖**：无（独立模块）

---

### M8 — 可观测性与日志 `[全局]`

**范围**：
- 日志写入 `~/.holmes/logs/<date>.log` + `<date>.jsonl`，按天滚动，保留 30 天
- 所有 CLI 操作（import、approve、delete）写入 span 事件，trace_id = 源文档文件名 stem
- `holmes log list`：列出所有 trace 最后事件摘要（import / draft / mcp session）
- `holmes log show <trace_id>`：展示完整 span 树；支持 `--json`、`--since <date>`
- `holmes import --verbose`：实时打印 span 级日志到 terminal
- `config.username` 未配置时 import 报错并写入 ERROR 日志

**依赖**：M1

---

### M9 — MCP 接口 `[全局]`

**范围**：
- **删除 `kb_submit` 工具**（MCP server.py + tools.py）：原有的 MCP 内联 import pipeline 与"质量由人工保障"原则冲突
- **新增 `kb_draft` 工具**：检查 `config.username` → 保存到 `_drafts/<title>.md`（含 `author` frontmatter）→ 写 `mcp.draft` 日志事件 → 返回 import 提示
- `holmes kb drafts`：列出 `_drafts/` 下待 import 的草稿，含保存时间和来源
- `holmes import` 处理 `_drafts/<file>` 后自动将其移入 `_drafts/_imported/`
- store 层适配（详见 MCP 章节）：ID 格式无关化、`kb_status` 过滤、sub-entry 可见性、`children` 树导航字段
- MCP 读操作日志（session trace）：`kb_overview` / `kb_search` / `kb_read` / `kb_confirm` 写入 `session-<id>` trace

**依赖**：M1、M8

---

## 施工计划

### 阶段总览

```
阶段一（全局地基）       阶段二（全局生命周期）    阶段三（pitfall pipeline）  阶段四（pitfall 生命周期）
──────────────────       ──────────────────────    ──────────────────────────  ──────────────────────────
M1  基础字段与过滤   →   M2  去重与更新检测    →   M3  Classifier 路由      →   M6b  树级联 approve
M7  kb delete 垃圾箱     M6a 基础 approve 流程      M4  Agent 1 DAG 提取
M8  可观测性与日志                                  M5  Agent 2 双源生成
M9  MCP 接口
```

- 阶段一、二完成后，所有 entry 类型立即获得去重、approve、delete、日志能力
- 阶段三、四专注 pitfall pipeline，对其他类型无影响
- 阶段一内 M7/M8/M9 互相独立，可与 M1 并行

### 实现约定

每个模块按以下 speckit 流程实现，在模块对应子目录下执行：

```
specs/037-dag-import-pipeline/<模块>/   ← 工作目录
  spec.md     ← /speckit-specify 生成
  plan.md     ← /speckit-plan 生成
  tasks.md    ← /speckit-tasks 生成
```

执行顺序：`/speckit-specify → /speckit-plan → /speckit-tasks → /speckit-implement → /speckit-analyze`

---

### 阶段一 — 全局地基

#### M1 — 基础字段与过滤

**目标**：让所有现有 entry 和后续新 entry 支持新 frontmatter 字段；list/search 按 `kb_status` 过滤；隐藏 process sub-entries。

**spec 引用章节**：
- `§ Entry 状态字段`（kb_status 三态定义）
- `§ Frontmatter 新增字段`（字段表格）
- `§ Process Sub-entry 可见性规则`
- `§ Store 层适配（对 MCP 透明）`
- `§ KB Entry 可读性规范 > 2. 必填元信息字段`

**涉及文件**：
```
kb/holmes/kb/schema.py          ← 新增字段 Literal / TypedDict
kb/holmes/kb/store.py           ← list_entries 过滤逻辑；find_entry ID 无关化；read_entry 附加 children
kb/holmes/kb/search.py          ← kb_status=active 过滤
kb/holmes/cli.py                ← kb list/search 新增 --all flag；holmes config set username
```

**验收条件**：
- `holmes kb list` 不显示 `kb_status: pending/deprecated` 和有 `parent_id` 的 process 条目
- `holmes kb list --all` 包含 deprecated；`holmes kb list --all-types` 包含 sub-entries
- `holmes config set username <name>` 写入 `~/.holmes/config.json`
- 旧 entry 无 `kb_status` 字段时默认视为 active（向后兼容）
- 新增字段均有单元测试覆盖

---

#### M7 — `holmes kb delete`（垃圾箱）

**目标**：所有类型 entry 软删除到 `_trash/`；pitfall 根节点默认级联整棵树。

**spec 引用章节**：
- `§ CLI 兼容性` — `holmes kb delete` 行为描述
- `§ CLI 兼容性 > holmes kb delete 行为`（四条规则）

**涉及文件**：
```
kb/holmes/cli.py                ← kb delete 子命令，--no-cascade flag
kb/holmes/kb/store.py           ← move_to_trash(entry_id, cascade=True)
```

**验收条件**：
- 非根 entry：只移自身到 `_trash/<type>/<category>/`，不影响兄弟节点
- pitfall 根节点：默认级联移整棵树；`--no-cascade` 只移根节点
- `_trash/` 内文件保留原始内容，git 可 revert 恢复
- pending 和 confirmed entry 均可删除

---

#### M8 — 可观测性与日志

**目标**：所有 CLI 操作写入结构化日志；trace_id 贯穿单个文档生命周期；`holmes log` 查询接口。

**spec 引用章节**：
- `§ 可观测性与日志`（全节）

**涉及文件**：
```
kb/holmes/kb/logger.py          ← 新建；Logger 类：write_span(), rotate(), 双格式输出
kb/holmes/cli.py                ← holmes log list / holmes log show 子命令
kb/holmes/config.py             ← HolmesConfig 新增 username 字段
```

**验收条件**：
- import/approve/delete 操作均写入 `~/.holmes/logs/<date>.log` 和 `.jsonl`
- 每条记录包含 `ts / trace / span / level / msg` 字段
- `holmes log list` 打印所有 trace 最后事件摘要
- `holmes log show <trace_id>` 打印完整 span 树，支持 `--json / --since`
- 日志按天滚动，30 天后自动删除旧文件

---

#### M9 — MCP 接口

**目标**：删除 `kb_submit`；新增 `kb_draft`；store 层适配使 MCP 工具无感知新数据模型；MCP 操作写日志。

**spec 引用章节**：
- `§ MCP 接口`（全节）

**涉及文件**：
```
kb/holmes/mcp/server.py         ← 删除 kb_submit 注册；新增 kb_draft 注册
kb/holmes/mcp/tools.py          ← 删除 handle_kb_submit；新增 handle_kb_draft
kb/holmes/kb/store.py           ← 依赖 M1 store 层适配（已完成）
kb/holmes/cli.py                ← holmes kb drafts 子命令
```

**验收条件**：
- `kb_submit` 工具从 MCP 服务中消失，调用返回 not-found 或 method-not-allowed
- `kb_draft(content, title)` 保存文件到 `_drafts/<title>.md`，frontmatter 含 `author` 和时间戳
- `kb_draft` 未配置 `config.username` 时返回明确错误
- `holmes kb drafts` 列出 `_drafts/` 下待 import 的草稿（不含 `_imported/` 子目录）
- `holmes import _drafts/<file>` 完成后将草稿移入 `_drafts/_imported/`
- MCP 读操作（overview/list/search/read/confirm）和 kb_draft 均写入日志（依赖 M8）

---

### 阶段二 — 全局生命周期

#### M2 — Step 0：去重与更新检测

**目标**：import 时计算 source_hash，检测完全重复和文档更新两种情况。

**spec 引用章节**：
- `§ Step 0：去重与更新检测`（全节，含三层并存场景）

**涉及文件**：
```
kb/holmes/kb/importer.py        ← import 入口新增 Step 0 逻辑
kb/holmes/kb/store.py           ← find_entries_by_source_file(); find_entries_by_source_hash()
kb/holmes/cli.py                ← holmes import --force flag
```

**验收条件**：
- 完全相同文档（hash 匹配）：打印"已存在，跳过"，不启动 pipeline
- 同路径文档 hash 变化：展示"文档有更新"，继续走更新流程
- `--force` 跳过去重检测，强制重新生成
- 同时搜索 pending + confirmed 两个空间

---

#### M6a — Pending/Approve 基础流程

**目标**：pending 目录写入；approve 将 pending 移入 confirmed；处理同文档的旧 pending/confirmed 冲突。

**spec 引用章节**：
- `§ Step 4：写入 Pending 与 Approve 流程`（全节）
- `§ Step 0 > Pending 空间清理`
- `§ Step 0 > Confirmed 空间替换`

**涉及文件**：
```
kb/holmes/kb/store.py           ← write_pending(); approve_entry(); deprecate_entry()
kb/holmes/cli.py                ← holmes kb approve <id>；holmes kb pending
kb/holmes/kb/linter.py          ← approve 后更新 category index
```

**验收条件**：
- `write_pending` 将 entry 写入 `_pending/<type>/<category>/`
- `approve` 将文件从 `_pending/<type>/<category>/` 移入 `<type>/<category>/`，更新 `kb_status: active`
- approve 前检测同 `source_file` 的旧 pending entries → 提示用户清理
- approve 前检测同 `source_file` 的 active confirmed entries → 提示 deprecate
- approve 后 category index 更新，`holmes kb list` 立即可见新 entry

---

### 阶段三 — Pitfall Pipeline

#### M3 — Classifier 路由

**目标**：`--type pitfall` 强制走 DAG pipeline；Classifier 识别 single_incident / multi_incident 自动路由。

**spec 引用章节**：
- `§ Step 1：Classifier`
- `§ 适用范围`
- `§ CLI 兼容性` — `holmes import --type pitfall`

**涉及文件**：
```
kb/holmes/kb/agent/phases/classifier.py   ← 已有；确认 single_incident/multi_incident 路由逻辑
kb/holmes/kb/agent/pipeline.py            ← 新增 pitfall 分支路由
kb/holmes/cli.py                          ← holmes import --type pitfall flag
```

**验收条件**：
- `holmes import doc.md --type pitfall` 跳过 Classifier 直接进 DAG pipeline
- Classifier 返回 `single_incident` / `multi_incident` 时路由到 DAG pipeline
- 其他类型（runbook / guideline / model / decision / non_kb）继续走现有 pipeline
- `multi_incident` 额外打印 warning："建议拆分为独立文档分别导入"

---

#### M4 — Agent 1：DAG 提取

**目标**：全自动三阶段 agent loop 提取排查树，输出用户可编辑的 `.dag.md`；支持断点续传。

**spec 引用章节**：
- `§ Step 2：DAG 提取（Agent 1）`（全节）
- `§ DAG 节点 schema`
- `§ DAG 文档格式（.dag.md）`
- `§ Step 2.5 > Agent 1 完成后的交互选择`（[1/2/3] 菜单）

**涉及文件**：
```
kb/holmes/kb/agent/dag/              ← 新建目录
  agent1.py                          ← Agent 1 harness：工具白名单、maxTurns、output_dag 校验
  tools.py                           ← write_dag / read_dag / output_dag 工具实现
  schema.py                          ← DAGNode / DAGGraph dataclass
  prompt.py                          ← Agent 1 system prompt（三阶段说明）
kb/holmes/kb/agent/pipeline.py       ← 调用 Agent 1，展示 [1/2/3] 菜单，保存 session 快照
```

**验收条件**：
- Agent 1 只能调用 5 个白名单工具，其他工具调用被拒绝
- `output_dag` 校验通过后生成 `_import-state/<hash>.dag.md` 和 `.dag.json`
- 校验失败（悬空节点、循环引用等）：返回 error，agent 修正后重试
- 每 20 turns 写入 `<hash>.session.json` crash recovery 快照
- `holmes import --resume` 从快照恢复继续，跳过已完成的阶段
- `--no-interactive` 自动选 [2]，跳过用户编辑

---

#### M5 — Agent 2：双源知识生成

**目标**：Step 2.5 解析规范化 + 交叉验证；Agent 2 顺序生成所有 entries；lint 校验；ImportReport。

**spec 引用章节**：
- `§ Step 2.5：解析规范化与交叉验证`（全节）
- `§ Step 3：双源知识生成（Agent 2）`（全节）
- `§ Entry ID 预生成`
- `§ 程序化格式校验`
- `§ Lint 规则`
- `§ ImportReport 展示格式`
- `§ 证据初始化`

**涉及文件**：
```
kb/holmes/kb/agent/dag/
  step25.py                      ← 解析规范化 LLM 调用；交叉验证；用户确认屏
  agent2.py                      ← Agent 2 harness：工具集、maxTurns、write_entry 格式校验
  tools2.py                      ← read_dag / write_entry / read_entry / finalize 工具
  id_gen.py                      ← Entry ID 预生成（遍历 DAG 节点，分配 ID 表）
  lint.py                        ← 7 条 lint 规则实现
  report.py                      ← ImportReport 生成与 terminal 打印
  prompt2.py                     ← Agent 2 system prompt（四阶段说明、格式约束）
kb/holmes/kb/agent/pipeline.py   ← 串联 Step 2.5 → Agent 2 → lint → report
```

**验收条件**：
- Step 2.5 合并展示"编辑识别 + 内容验证"一屏，用户一次确认
- Agent 2 生成顺序：叶节点 → 父节点 → pitfall root（拓扑逆序）
- `write_entry` 格式校验失败：返回 error，agent 修正后重试；重试仍失败进 errors
- `section_heading=null` 且 Grep 定位失败：frontmatter 标注 `content_source: description_match_failed` 进 warnings
- 7 条 lint 规则全部覆盖，任意失败写入 ImportReport.errors
- ImportReport 末尾固定展示"下一步"操作提示
- `holmes import --retry-entry <node-id>` 单独重新生成指定节点

---

### 阶段四 — Pitfall 生命周期

#### M6b — Pending/Approve 树级联

**目标**：approve pitfall 根节点时级联处理整棵树；`holmes kb pending` 按树形分组展示。

**spec 引用章节**：
- `§ Step 4 > Approve 流程`（级联部分）
- `§ Step 4 > Approve 时的提示示例`
- `§ Step 0 > 三层并存场景`
- `§ CLI 兼容性` — `holmes kb pending`

**涉及文件**：
```
kb/holmes/kb/store.py           ← approve_tree(root_id)：整棵树原子操作
kb/holmes/cli.py                ← holmes kb pending 树形分组展示
```

**验收条件**：
- `holmes kb approve <pitfall-root-id>` 级联 approve 根节点 + 所有关联 process sub-entries
- 整棵树作为整体原子操作，不允许部分 approve
- approve 前检测同 source_file 的旧 pending 树 → 提示取消旧树
- approve 前检测同 source_file 的旧 confirmed 树 → 提示 deprecate 旧树
- 三层并存场景（一次 approve 清理两层旧数据）正确处理
- `holmes kb pending` 以 pitfall root 为标题、process sub-entries 缩进展示
