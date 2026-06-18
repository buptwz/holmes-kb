# 快速入门指南：Holmes Agent

**版本**：1.0 | **日期**：2026-05-26

---

## 前置依赖

| 依赖 | 版本要求 | 验证命令 |
|------|----------|----------|
| git | ≥ 2.30 | `git --version` |
| Python | ≥ 3.11 | `python3 --version` |
| Bun | ≥ 1.3 | `bun --version` |
| conda（可选） | ≥ 23.0 | `conda --version` |
| ANTHROPIC_API_KEY | — | `echo $ANTHROPIC_API_KEY` |

---

## 步骤一：安装 Holmes Agent

```bash
# 1. clone Holmes 项目
git clone <holmes-repo-url> ~/holmes
cd ~/holmes

# 2. 安装 Python agent 依赖（选其一）
# 方式 A：直接安装
cd agent && pip install -e .

# 方式 B：使用 conda 隔离环境（推荐）
conda create -n holmes python=3.11 -y
conda activate holmes
cd agent && pip install -e .

# 3. 安装 TUI 依赖
cd ../tui && bun install

# 4. 设置 API Key
export ANTHROPIC_API_KEY="your-api-key-here"
# 建议写入 ~/.bashrc 或 ~/.zshrc，重启终端后生效

# 5. 验证安装
holmes --version
```

---

## 步骤二：Clone 知识库

```bash
# clone 共享知识库到本地
git clone <knowledge-base-repo-url> ~/holmes-kb

# 验证知识库结构
ls ~/holmes-kb
# 预期输出：
# README.md  CHANGELOG.md  index.json
# pitfall/  model/  guideline/  process/  decision/  contributions/
```

**知识库目录说明**：

| 目录 | 存储内容 |
|------|---------|
| `pitfall/` | 已知风险、故障模式、排查步骤（最常用）|
| `model/` | 概念定义、实体说明 |
| `guideline/` | 推荐/禁止做法 |
| `process/` | 操作步骤、标准流程 |
| `decision/` | 技术选型记录 |
| `contributions/` | 协作暂存区（pending 待确认、conflicts 待裁决）|

---

## 步骤三：初始化配置

```bash
# 交互式初始化（推荐）
holmes config init

# 或直接指定知识库路径，跳过交互
holmes config init --kb-path ~/holmes-kb

# 验证配置
holmes config show
# 预期输出：
# kb_path: /home/user/holmes-kb
# llm.model: claude-opus-4-6
# sessions_dir: ~/.holmes/sessions
```

---

## 步骤四：启动 TUI 开始排查

```bash
holmes
```

**TUI 操作说明**：

| 键位 | 功能 |
|------|------|
| `Enter` | 发送消息 |
| `Ctrl+R` | 标记当前会话为已解决（触发自动知识提取）|
| `Ctrl+H` | 查看历史会话列表 |
| `Ctrl+K` | 浏览知识库 |
| `Ctrl+C` | 退出当前会话（返回主界面）|
| `Ctrl+Q` | 退出 Holmes |

**典型排查流程**：

```
启动 holmes → 新建会话 → 多轮对话排查问题
    → 问题解决后按 Ctrl+R 标记为已解决
    → Holmes 自动生成知识总结，写入 contributions/pending/
    → 退出或继续新会话
```

---

## 步骤五：查看和确认自动生成的知识

会话标记为已解决后，Holmes 自动将排查总结写入暂存区，需要你确认后才进入正式知识库。

```bash
# 查看待确认的知识条目
holmes kb pending

# 输出示例：
# ID              来源   标题                              暂存时间
# ────────────────────────────────────────────────────────────────────
# PT-DB-003       auto   Redis 连接池耗尽排查              刚才（来自会话 sess-xxx）

# 查看某条待确认内容的详情
holmes kb pending show PT-DB-003

# 确认：执行三级门控校验后移入正式知识库
holmes kb confirm PT-DB-003
# 流程：
#   [门控 1] Schema 校验（frontmatter 字段 + 必要章节）
#   [门控 2] 重复检测（相似度 > 85% 会警告并阻止）
#   [门控 3] 强制预览全文，输入 y 确认

# 不满意：丢弃
holmes kb reject PT-DB-003
```

---

## 步骤六：导入自己的知识文档

已有排查笔记或文档？直接导入，**无需手动指定类型**，Holmes 自动识别。

```bash
# 最简用法：全自动识别类型、分类、标题、标签
holmes import ./my-redis-fix.md

# 输出示例：
# [识别结果]
#   类型：pitfall（已知风险/排查步骤）
#   分类：database
#   标题：Redis 连接池耗尽排查
#   标签：redis, connection-pool, database, timeout
# ✓ 已写入暂存区（PT-DB-004）
# 提示：运行 `holmes kb confirm PT-DB-004` 移入正式目录

# 先预览识别结果，不写入
holmes import ./my-doc.md --dry-run

# 手动覆盖自动识别结果（识别有误时使用）
holmes import ./my-doc.md --type model --category networking

# 确认导入
holmes kb confirm PT-DB-004
```

---

## 步骤七：同步到远端知识库

将本地新增的知识推送到远端，供所有人使用。

### 正常推送（无冲突）

```bash
cd ~/holmes-kb

# 提交本地变更（确认后的条目 + 暂存区日志）
git add .
git commit -m "feat(pitfall): add Redis connection pool guide"

# 拉取最新内容，再推送
git pull origin main --rebase
git push origin main
```

### 处理推送冲突

```bash
cd ~/holmes-kb

git pull origin main --rebase
# 若出现冲突，不要手动编辑冲突文件，使用 holmes 智能合并：

holmes kb merge

# 输出示例（大多数情况自动处理）：
# ✓ 自动合并：3 个新增条目均已保留
# ✓ PT-NET-001 成熟度自动提升至 proven
# ⚠ 内容矛盾：PT-DB-003
#   → 已写入 contributions/conflicts/PT-DB-003-conflict-20260526.md
#   → 运行 `holmes kb resolve PT-DB-003-conflict-20260526 --keep A|B` 后重试

# 若有内容矛盾，查看冲突详情后裁决
holmes kb resolve PT-DB-003-conflict-20260526 --keep B   # 保留远端版本
# 或保留本地版本：--keep A
# 或手动编辑后标记：--manual

# 完成后推送
git add .
git commit -m "merge: resolve PT-DB-003 conflict"
git push origin main
```

---

## 步骤八：知识库日常维护

```bash
# 拉取他人贡献的最新知识
cd ~/holmes-kb
git pull origin main

# 定期运行健康检查（推荐每周一次）
holmes kb lint

# 输出示例：
# ✓ 索引同步正常（45 条正式条目）
# ⚠ 成熟度衰减：PT-SYS-002 proven → verified（13 个月未引用）
# ✓ 无重复条目，无未解决冲突

# 自动修复可修复项
holmes kb lint --fix
```

---

## 常见问题

**Q: 启动时提示"知识库路径不存在"**
```bash
holmes config set kb_path ~/holmes-kb
```

**Q: 响应速度很慢**
```bash
# 检查 API Key 是否正确设置
echo $ANTHROPIC_API_KEY

# 检查知识库结构是否完整（缺少 README.md 会影响 agent 导航）
ls ~/holmes-kb/README.md
ls ~/holmes-kb/pitfall/_index.md
```

**Q: agent 回复没有引用知识库内容**
```bash
# 检查知识库 README.md 是否有内容（agent 以此为入口）
cat ~/holmes-kb/README.md

# 检查对应类型的 _index.md 是否存在且有条目
cat ~/holmes-kb/pitfall/_index.md

# 重建分类索引
holmes kb rebuild-index
```

**Q: 导入后找不到刚导入的条目**
```bash
# 导入后条目在暂存区，需要先确认
holmes kb pending
holmes kb confirm <ID>
```

**Q: git push 有冲突，不知道如何解决**
```bash
cd ~/holmes-kb
git pull origin main --rebase
holmes kb merge   # 自动处理大多数冲突，内容矛盾才需人工
```

**Q: 想撤销刚才的 confirm 操作**
```bash
# confirm 后条目已在正式目录，直接删除文件后重建索引
rm ~/holmes-kb/pitfall/database/redis-connection-pool.md
holmes kb rebuild-index
```

---

## 开发模式启动

```bash
# Python agent（带调试日志）
cd ~/holmes/agent
conda activate holmes
HOLMES_LOG_LEVEL=debug python -m holmes.cli

# TUI（开发模式，文件变更自动重载）
cd ~/holmes/tui
bun run dev
```
