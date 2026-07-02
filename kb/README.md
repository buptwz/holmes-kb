# Holmes KB

运维故障知识库管理系统。将故障处理文档自动提取为结构化知识条目，供 AI Agent 通过 MCP 协议检索使用。

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
| pitfall | 已知故障模式 | Symptoms → Root Cause → Resolution |
| process | 分步诊断流程 | 挂在 pitfall 下的子条目，描述具体排查步骤 |
| model | 思维模型 / 决策框架 | 帮助定位问题方向的分析模型 |
| guideline | 操作规范 / 最佳实践 | 预防性的标准操作指南 |
| decision | 架构决策记录 | 记录关键技术选型的上下文和权衡 |
| skill | 可执行技能 | SKILL.md 指令 + 脚本文件 |

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
├── skills/<name>/                  可执行技能
│   ├── SKILL.md                    技能指令
│   └── scripts/                    脚本文件
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
holmes search <query>             # 搜索条目
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

Holmes 通过 MCP (Model Context Protocol) 将知识库暴露给 AI Agent。

### 启动

```bash
holmes start                      # 默认端口 8765
holmes start --port 9000          # 自定义端口
```

### MCP 工具

Agent 连接后可使用 6 个工具：

| 工具 | 用途 | 说明 |
|------|------|------|
| `kb_overview` | 会话初始化 | 返回知识库结构概览和 session_id |
| `kb_search` | 搜索条目 | BM25 排序，支持中英文混合搜索 |
| `kb_list` | 浏览条目 | 按类型/分类分页浏览 |
| `kb_read` | 读取内容 | 读取条目或技能的完整内容 |
| `kb_confirm` | 记录证据 | 条目帮助解决问题后记录使用证据 |
| `kb_draft` | 保存草稿 | Agent 发现新知识时保存草稿 |

### Agent 使用流程

```
遇到问题
  → kb_search("错误信息或症状描述")
  → kb_read(<条目ID>)
  → 按 Resolution 部分操作
  → 问题解决 → kb_confirm(<条目ID>, <session_id>)
  → KB 中没有 → 解决后 → kb_draft(<完整描述>)
```

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
