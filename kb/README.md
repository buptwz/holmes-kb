# Holmes KB

NPI 硬件故障知识库管理系统。将故障处理文档自动提取为结构化知识条目，供 AI Agent 通过 MCP 协议浏览使用。

## 快速开始

```bash
# 安装
pip install -e .

# 初始配置
holmes setup

# 导入一份故障文档
holmes import docs/redis-oom-postmortem.md

# 查看待审条目
holmes pending

# 审批通过
holmes approve <entry-id>

# 启动 MCP 服务，供 Agent 使用
holmes start
```

## 核心概念

### 条目类型

| 类型 | 说明 | 内容结构 |
|------|------|----------|
| pitfall | 已知故障模式 | Symptoms → Root Cause → Resolution（可多分支） |
| process | 标准操作流程 | Purpose → Steps → Outcome → Rollback |
| model | 概念解释 / 心智模型 | Overview → Key Concepts → Usage |
| guideline | 操作规范 / 最佳实践 | Context → Guideline → Rationale |
| decision | 架构决策记录 | Context → Decision → Rationale |

一份源文档 → 恰好一个条目。不拆分，不合并。

### 条目成熟度

| 成熟度 | 含义 | 升降规则 |
|--------|------|----------|
| draft | 未验证 | 导入后初始状态 |
| verified | 已验证 | Agent 使用并确认解决了问题（≥1 次） |
| proven | 已证实 | 多个用户/会话确认有效（≥2 次） |

升级：Agent 调用 `kb_confirm` 记录使用证据，自动升级。
降级：`holmes decay` 定期执行，长期未使用的条目自动降级（proven 12个月→verified，verified 6个月→draft）。

## 知识库目录结构

```
holmes-kb/
│
├── pitfall/<category>/<id>.md      正式条目（已审批）
├── guideline/<category>/<id>.md
├── process/<category>/<id>.md
├── model/<category>/<id>.md
├── decision/<category>/<id>.md
│
├── _drafts/                        草稿（Agent 通过 kb_draft 保存，等待 import）
├── _pending/<type>/<category>/     待审批（import 后自动生成，等待 approve）
├── _trash/<type>/<category>/       回收站（delete 后软删除）
│
├── skills/<name>/SKILL.md          可执行技能（Anthropic Agent 指令格式）
│
├── contributions/
│   ├── evidence/<id>/              使用证据（Agent kb_confirm 自动写入）
│   ├── archive/                    归档条目
│   └── log.md                      操作日志
│
├── .history/                       版本快照（decay 降级前自动保存）
└── index.json                      条目索引（自动生成）
```

路径规律：`_` 前缀 = 临时/待处理，无前缀 = 正式生效。

## 条目生命周期

```
源文档 ──► holmes import ──► _pending/ ──► holmes approve ──► 正式条目
                                                                    │
                                                          Agent 使用并确认
                                                                    │
                                                           evidence 累积
                                                         draft → verified → proven
                                                                    │
                                                          长期未使用 (decay)
                                                         proven → verified → draft
```

## CLI 命令

### 导入

```bash
holmes import <file>              # 导入单个文档
holmes import --dir <dir>         # 批量导入目录
holmes import --dry-run <file>    # 预览，不实际写入
```

### 知识库管理

```bash
holmes list                       # 列出所有条目
holmes list --type pitfall        # 按类型筛选
holmes show <id>                  # 查看条目内容
holmes pending                    # 查看待审条目
holmes approve <id>               # 审批通过
holmes delete <id>                # 软删除到回收站
holmes overview --json            # 知识库概览
holmes doctor                     # 自诊断
holmes doctor --fix               # 自诊断 + 自动修复
holmes decay                      # 执行成熟度衰减
```

### 配置

```bash
holmes setup                      # 交互式初始配置
holmes config set api_key <key>   # 设置 API Key
holmes config set kb_path <path>  # 设置知识库路径
holmes config show                # 查看当前配置
```

## MCP 服务

Holmes 通过 MCP (Model Context Protocol) 将知识库暴露给 AI Agent。MCP 是纯透传通道——Agent 像浏览本地目录一样浏览知识库，自行判断哪些条目相关。

### 启动

```bash
holmes start                      # 默认端口 8765
holmes start --port 9000          # 自定义端口
```

### MCP 工具

Agent 连接后可使用 4 个工具：

| 工具 | 用途 | 说明 |
|------|------|------|
| `kb_browse` | 浏览目录 | 返回条目列表（title + brief），支持 type/category 过滤和分页 |
| `kb_read` | 读取内容 | 默认返回结构化摘要；`full=true` 返回完整内容 |
| `kb_confirm` | 记录结果 | 条目帮助解决问题后记录证据（solved / not_solved） |
| `kb_draft` | 保存草稿 | Agent 发现新知识时保存草稿，等待人工 import |

### Agent 使用流程

```
用户报告问题
  → kb_browse()                    浏览目录，扫描 title + brief
  → kb_browse(type='pitfall')      按类型缩小范围（可选）
  → kb_read(<id>)                  读摘要：症状、根因、解决路径概览
  → 确认匹配
  → kb_read(<id>, full=true)       读完整内容：逐步引导工程师排查
  → 问题解决 → kb_confirm(<id>, <session_id>, outcome='solved')
  → KB 中没有 → 解决后 → kb_draft(<完整描述>)
```

**行为标签**：条目中的步骤带有行为标签，指导 Agent 如何执行：

| 标签 | 含义 | Agent 行为 |
|------|------|-----------|
| `[api]` | 执行命令 | 运行命令并检查输出 |
| `[physical]` | 物理操作 | 请用户检查硬件（看 LED、拔插模块等） |
| `[decide]` | 分支判断 | 询问用户当前情况，选择对应路径 |
| `[remote]` | 远程操作 | 执行远程/有状态变更的操作 |

### kb_browse 响应结构

首次调用返回目录总览 + 条目列表：

```json
{
  "directory": {
    "by_type": {"pitfall": 45, "process": 25, "model": 15, ...},
    "by_category": {"memory": 12, "pcie": 18, "thermal": 8, ...}
  },
  "entries": [
    {"id": "...", "type": "pitfall", "title": "...", "brief": "一句话摘要"},
    ...
  ],
  "total": 85,
  "page": 1,
  "total_pages": 2,
  "session_id": "abc123",
  "guide": "..."
}
```

每条目只有 4 个字段（id/type/title/brief），~60 tokens。50 条一页，全页 ~3000 tokens。

### kb_read 两层结构

**摘要层**（默认）——确认相关性，不用读全文：

```json
// pitfall 类型
{"symptoms": [...], "root_cause": "...", "resolution_overview": "3 branches: ..."}

// process 类型
{"purpose": "...", "steps_count": 6, "prerequisites": [...], "warnings": [...]}

// model 类型
{"overview": "...", "key_concepts": ["PROCHOT", "THERMTRIP", ...]}
```

**完整层**（`full=true`）——纯正文 body，无重复 frontmatter。

### MCP 客户端配置

在 `.mcp.json` 或 MCP 客户端配置中添加：

```json
{
  "mcpServers": {
    "holmes-kb": {
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

## 导入流水线

```
源文档 → Classify → Summarize → Review → Generate → Normalize → Fidelity → Write
```

| 阶段 | 作用 |
|------|------|
| Classify | LLM 判断文档类型（pitfall/process/model/guideline/decision）和语言 |
| Summarize | 按类型提取关键信息（症状、根因、步骤、概念等） |
| Review | 用户确认提取的摘要内容 |
| Generate | 按类型模板生成结构化 Markdown 条目 |
| Normalize | 确定性后处理（ID slug 化、分类标准化、行为标签修正等） |
| Fidelity | 校验关键内容未丢失，格式问题自动反馈重试（最多 2 次） |
| Write | 写入 `_pending/` 目录 |

## 配置文件

`~/.holmes/config.json`：

```json
{
  "kb_path": "/path/to/holmes-kb",
  "api_key": "your-api-key",
  "api_base_url": "https://api.openai.com/v1",
  "model": "gpt-4o",
  "username": "your-name"
}
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 运行 LLM 集成测试
HOLMES_LLM_TESTS=1 pytest -m llm
```
