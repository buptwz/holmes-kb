# Spec 043: KB 系统加固与 NPI 场景适配

- **状态**: Draft（方案已与产品 owner 对齐，待开工）
- **日期**: 2026-07-20
- **分支**: `043-kb-hardening`
- **上游参考**: [Harness 不是目的，知识才是护城河（知乎）](https://zhuanlan.zhihu.com/p/2032094280060252204)、claude-code agent 架构

---

## 1. 背景

Holmes 处于设计打磨期，尚无真实文档与真实用户。目标场景：半导体测试验证团队（NPI 方向）的排障知识库——文档特点是流程长、分支条件多、物理操作（看信号/量测）与远程命令调试混排。两种部署形态都必须成立：

- **分布式**：用户各自 clone KB（git 仓库），本地 import、本地跑 MCP server，改动 push，多人冲突在 git 端处理
- **集中式**：中心服务器统一 import、统一跑 MCP server，多工程师的 agent 连接中心 server，管理员统一操作

产品定位（owner 明确，冻结）：

1. **MCP 不提供搜索**。MCP 是透明通道，让 agent 像读本地文件一样读远端 KB。可发现性负担由 browse 体验承担（排序、brief、decision_map、guide 字段）。
2. **不自建 agent**。只对外暴露 MCP server，用户用自己的 agent 产品接入。agent 引导只能通过 MCP 工具 description 和 `kb_browse` 的 `guide` 字段传达。

## 2. 任务目标

把系统从"设计期、主链路断裂"推进到"骨架正确、闭环真实成立、两种部署形态可试点"，随后用真实文档/真实用户数据驱动后续迭代。

## 3. 已确认问题清单（全部经代码逐行核实）

### 3.1 第一梯队：主链路断裂

| # | 问题 | 证据 |
|---|------|------|
| P1 | **read→confirm 必判 duplicate，成熟度永不提升**：`kb_read(full)` 带 session_id 写 referenced 证据，同 session `kb_confirm` 被 session 去重拒绝 | `kb/holmes/mcp/tools.py:359,386-402,859-861`、`kb/holmes/kb/store.py:426` |
| P2 | **import→approve 断裂**：import 写 `contributions/pending/`，approve 只扫 `_pending/` | `kb/holmes/kb/pending.py:22`、`kb/holmes/kb/store.py:604-633`、`kb/holmes/cli/pending.py:304-307` |
| P3 | **文档命令不存在**：管理命令全在 hidden `kb` 子组，顶层只有 setup/import/start/config/log | `kb/holmes/cli/browse.py:15`、`pending.py:274`、`confirm.py:396` 等 |

### 3.2 第二梯队：集中式架构缺陷

| # | 问题 | 证据 |
|---|------|------|
| P4 | contributor 取 server 机器 git config，集中式下 proven（≥2 contributor）数学不可达 | `kb/holmes/mcp/tools.py:35-50`、`store.py:355-358` |
| P5 | 存储层无并发原语，`append_evidence` 为 read-modify-write，并发下升级丢失且不可恢复；sidecar 非原子写 | `store.py:405-448`（sidecar `write_text` 于 :434） |
| P6 | MCP server 无认证、无 `--host` 选项 | `kb/holmes/mcp/server.py:151-175`、`cli/server.py:10-21` |
| P7 | session_id 8 字符截断易碰撞、不校验来源、空 sid 绕过去重覆写 `unknown.json` | `tools.py:163-164`、`store.py:426,432-433` |

### 3.3 第三梯队：git 协作必撞点

| # | 问题 | 证据 |
|---|------|------|
| P8 | 派生文件（index.json 含时间戳、_index.md、log.md）全部入库，两人 approve 后必冲突；`kb merge` 对无 frontmatter 文件判 content_contradiction 后移出原位 | `cli/confirm.py:424-429`、`merger.py:55`（只扫 .md，index.json 冲突无工具） |
| P9 | `generate_id` 本地 max+1，多人本地 approve 必撞号 | `validator.py:102-147` |
| P10 | server 启动重建 index 写入本机绝对路径，污染 git 仓库 | `store.py:894`、`server.py:168-170` |

### 3.4 第四梯队：import 对 NPI 场景的缺口

| # | 问题 | 证据 |
|---|------|------|
| P11 | Summarizer schema 无 steps/physical/remote 维度，物理操作步骤在提取时丢失且 fidelity 无法校验 | `phases/summarizer.py:9-16,93-104` |
| P12 | 长文档截断点：Classifier 只看前 8K 字符、多主题偏移基于截断片段、Summarizer 15 轮上限静默丢弃 | `phases/classifier.py:223`、`pipeline.py:453-464`、`summarizer.py:44` |
| P13 | 语义查重 `SemanticDeduplicator` 是死代码，同根因换表述会重复入库 | `dedup.py` 仅测试引用 |

### 3.5 待核实（修复触及对应文件时确认，证伪即划掉）

- ~~Anthropic provider 下 compact 失效（`compact.py:194` 只认 OpenAI 格式）~~ **已证实并修复（T035）**：`snip_old_tool_results` 只认 `role:"tool"`、`extract_read_ranges` 只解析 `tool_calls`，Anthropic 形状（tool_result/tool_use content block）下 snip 恒 0、阅读进度为空。已改为同时识别两种消息形状（`compact.py`），test_compact.py 配 Anthropic 形状用例。
- index.json `file_path` 无目录约束校验（`store.py:98-102`）
- CLI 侧 decay/add_contributor 裸写文件（`decay.py:254`、`store.py:470`）

## 4. 设计决策（已冻结）

### D1. 证据模型事件溯源化（修 P1/P5/P8-maturity）

- sidecar 记录 = 一个 session 与一条条目的一次完整交互，状态机：`referenced → solved/not_solved`；`kb_confirm` **升级**同 session 已有记录（覆写自己的 `<session>.json`），而非追加新记录。去重语义保留，duplicate bug 消除。
- maturity **读时推导**（`derive_maturity` 现成），frontmatter 字段降级为缓存，`rebuild-index` 时重算校准。证据（sidecar）为唯一真值。
- 效果：高频写 = 纯文件追加（并发安全）；条目文件只有人工 approve 才写；maturity 的 git 冲突类别消失，`merger.py` 相关逻辑可删。

### D2. ID 改为 类型前缀 + 短随机后缀（修 P9，owner 已拍板）

- 格式：`PT-DB-a3f8c2`（前缀保留类型/子类可读性，6-8 位随机 hex，生成时存在性重试）。
- 一个方案通吃集中式/单人本地/多人分布式；删除 fetch 检测与 renumber 工具的需求。
- 代价与配套：编号不再递增（排序靠 `created_at`）；失去"撞号=重复信号"的副作用 → **approve 门控语义查重从 M3 提前到 M2 作为必做配套**。
- 时机：当前 KB 无任何真实条目，切换零迁移成本。

### D3. 身份由调用方声明（修 P4/P7）

- `kb_browse`/`kb_confirm` 增加 `contributor` 参数；agent 侧使用 `config.py` 已有的 `username` 字段。
- server 仅在 local 模式回退 git config；`_record_reference` 不再硬编码 `"agent"`。
- session_id 完整 uuid 不截断；**空 sid 的 confirm 一律拒绝**（已拍板 2026-07-20），hint 引导 agent 先调 `kb_browse` 获取 session。集中式下无匿名桶。

### D4. 部署模式一等公民（修 P5/P6）

- `holmes start --mode local|central`、`--host`：local（默认）= loopback + git config 身份兜底 + 免认证；central = 绑定对外 + 强制 contributor + 静态 token 认证 + 低频人工写加进程内锁。
- 不做完整 RBAC，等真实需求。

### D5. 派生文件出 git（修 P8/P10）

- `.gitignore` 忽略 `index.json`、`_index.md`（纯派生，本地重建，server 启动/approve 后已自动重建）。
- `.gitattributes`：`contributions/log.md merge=union`。
- `kb merge` 不再把 log.md/_index.md 判为 content_contradiction 移走（索引类文件走 rebuild）。
- index.json 的 `file_path` 改相对路径，读取侧加 `is_relative_to(kb_root)` 校验。

### D6. applies_to 适用性元数据（新增能力，对齐知乎"时空型知识"）

- frontmatter 新增**可选**字段（旧条目零迁移）：

```yaml
applies_to:
  product_line: [serdes-gen2]
  test_stage: [dvt]
  firmware: "<=2.3"
```

- **键预设、值开放**（已拍板 2026-07-20）：维度的键固定为 `product_line` / `test_stage` / `firmware` 三个（`station` 等试点后按需追加——加键零成本，删改键有成本，故从有把握的起步）。`firmware` 存字符串，doctor 只做简单版本比较，不搞语义化版本解析。
- **值是开放世界，词表自积累**：不预设取值。import 时 pipeline 把 KB 当前词表注入 Summarizer prompt，LLM 提取时优先复用已有取值（防 "gen2"/"serdes_gen2" 同义发散）；人 approve 把关；新取值 approve 后沉淀进词表（`kb-config.yml` 或从现有条目聚合）；doctor 对词表外取值报"疑似笔误"；`kb_browse` 的 guide 字段把词表告诉 agent 供过滤使用。
- 配套四处：① `kb_browse` 按适用性过滤；② `holmes doctor` 适用性过期检查（`kb-config.yml` 记 `current_context`，约束不符仅报告不自动删）；③ import 时 LLM 提取该字段；④（可选，owner 待定）proven 增加独立场景维度。

### D7. import IR 扩展（修 P11/P12/P13）

- Summarizer schema 加 `steps: [{action, actor: human|agent|remote, command?, expected?}]`；Generator 的 `[physical]/[remote]/[api]` 标签从 actor 字段**机械生成**（不再靠 LLM 自觉）。
- fidelity 增加步骤保真检查（物理步骤丢失可检出）。
- 长文档不变量：Classifier 对全文取 outline；pipeline 结束前硬校验"每个 outline section 被读过"，未覆盖强制补读，杜绝静默截断。
- 语义查重接入 approve 门控（提示疑似重复，人裁决）。
- 合成评测集：按 NPI 特征造 5-10 篇对抗性 fixture（超长多分支/物理混排/密集纯文本/中英混杂），pipeline 改动跑回归。

### D8. 收敛（修 P2/P3 + 死代码）

- pending 单轨：只留 `contributions/pending/`，删 `_pending/<type>/<category>/` 与 `store.write_pending`。
- CLI 顶层化：`approve/pending/search/show/list/decay/doctor` 等注册到顶层；`holmes kb xxx` 保留 hidden 别名一个版本周期。
- 删死代码：`SemanticDeduplicator`（接线后原死路径清理）、`merge_pending_entry`、`resolve_maturity_conflict`、根包旧 CLI、`agent/src/tools/kb/*.ts`。

## 5. Phase 计划

### M1 — 闭环修复 + 收敛（系统从断到通）

1. **复现测试先行**：三个红测试——import 后 approve 找不到；`holmes approve` 报 No such command；read(full)+confirm 返回 duplicate
2. D1 证据模型（sidecar 升级语义 + maturity 读时推导带缓存）
3. D8 收敛（pending 单轨、CLI 顶层化、死代码清理）
4. **golden loop 测试**：合成文档走通 import→approve→browse→read→confirm→verified→第二 contributor confirm→proven→decay 全环

### M2 — 两种部署形态可用

1. D5 派生文件出 git + log.md union + index 相对路径化
2. D2 UUID ID + approve 门控语义查重（配套提前）
3. D3 contributor 声明 + session_id 加固
4. D4 部署模式 + token 认证 + 写锁

### M3 — import 质量 + applies_to（NPI 核心竞争力）

1. D7 IR 扩展（steps/actor）+ fidelity + 长文档不变量 + 合成评测集
2. D6 applies_to 字段 + browse 过滤 + doctor 过期检查 + import 提取

### M3.5 — 可交付（按最终贡献排序）

1. 打包收敛：一条安装命令、一个确定的 `holmes` 入口行为
2. MCP 内嵌引导打磨：4 个工具 description + `kb_browse` guide 字段写清排查方法论（browse→summary→按需读 branch→confirm/draft）
3. 文档重写：OPERATIONS.md 等按新行为重写
4. telemetry 接线（CLI 上报点，集中式部署需要时）

### 试点后由数据决策（本 spec 不做）

- MCP 是否仍不需要搜索（观察 agent 找到率）
- 角色权限、规模化性能缓存、proven 场景维度

## 6. 验证方式

- 每个修复先有其复现测试变红、修复后变绿
- golden loop 端到端测试常驻 CI
- import 质量以合成评测集量化（提取完整率、fidelity 通过率）
- 设计合规自查：不违反知乎理念（证据驱动、渐进披露、git 原生、无数据库）；全部改动"加而不改"（字段可选、参数有兜底、模式默认 local、旧命令留别名）

## 7. 明确不做

- MCP 搜索/语义检索（通道定位，试点后数据再议）
- 自建 agent / TUI 投入（只暴露 MCP；`skills/`、`agent/` 降级为示例或清理）
- 完整 RBAC、五层存储架构、三角色系统（过度工程，等真实需求）
- 顺序号 ID 的一切抢救措施（D2 已改 UUID）
