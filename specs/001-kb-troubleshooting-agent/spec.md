# 功能规格说明：基于知识库的问题排查 Agent

**功能分支**：`001-kb-troubleshooting-agent`

**创建日期**：2026-05-26

**修订日期**：2026-05-26

**状态**：修订版 v3

---

## 产品定位

Holmes 是一个以知识库为核心的排查经验管理工具。
**用户通过 `holmes` 命令启动 Holmes Agent 进行交互**，无需自研 agent 引擎或 TUI。
我们只构建知识库本体、原生工具层（以 TypeScript 插件形式集成进 Holmes Agent，与 `Read`/`Grep` 同级）、CLI 管理工具和 Holmes Agent 集成配件。
**KB 工具不通过 MCP 协议接入**，而是直接实现为 Holmes Agent 原生工具（`buildTool`/`ToolDef` 模式），调用 `holmes-kb` Python 包完成文件系统操作。

---

## 用户场景与测试

### 用户故事 1 - 安装配置与首次排查（优先级：P1）

新用户安装 holmes-kb，clone 远端知识库，执行 `holmes setup` 完成
KB 路径配置与 HOLMES.md 初始化，随后通过 `holmes` 命令启动 Holmes Agent 开始排查。

**独立测试方法**：
安装 holmes-kb、执行 `holmes setup --kb-path <path>`、运行 `holmes`，
在会话中提问并验证 Holmes Agent 成功调用了 KB 原生工具。

**验收场景**：

1. **前置条件**：已安装 holmes-kb 并 clone 知识库；
   **操作**：执行 `holmes setup --kb-path <path>`；
   **预期结果**：KB 路径写入 `~/.holmes/settings.json` 的 `env` 字段（`HOLMES_KB_PATH`），
   HOLMES.md 写入知识库根目录，命令输出确认两项均已完成。
2. **前置条件**：setup 完成，用户运行 `holmes` 并提问；
   **操作**：提交排查问题（如"Redis 连接超时怎么排查"）；
   **预期结果**：Holmes Agent 调用 `KbReadOverview` 或 `KbSearch` 原生工具，
   响应中引用了知识库中的相关条目内容。
3. **前置条件**：KB 中有相关条目；
   **操作**：提交更具体的追问；
   **预期结果**：Holmes Agent 调用 `KbReadEntry` 读取具体条目全文，
   给出基于条目内容的针对性建议。

---

### 用户故事 2 - 排查成功后提取并保存知识（优先级：P1）

排查完成后，用户在 Holmes Agent 会话中执行 `/holmes-resolve`，
触发知识提取并写入本地知识库 pending 区，供后续审阅确认。

**独立测试方法**：
完成一次排查会话，执行 `/holmes-resolve`，验证 `contributions/pending/`
中出现新条目，且条目结构符合 KB Schema。

**验收场景**：

1. **前置条件**：排查会话已完成；
   **操作**：用户执行 `/holmes-resolve`；
   **预期结果**：Holmes Agent 调用 `KbExtractAndSave` 原生工具，
   自动生成结构化排查总结（含 Symptoms/Root Cause/Resolution 章节），
   写入 `contributions/pending/`，输出 pending ID。
2. **前置条件**：pending 条目已生成；
   **操作**：执行 `holmes kb pending`；
   **预期结果**：新条目出现在列表中，含标题、类型（pitfall）和暂存时间。
3. **前置条件**：条目经 `holmes kb confirm` 确认入库；
   **操作**：在新 Holmes Agent 会话中提交同类问题；
   **预期结果**：Holmes Agent 通过 KB 原生工具检索到该条目并引用。

---

### 用户故事 3 - CLI 导入外部知识（优先级：P1）

用户通过 `holmes import <file>` 将已有的知识文档（运维经验、故障报告等）
导入本地知识库 pending 区，无需手动格式化为 KB Schema。

**独立测试方法**：
提供一份非结构化故障记录文档，执行 `holmes import`，
验证 pending 区出现结构化条目（含完整 frontmatter 和必要章节）。

**验收场景**：

1. **前置条件**：用户有一份知识文档（任意格式）；
   **操作**：执行 `holmes import <file> --type pitfall --category database`；
   **预期结果**：LLM 对文档进行结构化，结果写入 `contributions/pending/`，
   输出 pending ID 和内容预览，整个过程无需用户手动填写 frontmatter。
2. **前置条件**：导入结果在 pending 区；
   **操作**：执行 `holmes import <file> --dry-run`；
   **预期结果**：仅展示结构化预览，不写入文件。
3. **前置条件**：导入的文档内容 < 50 字符（含空白）；
   **预期结果**：命令直接拒绝，输出错误提示（"内容过短，至少需要 50 字符"），不调用 LLM，不写入任何条目。

---

### 用户故事 4 - 知识库 CLI 运维（优先级：P1）

用户通过 `holmes kb` 子命令集完成知识库日常运维：
审阅 pending 条目、执行 3-gate 确认入库、处理冲突、运行健康检查。

**独立测试方法**：
执行 `/holmes-resolve` 或 `holmes import` 生成一条 pending 条目，
然后完整走完 `pending → confirm → lint` 全流程，验证状态正确流转。

**验收场景**：

1. **前置条件**：存在 pending 条目；
   **操作**：执行 `holmes kb pending`；
   **预期结果**：表格展示条目 ID、类型、标题、暂存时间。

2. **前置条件**：pending 条目 Schema 完整，无重复；
   **操作**：执行 `holmes kb confirm <ID>`，输入 `y` 确认；
   **预期结果**：条目经过三项校验（Schema → 重复检测 → 强制预览）后
   移入正式目录，系统自动按类型前缀+类目+序号分配永久 ID（扫描现有条目取最大值+1），
   在 holmes-agent 会话中可被检索。

3. **前置条件**：pending 条目缺少必填字段或必要章节；
   **操作**：执行 `holmes kb confirm <ID>`；
   **预期结果**：Schema 校验失败，输出具体缺失项，条目保留在 pending 区。

4. **前置条件**：pending 条目与现有条目标题相似度 > 85%；
   **操作**：执行 `holmes kb confirm <ID>`；
   **预期结果**：重复检测拦截写入，展示相似条目列表，
   提示用户追加 `--force` 参数才能强制写入。

5. **前置条件**：`git pull` 后出现知识库文件冲突（git conflict markers 存在）；
   **操作**：用户手动执行 `holmes kb merge`；
   **预期结果**：Holmes 读取当前工作区的 git conflict markers，
   自动处理纯新增（保留）、证据追加（合并）、成熟度变更（取适当值）三类情形；
   内容矛盾型冲突隔离至 `contributions/conflicts/` 并提示人工裁决。
   Holmes 不自动执行 `git pull`，不写入 git hooks。

6. **前置条件**：存在待裁决冲突；
   **操作**：执行 `holmes kb resolve <ID> --keep A`；
   **预期结果**：冲突文件移除，选定版本写入正式目录，日志记录操作。

7. **前置条件**：知识库运行一段时间；
   **操作**：执行 `holmes kb lint [--fix]`；
   **预期结果**：输出健康报告（总条目数、pending 数、冲突数、警告/错误列表），
   `--fix` 时自动修复索引不一致问题。

8. **前置条件**：用户想删除某条 pending 条目；
   **操作**：执行 `holmes kb reject <ID> --reason "内容有误"`；
   **预期结果**：条目从 pending 区删除，操作记录写入 `contributions/log.md`。

---

### 用户故事 5 - 知识库内容浏览（优先级：P2）

用户通过 CLI 或在 Holmes Agent 会话中浏览知识库内容，查阅条目详情。

**验收场景**：

1. **前置条件**：知识库有条目；
   **操作**：执行 `holmes kb list [--type pitfall]`；
   **预期结果**：表格展示所有（或指定类型的）条目 ID、类型、成熟度、标题。
2. **前置条件**：知道某条目 ID；
   **操作**：执行 `holmes kb show <ID>`；
   **预期结果**：展示条目完整 Markdown 内容（含 frontmatter）。
3. **前置条件**：Holmes Agent 已加载 KB 原生工具（setup 完成）；
   **操作**：在会话中请求"列出所有数据库类故障条目"；
   **预期结果**：Holmes Agent 调用 `KbSearch` 或 `KbReadCategoryIndex` 原生工具，
   返回结果与 `holmes kb list --type pitfall` 一致。

---

## 系统组成

| 组件 | 技术 | 说明 |
|------|------|------|
| Agent + TUI | holmes-agent（fork 自 claude-code，重命名品牌） | 不自研核心引擎，只做品牌替换和配置扩展 |
| `holmes-kb` Python 包 | Python 3.11+，纯文件系统 | KB 存储、validator、linter、merger、conflict |
| KB 原生工具层 | TypeScript（`buildTool`/`ToolDef`），调用 `holmes-kb` CLI | 以与 `Read`/`Grep` 同等方式集成进 holmes-agent，不走 MCP 协议 |
| `holmes` CLI | click | setup / import / kb 子命令集 |
| holmes-agent Skills | Markdown skill 文件 | `/holmes-resolve`、`/holmes-search` |
| HOLMES.md 模板 | Markdown | 排查规范注入 holmes-agent system prompt |

---

## KB 原生工具清单

工具以 TypeScript 实现，通过 `subprocess` 调用 `holmes-kb` Python 包执行文件系统操作，与 Holmes Agent 内置的 `Read`、`Grep` 工具处于同一层级。

| 工具名（TypeScript） | 读/写 | 说明 |
|----------------------|-------|------|
| `KbReadOverview` | 只读 | README.md + 各类目 _index.md |
| `KbReadCategoryIndex` | 只读 | 指定类目条目索引 |
| `KbReadEntry` | 只读 | 单条知识条目全文 |
| `KbSearch` | 只读 | 按关键词全文搜索 |
| `KbWriteEntry` | 写入 | 将内容写入 pending 区（claude-code 原生权限提示） |
| `KbExtractAndSave` | 写入 | 从会话上下文提取知识写入 pending 区（claude-code 原生权限提示） |
| `KbListPending` | 只读 | 列出 pending 条目 |

---

## holmes-agent Fork 定制需求

holmes-agent 是基于 claude-code 的 fork，需在 fork 基础上完成以下定制，**不修改核心 agent 引擎逻辑**：

### 品牌替换

- **BR-001**：CLI 二进制名从 `ccb`/`claude-code-best` 改为 `holmes`；
  `package.json` 中 `bin` 字段更新为 `{ "holmes": "dist/cli-node.js" }`
- **BR-002**：`src/main.tsx` 中 commander 程序名从 `.name('claude')` 改为 `.name('holmes')`；
  描述从 `Claude Code - ...` 改为 `Holmes - AI-powered knowledge-based troubleshooting assistant`
- **BR-003**：版本字符串从 `${MACRO.VERSION} (Claude Code)` 改为 `${MACRO.VERSION} (Holmes)`；
  所有面向用户的提示文字中 "Claude Code" 替换为 "Holmes"
- **BR-004**：默认配置目录从 `~/.claude` 改为 `~/.holmes`；
  `src/utils/envUtils.ts` 中 `getClaudeConfigHomeDir` 的默认路径由 `join(homedir(), '.claude')`
  改为 `join(homedir(), '.holmes')`，环境变量名保持 `CLAUDE_CONFIG_DIR` 兼容

### 模型配置支持

- **MC-001**：holmes-agent 启动入口（`src/entrypoints/cli.tsx`）在任何模块加载前，
  读取 `$HOLMES_HOME/config.json`（`HOLMES_HOME` 默认为 `~/.holmes`），
  提取以下字段并映射到 OpenAI provider 环境变量：
  - `api_key` → `OPENAI_API_KEY`（仅在该 env 未设置时生效）
  - `api_base_url` → `OPENAI_BASE_URL`（仅在该 env 未设置时生效）
  - `model` → `OPENAI_MODEL`（仅在该 env 未设置时生效）
  - 若 `api_key` 或 `api_base_url` 任一存在，自动设置 `CLAUDE_CODE_USE_OPENAI=1`
- **MC-002**：`holmes setup` 命令支持 `--model`、`--api-key`、`--api-base-url` 参数，
  将模型配置写入 `$HOLMES_HOME/config.json`；
  用户无需手动设置 OpenAI 相关环境变量

---

## 功能需求

- **FR-001**：`holmes setup --kb-path <path>` 将 `HOLMES_KB_PATH` 环境变量写入
  `~/.holmes/settings.json` 的 `env` 字段，并在 KB 根目录生成 HOLMES.md；
  命令输出确认两项均已完成
- **FR-002**：KB 原生工具（`KbReadOverview` 等）以 TypeScript `buildTool`/`ToolDef` 模式
  实现，在 holmes-agent 启动时自动加载，读取 `HOLMES_KB_PATH` 环境变量定位知识库；
  通过 `subprocess` 调用 `holmes-kb` CLI 执行文件系统操作，不依赖 MCP 协议
- **FR-003**：KB 只读工具响应时间 < 200ms（本地文件读取，≤ 1000 条目线性扫描场景下保证）；
  `search.py` 当前实现为线性扫描，接口设计预留索引后端扩展点，未来可替换为倒排索引而不改变上层工具调用方式
- **FR-004**：`KbWriteEntry` 和 `KbExtractAndSave` 通过 `isReadOnly: false` 标记，
  触发 holmes-agent 原生权限确认流程（与 `Write`/`Edit` 工具相同机制）
- **FR-005**：`/holmes-resolve` skill 调用 `KbExtractAndSave` 原生工具完成
  知识提取到 pending 的完整流程，30 秒内完成（不含用户确认等待时间）
- **FR-006**：`holmes import` 使用 LLM 对任意文档进行结构化，
  结果符合 KB Schema，写入 pending 区，60 秒内完成；
  文档内容 < 50 字符时直接拒绝，不调用 LLM
- **FR-007**：`holmes kb confirm` 三项校验：Schema 校验（必填 frontmatter + 类型对应章节）、
  重复检测（Jaccard 相似度 > 85% 阻止写入）、强制预览（用户明确 y/n）；
  通过后系统自动按类型前缀+类目+序号生成永久 ID（扫描目录取最大值+1）
- **FR-008**：`holmes kb merge` 由用户在 `git pull` 后手动触发，
  读取工作区 git conflict markers，处理 5 类冲突场景：
  纯新增 / 证据追加 / 成熟度变更自动处理，内容矛盾隔离至 conflicts 目录；
  Holmes 不自动执行 git 操作，不注册 git hooks
- **FR-009**：`holmes kb lint` 检测并报告索引不一致、成熟度衰减、
  contradiction 标记、超时 pending 条目，`--fix` 时自动修复可程序化问题
- **FR-010**：所有知识条目以 Markdown + YAML frontmatter 存储，
  保证 git diff/merge 原生可用

---

## 成功标准

- **SC-001**：新用户依照文档，10 分钟内完成安装、`holmes setup`、首次 KB 工具调用
- **SC-002**：`holmes kb confirm` 3-gate 拦截 100% 结构残缺条目和相似度 > 85% 的重复条目
- **SC-003**：`holmes kb merge` 对纯新增、证据追加、成熟度变更三类冲突自动处理成功率 100%
- **SC-004**：`/holmes-resolve` 30 秒内完成知识提取并写入 pending 区
- **SC-005**：`holmes import` 60 秒内完成导入，无需用户手动格式化

---

## 澄清记录

### Session 2026-05-27

- Q: pending 条目 confirm 后永久 ID 如何生成？ → A: 系统自动递增——按类型前缀+类目+序号扫描现有条目取最大值+1（如现有 PT-DB-001 则新条目为 PT-DB-002），用户无需手动输入 ID。
- Q: 用户侧文档和场景中统一使用哪个名称？ → A: 全部使用 `holmes`（CLI 命令）和"Holmes Agent"（产品名），不向用户暴露底层 claude-code fork 实现。
- Q: `holmes kb merge` 如何被触发？ → A: 完全手动——用户在 `git pull` 后发现冲突，手动执行 `holmes kb merge`；Holmes 读取当前 git conflict markers 处理，不自动执行 git 操作，不注册 git hooks。
- Q: `holmes import` 对过短内容的最低门槛？ → A: 文档内容 < 50 字符直接拒绝，输出错误提示，不调用 LLM。
- Q: KB 规模预期与 `KbSearch` 性能设计？ → A: 不设硬性上限；设计上预留索引后端扩展接口，当前实现为线性扫描，在 ≤ 1000 条目场景下保证 < 200ms。

---

## 假设前提

- 用户已安装 holmes-agent（基于 claude-code fork 构建，提供 `holmes` 命令）
- 用户已安装 Python 3.11+ 和 git
- 远端知识库在用户 clone 之前已预置基础条目
- holmes-agent 配置目录默认为 `~/.holmes`，`settings.json` 支持 `env` 字段注入环境变量
- 用户自行决定何时 `git push`，holmes 不自动推送
