# Holmes 操作手册

**版本**：1.0 | **适用对象**：所有使用 Holmes 的工程师

---

## 目录

1. [安装与初始化](#1-安装与初始化)
2. [日常排查](#2-日常排查)
3. [知识提取与保存](#3-知识提取与保存)
4. [知识库管理命令详解](#4-知识库管理命令详解)
5. [外部文档导入](#5-外部文档导入)
6. [多人协作与冲突处理](#6-多人协作与冲突处理)
7. [知识库健康维护](#7-知识库健康维护)
8. [配置管理](#8-配置管理)
9. [常见场景速查](#9-常见场景速查)
10. [错误处理与恢复](#10-错误处理与恢复)

---

## 1. 安装与初始化

### 1.1 前置依赖

| 依赖 | 版本要求 | 检查命令 |
|------|----------|----------|
| Python | >= 3.11 | `python3 --version` |
| git | >= 2.30 | `git --version` |
| holmes-agent | 任意 | `holmes --version` |

### 1.2 安装 holmes-kb

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
  --model gpt-4o \
  --api-key sk-xxxx \
  --api-base-url https://api.example.com/v1
```

**参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--kb-path` | 是 | 知识库本地路径，不存在时自动创建 |
| `--model` | 否 | LLM 模型名，默认 `gpt-4o` |
| `--api-key` | 否 | API Key，也可通过环境变量设置 |
| `--api-base-url` | 否 | OpenAI 兼容接口地址，使用自有 LLM 服务时填写 |

**执行后自动完成**：
- `~/.holmes/config.json` — 保存模型配置
- `~/.holmes/settings.json` — 写入 `HOLMES_KB_PATH` 环境变量和 KB 工具权限
- `~/holmes-kb/HOLMES.md` — 生成排查方法论注入文件
- `~/.holmes/skills/holmes-search.md` — 部署 `/holmes-search` 技能

**验证**：
```bash
holmes config show
# 输出：
# kb_path: /home/user/holmes-kb
# model:   gpt-4o
# api_base_url: https://api.example.com/v1
```

---

## 2. 日常排查

### 2.1 启动 Agent

```bash
holmes-agent
```

### 2.2 排查流程

Agent 遵循固定的排查方法论（来自 HOLMES.md）：

```
1. KbReadOverview    — 浏览知识库全景，了解已有条目范围
2. KbSearch          — 按症状关键词搜索匹配条目
3. KbReadEntry       — 读取最相关条目全文，获取排查步骤
4. 给出建议          — 基于 KB 条目或通用知识回答
```

**示例对话**：

```
你: Redis 连接一直超时，帮我排查

Agent: 我先查一下知识库...
       [调用 KbSearch: "Redis 连接超时"]
       找到相关条目 PT-DB-001 《Redis 连接池耗尽排查》
       [调用 KbReadEntry: PT-DB-001]

       根据知识库条目 PT-DB-001，Redis 连接超时通常由以下原因引起：
       1. 连接池耗尽（max_clients 配置过低）
       2. 大量慢查询占用连接
       3. 客户端连接泄漏

       建议排查步骤：
       第一步：执行 redis-cli INFO clients 查看当前连接数...
```

### 2.3 快捷技能

在 Agent 会话中可直接输入：

| 技能 | 说明 |
|------|------|
| `/holmes-resolve` | 提取本次会话的排查知识，保存至 pending 区 |
| `/holmes-search <关键词>` | 快速搜索知识库 |

---

## 3. 知识提取与保存

### 3.1 知识自动提取

**无需任何命令**。当你告诉 Agent 问题已解决，Agent 会自动触发知识提取：

> "搞定了" / "问题解决了" / "that fixed it" / "it's working now"

Agent 检测到问题已解决后自动执行：
1. 分析本次排查会话的全过程
2. 提取 Symptoms / Root Cause / Resolution 结构
3. 写入 `contributions/pending/` 目录
4. 输出 pending ID，提示下一步操作

如需**手动触发**（例如想主动保存中途经验），在会话中执行：

```
/holmes-resolve
```

**示例输出**：
```
已提取排查知识并写入暂存区
pending ID: auto-20260526-redis-conn-timeout
类型: pitfall / database
标题: Redis 连接超时排查（连接池配置不当）

运行以下命令审阅并确认入库：
  holmes kb confirm auto-20260526-redis-conn-timeout
```

### 3.2 查看待确认条目

```bash
holmes kb pending
```

**输出示例**：
```
ID                                    类型     标题                          暂存时间
────────────────────────────────────────────────────────────────────────────────────
auto-20260526-redis-conn-timeout      pitfall  Redis 连接超时排查            2分钟前
import-20260525-mysql-deadlock        pitfall  MySQL 死锁排查                昨天
```

查看某条目详情：

```bash
holmes kb pending --show auto-20260526-redis-conn-timeout
```

### 3.3 确认入库（3-Gate 流程）

```bash
holmes kb confirm auto-20260526-redis-conn-timeout
```

**三道门控依次执行**：

```
[门控 1] Schema 校验
  检查 frontmatter 必填字段：type / title / tags / created_at
  检查对应类型的必要章节：pitfall 需含 ## Symptoms / ## Root Cause / ## Resolution
  不通过 → 报错并阻止，条目留在 pending 区

[门控 2] 重复检测
  计算标题与现有条目的 Jaccard 相似度
  相似度 > 85% → 列出相似条目，阻止写入
  可追加 --force 强制绕过

[门控 3] 强制预览
  展示条目完整内容
  要求输入 y 确认（不接受空回车）
  确认后写入正式目录，分配永久 ID
```

**成功示例**：
```
[门控 1] Schema 校验 ✓
[门控 2] 重复检测 ✓（无相似条目）
[门控 3] 条目预览：
─────────────────────────────────────────────────────
标题：Redis 连接超时排查（连接池配置不当）
类型：pitfall / database
标签：redis, connection-pool, timeout, configuration

## Symptoms
用户反馈 Redis 操作大量超时，错误日志显示 "ERR max number of clients reached"

## Root Cause
maxclients 配置值过低，在业务高峰期连接耗尽

## Resolution
1. redis-cli CONFIG GET maxclients 查看当前值
2. 调整 maxclients 至合理值（建议 10000）
3. 检查客户端是否有连接泄漏
─────────────────────────────────────────────────────
确认写入正式知识库？[y/N] y
✓ 已写入 pitfall/database/redis-conn-timeout.md
✓ 永久 ID：PT-DB-003
✓ _index.md 已更新
```

**门控 2 拦截示例**：
```
[门控 2] 发现相似条目（相似度 91%）：
  PT-DB-001  Redis 连接超时排查  pitfall/database/
如需强制写入，请追加 --force 参数
已阻止写入。
```

**门控 1 拦截示例**：
```
[门控 1] Schema 校验失败：
  缺少必填字段：tags
  pitfall 类型缺少 ## Resolution 章节
请修复后重新运行 confirm。
已阻止写入。
```

**confirm 的附加选项**：

```bash
# 覆盖类型（LLM 分类有误时使用）
holmes kb confirm <id> --type pitfall

# 同时覆盖分类
holmes kb confirm <id> --type pitfall --category database

# 跳过重复检测（确认是不同条目时使用）
holmes kb confirm <id> --force
```

### 3.4 拒绝条目

```bash
holmes kb reject auto-20260526-redis-conn-timeout
```

条目从 pending 区删除，操作记录写入 `contributions/log.md`。

---

## 4. 知识库管理命令详解

### 4.1 列出所有条目

```bash
# 列出全部
holmes kb list

# 按类型过滤
holmes kb list --type pitfall
holmes kb list --type model
holmes kb list --type guideline
holmes kb list --type process
holmes kb list --type decision

# 按分类过滤（pitfall 专用）
holmes kb list --category database
holmes kb list --category network
holmes kb list --category system
holmes kb list --category application

# 关键词搜索（匹配标题和标签）
holmes kb list --query redis
holmes kb list --query "连接池"

# 分页（大型知识库）
holmes kb list --limit 20 --offset 0    # 第 1 页
holmes kb list --limit 20 --offset 20   # 第 2 页

# JSON 格式输出（适合脚本处理）
holmes kb list --format json

# 组合过滤
holmes kb list --type pitfall --category database --query redis --limit 10
```

**输出示例**：
```
ID          类型      分类      成熟度     标题
──────────────────────────────────────────────────────────────────
PT-DB-001   pitfall   database  proven     Redis 连接池耗尽排查
PT-DB-002   pitfall   database  verified   MySQL 慢查询导致锁等待
PT-NET-001  pitfall   network   draft      DNS 解析异常排查
MD-001      model     —         verified   Redis 数据结构模型
```

### 4.2 查看单条条目

```bash
holmes kb show PT-DB-001
```

输出条目完整 Markdown 内容（含 frontmatter 和所有章节）。

### 4.3 查看知识库概览

```bash
holmes kb overview
```

输出 README.md 和各类目 `_index.md` 汇总，适合快速了解知识库全貌。

### 4.4 查看分类索引

```bash
holmes kb read-category pitfall
holmes kb read-category database   # 按子分类
```

### 4.5 重建索引

当文件手动修改后（如直接编辑 Markdown 文件），索引可能失同步，执行：

```bash
holmes kb rebuild-index
```

重建所有 `_index.md` 和根目录的 `index.json`。

---

## 5. 外部文档导入

### 5.1 基本用法

```bash
# 最简：全自动识别类型、分类、标题、标签
holmes import ./redis-runbook.md

# 输出示例：
# [识别结果]
#   类型：pitfall
#   分类：database
#   标题：Redis 连接池耗尽排查
#   标签：redis, connection-pool, timeout
# ✓ 已写入暂存区（auto-20260526-xxxxxx）
# 提示：运行 `holmes kb confirm auto-20260526-xxxxxx` 移入正式目录
```

### 5.2 参数详解

```bash
holmes import <文件路径> [选项]
```

| 参数 | 说明 | 示例 |
|------|------|------|
| `--type` | 强制指定类型（跳过 LLM 分类） | `--type pitfall` |
| `--category` | 强制指定分类 | `--category database` |
| `--title` | 覆盖标题 | `--title "Redis 超时排查"` |
| `--tags` | 覆盖标签（逗号分隔）| `--tags "redis,timeout,ops"` |
| `--dry-run` | 仅预览，不写入文件 | |
| `--force` | 跳过重复 pending 检测 | |

### 5.3 场景示例

**场景 A：导入故障报告**
```bash
# 故障报告通常是 pitfall 类型，指定类型跳过 LLM 分类（更快）
holmes import ./2026-05-20-incident-report.md \
  --type pitfall \
  --category system \
  --title "内存泄漏导致 OOM 排查"
```

**场景 B：导入技术规范文档**
```bash
# 先预览识别结果
holmes import ./coding-standards.md --dry-run

# 确认无误后正式导入
holmes import ./coding-standards.md --type guideline
```

**场景 C：批量导入（脚本）**
```bash
for f in ./runbooks/*.md; do
  echo "导入: $f"
  holmes import "$f" --force
done
# 然后逐一 confirm
holmes kb pending
```

**场景 D：文档内容识别有误，手动覆盖**
```bash
# LLM 把一篇决策文档误识别为 guideline，手动纠正
holmes import ./arch-decision-redis-cluster.md \
  --type decision \
  --title "Redis Cluster vs Sentinel 选型决策"
```

### 5.4 内容要求

- 最小长度：去除空白后 >= 50 字符，否则直接拒绝
- 支持任意格式：Markdown、纯文本均可
- 已有 KB 格式 frontmatter 的文档：跳过 LLM 分类，直接写入

---

## 6. 多人协作与冲突处理

### 6.1 标准协作流程

```
每位工程师独立工作在本地 clone：

本地排查 → /holmes-resolve → holmes kb confirm → git commit → git pull → holmes kb merge → git push
```

### 6.2 正常推送（无冲突）

```bash
cd ~/holmes-kb

# 提交本地变更
git add .
git commit -m "feat(pitfall): add Redis connection pool guide"

# 先拉取，再推送
git pull origin main --rebase
git push origin main
```

### 6.3 处理 git 冲突

```bash
cd ~/holmes-kb
git pull origin main --rebase
# 若出现冲突标记，执行智能合并：

holmes kb merge
```

**五种冲突场景及处理结果**：

| 场景 | 触发条件 | 处理方式 | 是否需要人工 |
|------|---------|---------|------------|
| 纯新增 | 双方各自新增不同条目 | 自动保留双方 | 否 |
| 证据追加 | 同条目只有 reference_count / last_referenced 不同 | 取较大值/较晚时间 | 否 |
| 成熟度提升 | 同条目 maturity 方向一致（都在升级）| 取较高值 | 否 |
| 字段更新 | 同条目 tags/category 等非核心字段不同 | 取 updated_at 较新版本 | 否 |
| 内容矛盾 | 正文实质性差异 | 隔离至 conflicts/，阻止推送 | **是** |

**智能合并输出示例**：
```
✓ 自动合并：PT-NET-002 PT-SYS-003（纯新增，双方均已保留）
✓ PT-DB-001 证据追加：reference_count 取最大值 5，last_referenced 取较晚时间
✓ PT-DB-002 成熟度自动提升至 proven
⚠ 内容矛盾：PT-DB-003
  → 已隔离至 contributions/conflicts/PT-DB-003-conflict-20260526.md
  → 请运行 `holmes kb resolve PT-DB-003-conflict-20260526 --side A|B` 后重试推送
```

### 6.4 裁决内容矛盾

**查看冲突详情**：
```bash
cat ~/holmes-kb/contributions/conflicts/PT-DB-003-conflict-20260526.md
```

冲突文件包含两个版本：
```
## 版本 A（本地，user-a）
[本地版本正文内容]

## 版本 B（远端，user-b）
[远端版本正文内容]
```

**裁决命令**：
```bash
# 保留本地版本（A）
holmes kb resolve PT-DB-003-conflict-20260526 --side A

# 保留远端版本（B）
holmes kb resolve PT-DB-003-conflict-20260526 --side B

# 手动合并两个版本后标记为已解决
# 1. 编辑冲突文件，写入合并后的内容
# 2. 执行：
holmes kb resolve PT-DB-003-conflict-20260526 --manual
```

裁决完成后继续推送：
```bash
git add .
git commit -m "merge: resolve PT-DB-003 content conflict"
git push origin main
```

### 6.5 成熟度冲突特殊处理

当本地提升、远端降级（或反之）时，`holmes kb merge` 取较低成熟度并追加 `contradiction` 标签：

```yaml
# 合并结果 frontmatter
maturity: draft           # 取较低值
tags: [redis, timeout, contradiction]   # 追加 contradiction
```

此后 `holmes kb lint` 会持续报告含 `contradiction` 标签的条目，提醒 maintainer 人工复核。

---

## 7. 知识库健康维护

### 7.1 运行健康检查

```bash
holmes kb lint
```

**检查项说明**：

| 检查项 | 说明 | 自动修复 |
|--------|------|---------|
| 索引一致性 | `_index.md` 中的条目与磁盘文件是否匹配 | `--fix` 时自动重建 |
| 孤儿文件 | 磁盘上有文件但未记录在索引中 | `--fix` 时自动重建 |
| 超时 pending | pending 区存在 > 30 天未确认的条目 | 警告，人工处理 |
| 成熟度衰减 | proven > 365 天 / verified > 180 天未被引用 | `--fix` 时自动降级 |
| 重复条目 | 两条目标题 Jaccard 相似度 > 85% | 警告，人工决定 |
| 矛盾标记 | 条目含 contradiction 标签 | 警告，maintainer 裁决 |
| 矛盾关键词 | 正文含 "deprecated by" 等关键词 | 警告，人工处理 |

**输出示例**：
```
Holmes KB 健康报告
═══════════════════════════════════════════
正式条目：45  | Pending：3  | 待裁决冲突：1

警告：
  [W001] PT-SYS-002 maturity 为 proven，但 428 天未被引用（阈值 365）
  [W002] PT-DB-003 和 PT-DB-007 标题相似度 89%（可能重复）
  [W003] pending 条目 import-20260420-xxxx 已暂存 38 天

错误：
  [E001] pitfall/_index.md 缺失 PT-NET-003（文件存在但未列入索引）

建议：运行 `holmes kb lint --fix` 自动修复可程序化问题
```

### 7.2 自动修复

```bash
holmes kb lint --fix
```

自动执行：
- 重建所有 `_index.md` 和 `index.json`
- 对超过阈值的条目降级成熟度

```
已修复：
  ✓ 重建 pitfall/_index.md（新增 PT-NET-003）
  ✓ PT-SYS-002 成熟度降级：proven → verified（428 天未引用）
```

### 7.3 导出检查报告

```bash
holmes kb lint --report ./lint-report-20260526.json
```

JSON 格式，适合集成到 CI 或自动化脚本。

### 7.4 推荐维护频率

| 操作 | 频率 |
|------|------|
| `git pull` 拉取他人贡献 | 每天 |
| `holmes kb lint` 健康检查 | 每周 |
| `holmes kb lint --fix` 自动修复 | 每月或按需 |
| `git push` 推送本地贡献 | 确认入库后尽快推送 |

---

## 8. 配置管理

### 8.1 查看当前配置

```bash
holmes config show
```

```
kb_path:      /home/user/holmes-kb
model:        gpt-4o
api_base_url: https://api.example.com/v1
api_key:      sk-****（已隐藏）
```

### 8.2 修改配置项

```bash
holmes config set model gpt-4o-mini       # 切换模型
holmes config set api_key sk-new-key       # 更新 API Key
holmes config set api_base_url https://... # 更新接口地址
holmes config set kb_path ~/new-kb         # 切换知识库路径
```

### 8.3 环境变量覆盖

以下环境变量可临时覆盖配置文件中的值：

```bash
HOLMES_KB_PATH=~/another-kb holmes kb list    # 临时切换知识库
```

---

## 9. 常见场景速查

### 场景 1：我排查了一个 Redis 问题，想把经验记录下来

```bash
# 在 holmes-agent 会话结束后执行
/holmes-resolve

# 查看生成的 pending 条目
holmes kb pending
holmes kb pending --show <pending-id>

# 确认入库
holmes kb confirm <pending-id>

# 推送到远端共享
cd ~/holmes-kb
git add .
git commit -m "feat(pitfall): add Redis timeout troubleshooting guide"
git pull origin main --rebase && git push origin main
```

### 场景 2：我有一份旧的故障报告文档，想批量入库

```bash
# 先预览，确认 LLM 识别结果正确
holmes import ./incident-2026-05-01.md --dry-run

# 正式导入
holmes import ./incident-2026-05-01.md --type pitfall --category system

# 审核并入库
holmes kb pending
holmes kb confirm <id>
```

### 场景 3：同事推送了新条目，我想在本地用上

```bash
cd ~/holmes-kb
git pull origin main

# 如有冲突：
holmes kb merge

# 验证新条目可检索
holmes kb list --query <关键词>
```

### 场景 4：发现知识库里有一条错误的条目

```bash
# 找到条目 ID
holmes kb list --query <相关关键词>

# 直接删除文件（confirm 后的条目没有软删除命令）
rm ~/holmes-kb/pitfall/database/wrong-entry.md

# 重建索引
holmes kb rebuild-index

# 提交删除
cd ~/holmes-kb
git add .
git commit -m "fix: remove incorrect entry PT-DB-003"
git push origin main
```

### 场景 5：我 confirm 了一条错误的条目，想撤销

```bash
# 找到误操作前的 commit
git -C ~/holmes-kb log --oneline -5

# 撤销最近一次 commit（保留文件变更）
git -C ~/holmes-kb revert HEAD

# 重建索引
holmes kb rebuild-index
```

### 场景 6：pull 之后有冲突，不知道如何处理

```bash
cd ~/holmes-kb

# 不要手动编辑冲突文件
# 直接用 holmes 智能合并
holmes kb merge

# 若有内容矛盾（系统提示），查看冲突详情
cat contributions/conflicts/<conflict-id>.md

# 选择保留哪个版本
holmes kb resolve <conflict-id> --side A    # 或 --side B

# 完成后推送
git add .
git commit -m "merge: resolve conflict"
git push origin main
```

### 场景 7：知识库有条目 30 天没人确认，想清理

```bash
# 查看 pending 列表（lint 会标出超期的）
holmes kb lint

# 逐一处理
holmes kb pending --show <id>   # 确认内容
holmes kb reject <id>           # 不需要则拒绝
# 或
holmes kb confirm <id>          # 内容 OK 则入库
```

---

## 10. 错误处理与恢复

### 常见错误及解决

**错误：`Knowledge base path not configured`**
```bash
holmes setup --kb-path ~/holmes-kb --model gpt-4o
# 或
holmes config set kb_path ~/holmes-kb
```

**错误：`ContentTooShortError: 内容过短`**
```
导入的文档去除空白后不足 50 字符，请提供更完整的内容。
```

**错误：`DuplicatePendingError: 同名条目已存在`**
```bash
# 强制覆盖（确认是不同内容时使用）
holmes import <file> --force
```

**错误：`Schema 校验失败：缺少 ## Resolution 章节`**
```bash
# 查看条目详情，手动编辑 pending 文件补充章节
holmes kb pending --show <id>
# 编辑文件：
vim ~/holmes-kb/contributions/pending/<filename>.md
# 补充缺失章节后重新 confirm
holmes kb confirm <id>
```

**错误：`git push` 被拒绝（有未解决冲突）**
```bash
# 查看未解决的冲突
ls ~/holmes-kb/contributions/conflicts/

# 逐一裁决
holmes kb resolve <conflict-id> --side A
holmes kb resolve <conflict-id> --side B

# 再次推送
git add .
git commit -m "merge: resolve all conflicts"
git push origin main
```

**错误：`_index.md 与磁盘文件不一致`**
```bash
holmes kb rebuild-index
```

### 数据恢复

知识库所有操作均由 git 版本控制，任何时间点均可恢复：

```bash
# 查看最近操作记录
git -C ~/holmes-kb log --oneline -20

# 查看某次 commit 的具体变更
git -C ~/holmes-kb show <commit-hash>

# 恢复到指定时间点前
git -C ~/holmes-kb revert <commit-hash>

# 重建索引（恢复后务必执行）
holmes kb rebuild-index
```
