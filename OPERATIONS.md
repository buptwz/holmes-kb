# Holmes 操作手册

**版本**：2.0（对齐 043-kb-hardening） | **适用对象**：所有使用 Holmes 的工程师

---

## 目录

1. [安装与初始化](#1-安装与初始化)
2. [部署形态与 MCP 接入](#2-部署形态与-mcp-接入)
3. [日常排查（Agent + MCP）](#3-日常排查agent--mcp)
4. [知识沉淀与审核入库](#4-知识沉淀与审核入库)
5. [知识库管理命令详解](#5-知识库管理命令详解)
6. [外部文档导入](#6-外部文档导入)
7. [多人协作与冲突处理](#7-多人协作与冲突处理)
8. [知识库健康维护](#8-知识库健康维护)
9. [配置管理](#9-配置管理)
10. [常见场景速查](#10-常见场景速查)
11. [错误处理与恢复](#11-错误处理与恢复)

> **命令形式说明**：所有管理命令都是顶层命令，如 `holmes approve`、`holmes pending`。
> 旧写法 `holmes kb approve` 仍作为 hidden 别名保留一个版本周期，但新文档和脚本请一律使用顶层写法。
>
> **新手入口**：如果你只想快速解决一个具体问题（怎么装、怎么导、报错了怎么修），先看 [docs/scenarios.md](docs/scenarios.md) 场景手册，本手册作为完整参考。

---

## 1. 安装与初始化

### 1.1 前置依赖

| 依赖 | 版本要求 | 检查命令 |
|------|----------|----------|
| Python | >= 3.11 | `python3 --version` |
| git | >= 2.30 | `git --version` |
| holmes | 任意 | `holmes --version` |

### 1.2 安装

```bash
pip install holmes-kb
```

### 1.3 Clone 知识库

```bash
git clone <知识库仓库地址> ~/holmes-kb
```

### 1.4 初始化配置

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --provider anthropic \
  --model claude-sonnet-4-6 \
  --api-key sk-xxxx
```

**参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--kb-path` | 是 | 知识库本地路径，不存在时自动创建 |
| `--provider` | 否 | `anthropic`（默认）或 `openai`（OpenAI 兼容接口，含 Azure、Ollama） |
| `--model` | 否 | LLM 模型名，默认 `gpt-4o` |
| `--api-key` | 否 | API Key |
| `--api-base-url` | 否 | OpenAI 兼容接口地址，使用自有 LLM 服务时填写 |

**执行后自动完成**：
- `~/.holmes/config.json` — 保存 KB 路径与模型配置
- `~/.holmes/settings.json` — 写入 `HOLMES_KB_PATH` 环境变量和 KB 工具权限
- `~/holmes-kb/CLAUDE.md` 与 `~/.holmes/CLAUDE.md` — agent 引导文件
- `~/.holmes/skills/holmes-search.md` — 部署 `/holmes-search` 技能

**设置身份（import 前必须）**：

```bash
holmes config set username <你的名字>
```

import pipeline 会把 `username` 写入条目贡献者；未设置时 `holmes import` 会直接报错退出。

**验证**：

```bash
holmes config show
# 输出（JSON）：
# {
#   "kb_path": "/home/user/holmes-kb",
#   "model": "claude-sonnet-4-6",
#   "api_base_url": "",
#   "username": "wangzhi",
#   ...
# }
```

---

## 2. 部署形态与 MCP 接入

Holmes 不自建 agent，只对外暴露 MCP server（streamable-http 传输），工程师用自己的 MCP 兼容 agent（Claude、GPT-4o 等）接入。两种部署形态：

### 2.1 本地模式（默认）

```bash
holmes start                    # 绑定 127.0.0.1:8765，免认证
holmes start --port 9000        # 自定义端口
```

- 绑定 loopback，仅本机可连
- 免认证
- 身份兜底：`kb_confirm`/`kb_draft` 未声明 `contributor` 时回退到本机 git config

MCP client 配置：

```json
{ "url": "http://localhost:8765" }
```

### 2.2 集中模式

```bash
# 管理员在中心服务器上：
holmes config set mcp_token <共享令牌>
holmes start --mode central            # 默认绑定 0.0.0.0:8765
holmes start --mode central --host 0.0.0.0 --port 9000
```

- 绑定对外接口（`--mode central` 时默认 `0.0.0.0`，可用 `--host` 覆盖）
- **静态 bearer token 认证**：未配置 `mcp_token` 时 central 模式拒绝启动
- **强制 contributor**：`kb_confirm`/`kb_draft` 必须声明 `contributor` 参数，否则拒绝

agent 侧 MCP client 配置（带认证头，具体字段名以你的 MCP client 为准）：

```json
{
  "url": "http://<中心服务器>:8765",
  "headers": { "Authorization": "Bearer <共享令牌>" }
}
```

集中模式下 agent 每次调用都应声明 `contributor`（你的名字），否则证据无法归属、proven 级（≥2 贡献者）不可达。

### 2.3 MCP 工具一览

server 只暴露 4 个工具（MCP 不提供搜索，可发现性由 browse 承担）：

| 工具 | 作用 |
|------|------|
| `kb_browse` | 目录式浏览：type → category → 条目，分页，支持适用性过滤 |
| `kb_read` | 渐进式阅读：summary（默认）→ section/branch → full |
| `kb_confirm` | 记录使用结果：`solved`（提升成熟度）或 `not_solved`（中立） |
| `kb_draft` | 保存原始草稿到 `_drafts/`（不做 LLM 处理），等人 import |

发布、删除、合并等结构性操作不暴露给 MCP，只能由人通过 CLI 执行。

---

## 3. 日常排查（Agent + MCP）

### 3.1 排查流程

agent 侧遵循固定方法论（由工具 description 引导）：

```
1. kb_browse          — 浏览知识库全景（保存返回的 session_id）
2. kb_read <id>       — 先读 summary，再按需读 section/branch/full
3. 按条目步骤排查      — 遵循步骤前的行为标签（[api]/[physical]/[remote]/[decide]）
4. kb_confirm         — 用户确认解决后记录结果
```

**示例对话**：

```
你: Redis 连接一直超时，帮我排查

Agent: 我先查一下知识库...
       [调用 kb_browse]
       找到相关条目 PT-DB-a3f8c2 《Redis 连接池耗尽排查》
       [调用 kb_read(entry_id="PT-DB-a3f8c2")]

       根据知识库条目 PT-DB-a3f8c2，Redis 连接超时通常由以下原因引起：
       1. 连接池耗尽（maxclients 配置过低）
       2. 大量慢查询占用连接
       3. 客户端连接泄漏
       ...
```

### 3.2 证据与成熟度

- `kb_read(detail="full")` 带 `session_id` 时记录一条 `referenced` 证据（重置 decay 计时器）
- 同一 session 随后调用 `kb_confirm(outcome="solved")` 会**升级**这条记录为 `solved`（不是追加新记录）
- 成熟度由证据实时推导：`draft`（0 条 solved）→ `verified`（≥1 条 solved）→ `proven`（≥2 个不同 session 且 ≥2 个不同 contributor 的 solved）
- `session_id` 为完整 UUID，由 `kb_browse` 返回；`kb_confirm` 不带 `session_id` 一律被拒绝（先调 `kb_browse` 获取）

### 3.3 条目 ID 格式

- **永久 ID**：`类型前缀-类目前缀-6位hex`，如 `PT-DB-a3f8c2`。在 `holmes approve` 时随机铸造（存在性重试防碰撞），不再递增
- **pending 临时 ID**：`pending-YYYYMMDD-HHMMSS-xxxx`，如 `pending-20260720-153000-ab1f`；approve 后临时 ID 记录在新条目的 `former_id` 字段中，可追溯

---

## 4. 知识沉淀与审核入库

### 4.1 主链路：draft → import → approve

排查结束后，知识入库分三步，**agent 永远不直接写正式 KB**：

```
1. agent 调用 kb_draft        → 原始草稿写入 _drafts/（无 LLM 处理）
2. holmes import _drafts/<file> → LLM pipeline 结构化为条目，写入 contributions/pending/
3. holmes pending / approve    → 人工审阅、发布
```

```bash
# 查看待 import 的草稿
holmes drafts

# 导入草稿（导入后原草稿移入 _drafts/_imported/）
holmes import _drafts/redis-oom-2026-06-23.md

# 查看 pending 区
holmes pending
holmes pending --show pending-20260720-153000-ab1f   # 查看全文

# 审阅发布
holmes approve pending-20260720-153000-ab1f
```

### 4.2 approve 的行为

`holmes approve <pending-id>` 依次执行：

1. **同源检测**：发现同一源文档的旧 pending / 旧 confirmed 条目时，提示取消旧 pending、把旧 confirmed 标为 deprecated
2. **语义查重门控**：LLM 对比同 category 的 active 条目，发现疑似重复时列出并默认要求人工确认（`--skip-dedup` 跳过；查重服务不可用时跳过不阻塞）
3. **铸造永久 ID**：生成 `PT-DB-a3f8c2` 式随机 ID，正文和元数据中对临时 ID 的自引用一并改写，旧 ID 记入 `former_id`
4. **重建索引**：自动重建 `index.json` 与各 `_index.md`

```bash
holmes approve <pending-id> --no-interactive   # CI 环境：全部提示按默认处理
holmes approve <pending-id> --skip-dedup       # 跳过语义查重门控
```

**成功示例**：

```
✓ Approved: PT-DB-a3f8c2 → pitfall/database/PT-DB-a3f8c2.md
  (former temporary id: pending-20260720-153000-ab1f)
```

### 4.3 手工写 pending（含勘误流程）

agent 或人也可以直接把结构化内容写入 pending 区：

```bash
# 新条目
holmes write-pending --file ./new-entry.md

# 勘误：提交一个替换 PT-DB-a3f8c2 的提案
holmes write-pending --corrects PT-DB-a3f8c2 --file ./corrected-entry.md

# 修改 pending 内容（保留系统字段）
holmes amend-pending pending-20260720-153000-ab1f --file ./revised.md
```

勘误提案（带 `corrects` 字段）用 `holmes confirm <pending-id>` 入库：原条目自动存快照到 `.history/` 后被替换，证据与贡献者保留。

### 4.4 confirm（3-Gate 人工确认）

`holmes confirm <pending-id>` 适用于手工/勘误类 pending，依次执行三道门控：

```
[门控 1] Schema 校验   — frontmatter 必填字段 + 类型必需章节（pitfall 需 Symptoms/Root Cause/Resolution）
[门控 2] 重复检测      — 标题相似条目列出，默认阻止（--force 绕过；勘误提案自动跳过）
[门控 3] 强制预览      — 展示条目内容，确认后写入正式目录并铸造永久 ID
```

```bash
holmes confirm <pending-id>
holmes confirm <pending-id> --type pitfall --category database   # 覆盖 LLM 分类
holmes confirm <pending-id> --force                              # 跳过重复检测
holmes confirm <pending-id> --contributor wangzhi                # 记录确认人
```

confirm 成功后，确认动作本身写入第一条 solved 证据（contributor 缺省为 `maintainer`）。

### 4.5 拒绝 pending

```bash
holmes reject pending-20260720-153000-ab1f --reason "内容过时"
holmes reject --stale-days 30 --dry-run    # 预览超期 pending
holmes reject --stale-days 30 --force      # 批量清理超期 pending
```

拒绝操作记录写入 `contributions/log.md`。

### 4.6 修正错误内容（--corrects 纠错流程）

发现正式条目**内容有误**（步骤错误、寄存器值过时、分支缺失）时，不要直接改正式目录——走与入库相同的审批流，只是多一个 `--corrects` 指向被修正的旧条目：

```bash
# 1. 准备修正版条目（手工编辑，或让 agent 生成）
vim fix-pcie.md

# 2. 提交修正提案，声明修正对象
holmes write-pending --file fix-pcie.md --corrects PT-DB-a3f8c2

# 3. 正常审批
holmes approve pending-20260720-153000-ab1f
# → 修正版入库，旧条目自动标记 deprecated
# → 旧版本保留在 .history/ 快照，可随时回滚
```

> 形式类小瑕疵（行为标签误标、`firmware: "unknown"` 占位值）不需要走这个流程，用 `holmes doctor --fix` 机械清洗即可（见 8.1）。

---

## 5. 知识库管理命令详解

### 5.1 列出条目

```bash
holmes list                                   # 全部 active 条目
holmes list --type pitfall                    # 按类型
holmes list --category database               # 按分类
holmes list --query redis                     # 关键词（匹配标题和标签）
holmes list --maturity proven                 # 按成熟度（draft/verified/proven）
holmes list --limit 20 --offset 20            # 分页
holmes list --format json                     # table（默认）/ json / id-only
holmes list --all                             # 含 deprecated
holmes list --all-types                       # 含 process 子条目
```

**输出示例**：

```
ID                   TYPE         MATURITY   TITLE
--------------------------------------------------------------------------------
PT-DB-a3f8c2         pitfall      proven     Redis 连接池耗尽排查
PT-DB-b71e04         pitfall      verified   MySQL 慢查询导致锁等待
PT-NET-9c2d51        pitfall      draft      DNS 解析异常排查
```

### 5.2 查看单条条目

```bash
holmes show PT-DB-a3f8c2                      # 完整内容
holmes show PT-DB-a3f8c2 --with-evidence      # 附证据摘要（会话数/贡献者/最近日期）
holmes show PT-DB-a3f8c2 --json
```

### 5.3 概览与分类索引

```bash
holmes overview                # README + 条目总数
holmes read-category pitfall   # 该类型的 _index.md
holmes search "redis 连接池"    # 全文搜索（BM25，--limit/--type/--all/--json）
holmes history PT-DB-a3f8c2    # .history/ 版本快照列表
```

### 5.4 重建索引

`index.json` 与各 `_index.md` 是**纯派生文件**（不入 git），以下时机自动重建：server 启动、approve/confirm/resolve 之后。手动编辑过条目文件后可手动重建：

```bash
holmes rebuild-index
```

### 5.5 删除条目

```bash
holmes delete PT-DB-a3f8c2            # 软删除：移入 _trash/，可 git 恢复
holmes delete PT-DB-a3f8c2 --force    # 跳过确认
```

恢复：`git checkout HEAD -- <原路径>`。

---

## 6. 外部文档导入

### 6.1 基本用法

```bash
# 最简：自动识别类型、分类、标题、标签，写入 contributions/pending/
holmes import ./redis-runbook.md

# 批量导入目录（.md/.txt/.rst）
holmes import --dir ./runbooks/

# 从 stdin 读
cat incident.txt | holmes import -
```

### 6.2 参数详解

| 参数 | 说明 | 示例 |
|------|------|------|
| `--type` | 强制指定类型（跳过 LLM 分类） | `--type pitfall` |
| `--category` | 强制指定分类 | `--category database` |
| `--title` | 覆盖标题 | `--title "Redis 超时排查"` |
| `--tags` | 覆盖标签（逗号分隔） | `--tags "redis,timeout,ops"` |
| `--dry-run` | 仅预览，不写入文件 | |
| `--force` | 跳过重复 pending 检测 | |
| `--no-interactive` | 跳过所有确认提示（CI 适用） | |
| `--verbose` | 显示每步决策理由 | |

### 6.3 场景示例

**场景 A：导入故障报告**

```bash
holmes import ./2026-05-20-incident-report.md --type pitfall --category system
holmes pending
holmes approve pending-20260720-153000-ab1f
```

**场景 B：先预览再导入**

```bash
holmes import ./coding-standards.md --dry-run
holmes import ./coding-standards.md --type guideline
```

**场景 C：批量导入**

```bash
holmes import --dir ./runbooks/ --no-interactive
holmes pending          # 逐一 approve
```

### 6.4 内容要求与可靠性

- 最小长度：去除空白后 >= 50 字符
- 支持 Markdown / 纯文本 / rst
- 幂等：每条目嵌入 `source_hash`（SHA-256 指纹），重复导入同一文件会被识别并跳过
- pipeline 全程 `temperature=0`，每个 LLM 输出经 validate → feedback → retry（最多 2 次）

---

## 7. 多人协作与冲突处理

### 7.1 协作模型

```
本地排查 → kb_draft/import → holmes approve → git commit → git pull --rebase → git push
                                                  ↑ 有冲突标记时先 holmes merge
```

**从源头上消除的冲突**（043 加固后）：

- **证据**：每条证据是 `contributions/evidence/<entry>/<session>.json` 独立文件，纯新增，git 永不冲突
- **成熟度**：由证据读时推导，frontmatter 只是缓存，不再产生 maturity 冲突
- **派生文件**：`index.json`、各 `_index.md` 已 gitignore，本地重建，不入库不冲突
- **操作日志**：`contributions/log.md` 配置 `merge=union`（`.gitattributes`），pull 时自动并集合并
- **ID**：随机后缀（`PT-DB-a3f8c2`），两人同时 approve 不再撞号

### 7.2 处理 git 冲突

```bash
cd ~/holmes-kb
git pull origin main --rebase
# 若仍出现冲突标记（条目正文被两边同时修改）：
holmes merge
```

`holmes merge` 的处理规则：

| 文件/场景 | 处理方式 | 需要人工 |
|-----------|---------|---------|
| `contributions/log.md` | 行级 union 合并（双方保留、去重） | 否 |
| `_index.md` / `index.json` | 任取一侧，随后从条目重建 | 否 |
| 条目文件可自动合并 | 自动解决 | 否 |
| 条目正文实质矛盾 | 隔离至 `contributions/conflicts/` | **是** |

### 7.3 裁决内容矛盾

```bash
# 查看冲突
ls ~/holmes-kb/contributions/conflicts/
cat ~/holmes-kb/contributions/conflicts/<conflict-id>.md

# 保留本地（A）或远端（B）
holmes resolve <conflict-id> --keep A
holmes resolve <conflict-id> --keep B

# 或手动编辑原文件消除冲突标记后：
holmes resolve <conflict-id> --manual
```

裁决后自动重建索引，继续 `git add . && git commit && git push`。

另有 `holmes check-conflicts`：扫描带 `contradiction: true` 标记、待人工复核的条目。

---

## 8. 知识库健康维护

### 8.1 doctor（综合诊断，首选）

```bash
holmes doctor                 # 只读诊断
holmes doctor --fix           # 自动修复安全项（建目录、重建索引、校准成熟度缓存、清洗条目）
holmes doctor --verbose       # 逐项明细
holmes doctor --check-api     # 附带 LLM API 连通性测试
```

检查范围：配置、目录结构、条目完整性、索引一致性、搜索健康、证据/成熟度一致性、**适用性（applies_to）**、**条目卫生**、**not_solved 反馈**、git 状态。

**条目卫生检查**（管线升级后翻新旧库用）：机械检测两类形式瑕疵——行为标签误标（如 `i2cset` 写命令被标成 `[api:read]`，按确定性动词规则判定）、`applies_to` 占位噪声（`firmware: "unknown"` 等）。`--fix` 时自动改写，只修机械可判定的错误，不动内容：

```
⚠  PT-GEN-bdb332: 7 处行为标签疑似误标 (read→write (i2cset ...)) — 运行 --fix 修正
✓ fixed  PT-GEN-bdb332: corrected 7 behavior tag(s): read→write ...
```

**not_solved 反馈检查**：agent 按条目排查但没解决时会留下 `not_solved` 证据——这是"内容可能有误"的信号。doctor 把有 not_solved 反馈的条目列出来，提醒人工复核（内容错误机器判不了，必须先被注意到）：

```
⚠  PT-GEN-bdb332: 2 条 not_solved 反馈（最近 2026-07-19） — 内容可能有误，请人工复核
```

复核后确属内容错误的，走 4.6 的 `--corrects` 纠错流程。

### 8.2 lint（轻量健康检查）

```bash
holmes lint
holmes lint --fix             # 自动修复可程序化问题
holmes lint --report          # JSON 输出（适合 CI）
```

检查项：索引一致性（`_index.md` 与磁盘文件）、超期 pending、标题重复、contradiction 标记。

### 8.3 decay（成熟度衰减，事件化）

```bash
holmes decay --dry-run        # 预览
holmes decay                  # 执行
holmes decay --type pitfall   # 限定类型
```

规则（阈值可在 `kb-config.yml` 的 `decay:` 段配置）：

| 级别 | 条件 | 结果 |
|------|------|------|
| `proven` | 最后证据 > 12 个月 | 降为 `verified` |
| `verified` | 最后证据 > 6 个月 | 降为 `draft` |
| `draft` | 条目年龄 > 30 天且最后证据 > 3 个月 | 归档至 `contributions/archive/` |

每次降级：先存 `.history/` 快照，再写入一条系统证据（`outcome: "decayed"`，含 `maturity_after`）。成熟度推导以最近一次 decay 事件为下限锚点，重建索引不会把级别弹回去。

### 8.4 archive-orphans

```bash
holmes archive-orphans --dry-run
holmes archive-orphans
```

把没有任何证据的孤儿 draft 条目移入 `contributions/archive/`。

### 8.5 推荐维护频率

| 操作 | 频率 |
|------|------|
| `git pull` 拉取他人贡献 | 每天 |
| `holmes doctor` 综合诊断 | 每周 |
| `holmes decay --dry-run` → `holmes decay` | 每月 |
| `git push` 推送本地贡献 | approve 后尽快 |

---

## 9. 配置管理

### 9.1 查看当前配置

```bash
holmes config show      # JSON 输出：kb_path / model / api_base_url / username / 配置文件路径
```

### 9.2 修改配置项

```bash
holmes config set model gpt-4o-mini
holmes config set api_key sk-new-key
holmes config set username wangzhi
holmes config set mcp_token <共享令牌>     # central 模式必需
holmes config set kb_path ~/new-kb
```

允许设置的键：`kb_path`、`model`、`api_key`、`api_base_url`、`username`、`mcp_token`、`langfuse_enabled`、`langfuse_public_key`、`langfuse_secret_key`、`langfuse_host`。

### 9.3 环境变量覆盖

```bash
HOLMES_KB_PATH=~/another-kb holmes list    # 临时切换知识库
# 或
holmes --kb-path ~/another-kb list
```

注意 `--kb-path` 是顶层选项，放在子命令**之前**。

---

## 10. 常见场景速查

### 场景 1：排查了一个新问题，想把经验记录下来

```
1. 告诉 agent"问题解决了，把这次经验存下来"  → agent 调用 kb_draft
2. holmes drafts                              → 确认草稿已保存
3. holmes import _drafts/<file>               → 结构化为 pending 条目
4. holmes pending --show <pending-id>         → 人工审阅
5. holmes approve <pending-id>                → 发布，获得永久 ID（PT-DB-a3f8c2）
6. cd ~/holmes-kb && git add . && git commit && git pull --rebase && git push
```

### 场景 2：旧故障文档批量入库

```bash
holmes import ./incident-2026-05-01.md --dry-run     # 先预览
holmes import --dir ./incidents/ --no-interactive    # 批量
holmes pending
holmes approve <pending-id>                          # 逐条审核
```

### 场景 3：同事推送了新条目，本地用上

```bash
cd ~/holmes-kb && git pull origin main
holmes merge               # 仅当有冲突标记时
holmes list --query <关键词>
```

### 场景 4：发现知识库里有一条错误条目

```bash
holmes list --query <关键词>          # 找到条目 ID
holmes delete PT-DB-a3f8c2            # 软删除到 _trash/
cd ~/holmes-kb && git add . && git commit -m "remove PT-DB-a3f8c2" && git push
# 误删恢复：git checkout HEAD -- pitfall/database/PT-DB-a3f8c2.md
```

### 场景 5：条目内容部分过时，想勘误

```bash
holmes write-pending --corrects PT-DB-a3f8c2 --file ./corrected.md
holmes confirm <pending-id>       # 原条目存 .history/ 快照后被替换，证据保留
```

### 场景 6：pull 之后有冲突

```bash
cd ~/holmes-kb
holmes merge                                # 不要手动编辑冲突文件
# 若提示有内容矛盾被隔离：
holmes resolve <conflict-id> --keep A       # 或 --keep B / --manual
git add . && git commit -m "merge: resolve conflict" && git push
```

### 场景 7：pending 区积压，定期清理

```bash
holmes pending                              # 查看全部
holmes reject --stale-days 30 --dry-run     # 预览超期项
holmes reject --stale-days 30               # 批量清理
```

---

## 11. 错误处理与恢复

**错误：`KB path not configured`**

```bash
holmes setup --kb-path ~/holmes-kb
# 或
holmes config set kb_path ~/holmes-kb
```

**错误：`config.username not set`（import 时）**

```bash
holmes config set username <你的名字>
```

**错误：`Content too short`（导入文档过短）**

导入内容去除空白后不足 50 字符，请提供更完整的文档。

**错误：`holmes start --mode central` 启动失败**

central 模式要求先配置令牌：`holmes config set mcp_token <共享令牌>`。

**错误：`kb_confirm` 返回需要 session_id**

`kb_confirm` 的 `session_id` 必填且不允许为空。先调用 `kb_browse` 获取本 session 的 `session_id`，confirm 时原样传回。

**错误：confirm 门控 1 Schema 校验失败**

```bash
holmes pending --show <pending-id>                        # 查看内容
holmes amend-pending <pending-id> --file ./fixed.md       # 修正后重试
holmes confirm <pending-id>
```

**错误：`git push` 前有未解决冲突**

```bash
ls ~/holmes-kb/contributions/conflicts/
holmes resolve <conflict-id> --keep A
git add . && git commit -m "merge: resolve all conflicts" && git push
```

**错误：`_index.md` 与磁盘文件不一致**

```bash
holmes rebuild-index
```

### 数据恢复

知识库所有内容均由 git 版本控制（派生文件除外，可随时重建）：

```bash
git -C ~/holmes-kb log --oneline -20        # 最近操作
git -C ~/holmes-kb show <commit-hash>       # 某次变更详情
git -C ~/holmes-kb revert <commit-hash>     # 回滚
holmes rebuild-index                        # 回滚后重建索引
```

CLI 操作日志（import/approve/delete 等 span）也可用 `holmes log list` / `holmes log show <trace-id>` 查看。
