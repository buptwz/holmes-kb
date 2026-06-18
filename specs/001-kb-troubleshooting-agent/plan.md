# 实现方案：基于知识库的问题排查 Agent

**分支**：`001-kb-troubleshooting-agent` | **日期**：2026-05-26 | **规格**：[spec.md](spec.md)

---

## 摘要

Holmes 的核心价值有两点：

1. **知识库生命周期管理**：从知识导入、结构化、暂存审阅、确认入库、冲突合并，到健康检查——构建一套围绕 Markdown + YAML frontmatter 的完整 KB 生命周期工具链（`holmes-kb` Python 包）。
2. **Agent 与知识库联动**：将 KB 能力以原生工具（`buildTool`/`ToolDef`）的形式嵌入 holmes-agent，使 Agent 能无缝读取知识、提取经验写回 KB；同时通过 `/holmes-resolve` skill 和 HOLMES.md 将排查规范注入 Agent 上下文。

**不自研 Agent 引擎与 TUI**。holmes-agent 是对 claude-code 的轻量 fork，只做品牌替换、配置目录切换、模型配置加载三项改动，核心 agentic 引擎和 TUI 原封不动复用。

---

## 架构全景

```text
用户
 │
 ▼
holmes-agent（fork of claude-code）          ← TUI + agentic 引擎（不自研）
 │  启动时读 ~/.holmes/config.json           ← MC-001：模型配置注入
 │  配置目录 ~/.holmes/                      ← BR-004：品牌替换
 │
 ├─ HOLMES.md（系统提示注入）                ← 排查规范上下文
 │
 ├─ KB 原生工具（TypeScript, buildTool）      ← Agent-KB 联动核心
 │   ├─ KbReadOverview / KbSearch            ← 检索侧：Agent 主动查阅 KB
 │   ├─ KbReadCategoryIndex / KbReadEntry    ← 检索侧
 │   ├─ KbExtractAndSave                     ← 写入侧：排查结束提取知识
 │   ├─ KbWriteEntry                         ← 写入侧：直接写入 pending
 │   └─ KbListPending                        ← 查看侧
 │       │
 │       └─ subprocess → holmes-kb CLI       ← Python 包，文件系统操作
 │
 └─ Skills（Markdown 文件）
     └─ /holmes-resolve                      ← 触发 KbExtractAndSave

holmes-kb Python 包                          ← KB 生命周期管理核心
 ├─ store.py          文件系统读写（条目 CRUD）
 ├─ importer.py       LLM 结构化导入（任意文档 → KB Schema）
 ├─ validator.py      3-gate confirm（Schema + 重复检测 + 强制预览）
 ├─ pending.py        暂存区管理
 ├─ merger.py         智能合并（5 类冲突场景）
 ├─ conflict.py       冲突条目隔离与裁决
 ├─ linter.py         健康检查（lint / --fix）
 └─ cli.py            holmes CLI（setup / import / kb 子命令集）
```

---

## 技术上下文

**语言/版本**：
- holmes-agent：TypeScript（Bun ≥ 1.3），fork 自 `/home/wangzhi/project/claude-code`
- holmes-kb + CLI：Python 3.11+

**主要依赖**：
- holmes-agent：在 claude-code 原有依赖基础上不增加外部依赖
- holmes-kb：`python-frontmatter`、`openai`（OpenAI-compatible SDK）、`click`、`pydantic`
- 代码风格（TS）：biome（沿用 claude-code 已有配置）
- 代码风格（Python）：ruff（Google style 规则集）

**存储**：文件系统（禁止使用任何数据库）

**测试**：
- Python：pytest + pytest-asyncio
- TypeScript：bun:test（沿用 claude-code）

**目标平台**：Linux（Ubuntu，已装 git、Python 3.11+）

---

## 宪法检查（Constitution Check）

| 原则 | 状态 | 说明 |
|------|------|------|
| 软件工程原则（SOLID + 合成复用） | ✅ | KB 生命周期各阶段单一职责（store/validator/merger/linter 独立模块）；原生工具通过 subprocess 边界与 Python 解耦 |
| 环境配置原则 | ✅ | 模型配置通过 `~/.holmes/config.json` 外部化；`HOLMES_HOME`/`HOLMES_KB_PATH` 环境变量覆盖默认路径 |
| 验证原则 | ✅ | pytest 覆盖 KB 生命周期全流程；confirm 3-gate 有独立单元测试 |
| 渐进式实现原则 | ✅ | fork 改动最小化；KB 工具先只读、后写入；先 P1 故事再 P2 |
| 可观测性原则 | ✅ | Python 使用 `logging`；KB 写操作追加 `contributions/log.md` |
| 代码规范 | ✅ | Python: ruff (Google)；TypeScript: biome |
| 安全 | ✅ | API Key 只读环境变量；KB 写入工具通过 `isReadOnly: false` 触发 Agent 原生权限确认；不暴露诊断命令执行（复用 claude-code 原生 Bash 工具） |
| 最小化改动原则 | ✅ | holmes-agent fork 改动仅限品牌替换、配置路径、启动配置加载，不触及核心引擎 |

---

## 项目结构

### 设计文档（本功能）

```text
specs/001-kb-troubleshooting-agent/
├── plan.md              # 本文件
├── research.md          # 技术调研
├── data-model.md        # 数据模型
├── quickstart.md        # 快速入门
├── contracts/
│   └── cli-schema.md    # CLI 命令接口规范
└── tasks.md             # 任务列表
```

### 源代码结构

```text
holmes/
│
├── agent/                                   # holmes-agent：fork 自 claude-code
│   │                                        # 仅做三项改动，不动核心引擎
│   ├── src/
│   │   ├── entrypoints/
│   │   │   └── cli.tsx                      # +MC-001：启动时加载 ~/.holmes/config.json
│   │   ├── utils/
│   │   │   └── envUtils.ts                  # +BR-004：默认配置目录改为 ~/.holmes
│   │   ├── main.tsx                         # +BR-002/003：CLI 名/描述/版本字符串替换
│   │   └── tools/
│   │       └── kb/                          # KB 原生工具（新增，Agent-KB 联动核心）
│   │           ├── KbReadOverview.ts
│   │           ├── KbReadCategoryIndex.ts
│   │           ├── KbReadEntry.ts
│   │           ├── KbSearch.ts
│   │           ├── KbWriteEntry.ts          # isReadOnly: false
│   │           ├── KbExtractAndSave.ts      # isReadOnly: false
│   │           ├── KbListPending.ts
│   │           └── index.ts                 # 注册到 tools.ts
│   ├── skills/
│   │   ├── holmes-resolve.md                # /holmes-resolve skill
│   │   └── holmes-search.md                 # /holmes-search skill
│   ├── HOLMES.md                            # 排查规范（系统提示模板）
│   └── package.json                         # +BR-001：bin 改为 "holmes"
│
├── kb/                                      # holmes-kb：KB 生命周期管理核心
│   ├── holmes/
│   │   ├── __init__.py
│   │   ├── kb/
│   │   │   ├── __init__.py
│   │   │   ├── store.py                     # 条目 CRUD（文件系统，纯读写）
│   │   │   ├── importer.py                  # LLM 结构化：任意文档 → KB Schema
│   │   │   ├── validator.py                 # confirm 3-gate（Schema+重复检测+强制预览）
│   │   │   ├── pending.py                   # 暂存区 CRUD（pending/confirm/reject）
│   │   │   ├── merger.py                    # 智能合并（5 类 git 冲突场景）
│   │   │   ├── conflict.py                  # 冲突隔离与裁决（conflicts/ 目录）
│   │   │   ├── linter.py                    # 健康检查（lint/--fix）
│   │   │   └── search.py                    # 全文关键词检索（纯文件系统，无索引引擎）
│   │   └── cli.py                           # holmes CLI：setup/import/kb 子命令集
│   ├── tests/
│   │   ├── test_store.py
│   │   ├── test_importer.py
│   │   ├── test_validator.py
│   │   ├── test_pending.py
│   │   ├── test_merger.py
│   │   └── test_linter.py
│   ├── pyproject.toml
│   └── ruff.toml
│
├── kb-template/                             # 知识库起始模板（供用户 clone）
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── pitfall/
│   │   ├── _index.md
│   │   ├── network/
│   │   ├── system/
│   │   ├── application/
│   │   └── database/
│   ├── model/
│   │   └── _index.md
│   ├── guideline/
│   │   └── _index.md
│   ├── process/
│   │   └── _index.md
│   ├── decision/
│   │   └── _index.md
│   └── contributions/
│       ├── pending/
│       ├── conflicts/
│       └── log.md
│
└── docs/
    ├── quickstart.md
    ├── user-guide.md
    └── developer-guide.md
```

---

## 知识库生命周期设计

知识库是 Holmes 的核心资产，所有 KB 操作均以 Markdown + YAML frontmatter 为存储单元，保证 git diff/merge 原生可用。

### 条目类型与 Schema

```yaml
# pitfall 条目（最常见）
---
id: PT-DB-001
type: pitfall
title: Redis 连接池耗尽
maturity: draft | verified | deprecated
category: network | system | application | database
tags: [redis, connection-pool]
created_at: "2026-05-26"
updated_at: "2026-05-26"
---
## Symptoms
## Root Cause
## Resolution
## Prevention   # optional
```

其他类型（model/guideline/process/decision）有各自对应的必需章节，详见 [data-model.md](data-model.md)。

### 生命周期流转

```text
外部文档 ──holmes import──▶ contributions/pending/
                                    │
排查会话 ──/holmes-resolve──▶       │  (KbExtractAndSave 写入)
                                    │
                          holmes kb pending（查看）
                                    │
                          holmes kb confirm <ID>
                           ├─ [gate 1] Schema 校验
                           ├─ [gate 2] 重复检测（Jaccard > 85% 拦截）
                           └─ [gate 3] 强制预览（y/n）
                                    │ 通过
                          pitfall/ | model/ | ...（正式目录）
                                    │
                          git add / git commit / git push（用户手动）
                                    │
                          git pull + holmes kb merge
                           ├─ 纯新增 → 自动保留
                           ├─ 证据追加 → 自动合并
                           ├─ 成熟度变更 → 取适当值
                           └─ 内容矛盾 → contributions/conflicts/（人工裁决）
                                    │
                          holmes kb resolve <ID> --keep A|B
```

### confirm 三级门控详设

| Gate | 实现 | 失败行为 |
|------|------|---------|
| Schema 校验 | `validator.py`：检查必填 frontmatter 字段 + 类型对应章节是否完整 | 输出缺失项，条目留 pending |
| 重复检测 | `validator.py`：对所有正式条目标题计算 Jaccard 相似度，> 85% 拦截 | 展示相似条目，提示 `--force` 强制写入 |
| 强制预览 | `pending.py`：打印条目全文，等待用户 y/n | 用户输入 n → 条目留 pending |

### merger.py 冲突分类

| 场景 | 判断依据 | 处理方式 |
|------|---------|---------|
| 纯新增 | 一方新增，另一方无该文件 | 自动保留新增 |
| 证据追加 | 同一 id，仅 Resolution/Prevention 章节追加 | 自动合并追加内容 |
| 成熟度变更 | 仅 maturity 字段不同 | 取较高成熟度值 |
| 字段更新 | 非内容字段（tags/category）冲突 | 取较新版本 |
| 内容矛盾 | Root Cause 或 Resolution 正文有实质性冲突 | 隔离至 conflicts/，提示人工裁决 |

---

## Agent-KB 联动设计

### KB 原生工具实现模式

每个工具以 TypeScript `buildTool`/`ToolDef` 模式实现，通过 `subprocess` 调用
`holmes-kb` CLI，不走 MCP 协议：

```typescript
// 示例：KbSearch.ts
export const KbSearch = buildTool({
  name: 'KbSearch',
  description: '在知识库中按关键词全文搜索，返回匹配条目列表',
  isReadOnly: true,
  inputSchema: z.object({ query: z.string(), limit: z.number().optional() }),
  async execute({ query, limit = 5 }) {
    const kbPath = process.env.HOLMES_KB_PATH ?? ''
    const result = await execa('holmes', ['kb', 'search', query,
      '--kb-path', kbPath, '--limit', String(limit), '--json'])
    return result.stdout
  },
})

// KbExtractAndSave.ts：写入工具，触发原生权限确认
export const KbExtractAndSave = buildTool({
  name: 'KbExtractAndSave',
  description: '从当前会话提取排查经验，结构化后写入知识库 pending 区',
  isReadOnly: false,   // 触发 holmes-agent 原生权限提示
  inputSchema: z.object({ summary: z.string(), type: z.string().optional() }),
  async execute({ summary, type = 'pitfall' }) {
    // ...
  },
})
```

### /holmes-resolve Skill

```markdown
# holmes-resolve

用户执行此 skill 时，调用 KbExtractAndSave 工具，
从当前会话提取排查思路，结构化为 KB Schema 格式，写入 pending 区。

## 执行步骤
1. 总结本次排查的 Symptoms、Root Cause、Resolution
2. 调用 KbExtractAndSave 工具写入 pending
3. 输出 pending ID，提示用户执行 `holmes kb confirm <ID>` 完成入库
```

### HOLMES.md 系统提示注入

HOLMES.md 放置于知识库根目录，holmes-agent 启动时自动载入，内容包含：
- 排查方法论（先读 KB 概览，再精准检索，再读全文）
- 知识更新规范（排查成功后执行 `/holmes-resolve`）
- KB 工具使用提示

---

## holmes-agent Fork 改动清单

改动严格限制在以下 4 处，不涉及 agentic 引擎：

| 文件 | 改动内容 | 对应需求 |
|------|---------|---------|
| `package.json` | `bin` 字段改为 `{ "holmes": "dist/cli-node.js" }` | BR-001 |
| `src/main.tsx` | `.name('holmes')`、description、version 字符串中的品牌文字 | BR-002/003 |
| `src/utils/envUtils.ts` | `getClaudeConfigHomeDir` 默认路径改为 `~/.holmes` | BR-004 |
| `src/entrypoints/cli.tsx` | 最早期读取 `$HOLMES_HOME/config.json`，注入 `OPENAI_*` 环境变量并激活 openai provider | MC-001 |

**新增文件**（不修改现有文件逻辑）：
- `src/tools/kb/` — KB 原生工具（7 个）
- `skills/holmes-resolve.md`、`skills/holmes-search.md`
- `HOLMES.md`（模板）

---

## Phase 0：技术调研（已完成）

- **知识库格式**：Markdown + YAML frontmatter，渐进式文件读取（无检索引擎）
- **Agent 框架**：复用 claude-code（fork），不重实现
- **工具集成**：TypeScript `buildTool`/`ToolDef` 原生工具，subprocess 调用 Python CLI
- **模型配置**：`~/.holmes/config.json` → `OPENAI_*` env vars → claude-code openai provider 路径
- **IPC**：不需要自建，复用 claude-code 内部机制

---

## Phase 1：设计产物（已完成）

- [data-model.md](data-model.md) — 知识条目 Schema、KB 目录结构、配置文件格式
- [contracts/cli-schema.md](contracts/cli-schema.md) — CLI 命令接口规范（`holmes setup / import / kb`）
- [quickstart.md](quickstart.md) — 安装配置与使用指南

---

## Phase 2：实现规划

### 工作流 A：holmes-kb（KB 生命周期管理）— 核心价值

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P1 | `store.py` | 条目 CRUD，文件系统操作基础 |
| P1 | `search.py` | 全文关键词检索（供 KB 工具调用） |
| P1 | `pending.py` | 暂存区 CRUD（list/write/confirm/reject） |
| P1 | `validator.py` | confirm 3-gate（Schema + Jaccard 重复检测 + 强制预览） |
| P1 | `importer.py` | LLM 结构化导入（`holmes import` 命令） |
| P1 | `cli.py` | `holmes setup / import / kb` 命令集 |
| P2 | `merger.py` | 5 类 git 冲突场景智能合并（`holmes kb merge`） |
| P2 | `conflict.py` | 冲突条目隔离与人工裁决（`holmes kb resolve`） |
| P2 | `linter.py` | 健康检查与自动修复（`holmes kb lint --fix`） |

### 工作流 B：Agent-KB 联动 — 核心价值

| 优先级 | 内容 | 说明 |
|--------|------|------|
| P1 | KB 只读原生工具（4 个） | `KbReadOverview` / `KbSearch` / `KbReadCategoryIndex` / `KbReadEntry` |
| P1 | HOLMES.md 模板 | 排查规范系统提示 |
| P1 | `/holmes-resolve` skill | 排查结束触发知识提取 |
| P2 | KB 写入原生工具（3 个） | `KbExtractAndSave` / `KbWriteEntry` / `KbListPending` |
| P2 | `/holmes-search` skill | 主动知识检索 |

### 工作流 C：holmes-agent Fork — 支撑层

| 优先级 | 内容 | 说明 |
|--------|------|------|
| P1 | 品牌替换（BR-001~004） | CLI 名、描述、版本字符串、配置目录 |
| P1 | 模型配置加载（MC-001） | 启动时读 `config.json` → OPENAI 环境变量 |
| P1 | `holmes setup` 命令（MC-002） | 写入 KB 路径 + 模型配置 |

### 实现顺序

```
Week 1: 工作流A（P1）+ 工作流C（P1）
  → holmes-kb P1 模块 + fork 品牌替换 + holmes setup 命令

Week 2: 工作流B（P1）+ 工作流A（P2 部分）
  → KB 只读工具 + HOLMES.md + /holmes-resolve + merger/conflict

Week 3: 工作流B（P2）+ 工作流A（P2 收尾）+ 测试
  → KB 写入工具 + linter + 集成测试 + 文档
```

---

## 成功标准与验收

| 标准 | 验收方式 |
|------|---------|
| SC-001：10 分钟完成安装配置首次调用 | quickstart.md 指引走通，KB 工具被调用 |
| SC-002：confirm 3-gate 拦截率 100% | 单元测试：残缺条目 + 相似度 > 85% 各 5 个用例 |
| SC-003：merge 自动处理率 100%（纯新增/证据追加/成熟度变更） | 单元测试：每类 3 个用例 |
| SC-004：/holmes-resolve 30s 内完成 | 集成测试：mock LLM，计时 |
| SC-005：holmes import 60s 内完成 | 集成测试：真实 LLM 调用，计时 |
