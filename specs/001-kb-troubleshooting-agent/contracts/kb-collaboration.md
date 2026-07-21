# 知识库协作规范：本地 ↔ 远端同步与冲突处理

**版本**：1.0 | **日期**：2026-05-26

---

## 设计理念

参照知识库参考文档的核心洞察：

> 自动处理可编程的同步操作，只有真正的内容语义冲突才需人工介入。

所有操作遵循「贡献暂存 + 异步合并」模式：
- Agent 自动写入 → 暂存区（`contributions/pending/`）
- 用户审阅确认 → 提交到正式目录
- 推送前自动智能合并 → 仅内容矛盾时才需人工介入

---

## 一、知识库目录完整结构

```
knowledge-base/
├── README.md                   # 全景目录（~50 行，人工维护）
├── index.json                  # 机器可读索引（自动生成，可重建）
├── CHANGELOG.md                # 知识库变更日志（自动追加）
│
├── pitfall/                    # 已知风险/故障模式/排查步骤
│   ├── _index.md               # 分类清单（自动生成）
│   ├── network/
│   ├── system/
│   ├── application/
│   └── database/
├── model/                      # 实体定义/概念知识
│   └── _index.md
├── guideline/                  # 推荐/禁止做法
│   └── _index.md
├── process/                    # 操作步骤/工作流程
│   └── _index.md
├── decision/                   # 技术选型/架构决策
│   └── _index.md
│
└── contributions/              # 协作暂存区（参与 git 版本管理）
    ├── pending/                # 待审阅条目（本地写入，推送前人工确认）
    │   └── {user}-{date}-{slug}.md
    ├── conflicts/              # 内容矛盾（需人工裁决后才可推送）
    │   └── {conflict-id}.md
    └── log.md                  # 贡献日志（追加写入，全量记录）
```

---

## 二、角色体系

| 角色 | 写入权限 | 说明 |
|------|---------|------|
| **maintainer** | 全部目录 + 成熟度裁决 + 冲突裁决 | 团队负责人，负责内容质量把关 |
| **contributor** | 正式条目目录 + contributions/ | 正式成员，可贡献和确认知识 |
| **reader** | 只读 | 仅使用知识，不贡献 |

> **Holmes 默认**：所有安装了 agent 并完成配置的用户均为 contributor。
> maintainer 由远端仓库的 git 权限管理（branch protection 等），agent 不实现额外鉴权。

---

## 三、知识贡献完整工作流

### 3.1 Agent 自动写入（会话解决后）

```
会话标记为已解决
    → AgentEngine.extract_knowledge(session)
        → LLM 生成结构化总结
        → 写入 contributions/pending/{user}-{date}-{slug}.md
        → maturity: "draft"，source: "auto"，source_session: {session_id}
    → 追加 contributions/log.md
    → 重建 index.json（包含 pending 条目，标记 pending=true）
```

`contributions/log.md` 格式（追加式，只增不改）：

```markdown
| 时间 | 操作 | 条目 ID | 条目标题 | 操作者 | 来源会话 |
|------|------|---------|---------|--------|---------|
| 2026-05-26T14:45:11Z | auto_create | PT-DB-003 | Redis 连接池耗尽排查 | local | sess-20260526-143022 |
| 2026-05-26T15:00:00Z | import | PT-NET-002 | DNS 解析失败排查 | local | — |
| 2026-05-26T15:30:00Z | confirm | PT-DB-003 | Redis 连接池耗尽排查 | local | — |
```

### 3.2 用户导入知识（CLI import）

```
holmes import <文件> --type pitfall --category database
    → 解析文件，提取 title/tags
    → 写入 contributions/pending/{user}-{date}-{slug}.md
    → maturity: "draft"，source: "import"
    → 追加 contributions/log.md
```

### 3.3 用户审阅并确认（CLI review）

`holmes kb confirm` 在写入正式目录前执行**三级校验门控**，任意一级不通过则阻止写入：

```
holmes kb confirm PT-DB-003
    │
    ├── [门控 1] Schema 校验
    │     检查 frontmatter 必填字段是否完整（id / title / type / tags / created）
    │     检查对应类型的必要正文章节是否存在
    │     （pitfall 必须有「问题描述」和「解决步骤」）
    │     不通过 → 报错，列出缺失字段，拒绝写入
    │
    ├── [门控 2] 重复检测
    │     扫描 index.json，计算标题 + tags 与现有条目的相似度
    │     相似度 > 85% → 警告并列出相似条目，要求 --force 确认
    │
    └── [门控 3] 强制预览
          自动展示条目全文（等同于 pending show）
          要求用户输入 y/n 确认，不接受盲回车
          确认后写入正式目录
```

```bash
# 确认（会自动触发三级校验）
holmes kb confirm PT-DB-003

# 输出示例（全部通过）：
# [门控 1] Schema 校验 ✓
# [门控 2] 重复检测 ✓（无相似条目）
# [门控 3] 条目预览：
# ─────────────────────────────────────
# 标题：Redis 连接池耗尽排查
# 类型：pitfall / database
# 标签：redis, connection-pool, timeout
#
# ## 问题描述
# Redis 报 max clients reached...
# ─────────────────────────────────────
# 确认写入正式知识库？[y/N] y
# ✓ 已写入 pitfall/database/redis-connection-pool-exhausted.md

# 输出示例（门控 2 命中重复）：
# [门控 2] ⚠ 发现相似条目（相似度 91%）：
#   PT-DB-001  Redis 连接超时排查  pitfall/database/redis-timeout.md
# 如需覆盖或新增，请追加 --force 确认
# 已阻止写入。

# 输出示例（门控 1 Schema 不通过）：
# [门控 1] ✗ Schema 校验失败：
#   缺少必填字段：tags
#   pitfall 类型缺少「解决步骤」章节
# 请修复后重新运行 confirm。
# 已阻止写入。

# 拒绝：删除该 pending 条目
holmes kb reject PT-DB-003
```

确认后：
- 文件从 `contributions/pending/` 移至 `pitfall/database/redis-connection-pool-exhausted.md`
- maturity 保持 `draft`（首次进入正式目录，未经跨会话验证）
- 追加 `contributions/log.md`

### 3.4 提交与推送

```bash
# 用户手动 git commit（agent 不自动 commit）
cd ~/holmes-kb
git add .
git commit -m "feat(pitfall): add Redis connection pool exhausted guide"

# 推送前先拉取
git pull origin main --rebase

# 若无冲突，直接推送
git push origin main

# 若有冲突，执行智能合并（见第四节）
holmes kb merge
```

---

## 四、冲突处理：五种场景

拉取时若出现 git 冲突，执行 `holmes kb merge` 进行智能处理。

### 场景 1：纯新增条目（双方各自新增不同条目）

**判断依据**：冲突文件路径不同，或 `index.json` 中 ID 不重叠。

**处理**：**自动合并**，两条都保留，无需人工介入。

```bash
# holmes kb merge 自动执行：
git checkout --ours  {新条目 A}
git checkout --theirs {新条目 B}
git add .
# 提示用户：✓ 自动合并：2 个新条目均已保留
```

---

### 场景 2：同条目证据追加（双方都更新了同一条目的引用数据）

**判断依据**：同一文件中，仅 `reference_count` / `last_referenced` / `evidence` 字段冲突。

**处理**：**自动合并**，取 `reference_count` 较大值，`last_referenced` 取较晚日期。

```yaml
# 合并结果示例
reference_count: 5   # 取 max(3, 5)
last_referenced: 2026-05-26  # 取较晚日期
maturity: verified   # 见场景 3
```

---

### 场景 3：成熟度提升冲突

**判断依据**：同一条目，双方 `maturity` 字段值不同。

**处理规则**：

| 本地 | 远端 | 合并结果 |
|------|------|---------|
| verified | proven | proven（取较高，自动合并）|
| proven | verified | proven（取较高，自动合并）|
| draft | verified | verified（取较高，自动合并）|
| proven | draft | **verified**（一升一降，取较低，标记 `contradiction` 标签，通知 maintainer）|

---

### 场景 4：内容矛盾（同一条目的正文内容有实质差异）

**判断依据**：同一文件中，`## 问题描述` / `## 解决步骤` 等正文章节存在实质性差异（非仅元数据）。

**处理**：**提交至 `contributions/conflicts/`，通知用户人工裁决，禁止自动合并。**

```bash
# holmes kb merge 自动执行：
# 1. 将冲突文件复制到 contributions/conflicts/
cp <冲突文件> contributions/conflicts/PT-DB-003-conflict-20260526.md
# 2. 在冲突文件中保留两个版本：
```

`contributions/conflicts/PT-DB-003-conflict-20260526.md` 格式：

```markdown
---
conflict_id: PT-DB-003-conflict-20260526
entry_id: PT-DB-003
created: 2026-05-26
status: pending_review
local_author: user-a
remote_author: user-b
---

# 冲突裁决：PT-DB-003 Redis 连接池耗尽排查

## 版本 A（本地，user-a，2026-05-25）

[本地版本正文内容]

---

## 版本 B（远端，user-b，2026-05-26）

[远端版本正文内容]

---

## 裁决说明

> maintainer 填写裁决意见后，运行 `holmes kb resolve PT-DB-003-conflict-20260526 --keep A|B|manual`
```

**裁决命令**：

```bash
# 保留版本 A（本地）
holmes kb resolve PT-DB-003-conflict-20260526 --keep A

# 保留版本 B（远端）
holmes kb resolve PT-DB-003-conflict-20260526 --keep B

# 手动编辑后标记为已解决
holmes kb resolve PT-DB-003-conflict-20260526 --manual
```

---

### 场景 5：成熟度冲突（一方提升，另一方降级）

**判断依据**：本地将条目从 `verified` → `proven`，远端将同一条目从 `verified` → `draft`。

**处理**：**保留较低成熟度（draft），追加 `contradiction` 标签，记录到 `contributions/log.md`，通知用户复查。**

```yaml
# 合并结果
maturity: draft
tags: [...原有标签, "contradiction"]
```

---

## 五、合并操作完整流程图

```
git pull origin main --rebase
    │
    ├── 无冲突 → git push，完成
    │
    └── 有冲突 → holmes kb merge
                    │
                    ├── 场景 1：纯新增 → 自动保留双方 → git add → 继续
                    ├── 场景 2：证据追加 → 自动取最大值 → git add → 继续
                    ├── 场景 3：成熟度提升 → 自动取较高/较低 → git add → 继续
                    ├── 场景 4：内容矛盾 → 移入 conflicts/ → 等待人工裁决
                    │                       → holmes kb resolve → git add → 继续
                    └── 场景 5：成熟度冲突 → 取较低 + contradiction 标签 → git add → 继续
                    │
                    └── 所有冲突处理完毕 → git rebase --continue → git push
```

---

## 六、知识库健康治理（Lint）

```bash
# 运行健康检查
holmes kb lint
```

**Lint 检查项及自动修复**：

| 检查项 | 自动处理 | 需人工处理 |
|--------|---------|-----------|
| index.json 与文件不一致 | ✅ 自动重建索引 | — |
| 孤儿条目（0 引用、从未验证）| 降级为 draft | — |
| 成熟度衰减（超时未引用） | ✅ 自动降级 | — |
| 内容矛盾条目（contradiction 标签）| 标记并报告 | maintainer 人工裁决 |
| 重复条目（标题相似度 > 85%）| 标记为合并候选 | 用户决定是否合并 |
| `contributions/pending/` 超过 30 天未确认 | 发出警告 | 用户确认或拒绝 |
| `contributions/conflicts/` 未解决冲突 | 阻止 push（警告）| 用户解决 |

**Lint 触发时机**：
- `holmes kb lint` 手动触发
- 每完成 10 次会话自动提醒运行
- `git push` 前自动检查 `contributions/conflicts/` 是否有未解决冲突（有则阻止推送并提示）

---

## 七、引用追踪与成熟度自动更新

Agent 每次会话结束时，自动更新被引用条目的元数据：

```python
# 会话结束时执行（无论是否标记解决）
for entry_id in session.all_kb_refs:
    entry = kb.get(entry_id)
    entry.reference_count += 1
    entry.last_referenced = today()
    # 检查是否满足成熟度晋升条件
    if entry.maturity == "draft" and entry.reference_count >= 1:
        entry.maturity = "verified"
    elif entry.maturity == "verified" and unique_session_count(entry_id) >= 2:
        entry.maturity = "proven"
    kb.save(entry)
```

更新仅写入本地 clone，用户在下次 `git push` 时一并推送。

---

## 八、典型协作场景示例

### 场景：用户 A 和用户 B 同时排查了同一类问题

```bash
# 用户 A（本地）：
# 会话解决 → agent 写入 contributions/pending/
# holmes kb confirm PT-DB-004
# git add . && git commit -m "feat(pitfall): add MySQL deadlock guide"
# git pull --rebase → 无冲突 → git push ✓

# 用户 B（本地，稍晚推送）：
# 会话解决 → agent 写入 contributions/pending/
# holmes kb confirm PT-DB-004  # 同 ID！
# git add . && git commit -m "feat(pitfall): add MySQL deadlock guide v2"
# git pull --rebase → 发现冲突

# 执行智能合并：
holmes kb merge
# 输出：
# ⚠ 发现内容矛盾：PT-DB-004
#   → 已移入 contributions/conflicts/PT-DB-004-conflict-20260526.md
#   → 请运行 `holmes kb resolve PT-DB-004-conflict-20260526 --keep A|B|merge` 后重试推送

# 用户 B 查看冲突：
holmes kb resolve PT-DB-004-conflict-20260526 --keep B  # 或人工合并

# 最终推送：
git add . && git commit -m "merge: resolve PT-DB-004 conflict"
git push ✓
```

---

## 九、知识库完整性防护体系

### 9.1 防护层全景

```
写入前                写入时               写入后               使用时
──────────────────────────────────────────────────────────────────────
pending 暂存          confirm 三级门控      lint 健康检查         成熟度权重
(不参与检索)          ├ Schema 校验         ├ 结构一致性           draft < verified
                      ├ 重复检测            ├ 成熟度衰减           < proven
                      └ 强制预览确认         ├ 孤儿条目清理
                                           └ contradiction 标记

合并时                历史回溯
──────────────────────────────────────────────────────────────────────
holmes kb merge       git revert / git log
5 种场景分级处理       任意时间点可恢复
内容矛盾隔离至 conflicts/
```

### 9.2 各风险场景覆盖

| 风险场景 | 防护机制 | 是否覆盖 |
|---------|---------|---------|
| Agent 生成质量差的知识总结 | pending 暂存 + confirm 强制预览 | ✅ |
| 用户导入无关/错误文档 | pending 暂存 + Schema 校验 + 强制预览 | ✅ |
| 盲目 confirm 未读内容 | confirm 强制预览（必须输入 y/n）| ✅ |
| 导入重复条目 | confirm 重复检测（相似度 > 85% 阻止）| ✅ |
| 条目结构残缺（缺字段/章节）| confirm Schema 校验门控 | ✅ |
| git merge 引入错误内容 | holmes kb merge 隔离内容矛盾 | ✅ |
| 误操作删除/覆盖条目 | git revert 全量历史恢复 | ✅ |
| 过时知识误导排查 | maturity 衰减 + agent 标注成熟度 | ✅ |
| 同一问题多个矛盾条目 | lint 检测 contradiction 标签 | ✅ |
| 大批量误导性内容被推送 | 远端 git branch protection（maintainer review）| ✅ |

### 9.3 成熟度作为污染隔离机制

正式目录中的条目按成熟度分级，agent 读取时标注来源可信度：

```
draft   → agent 引用时注明「此条目尚未经验证，仅供参考」
verified → agent 正常引用，不附加提示
proven  → agent 引用时注明「此条目已多次验证，可信度高」
```

这意味着即使一个质量一般的条目通过了 confirm 进入正式目录，
它在被引用验证之前始终以 `draft` 标注，不会以"确定性知识"呈现给用户。

### 9.4 误操作恢复

```bash
# 场景 1：confirm 了一个错误条目，想撤销
git -C ~/holmes-kb log --oneline -5          # 找到误操作前的 commit
git -C ~/holmes-kb revert HEAD               # 撤销最近一次 commit
holmes kb rebuild-index                       # 重建索引

# 场景 2：发现知识库中有一条长期存在的错误条目
holmes kb reject <ID>                         # 无此命令（confirm 后进正式目录）
# 直接删除文件：
rm ~/holmes-kb/pitfall/database/wrong-entry.md
holmes kb rebuild-index
git -C ~/holmes-kb add . && git commit -m "fix: remove incorrect entry PT-DB-003"

# 场景 3：远端被错误推送污染（需 maintainer 处理）
git -C ~/holmes-kb revert <bad-commit-hash>
git push origin main
```
