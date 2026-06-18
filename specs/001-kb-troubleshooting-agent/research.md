# 技术调研报告：基于知识库的问题排查 Agent

**分支**：`001-kb-troubleshooting-agent` | **日期**：2026-05-26

---

## 1. FR-015 决策：成功排查触发机制

**决策**：用户在 TUI 中通过明确操作（"标记为已解决"按键/命令）主动触发知识提取。

**理由**：
- 排查是否成功是业务语义判断，非技术可自动检测的信号
- 避免误触发：用户说"谢谢"不代表问题已解决
- 用户主动操作提供了明确的确认语义，与知识入库的"质量把关"对齐
- 与 User Story 3 的验收场景完全匹配

**已排除替代方案**：
- Agent 自动检测（误判率高，不可靠）
- 两者兼备（复杂度增加，当前阶段无明确收益）

---

## 2. 架构模式选择：TUI ↔ Agent IPC 通信

**决策**：TUI（TypeScript）与 Python Agent 通过 **JSON-RPC over Unix domain socket** 通信。

**理由**：
- Unix socket 比 TCP 快（本地通信），比 stdin/stdout 更适合并发请求
- JSON-RPC 2.0 是标准协议，有成熟实现
- 支持流式响应（通过通知消息 `agent/token`）
- TUI 进程启动 Python agent 子进程，管理其生命周期
- 与 claude-code 的 MCP 子进程通信模式一致

**已排除替代方案**：

| 方案 | 排除原因 |
|------|----------|
| stdin/stdout | 难以支持并发/流式，调试困难 |
| HTTP REST | 端口管理复杂，启动开销大 |
| gRPC | 依赖重，超出当前需求 |

---

## 3. 知识库存储方案

**决策**：纯文件系统存储，Markdown 文件 + YAML frontmatter，无任何数据库。
参照知识库参考文档（李米娜 / https://zhuanlan.zhihu.com/p/2032094280060252204）的设计理念。

**理由**：
- 完全满足"不允许使用数据库"约束
- Git 友好：每个知识条目是独立文件，冲突解决粒度合理
- 人类可读，无需工具即可直接编辑
- 知识条目与 git commit 自然对应，历史可追溯

**知识类型（5 种互斥，来自参考文档）**：

| 类型 | 目录 | 说明 |
|------|------|------|
| pitfall | `pitfall/` | 已知风险、故障模式、排查步骤（Holmes 核心类型）|
| model | `model/` | 实体定义、数据结构、概念解释 |
| guideline | `guideline/` | 推荐/禁止做法 |
| process | `process/` | 操作步骤、工作流程 |
| decision | `decision/` | 技术选型及架构决策 |

**目录结构（自定义，遵循参考文档设计理念）**：

```
knowledge-base/
├── README.md              # 全景目录（~50 行）
├── index.json             # 机器可读索引，自动生成，可重建
├── pitfall/
│   ├── _index.md          # pitfall 分类清单（100-300 行）
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── model/
│   ├── _index.md
│   └── ...
├── guideline/
│   ├── _index.md
│   └── ...
├── process/
│   ├── _index.md
│   └── ...
└── decision/
    ├── _index.md
    └── ...
```

**知识成熟度模型（来自参考文档）**：
- `draft` → `verified`（1 次会话引用后）→ `proven`（≥2 次不同会话验证后）
- 自动衰减：proven 12 月未引用降级，verified 6 月未引用降级

**条目 frontmatter 关键字段**：
`id`（如 PT-DB-001）、`type`、`maturity`、`last_referenced`、`reference_count`

---

## 4. 知识检索方式

**决策**：Agent（LLM）通过工具调用直接读取知识库文件，遵循**渐进式披露**原则，
不引入任何检索引擎、向量库或 BM25。

**理由**：
- 知识库三层索引结构天然支持渐进式读取，LLM 可自主导航
- 无需额外依赖（移除 `rank_bm25`），完全符合渐进式实现原则
- LLM 理解语义，比关键词匹配更适合模糊的排查问题描述
- `index.json` 保留，仅供 CLI 命令（`holmes kb list`）使用，不参与 agent 检索

**渐进式披露检索流程**：

```
用户提问
    │
    ▼
Agent 调用 kb_read_overview()
    → 读取 README.md（~50 行，全景目录）
    → 判断相关类型（pitfall? model? guideline?）
    │
    ▼
Agent 调用 kb_read_category_index(type)
    → 读取 {type}/_index.md（100-300 行，条目摘要列表）
    → 识别最相关的 1-3 个条目 ID
    │
    ▼
Agent 调用 kb_read_entry(entry_id)
    → 读取完整条目文件（50-200 行）
    → 将内容纳入回复上下文
    │
    ▼
生成排查响应，标注引用的条目 ID
```

**工具定义（3 个 KB 读取工具）**：

| 工具名 | 输入 | 读取目标 | 典型上下文消耗 |
|--------|------|---------|--------------|
| `kb_read_overview` | 无 | `README.md` | ~50 行 |
| `kb_read_category_index` | `type: str` | `{type}/_index.md` | 100-300 行 |
| `kb_read_entry` | `entry_id: str` | `{type}/{category}/{slug}.md` | 50-200 行 |

**已排除替代方案**：

| 方案 | 排除原因 |
|------|---------|
| BM25 全文检索 | 额外依赖，增加复杂度；LLM 语义理解更优 |
| 向量数据库 | 违反"禁止数据库"约束 |
| 预填充 system prompt | 盲注全部 KB 内容浪费 token，且无法按需深入 |

---

## 5. Agent 框架适配方案（claude-code → Holmes）

**决策**：参照 claude-code 的 `QueryEngine` 架构模式，用 Python 重新实现适配排查场景的 Agent 引擎。

**claude-code 核心模式对应**：

| claude-code 组件 | Holmes Python 对应 | 变化 |
|------------------|--------------------|------|
| `QueryEngine.ts` | `agent/engine.py` | 替换 Anthropic SDK 调用，注册 KB 读取工具 |
| `Tool.ts`（接口） | `agent/tools/base.py` | 适配 Python 抽象基类 |
| `BashTool` 等 | `tools/kb_read.py`（3 个工具）, `tools/kb_write.py` | 替换为 KB 读取和写入工具 |
| `sessionStorage.ts` | `agent/session.py` | 同等 JSON 文件存储 |
| `REPL.tsx` | `tui/src/screens/REPL.tsx` | 保留 React/Ink，替换 QueryEngine 调用 |
| `coordinatorMode.ts` | 不需要（单 agent 模式） | 简化 |

**TUI 适配范围**：
- **保留**：React/Ink 基础框架、VirtualMessageList、键盘绑定、主题系统
- **替换**：QueryEngine → HolmesIPCClient（JSON-RPC 客户端）
- **新增**：KnowledgeBrowser 屏幕、SessionList 屏幕
- **移除**：代码相关工具（BashTool、FileEditTool 等）

---

## 6. LLM 集成

**决策**：使用 Anthropic Python SDK，支持流式输出。

**理由**：
- 项目参考 claude-code，LLM 为 Claude 系列（与 constitution 中的知识来源一致）
- 官方 SDK 稳定，文档完整
- 支持 `stream=True` 流式响应，配合 SSE 通知传回 TUI

**上下文组装策略**：

```
系统提示 = 基础排查角色 system prompt（静态，不预填充知识）
用户提示 = 对话历史 + 当前问题
工具     = [kb_read_overview, kb_read_category_index, kb_read_entry,
             kb_write_entry]
```

Agent 按需调用 KB 读取工具，渐进式获取所需知识，而非一次性注入。

---

## 7. 会话存储方案

**决策**：JSON 文件存储，每个会话一个文件，存放于 `~/.holmes/sessions/`。

**结构**：

```json
{
  "id": "sess-20260526-143022",
  "created_at": "2026-05-26T14:30:22Z",
  "updated_at": "2026-05-26T14:45:11Z",
  "status": "active",
  "title": "Redis 连接池耗尽排查",
  "messages": [
    {"role": "user", "content": "...", "timestamp": "..."},
    {"role": "assistant", "content": "...", "timestamp": "..."}
  ],
  "resolved": false,
  "kb_entry_id": null
}
```

**理由**：
- 无数据库，完全文件系统
- 单文件即为完整会话，便于查看和备份
- Git 可选跟踪会话历史

---

## 8. 代码风格工具链

**决策**：
- Python：`ruff`（linting + formatting，符合 Google style guide）
- TypeScript：ESLint（`@google/eslint-plugin-typescript-googlelint` 风格）+ Prettier

**理由**：
- `ruff` 是最快的 Python linter，配置 Google style 规则集（`E`, `W`, `F`, `I`, `N`）
- ESLint + Prettier 是用户明确要求
- 两者都支持 CI 集成和 pre-commit hooks

---

## 9. 技术栈汇总

| 层次 | 语言/运行时 | 主要依赖 |
|------|-----------|---------|
| TUI | TypeScript / Bun | React, @anthropic/ink, ink |
| Agent | Python 3.11+ | anthropic, python-frontmatter, pydantic（importer 用 LLM 推断类型）|
| 知识库 | Python 3.11+ | python-frontmatter, pathlib（标准库） |
| IPC | JSON-RPC 2.0 | Unix socket（标准库） |
| 测试（Python） | pytest | pytest-asyncio, pytest-cov |
| 测试（TS） | bun:test | — |
| 代码风格（Python） | ruff | Google style 规则集 |
| 代码风格（TS） | ESLint + Prettier | — |
