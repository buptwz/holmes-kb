# 数据模型：基于知识库的问题排查 Agent

**分支**：`001-kb-troubleshooting-agent` | **日期**：2026-05-26

---

## 1. 知识条目（KnowledgeEntry）

**存储位置**：知识库 git 仓库文件系统（Markdown 文件）

### 知识类型与目录结构

参照知识库参考文档，定义 **5 种互斥知识类型**：

| 类型 | 目录 | 定义 | 排查 Agent 适用场景 |
|------|------|------|----------------------|
| **pitfall** | `pitfall/` | 已知风险、故障模式、排查步骤 | 核心类型：记录排查经验和已知坑 |
| **model** | `model/` | 实体定义、数据结构、概念解释 | 理解系统组件和术语 |
| **guideline** | `guideline/` | 推荐做法或禁止做法 | 最佳实践和操作规范 |
| **process** | `process/` | 业务流程、操作步骤、状态机 | 标准操作程序（SOP） |
| **decision** | `decision/` | 技术选型及决策理由 | 架构背景，辅助理解系统设计 |

**文件路径规则**：
```
{kb_root}/{type}/{category}/{slug}.md
```

示例：
```
pitfall/database/redis-connection-pool-exhausted.md
pitfall/network/tcp-connection-timeout.md
model/networking/tcp-ip-basics.md
guideline/system/memory-tuning-checklist.md
process/application/service-restart-procedure.md
```

### 知识成熟度模型

条目遵循三级递进式验证，通过 frontmatter `maturity` 字段标记：

| 级别 | 含义 | 晋升条件 |
|------|------|----------|
| **draft** | 单一来源，新提取或刚导入 | 在 1 次会话中被成功引用 → verified |
| **verified** | 经过 1 次实际排查引用验证 | 在 ≥2 次不同会话中被验证 → proven |
| **proven** | 经多次验证，高可信度 | — |

**自动衰减规则**：
- `proven` 超过 12 个月未被引用 → 降为 `verified`
- `verified` 超过 6 个月未被引用 → 降为 `draft`

### 文件格式（YAML frontmatter + Markdown 正文）

```yaml
---
id: string              # 全局唯一 ID，格式：{TYPE}-{CATEGORY}-{序号}，如 PT-NET-001
title: string           # 条目标题（必填）
type: enum              # "pitfall" | "model" | "guideline" | "process" | "decision"
category: string        # 所属分类目录（如 database, network, system）
tags: list[string]      # 检索标签列表（必填，至少 1 个）
maturity: enum          # "draft" | "verified" | "proven"（默认：draft）
created: date           # 创建日期，ISO 8601：YYYY-MM-DD
updated: date           # 最后更新日期，ISO 8601：YYYY-MM-DD
last_referenced: date   # 最后被会话引用的日期（系统自动更新）
reference_count: int    # 被引用次数（系统自动更新）
source: string          # 来源："auto"（自动提取）| "import"（用户导入）| "manual"
source_session: string  # 来源会话 ID（auto 时填写）
---
```

**ID 命名规则**：

| 类型 | 前缀 | 示例 |
|------|------|------|
| pitfall | PT | PT-DB-001 |
| model | MD | MD-NET-001 |
| guideline | GL | GL-SYS-001 |
| process | PR | PR-APP-001 |
| decision | DC | DC-ARCH-001 |

### 各类型正文结构

**pitfall（已知风险/故障模式）**：

```markdown
## 问题描述

[描述问题现象和触发条件]

## 根因分析

[描述根本原因]

## 解决步骤

1. [步骤 1]
2. [步骤 2]

## 验证方法

[如何确认问题已解决]

## 相关条目

- [可选：相关知识条目 ID]
```

**model（实体/概念定义）**：

```markdown
## 概述

[核心解释，50 字以内]

## 详细说明

[展开说明]

## 示例

[具体示例]
```

**guideline（推荐/禁止做法）**：

```markdown
## 适用场景

[何时应用此 guideline]

## 推荐做法

- [DO: ...]

## 禁止做法

- [DON'T: ...]

## 理由

[为何如此规定]
```

**process（操作步骤）**：

```markdown
## 前置条件

[执行前需满足的条件]

## 步骤

1. [步骤 1]
2. [步骤 2]

## 验证

[步骤完成后如何验证结果]
```

**decision（技术决策）**：

```markdown
## 决策内容

[选择了什么]

## 背景与理由

[为何做此决策]

## 已排除方案

| 方案 | 排除原因 |
|------|----------|
| ... | ... |
```

### 三级渐进式索引

参照参考文档的三层索引设计，知识库根目录维护以下索引文件：

```
{kb_root}/
├── README.md          # 全景目录（~50 行），列出所有类型和顶层分类
├── index.json         # 机器可读索引，仅供 CLI 命令使用（自动生成，不参与 agent 检索）
├── pitfall/
│   ├── _index.md      # pitfall 分类清单（100-300 行），列出本类所有条目摘要
│   └── database/
│       └── redis-connection-pool-exhausted.md   # 完整条目（50-200 行）
├── model/
│   └── _index.md
├── guideline/
│   └── _index.md
├── process/
│   └── _index.md
└── decision/
    └── _index.md
```

`_index.md` 格式示例（`pitfall/_index.md`）：

```markdown
# Pitfall 知识索引

| ID | 标题 | 分类 | 成熟度 | 更新日期 |
|----|------|------|--------|----------|
| PT-DB-001 | Redis 连接池耗尽排查 | database | proven | 2026-05-26 |
| PT-NET-001 | TCP 连接超时排查 | network | verified | 2026-05-20 |
```

**验证规则**：
- `id` 必须在整个知识库中全局唯一
- `title` 不超过 100 字符
- `tags` 至少包含 1 个元素
- `created` ≤ `updated`
- `pitfall` 类型必须包含「问题描述」和「解决步骤」章节
- `maturity` 只能为 `draft`、`verified`、`proven` 之一

---

## 1.5 贡献暂存条目（PendingEntry）

**存储位置**：`{kb_root}/contributions/pending/{user}-{date}-{slug}.md`

**用途**：Agent 自动写入或用户 CLI 导入的知识，在用户确认前存放于暂存区，
不参与正式检索（默认），等待用户 `holmes kb confirm` 后移入正式目录。

**与正式条目的区别**：

| 字段 | pending 条目 | 正式条目 |
|------|-------------|---------|
| 文件路径 | `contributions/pending/` | `{type}/{category}/` |
| `maturity` | 始终为 `draft` | `draft` → `verified` → `proven` |
| 是否参与检索 | 否（默认）| 是 |
| 是否可被 agent 引用 | 否 | 是 |

**frontmatter 额外字段**（pending 专有）：

```yaml
pending: true
pending_since: 2026-05-26T14:45:11Z
source_session: sess-20260526-143022
suggested_type: pitfall
suggested_category: database
```

---

## 1.6 冲突条目（ConflictEntry）

**存储位置**：`{kb_root}/contributions/conflicts/{entry_id}-conflict-{date}.md`

**用途**：`holmes kb merge` 检测到内容矛盾时，将双方版本保存至此目录，
待 maintainer 裁决后解除冲突。

**frontmatter 字段**：

```yaml
conflict_id: PT-DB-003-conflict-20260526
entry_id: PT-DB-003
status: pending_review          # pending_review | resolved
local_author: user-a
remote_author: user-b
created: 2026-05-26
resolved_at: null
resolution: null                # "keep_local" | "keep_remote" | "manual"
```

---

## 2. 知识库索引（KnowledgeIndex）

**存储位置**：`{kb_root}/index.json`（自动生成，非数据源）

**用途**：仅供 CLI 命令（`holmes kb list` / `holmes kb show`）使用，
**不参与 agent 检索**。Agent 通过渐进式读取文件（README.md → _index.md → 条目）导航知识库。
可随时从文件重建，删除不影响 agent 功能。

```json
{
  "version": "1",
  "generated_at": "2026-05-26T14:30:00Z",
  "entry_count": 42,
  "pending_count": 3,
  "conflict_count": 0,
  "entries": [
    {
      "id": "PT-NET-001",
      "title": "TCP 连接超时排查",
      "type": "pitfall",
      "category": "network",
      "tags": ["tcp", "network", "timeout"],
      "maturity": "verified",
      "file_path": "pitfall/network/tcp-connection-timeout.md",
      "updated": "2026-05-26",
      "pending": false
    },
    {
      "id": "PT-DB-003",
      "title": "Redis 连接池耗尽排查",
      "type": "pitfall",
      "category": "database",
      "tags": ["redis", "connection-pool", "database"],
      "maturity": "draft",
      "file_path": "contributions/pending/local-20260526-redis-pool.md",
      "updated": "2026-05-26",
      "pending": true
    }
  ]
}
```

**状态转移**：
```
文件变更（git pull / import / confirm / reject / lint）
    → IndexBuilder.rebuild()       # 重建 index.json 和各 _index.md
    → CLI 命令即可使用最新列表
    （agent 无需此步骤，直接读取文件）
```

---

## 3. 会话（Session）

**存储位置**：`~/.holmes/sessions/{session_id}.json`

**状态机**：

```
active ──(标记解决)──→ resolved ──(生成知识条目)──→ archived
  ↑                                                      │
  └──────────────────────────────────────────────────────┘
                     (删除后可恢复查看，只读)
```

**JSON 结构**：

```json
{
  "id": "sess-20260526-143022",
  "created_at": "2026-05-26T14:30:22Z",
  "updated_at": "2026-05-26T14:45:11Z",
  "status": "active",
  "title": "Redis 连接池耗尽排查",
  "messages": [
    {
      "role": "user",
      "content": "Redis 连接一直报 max clients reached 错误",
      "timestamp": "2026-05-26T14:30:25Z"
    },
    {
      "role": "assistant",
      "content": "这通常是连接池耗尽导致的，让我们逐步排查...",
      "timestamp": "2026-05-26T14:30:28Z",
      "kb_refs": ["PT-DB-001"]
    }
  ],
  "resolved": false,
  "kb_entry_id": null,
  "kb_entry_path": null
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 格式：`sess-{YYYYMMDD}-{HHMMSS}` |
| `status` | enum | `active` \| `resolved` \| `archived` |
| `title` | string | 首次 AI 响应后自动生成（≤50字）|
| `messages[].kb_refs` | list[string] | 本轮响应引用的知识条目 ID |
| `kb_entry_id` | string\|null | 解决后自动生成的知识条目 ID |
| `kb_entry_path` | string\|null | 知识条目在知识库中的相对路径 |

---

## 4. 配置（Configuration）

**存储位置**：`~/.holmes/config.json`（用户级全局配置）

**JSON 结构**：

```json
{
  "version": "1",
  "kb_path": "/path/to/local/knowledge-base",
  "llm": {
    "model": "claude-opus-4-6",
    "api_key_env": "ANTHROPIC_API_KEY",
    "max_tokens": 4096,
    "top_k_results": 3
  },
  "tui": {
    "theme": "dark",
    "language": "zh"
  },
  "sessions_dir": "~/.holmes/sessions"
}
```

**验证规则**：
- `kb_path` 必须是有效的 git 仓库目录路径
- `kb_path` 目录下必须存在 `index.json` 或可构建索引
- `llm.api_key_env` 指定的环境变量必须已设置
- `llm.top_k_results` 范围：1–10

---

## 5. IPC 消息（IPCMessage）

**用途**：TUI ↔ Python Agent 通信的消息信封

**基础结构**（JSON-RPC 2.0）：

```typescript
// 请求
interface IPCRequest {
  jsonrpc: '2.0';
  id: string;          // UUID
  method: string;      // 方法名，见 contracts/ipc-protocol.md
  params: unknown;
}

// 响应
interface IPCResponse {
  jsonrpc: '2.0';
  id: string;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}

// 流式通知（无 id，服务端主动推送）
interface IPCNotification {
  jsonrpc: '2.0';
  method: 'agent/token' | 'agent/done' | 'agent/error';
  params: unknown;
}
```

---

## 6. 知识库导入请求（ImportRequest）

**用途**：CLI `holmes import` 命令的输入数据结构

```python
@dataclass
class ImportRequest:
    source_path: str             # 源文件路径（绝对路径）
    target_type: str | None      # 可选；None 时由 LLM 自动推断
    target_category: str | None  # 可选；None 时由 LLM 自动推断
    title: str | None            # 可选；None 时从文件内容提取
    tags: list[str]              # 可为空；系统自动提取后可追加
    dry_run: bool = False        # True 时只输出识别结果，不写入

@dataclass
class ImportClassification:
    """LLM 对导入文件的自动识别结果"""
    type: str           # "pitfall" | "model" | "guideline" | "process" | "decision"
    category: str       # 推断的分类目录（如 "database"、"network"）
    title: str          # 提取的标题
    tags: list[str]     # 提取的标签列表
    confidence: str     # "high" | "medium" | "low"
    reasoning: str      # 识别依据（简短说明，展示给用户）
```

**自动识别流程**：

```
holmes import <file>
    │
    ├── 用户未指定 --type / --category
    │       → LLM 读取文件全文
    │       → 返回 ImportClassification
    │       → 终端展示识别结果
    │       → 写入 contributions/pending/
    │
    └── 用户指定了 --type（或 --category）
            → 跳过对应字段的 LLM 推断
            → 直接使用指定值
            → 未指定的字段仍由 LLM 推断
```

**识别提示词策略**（发给 LLM 的指令）：

```
给定以下文档内容，判断它属于哪种知识类型：
- pitfall：描述已知问题、故障现象、排查步骤或解决方案
- model：定义概念、实体、数据结构或术语
- guideline：提出推荐做法或禁止行为
- process：描述操作步骤、工作流程或状态机
- decision：记录技术选型或架构决策及其理由

同时推断：所属分类（如 database/network/system/application）、
标题（50 字以内）、标签（3-6 个关键词）。
```

---

## 7. 实体关系图

```
配置（Configuration）
    ├── kb_path → 知识库（KnowledgeBase，git 仓库）
    │                ├── 知识条目（KnowledgeEntry，.md 文件）
    │                └── 知识库索引（KnowledgeIndex，index.json）
    └── sessions_dir → 会话目录
                          └── 会话（Session，.json 文件）
                               ├── messages[].kb_refs → 知识条目.id
                               └── kb_entry_id → 知识条目.id（解决后生成）
```
