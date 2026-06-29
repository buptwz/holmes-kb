# 037 — DAG Import Pipeline 综合测试计划

> **版本**: v2.0
> **日期**: 2026-06-25
> **状态**: 待评审
> **适用分支**: `037-import-reliability`

---

## 1. 产品定位与测试目标

### 1.1 产品定位

Holmes 面向**有经验的硬件工程师**，解决的核心问题：

> 排查链路长、分支多，每次手动执行耗时。Holmes 把排查链路沉淀成可导航的决策树，agent **自动执行能远程做的步骤**（调接口、抓日志、跑诊断），只在必须人工介入时才停下来（看物理信号、换硬件）。

**提效 = agent 替你跑大部分排查步骤，你只管处理必须下线做的事。**

### 1.2 价值链与风险分布

```
资深工程师的排查文档（自由格式、无固定模板）
         ↓  holmes import
    Agent 1 提取 DAG 骨架               ← 风险最高：格式不可控，分支易遗漏
         ↓  工程师 review/编辑 .dag.md   ← 人工背书环节
    Agent 2 生成结构化 entries           ← 风险中：命令/接口信息可能截断
         ↓  工程师 approve
    知识上线（KB entries）
         ↓  agent 通过 MCP 绑定 KB
    工程师遇到问题 → agent 自动执行能做的 → 需要人工时才停下
                                         ← 风险中：node_type 错误导致 agent 行为错误
```

### 1.3 测试优先级（按产品影响排序）

| 优先级 | 维度 | 影响 | 占比目标 |
|---|---|---|---|
| **P0** | 提取准确性 — 分支完整、条件正确、node_type 准确 | 提取错了，后面全错 | 30% |
| **P0** | 内容保真度 — 命令/API/参数从原文完整保留 | agent 拿到错误命令，执行出错 | 20% |
| **P1** | agent 导航与自动执行 — 链路连续、类型驱动行为正确 | 直接决定提效效果 | 20% |
| **P1** | 生命周期正确性 — pending/approve/deprecate/delete | 知识管理基础 | 15% |
| **P2** | 鲁棒性 — 异常输入、大规模、并发 | 系统稳定性 | 15% |

---

## 2. 测试样本文档

### 2.1 设计原则

样本文档必须反映真实场景特征：
- **格式多样** — 有结构化 markdown、有纯文本叙述、有混合格式
- **深度真实** — 分支因为不同观察结果而展开，不是人为填充
- **命令真实** — 包含真实的 shell 命令、API endpoint、配置片段
- **node_type 混合** — 既有必须用户下线操作的步骤，也有 agent 可远程执行的步骤

### 2.2 样本清单

#### DOC-01: GPU 初始化失败排查（基准文档）
- **已存在**: `kb/tests/fixtures/gpu_init_failure.md`
- **格式**: 结构化 markdown（`###` 标题）
- **规模**: 5 节点，3 层深度
- **特征**: 中文，混合 human_observation（看 LED）和 api_call（nvidia-smi、dcgmi），shell 命令块
- **用途**: 所有基本功能的基准验证

#### DOC-02: 网络交换机故障切换排查
- **格式**: 结构化 markdown
- **规模**: 25 节点，5 层深度，含回路（"如果切换失败则回退到主链路重试"）
- **特征**:
  - `api_call` 密集段：连续 4 个节点都是 agent 可调的网络诊断接口（ping、traceroute、SNMP query、BGP status）
  - `human_observation` 段：检查光模块指示灯、线缆物理连接
  - 一处回路逻辑（切换失败重试）
  - 每个 api_call 节点包含完整的 curl/SNMP 命令和预期输出格式
- **核心测试点**: agent 能否连续自动执行 4 个 api_call 不打断用户；回路是否正确处理为 back_edge

#### DOC-03: 存储阵列重建排查
- **格式**: **纯文本叙述，无任何 markdown 标题**
- **规模**: 40 节点，8 层深度
- **特征**:
  - 全文叙述式（"首先检查 RAID 控制器状态，如果状态为 degraded 则执行 rebuild，rebuild 过程中如果速度低于 50MB/s 需要检查磁盘健康度..."）
  - 分支条件隐含在叙述中（无显式"如果...则..."关键词，而是"当出现 X 情况时..."）
  - 大量 CLI 命令散布在正文中（不在 code block 里）
  - 英文命令 + 中文描述混合
- **核心测试点**: Agent 1 对纯叙述文档的提取能力，section_heading=null 的 fallback 路径

#### DOC-04: 数据中心全链路故障排查（极限文档）
- **格式**: 混合（前半部分结构化，后半部分叙述）
- **规模**: 100+ 节点，15 层深度，每个决策节点 2~3 个分支
- **特征**:
  - 5 个大阶段：电力 → 网络 → 存储 → 计算（GPU/CPU）→ 应用层
  - 每个阶段内部有独立的深层决策树
  - 部分节点需要跨阶段引用（"如果网络正常但应用仍超时，回到存储阶段检查 IO"）
  - 约 35 个 process 节点需要独立 entry
  - 约 20 个 api_call 节点（agent 可自动执行）
  - 约 15 个 human_observation 节点（需要用户下线）
  - 包含设备型号条件分支（"如果是 A100 走这条路径，如果是 H100 走那条"）
- **核心测试点**: Agent 1 能否在 maxTurns 内完成提取；Agent 2 分批子 agent 模式（>20 process）；agent 导航是否在第 10 层以后仍然准确

#### DOC-05: 单步操作（最小文档）
- **格式**: markdown
- **规模**: 2 节点（检查 → 操作 → 结束），无分支
- **用途**: 最小路径验证——只生成 1 个 pitfall root + 0~1 个 process entry

#### DOC-06: 两个独立故障在同一文档
- **格式**: markdown
- **规模**: 2 个独立子树，各 8 节点
- **核心测试点**: multi_incident 识别、多根 DAG、各子树独立生成和 approve

#### DOC-07: 个人风格 markdown（非标准格式）
- **格式**: 工程师个人习惯——用 `**粗体**` 代替标题、用 `→` 代替列表、用表格描述分支
- **规模**: 15 节点
- **核心测试点**: Agent 1 对非标准 markdown 的容错能力

#### DOC-08: 全英文硬件排查指南
- **格式**: 英文 markdown
- **规模**: 20 节点
- **核心测试点**: 英文文档的提取质量；生成的 entry 内容语言是否与原文一致

#### DOC-09: 排查接口定义文档（API-heavy）
- **格式**: markdown，大量 API endpoint 定义和 JSON 请求/响应示例
- **规模**: 30 节点，其中 25 个是 api_call
- **特征**:
  - 每个排查步骤都有明确的 API 调用：`POST /api/diagnostic/gpu {"mode": "full"}`
  - 包含预期响应格式和分支条件：`status: "pass"` → 正常，`code: "E01"` → 走 E01 修复路径
  - 这是**最能体现 agent 提效**的场景——几乎全部步骤 agent 都能自动执行
- **核心测试点**: API endpoint、HTTP method、JSON body、预期响应在 entry 中**完整保留**；agent 连续自动执行的路径长度

---

## 3. 提取准确性测试（P0）

> 如果提取错了，后面全错。这是整个系统最脆弱的环节。

### 3.1 分支完整性

#### TC-E01: 结构化文档分支提取 (DOC-01) `@llm`

| 检查项 | 原文依据 | 预期 DAG 节点 |
|---|---|---|
| LED 红色分支 | "红色：供电异常，进入固件修复流程" | N1 → edge(红色) → N2(固件修复) |
| LED 不亮分支 | "不亮：电源线可能松动" | N1 → edge(不亮) → N3(检查电源线) |
| LED 绿色分支 | "绿色：供电正常，继续检查启动日志" | N1 → edge(绿色) → N4(检查启动日志) |
| 固件修复成功 | "如果 nvidia-smi 恢复正常 → 问题解决" | N2 → edge(成功) → END |
| 固件修复失败 | "如果仍然报错 → 需要硬件更换" | N2 → edge(失败) → N5(硬件更换) |
| POST 失败分支 | "如果出现 GPU POST failure → 进入 POST 诊断" | N4 → edge(POST失败) → N6(POST诊断) |

**通过标准**: 原文中的**每一条**显式分支在 DAG 中都有对应 edge。0 遗漏。

#### TC-E02: 纯叙述文档分支提取 (DOC-03) `@llm` `@manual`

| 检查项 | 方法 | 通过标准 |
|---|---|---|
| 显式分支覆盖率 | 人工标注原文中所有"如果/当/若"条件，对比 DAG | ≥ 95% |
| 隐性分支识别率 | 人工标注叙述中暗示的条件分支 | ≥ 70%（已知能力边界） |
| 无幻觉分支 | DAG 中每条 edge 在原文中有依据 | 0 幻觉 |

#### TC-E03: 混合格式文档提取 (DOC-04) `@llm` `@manual`

| 检查项 | 通过标准 |
|---|---|
| 5 个阶段全部识别（电力/网络/存储/计算/应用） | 全部出现在 DAG 中 |
| 跨阶段引用正确表达 | 标记为 back_edge 或在 description 中注明 |
| 设备型号条件分支 | "A100 vs H100"分支在 DAG 中存在 |
| 总节点数与原文一致度 | ≥ 90%（允许 simple 节点合并） |

#### TC-E04: 非标准 markdown 格式 (DOC-07) `@llm`

| 检查项 | 通过标准 |
|---|---|
| `**粗体**` 作为节点标题被识别 | 正确解析为节点 |
| `→` 箭头作为分支条件被识别 | 正确解析为 edge |
| 表格中的分支条件被提取 | 每行对应一条 edge |

#### TC-E05: 回路逻辑处理 (DOC-02) `@llm`

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | Agent 1 遇到"切换失败则回退到主链路重试" | 识别为回路 |
| 2 | output_dag 检测到循环 | Agent 标记 back_edge |
| 3 | 被标记的 edge | 在节点 description 中注明"失败可回退重试" |
| 4 | DAG 去掉 back_edge 后 | 无环，校验通过 |

---

### 3.2 node_type 准确性

> node_type 决定 agent 行为。分错了 = 该自动执行的不执行，或该问用户的不问。

#### TC-N01: node_type 分类准确性 (DOC-01) `@llm`

| 原文描述 | 正确 node_type | 判断依据 |
|---|---|---|
| "观察 GPU 卡背板的 LED 指示灯颜色" | `human_observation` | 需要用户到物理设备前观察 |
| "执行 `nvidia-smi -pm 1`" | `api_call` 或 `remote_action` | agent 可远程 SSH 执行 |
| "联系数据中心运维团队，提交工单" | `remote_action` | 需要人工操作（非物理观测），agent 可代提工单 |
| "根据输出判断" | `decision` | 基于已有信息做判断 |
| "拔出故障 GPU 卡" | `physical_action` | 必须用户下线物理操作 |

**通过标准**: 每个节点的 node_type 分类与人工判断一致率 ≥ 85%

#### TC-N02: api_call 节点 — agent 可执行性验证 (DOC-09) `@llm` `@manual`

| 检查项 | 通过标准 |
|---|---|
| 每个 api_call 节点的 process entry 包含可执行的命令或 API 调用 | 100% |
| 命令格式完整（不截断、不改写） | 100% |
| 预期输出/响应格式保留 | 100% |
| agent 理论上能根据 entry 内容自动执行该步骤 | 人工评审 ≥ 90% |

#### TC-N03: human_observation 节点 — agent 必须停下来

| 检查项 | 通过标准 |
|---|---|
| 每个 human_observation 节点的 entry 描述了用户需要观察什么 | 100% |
| agent 不会尝试自动执行这些步骤 | 导航测试验证 |
| 描述足够清晰，用户知道要看什么、报告什么 | 人工评审 |

#### TC-N04: complexity 分类准确性 (DOC-01) `@llm`

| 原文描述 | 正确 complexity | 判断依据 |
|---|---|---|
| "检查电源指示灯颜色" | `simple` | 一句话，不需要展开 |
| "固件修复流程" (3 条命令 + 等待 + 判断) | `process` | 多步骤，需要独立 entry |
| "硬件更换流程" (5 步操作) | `process` | 多步骤 |
| "重新插紧电源线" | `simple` | 一句话操作 |

**通过标准**: simple/process 分类准确率 ≥ 90%

---

### 3.3 section_heading 定位准确性

#### TC-S01: 结构化文档 — section_heading 匹配 (DOC-01) `@llm`

| DAG 节点 | section_heading | 原文中对应标题 | 验证 |
|---|---|---|---|
| 固件修复 | "### 固件修复流程" | 存在 | Grep 能定位 |
| 硬件更换 | "### 硬件更换流程" | 存在 | Grep 能定位 |
| POST 诊断 | "### POST 诊断流程" | 存在 | Grep 能定位 |

#### TC-S02: 纯叙述文档 — section_heading=null fallback (DOC-03) `@llm`

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 纯叙述文档中 process 节点无对应标题 | section_heading = null |
| 2 | Agent 2 用 description 关键词 Grep 原文 | — |
| 3a | 找到相关段落 | 提取内容生成 entry |
| 3b | 找不到 | frontmatter 标注 `content_source: match_failed` |
| 4 | ImportReport.warnings 包含未定位的节点 | reviewer 人工核查 |

### 3.4 line_range 定位准确性

#### TC-LR01: Agent 1 记录 line_range (DOC-01) `@llm`

| 检查项 | 通过标准 |
|---|---|
| 每个 process 节点的 DAG 中包含 `line_range` 字段 | 100% process 节点有 line_range |
| line_range 行号在原文行数范围内 | start ≥ 0，end ≤ 原文总行数，start < end |
| line_range 指向的原文区域包含该节点的核心内容 | 人工抽查 3 个节点 ≥ 2 个正确 |

#### TC-LR02: step25 line_range 验证 (DOC-01)

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 构造 line_range 超出原文行数（如原文 50 行，range=[40, 80]） | step25 `validation_warnings` 包含该节点 |
| 2 | 构造合法 line_range（range=[10, 25]） | 无警告 |
| 3 | process 节点同时有 line_range 和 section_heading | 优先验证 line_range，跳过 section_heading 检查 |

#### TC-LR03: Agent 2 locator 优先级链 (DOC-01) `@llm`

| 优先级 | 条件 | Agent 2 行为 | 验证 |
|---|---|---|---|
| 1 | line_range 存在 | 直接读取原文对应行范围 | entry 内容与该行范围一致 |
| 2 | line_range=null，section_heading 存在 | Grep section_heading | entry 内容与对应标题段一致 |
| 3 | line_range=null，section_heading=null | Grep description 关键词 | entry 有内容，或 match_failed 警告 |
| 4 | 三者均 Grep 不到 | frontmatter `content_source: match_failed` | ImportReport.warnings 包含该节点 |

---

### 3.5 行为标签与内容质量

#### TC-BT01: Steps 行为标签完整性 (DOC-01) `@llm`

每个 process entry 的 Steps 中，每步必须以行为标签开头：

| 标签 | 适用场景 | 验证方法 |
|---|---|---|
| `[api]` | shell 命令、API 调用、脚本 | 正则 `^\d+\. \[api\]` |
| `[remote]` | 远程操作但非 API（RDP、VPN 等） | 正则 `^\d+\. \[remote\]` |
| `[physical]` | 必须下线的物理操作 | 正则 `^\d+\. \[physical\]` |
| `[observe]` | 观察、读取状态、查看日志 | 正则 `^\d+\. \[observe\]` |
| `[decide]` | 判断分支 | 正则 `^\d+\. \[decide\]` |

**通过标准**: 100% 的 Steps 行以合法行为标签开头

#### TC-BT02: [api]/[remote] 步骤必须包含可执行内容 `@llm`

| 检查项 | 通过标准 |
|---|---|
| `[api]` 步骤包含 code block 或行内代码（命令/API endpoint） | 100% |
| `[remote]` 步骤包含 code block 或具体操作指令 | 100% |
| `[physical]` / `[observe]` / `[decide]` 步骤可以是纯文字 | 无强制要求 |
| 生成 entry 后 tools2.py 发出 content_quality_warnings | 缺失时出现在 ImportReport |

---

## 4. 内容保真度测试（P0）

> 命令截断了、API 参数改了 = agent 执行出错，比没有知识库还糟糕。

### 4.1 命令与 API 保真

#### TC-F01: shell 命令完整保留 (DOC-01) `@llm`

逐条对比原文命令与生成 entry 中的命令：

| 原文命令 | entry 中 | 通过标准 |
|---|---|---|
| `sudo nvidia-smi -pm 1` | 完全相同 | 字符级一致 |
| `sudo nvidia-smi --gpu-reset -i 0` | 完全相同 | 字符级一致 |
| `sudo systemctl restart nvidia-persistenced` | 完全相同 | 字符级一致 |
| `dcctl ticket create --type hardware --component gpu --node $(hostname) --description "..."` | 完全相同 | 含参数和引号 |
| `dmesg \| grep -i nvidia` | 完全相同 | 管道符保留 |
| `sudo nvidia-smi -q -d ECC` | 完全相同 | 字符级一致 |
| `sudo dcgmi diag -r 3 -j` | 完全相同 | 字符级一致 |

**自动化方法**: 提取原文所有 `$ ` 开头的命令行，提取 entry 中所有 code block 内命令，diff 对比。

#### TC-F02: API endpoint 与请求体保留 (DOC-09) `@llm`

| 检查项 | 通过标准 |
|---|---|
| HTTP method (GET/POST/PUT) | 与原文一致 |
| URL path | 与原文一致 |
| JSON request body | 字段名、值一致 |
| JSON response 分支条件 | `"code": "E01"` 等值一致 |
| Header 信息（如有） | 保留 |

#### TC-F03: 配置文件片段保留 `@llm`

| 检查项 | 通过标准 |
|---|---|
| 配置项名称 | 与原文一致 |
| 配置值 | 与原文一致 |
| 注释 | 保留或可接受省略 |

### 4.2 内容不捏造

#### TC-F04: 无捏造内容验证 (DOC-01) `@llm` `@manual`

| 检查项 | 方法 | 通过标准 |
|---|---|---|
| entry 中每一步操作 | 人工逐句核对原文 | 每步有原文依据 |
| 不存在原文未提及的命令 | 人工核对 | 0 捏造命令 |
| 不存在原文未提及的分支条件 | 人工核对 | 0 捏造条件 |
| 允许重组叙述为编号步骤 | — | 重组后信息完整 |

---

## 5. Agent 导航与自动执行测试（P1）

> 这是最终提效效果的验证。agent 能不能替工程师跑完排查链路？

### 5.1 基本导航

#### TC-A01: 从 root 到叶节点的完整导航 (DOC-01) `@manual`

模拟一次完整的排查交互：

```
工程师: "GPU 初始化失败，nvidia-smi 报 No devices found"
  agent: kb_search("GPU 初始化失败") → 找到 pitfall root
  agent: kb_read(root_id) → 读 Resolution
  agent: "请检查 GPU 卡背板 LED 指示灯颜色"           ← human_observation，必须问用户
工程师: "红色闪烁"
  agent: 从 Resolution 路由到 [固件修复流程]
  agent: kb_read(firmware_entry_id) → 读 Steps
  agent: "我来帮你执行固件修复命令"                     ← api_call，agent 可自动执行
  agent: 执行 nvidia-smi -pm 1 / gpu-reset / restart
  agent: "请检查 nvidia-smi 是否恢复正常"               ← human_observation
工程师: "还是报错"
  agent: 从 Steps 路由到 [硬件更换流程]
  agent: kb_read(hardware_entry_id)
  agent: "需要更换 GPU 卡，我帮你提交工单"              ← api_call (dcctl)
  agent: 执行 dcctl ticket create ...
  agent: "工单已提交，请确认备件到位后执行更换步骤"      ← human_observation
```

**检查项**:

| 维度 | 通过标准 |
|---|---|
| 链路路由 | 每个分支选择与用户输入一致 |
| node_type 行为 | human_observation → 问用户；api_call → agent 自动执行 |
| 链接正确性 | 每个 `[title](entry-id)` 指向正确的 entry |
| children 字段 | kb_read 返回正确的 children 列表 |
| 不迷路 | 不会重复问已回答的问题、不会跳到无关分支 |

#### TC-A02: agent 连续自动执行路径 (DOC-02 / DOC-09) `@llm` `@manual`

**场景**: 排查链路中有连续 4~5 个 api_call 节点

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | agent 读到第一个 api_call 节点 | 自动执行（不问用户） |
| 2 | 执行成功，结果匹配某个分支条件 | 自动路由到下一个 api_call 节点 |
| 3 | 连续执行 4 个 api_call | 中间不打断用户 |
| 4 | 遇到 human_observation 节点 | 停下来问用户 |
| 5 | 全程 | 工程师只在必要时被打断 |

**这是提效的核心体验**：连续 api_call 段 = agent 全自动跑完，工程师只需等结果。

#### TC-A03: 深层导航不断链 (DOC-04) `@llm` `@manual`

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 从 pitfall root 开始 | 读 Resolution |
| 2 | 进入第 1 层 process entry | child_entry_ids 正确 |
| 3 | 该 entry 有子分支，进入第 2 层 | 链接正确 |
| ... | 持续深入 | 每层链接正确 |
| N | 到达第 10+ 层叶节点 | 仍能正确导航 |
| N+1 | 叶节点标记 END 或给出结论 | 不悬空 |

**通过标准**: 从 root 到最深叶节点的**每一层**链路完整，无断链。

### 5.2 MCP 接口验证

#### TC-A04: kb_search 找到正确 pitfall

| 输入 | 预期 |
|---|---|
| 工程师描述的症状关键词 | 返回匹配的 pitfall root |
| 只返回 `kb_status: active` 的 | 不返回 deprecated / pending |
| 不返回 process sub-entry | 只返回 pitfall root 级别 |

#### TC-A05: kb_read 树形导航字段

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | `kb_read(pitfall_root_id)` | 返回 content + `children: [{id, title}, ...]` |
| 2 | `kb_read(process_entry_id)` | 如有子节点，同样返回 children |
| 3 | agent 沿 children 递归 kb_read | 可遍历整棵树 |

#### TC-A06: agent 自动执行需要的信息完整性

对每个 api_call 类型的 process entry，检查 agent 能否从 entry 内容中获取执行所需的全部信息：

| 信息类型 | 检查项 | 通过标准 |
|---|---|---|
| 命令 | shell 命令完整可执行 | 复制即可运行 |
| API 调用 | endpoint + method + body 完整 | 可构造请求 |
| 预期输出 | 不同输出对应的分支条件清晰 | agent 能判断走哪条路 |
| 超时/等待 | 如原文提及（"等待 30 秒"） | 保留在 entry 中 |

---

## 6. 文档格式鲁棒性测试（P0/P1）

> 文档格式不可控 = Agent 1 必须能处理各种写法。

### 6.1 五种文档格式覆盖

| 编号 | 格式类型 | 样本 | 核心验证 |
|---|---|---|---|
| TC-D01 | 标准 markdown（`###` 标题 + 列表） | DOC-01 | 基准，全通过 |
| TC-D02 | 纯文本叙述（无任何标题/列表） | DOC-03 | 隐性分支识别；section_heading=null 处理 |
| TC-D03 | 混合格式（前半结构化，后半叙述） | DOC-04 | 两种格式各自正确处理 |
| TC-D04 | 个人风格 markdown（粗体/箭头/表格代替标题） | DOC-07 | 非标准标记的容错 |
| TC-D05 | 全英文文档 | DOC-08 | 英文分支条件识别 |

### 6.2 每种格式的详细验证

#### TC-D02 详细: 纯叙述文档 (DOC-03) `@llm` `@manual`

**挑战**: 没有 `##` 标题，Agent 1 无法用 Grep("^#") 扫结构。

| 检查项 | 通过标准 |
|---|---|
| Agent 1 通过 Read 逐段阅读理解全文 | 调用 Read 覆盖全文 ≥ 80% |
| 用 Grep 定位分支关键词（如果/当/若/→） | 定位到主要分支点 |
| DAG 中节点的 description 足够具体 | 不是"检查某项"这种模糊描述 |
| process 节点 section_heading = null | 因为原文没有标题 |
| Agent 2 使用 description fallback 定位内容 | 生成的 entry 内容与原文对应段落一致 |

#### TC-D04 详细: 个人风格 markdown (DOC-07) `@llm`

示例：
```
**第一步检查电源** → 红灯：走固件修复 → 不亮：检查线缆

| 现象 | 处理 |
|---|---|
| 温度 > 85°C | 检查散热 |
| 温度正常 | 继续下一项 |
```

| 检查项 | 通过标准 |
|---|---|
| `**粗体**` 被识别为节点 | 不要求作为 section_heading，但 description 准确 |
| `→` 被识别为分支路由 | edge 条件正确 |
| 表格行被识别为分支条件 | 每行对应一条 edge |

---

## 7. 大规模提取测试（P1/P2）

### 7.1 规模分层测试矩阵

| 规模 | 文档 | Agent 1 | Agent 2 | 通过标准 |
|---|---|---|---|---|
| 小 (5 节点) | DOC-01 | ≤ 30 turns | 全局视野 | 全通过 |
| 中 (25 节点) | DOC-02 | ≤ 100 turns | 全局视野 | 分支完整率 ≥ 95% |
| 大 (40 节点) | DOC-03 | ≤ 150 turns | ≤30 process → 全局视野 | 分支完整率 ≥ 90% |
| 极大 (100+ 节点) | DOC-04 | ≤ 300 turns | >30 process → 分批子 agent | 分支完整率 ≥ 85% |

### 7.2 极大规模专项 (DOC-04) `@llm` `@manual`

| 维度 | 检查项 | 通过标准 |
|---|---|---|
| Agent 1 完成度 | 在 maxTurns=300 内 output_dag 通过 | 通过 |
| Agent 2 分批 | >30 process 节点触发分批（每批 10） | 验证触发 |
| 跨批次术语一致 | 同一概念在不同批次 entry 中用同样术语 | 人工抽查 5 对 |
| 树导航深度 | 从 root 到第 15 层叶节点，每层链接正确 | 全通过 |
| ImportReport | 明确列出所有 root + process 数量 | 与 DAG 一致 |

### 7.3 性能基线（记录，不设硬性阈值）

| 规模 | 记录指标 |
|---|---|
| DOC-01 (5 节点) | Agent 1 耗时, Agent 2 耗时, 总 token 消耗 |
| DOC-04 (100+ 节点) | Agent 1 耗时, Agent 2 耗时, 总 token 消耗, 分批数 |

---

## 8. 知识生命周期测试（P1）

### 8.1 首次导入 → 审核 → 上线

#### TC-L01: 完整 Happy Path

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | `holmes import gpu_init_failure.md` | Classifier → DAG pipeline |
| 2 | Agent 1 + Agent 2 完成 | entries 写入 `_pending/<type>/<category>/` |
| 3 | `holmes kb pending` | 树形分组展示（root 为标题，sub-entries 缩进） |
| 4 | `holmes kb approve <root-id>` | 整棵树原子 approve |
| 5 | `holmes kb list` | 只显示 pitfall root（sub-entries 隐藏） |
| 6 | `holmes kb show <root-id>` | 显示内容 + children 导航 |
| 7 | MCP `kb_search` / `kb_read` | 正常返回 |

#### TC-L02: Pending 目录结构验证

| entry 类型 | 预期路径 |
|---|---|
| pitfall root | `_pending/pitfall/<category>/<id>.md` |
| process sub-entry | `_pending/process/<category>/<id>.md` |

approve 后：

| entry 类型 | 预期路径 |
|---|---|
| pitfall root | `pitfall/<category>/<id>.md` |
| process sub-entry | `process/<category>/<id>.md` |

### 8.2 文档更新流程

#### TC-L03: 同一文档重新导入

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 导入 DOC-01 → approve → active | — |
| 2 | 修改 DOC-01（新增一个分支） | — |
| 3 | 再次 `holmes import DOC-01` | 检测到 source_file 匹配、hash 不同 → "文档有更新" |
| 4 | 生成新 ID 的 entries | 旧 entries 不受影响 |
| 5 | approve 新 entries | 提示 deprecate 旧 confirmed entries |
| 6 | 确认 | 旧 entries deprecated，新 entries active |
| 7 | `holmes kb list` | 只显示新版本 |

#### TC-L04: 三层并存场景

| 状态 | 内容 |
|---|---|
| confirmed | v1 (1月 import，已 approve) |
| pending | v2 (2月 import，未审核) |
| pending | v3 (3月 import，刚生成) |

approve v3 时：
- v2 从 pending **取消**（未审核草稿，直接移除）
- v1 **deprecated**（旧版本）
- v3 **active**（新版本）

一次 approve 清理两层。

### 8.3 去重

#### TC-L05: 完全重复跳过

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 导入 DOC-01 | 成功 |
| 2 | 再次导入完全相同的 DOC-01 | "已存在，跳过" |
| 3 | `--force` 导入 | 强制重新生成 |

#### TC-L06: 跨空间去重

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | DOC-01 → pending（未 approve） | — |
| 2 | 再次导入相同的 DOC-01 | 在 pending 空间检测到 hash 匹配 → 跳过 |
| 3 | DOC-01 → approve → confirmed | — |
| 4 | 再次导入 | 在 confirmed 空间检测到 → 跳过 |

### 8.4 删除

#### TC-L07: 级联删除整棵树

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 已 approve 的完整树 (root + 3 process) | — |
| 2 | `holmes kb delete <root-id>` | root + 3 process 全部移入 `_trash/<type>/<category>/` |
| 3 | `--no-cascade` | 只移 root，子节点不动 |
| 4 | 删除 pending entry | 同样移入 `_trash/` |

#### TC-L08: 删除后可恢复

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | 删除 entry → 移入 _trash | — |
| 2 | `git checkout HEAD -- <original_path>` | 文件恢复到原位 |

### 8.5 审核流程

#### TC-L09: 级联 approve 整棵树

| 步骤 | 操作 | 预期 |
|---|---|---|
| 1 | pending 中：pitfall root + 3 process | — |
| 2 | `approve_tree(kb_root, root_id)` | 4 个 entry 全部 approve |
| 3 | 部分失败 | 已 approve 的回滚到 _pending（原子性） |

#### TC-L10: approve 前冲突检测

| 场景 | 预期 |
|---|---|
| 同 source_file 的旧 pending 存在 | 提示取消旧 pending |
| 同 source_file 的旧 confirmed 存在 | 提示 deprecate 旧 confirmed |

---

## 9. Frontmatter 与结构完整性测试（P1）

### 9.1 字段完整性矩阵

每个生成的 entry 必须通过：

| 字段 | pitfall root | process entry | 验证规则 |
|---|---|---|---|
| `title` | 必填 | 必填 | 非空，自解释，≤40 字 |
| `description` | 必填 | 必填 | 非空，1-2 句话 |
| `type` | `pitfall` | `process` | 枚举值 |
| `category` | 必填 | 必填 | 合法分类值 |
| `pitfall_structure` | `tree` | — | 仅 pitfall |
| `kb_status` | `pending` | `pending` | 生成时固定 |
| `source_file` | 必填 | 必填 | 同批一致 |
| `source_hash` | 必填 | 必填 | 同批一致 |
| `import_trace_id` | 必填 | 必填 | 同批一致 |
| `parent_id` | null | 必填 | process 必须指向父节点 |
| `child_entry_ids` | ≥1 项 | 0+ 项 | 每项附标题注释 |
| `maturity` | `draft` | `draft` | 初始固定值 |
| `decay_status` | `active` | `active` | 初始固定值 |
| `next_decay_check` | today+180d | today+180d | 日期格式正确 |
| `contributors` | ≥1 项 | ≥1 项 | 含 user=config.username, role=initiator |
| `tags` | ≥1 项 | ≥1 项 | 从文档推断 |

### 9.2 树结构一致性

| 检查项 | 方法 | 通过标准 |
|---|---|---|
| parent_id 双向一致 | 子 entry 的 parent 的 child_entry_ids 包含该子 | 全部 |
| child_entry_ids 双向一致 | 父 entry 的每个 child 的 parent_id 指向该父 | 全部 |
| 无孤立节点 | 每个 process 的 parent_id 指向存在的 entry | 全部 |
| 无悬空引用 | child_entry_ids 中每个 ID 对应的 entry 存在 | 全部 |
| 无循环 | 沿 parent_id 向上追溯到 root | 全部 |

### 9.3 Lint 规则覆盖

7 条 lint 规则，每条一个失败用例：

| 规则 | 构造的失败条件 | 预期 lint 结果 |
|---|---|---|
| parent_id_consistency | parent_id 指向不存在的 ID | FAIL |
| child_entry_ids_consistency | child 引用不存在 | FAIL |
| tree_completeness | DAG 中的节点无对应 entry | FAIL |
| no_cycle | child_entry_ids 形成环 | FAIL |
| pitfall_has_root | 无 pitfall root | FAIL |
| source_file_consistent | source_file 不一致 | FAIL |
| evidence_fields_present | 缺少 maturity | FAIL |

---

## 10. 可观测性与工具链测试（P2）

### 10.1 日志

| 编号 | 检查项 | 通过标准 |
|---|---|---|
| TC-O01 | import 生成 `.log` + `.jsonl` 双格式 | 两个文件都存在 |
| TC-O02 | JSON 每行含 ts/trace/span/level/msg | 字段齐全 |
| TC-O03 | trace_id = 源文档文件名 stem | 格式正确 |
| TC-O04 | 30 天日志滚动 | 旧文件被删除 |
| TC-O05 | `--verbose` 实时打印 span | 终端可见 |

### 10.2 CLI 命令

| 编号 | 检查项 | 通过标准 |
|---|---|---|
| TC-O06 | `holmes log list` | 列出 trace 摘要 |
| TC-O07 | `holmes log show <trace_id>` | 展示 span 树 |
| TC-O08 | `holmes log show --json` | 原始 JSON 输出 |
| TC-O09 | config.username 未设置时 import | 报错 + 提示 |
| TC-O10 | `holmes kb pending` 树形分组 | root 为标题，sub-entries 缩进 |
| TC-O11 | `holmes import --dry-run` | Classifier 执行，不写入文件 |
| TC-O12 | `holmes import --dir <dir>` | 批量处理，隐含 --no-interactive |

### 10.3 MCP 接口

| 编号 | 检查项 | 通过标准 |
|---|---|---|
| TC-O13 | `kb_draft(content, title)` 保存到 `_drafts/` | frontmatter 含 author + 时间 |
| TC-O14 | `kb_draft` 未配置 username | 返回错误 |
| TC-O15 | `holmes kb drafts` 列出待 import 草稿 | 不含 `_imported/` |
| TC-O16 | import 后草稿移入 `_drafts/_imported/` | 生命周期完整 |
| TC-O17 | MCP 操作写入 session trace 日志 | 日志可查 |

---

## 11. 异常与边界测试（P2）

### 11.1 输入异常

| 编号 | 场景 | 预期 |
|---|---|---|
| ERR-01 | 空文件 | non_kb → 跳过 |
| ERR-02 | < 50 字符的文件 | 跳过，warn |
| ERR-03 | 超大文件 (>100KB) | 截断 + warning |
| ERR-04 | 非 UTF-8 编码 | 报编码错误 |
| ERR-05 | 路径含中文/空格 | 正常处理 |

### 11.2 LLM 异常

| 编号 | 场景 | 预期 |
|---|---|---|
| ERR-10 | API key 无效 | 人类可读错误提示 |
| ERR-11 | rate limit | 自动重试 |
| ERR-12 | 返回格式错误 | 捕获，写入 errors |
| ERR-13 | Agent 1 超 maxTurns | 强制终止 + 报告 |
| ERR-14 | Agent 2 write_entry 多次失败 | 进入 errors，`--retry-entry` |

### 11.3 Classifier 容错

| 编号 | 场景 | 预期 |
|---|---|---|
| ERR-20 | LLM 返回非 JSON | 默认 single_incident（不崩溃） |
| ERR-21 | 未知 doc_type 值 | 默认 single_incident |
| ERR-22 | 网络错误 | 默认 single_incident |

### 11.4 数据一致性边界

| 编号 | 场景 | 预期 |
|---|---|---|
| ERR-30 | approve 时 child entry 缺失 | FileNotFoundError |
| ERR-31 | approve_tree 部分失败 | 已 approve 的回滚到 _pending |
| ERR-32 | deprecate pending entry | 返回 False（不允许） |
| ERR-33 | _trash 中同名文件 | 加时间戳后缀 |
| ERR-34 | ID 预生成幂等性 | 二次调用返回相同 ID |
| ERR-35 | Agent 2 checkpoint recovery | 跳过已写节点 |

---

## 12. 回归测试（P2）

| 编号 | 功能 | 验证方法 |
|---|---|---|
| REG-01 | 旧格式 entry（无 kb_status）正常显示 | list_entries 默认视为 active |
| REG-02 | 旧 pitfall (pitfall_structure: flat) 正常检索 | kb_search 返回 |
| REG-03 | 非 pitfall import（guideline/runbook）走旧 pipeline | 不进 DAG |
| REG-04 | MCP kb_overview / kb_list / kb_search 接口兼容 | 返回格式不变 |
| REG-05 | `holmes kb show <old-id>` 正常 | 显示内容 |
| REG-06 | config.json 新增 username 字段不影响旧配置 | 加载不报错 |

---

## 13. 执行计划

### 第一轮（P0 — 必须全通过方可合并）

**提取准确性**:
- TC-E01 分支完整性（DOC-01 基准）`@llm`
- TC-N01 node_type 分类准确性 `@llm`
- TC-N04 complexity 分类准确性 `@llm`
- TC-S01 section_heading 匹配 `@llm`

**内容保真度**:
- TC-F01 shell 命令完整保留 `@llm`
- TC-F04 无捏造内容验证 `@llm` `@manual`

**生命周期基础**:
- TC-L01 完整 Happy Path
- TC-L02 目录结构
- TC-L05 去重
- 9.1 字段完整性矩阵
- 9.2 树结构一致性

### 第二轮（P1 — 核心体验）

**Agent 导航**:
- TC-A01 完整导航 `@manual`
- TC-A02 连续自动执行 `@llm` `@manual`
- TC-A05 kb_read 树形导航
- TC-A06 agent 可执行信息完整性

**格式鲁棒性**:
- TC-D01 ~ D05 五种格式覆盖 `@llm`
- TC-D02 纯叙述文档详细验证 `@llm` `@manual`

**大规模**:
- 7.1 规模分层矩阵（DOC-01 ~ DOC-04）`@llm`

**生命周期进阶**:
- TC-L03 文档更新
- TC-L04 三层并存
- TC-L07 级联删除
- TC-L09 级联 approve + 回滚
- 9.3 Lint 规则覆盖

### 第三轮（P2 — 鲁棒性）

- 11.x 全部异常边界
- 12.x 回归测试
- 10.x 可观测性
- 7.2 极大规模专项 `@llm` `@manual`

---

## 14. 测试标记说明

| 标记 | 含义 | 执行方式 |
|---|---|---|
| （无标记） | 确定性测试，可自动化 | pytest 自动执行 |
| `@llm` | 需要真实 LLM 调用 | 手动触发，需 API key |
| `@manual` | 需要人工主观判断 | 人工执行 + 填写检查表 |

---

## 15. 用例统计

| 类别 | 用例数 | 自动化 | 需 LLM | 需人工 |
|---|---|---|---|---|
| 提取准确性 (§3) | 19 | 2 | 14 | 6 |
| 内容保真度 (§4) | 4 | 1 | 3 | 2 |
| Agent 导航 (§5) | 6 | 2 | 3 | 4 |
| 格式鲁棒性 (§6) | 7 | 0 | 7 | 3 |
| 大规模 (§7) | 5 | 0 | 5 | 3 |
| 生命周期 (§8) | 10 | 10 | 0 | 0 |
| 字段与结构 (§9) | 10 | 10 | 0 | 0 |
| 可观测性 (§10) | 17 | 17 | 0 | 0 |
| 异常边界 (§11) | 18 | 14 | 0 | 0 |
| 回归 (§12) | 6 | 6 | 0 | 0 |
| **合计** | **102** | **62** | **32** | **18** |

**核心价值验证占比**: 提取(19) + 保真(4) + 导航(6) + 格式(7) + 大规模(5) = **41 个 / 40%** — 确保最重要的事情测得最深。

---

*本测试计划围绕"给有经验的硬件工程师提效"这一产品定位设计。排查链路提取的准确性、命令信息的保真度、agent 自动执行路径的连续性是三个核心验证维度。基础设施（生命周期、日志、MCP）作为支撑，确保知识能正确管理和交付。*
