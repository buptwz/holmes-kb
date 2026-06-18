# Holmes 测试计划

**版本**：1.0 | **日期**：2026-05-28
**依据**：spec.md · plan.md · data-model.md · contracts/cli-schema.md · tasks.md

---

## 前言：数据模型已知偏差（测试前需确认）

在执行测试前，需先确认以下实现与设计文档的偏差：

| 编号 | 设计文档 | 实际实现 | 影响 |
|------|---------|---------|------|
| DM-01 | `data-model.md` frontmatter 字段 `created` / `updated` | `schema.py` 使用 `created_at` / `updated_at` | Schema Gate 1 校验以代码为准，文档需更新 |
| DM-02 | `data-model.md` pitfall 正文章节：`## 问题描述`、`## 解决步骤` | `schema.py` 校验英文章节：`## Symptoms`、`## Root Cause`、`## Resolution` | 现有条目（PT-DB-001）用英文；新导入文档若用中文章节将被 Gate 1 拦截 |
| DM-03 | `data-model.md` maturity 三级：`draft / verified / proven` | `schema.py` 增加第四级 `deprecated` | 测试衰减逻辑时 `deprecated` 为有效值 |
| DM-04 | `cli-schema.md` 定义 `holmes config init`、`holmes session list`、`holmes session show` | 实际 `holmes --help` 无上述命令（仅有 `setup / import / kb`）| 上述命令属未实现功能，测试范围排除 |
| DM-05 | `data-model.md` 成熟度衰减基准：`last_referenced`（最后被会话引用时间） | `linter.py` 现已使用 `last_referenced` 作为衰减时钟；`EntryMeta` 已增加 `last_referenced`/`reference_count` 字段 | **已对齐**：未被引用的新条目不触发衰减 |
| DM-06 | `data-model.md` 成熟度升级：`draft→verified`（1次引用）、`verified→proven`（≥3次引用） | `store.py` 已实现 `update_references()`；`cli.py` 已增加 `holmes kb update-refs`；`KbExtractAndSave` 在 `/holmes-resolve` 时自动调用 | **已实现**：TC-US4-15/16 可正常执行 |
| DM-07 | `data-model.md` 成熟度升级 verified→proven 条件：**≥2 次不同会话** | 实现使用 `reference_count >= 3`（累计引用次数，不区分会话）| 语义有差异：设计要求区分会话，实现不区分；TC-US4-16 按实现测试，需后续决策是否对齐设计 |

---

## 测试范围

| 用户故事 | 优先级 | 测试类型 |
|---------|--------|---------|
| US1 安装配置与首次排查 | P1 · MVP | 冒烟 + 功能 + Agent 集成 |
| US2 排查后提取保存知识 | P1 | 功能 + 数据模型 + Agent 集成 |
| US3 CLI 导入外部知识 | P1 | 功能 + 边界 + 数据模型 |
| US4 KB CLI 运维 | P1 | 功能 + 边界 + 数据模型 |
| US5 KB 内容浏览 | P2 | 功能 + 一致性 |

---

## US1 — 安装配置与首次排查

### TC-US1-01：`holmes setup` 写入配置

**类型**：冒烟
**前置**：`~/.holmes/settings.json` 尚不含 `HOLMES_KB_PATH`
**步骤**：
```bash
holmes setup --kb-path ~/holmes-kb \
             --model gpt-4o \
             --api-key sk-xxx \
             --api-base-url https://api.openai.com/v1
```
**用户侧预期**：终端输出两行确认：
- `✓ KB path written to ~/.holmes/settings.json`
- `✓ Model config written to ~/.holmes/config.json`

**数据模型验证**：
```bash
# settings.json 的 env 字段必须有：
cat ~/.holmes/settings.json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['env']['HOLMES_KB_PATH']=='~/holmes-kb'"

# config.json 必须有 api_key / api_base_url / model：
cat ~/.holmes/config.json | python3 -c "import json,sys; d=json.load(sys.stdin); assert all(k in d for k in ['api_key','api_base_url','model'])"
```

**额外检查（DM-01 影响）**：`setup` 在 KB 根目录生成的 `HOLMES.md` 或 `CLAUDE.md` 内容是否符合设计。

---

### TC-US1-02：holmes-agent 版本与品牌

**类型**：冒烟
**步骤**：
```bash
holmes-agent --version
```
**预期**：输出格式为 `2.6.x (Holmes)`，不含 "Claude Code"。

---

### TC-US1-03：KB 只读工具链 — Agent 排查触发 KbSearch

**类型**：Agent 集成
**前置**：`setup` 完成，`holmes-kb` 含 PT-DB-001
**步骤**：
```bash
holmes-agent --print "Redis 连接一直超时，请帮我排查"
```
**用户侧预期**：
- 回答中引用了 KB 条目（出现 `PT-DB-001` 或条目标题）
- 排查建议包含连接池调整、泄漏检查等实质性内容

**数据模型验证**：无写入，KB 目录无变化。

---

### TC-US1-04：KB 只读工具链 — KbReadEntry 读取条目全文

**类型**：功能
**步骤**：
```bash
holmes-agent --print "请用 KbReadEntry 读取 PT-DB-001 并告诉我 Resolution 部分的具体步骤"
```
**预期**：
- Agent 调用 `KbReadEntry` 工具
- 回答中出现条目 Resolution 章节的具体步骤（连接池大小、泄漏修复、监控告警等）

---

### TC-US1-05：KB 搜索无命中时的行为

**类型**：边界
**步骤**：
```bash
holmes-agent --print "量子计算机散热失效怎么排查"
```
**预期**：
- Agent 说明 KB 中无匹配条目（而非静默返回空）
- 依据通用知识给出建议，并明确标注为"非 KB 内容"

---

### TC-US1-06：`holmes setup` 生成 HOLMES.md（FR-001）

**类型**：功能
**前置**：KB 根目录尚无 HOLMES.md
**步骤**：执行 TC-US1-01 的 `holmes setup` 命令后：
```bash
ls ~/holmes-kb/HOLMES.md
cat ~/holmes-kb/HOLMES.md | head -5
```
**预期**：
- 文件存在
- 内容包含排查方法论、KB 工具使用提示（非空文件）
- 命令输出含确认 HOLMES.md 已写入的提示

---

### TC-US1-07：CLI 描述字符串替换（BR-002）

**类型**：冒烟
**步骤**：
```bash
holmes --help
```
**预期**：
- `--help` 输出中出现 `Holmes` 或 `Holmes Agent` 字样
- **不含** `Claude Code` / `claude` / `ccb` 等原始品牌文字

---

### TC-US1-08：HOLMES.md 系统提示注入效果

**类型**：Agent 集成
**前置**：`holmes setup` 完成，HOLMES.md 存在于 KB 根目录
**步骤**：
```bash
holmes-agent --print "你的排查方法论是什么？请描述你处理问题的步骤。"
```
**预期**：
- Agent 回答体现 HOLMES.md 中的排查规范（先读 KB 概览→精准检索→读全文）
- Agent 提及执行 `/holmes-resolve` 保存知识的规范

**数据模型验证**：无写入。

---

## US2 — 排查后提取并保存知识

### TC-US2-01：`/holmes-resolve` 触发知识提取

**类型**：Agent 集成（核心）
**前置**：
1. 启动 `holmes-agent` 交互会话
2. 完成一次排查（描述问题、获得解决方案）
3. 用户确认："问题已解决"

**步骤**：在 Agent 会话中输入 `/holmes-resolve`

**用户侧预期**：
- Agent 调用 `KbExtractAndSave` 工具前弹出 holmes-agent 原生权限确认（因 `isReadOnly: false`）
- 用户确认后，Agent 输出：
  ```
  ✓ Knowledge saved to pending area
  Pending ID: <id>
  To promote: holmes kb confirm <id>
  ```

**数据模型验证**：
```bash
ls ~/holmes-kb/contributions/pending/
# 必须出现新文件，文件名含日期

# 新文件的 frontmatter 必须包含：
python3 -c "
import frontmatter, glob, os
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
if files:
    p = frontmatter.load(files[-1])
    assert p.get('type') in ['pitfall','model','guideline','process','decision']
    assert p.get('maturity') == 'draft'         # pending 条目始终 draft
    # 注意：pending 条目无 id 字段（尚未 confirm）
    print('OK:', files[-1])
"
```

**DM-02 偏差验证**：pending 条目正文章节应为英文（`## Symptoms`），确认 `KbExtractAndSave` 使用英文模板而非 `data-model.md` 中的中文模板。

---

### TC-US2-02：`holmes kb pending` 展示 pending 列表

**类型**：功能
**前置**：TC-US2-01 成功，pending 区有条目
**步骤**：
```bash
holmes kb pending
```
**用户侧预期**：
- 表格输出，含列：ID / 类型 / 标题 / 暂存时间
- 刚写入的条目出现在列表中

**数据模型验证**：pending 列表中的条目文件路径均在 `contributions/pending/` 下。

---

### TC-US2-03：`holmes kb confirm` 3-Gate 完整流程

**类型**：功能（核心）
**前置**：pending 区有一条 schema 完整的新条目
**步骤**：
```bash
holmes kb confirm <pending_id>
# Gate 3 提示时输入 y
```
**用户侧预期**：
1. 输出"Schema 校验通过"
2. 输出"无重复条目"（若标题全新）
3. 展示条目全文，等待 `y/n`
4. 用户输入 `y` 后：`✓ Entry confirmed: PT-XX-NNN`

**数据模型验证**：
```bash
# 条目移入正式目录（不再在 pending/ 下）
ls ~/holmes-kb/contributions/pending/  # 该条目消失

# 正式目录出现对应文件
python3 -c "
import frontmatter, glob
# 找最新条目
files = sorted(glob.glob('~/holmes-kb/**/*.md', recursive=True))
# 排除 pending/conflicts/_index.md
official = [f for f in files if 'pending' not in f and 'conflicts' not in f and '_index' not in f]
p = frontmatter.load(official[-1])
assert 'id' in p.metadata            # 已分配永久 ID
assert p['maturity'] == 'draft'      # 新入库仍为 draft
print('ID:', p['id'])
"

# _index.md 已更新（含新条目行）
grep "$(holmes kb pending --json | python3 -c 'import json,sys; d=json.load(sys.stdin)')" \
  ~/holmes-kb/pitfall/_index.md || echo "check _index.md manually"
```

**ID 格式验证（FR-007 + validator.py）**：
- pitfall/database 条目：格式必须是 `PT-DB-NNN`，NNN 为当前最大序号 +1
- pitfall/network 条目：格式必须是 `PT-NET-NNN`
- model 条目：`MD-GEN-NNN`（无子分类时）

---

### TC-US2-04：`confirm` 后新会话可检索到该条目

**类型**：集成
**前置**：TC-US2-03 成功，新条目已入库
**步骤**：
```bash
holmes-agent --print "（用新条目描述的症状提问）"
```
**预期**：Agent 通过 KbSearch 检索到新条目并引用其 ID。

---

### TC-US2-05：pending 条目 `source` / `source_session` 字段（data-model.md §1.5）

**类型**：数据模型
**前置**：TC-US2-01 成功，pending 区有新条目
**步骤**：
```bash
python3 -c "
import frontmatter, glob
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
p = frontmatter.load(files[-1])
print('source:', p.metadata.get('source'))
print('source_session:', p.metadata.get('source_session'))
"
```
**预期**：
- `source` 值为 `"auto"`（来自 `/holmes-resolve` 提取）
- `source_session` 非空（包含会话标识）

---

### TC-US2-06：pending 条目专有字段完整性（data-model.md §1.5）

**类型**：数据模型
**前置**：TC-US2-01 成功
**步骤**：
```bash
python3 -c "
import frontmatter, glob
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
p = frontmatter.load(files[-1])
# pending 专有字段
print('pending:', p.metadata.get('pending'))
print('pending_since:', p.metadata.get('pending_since'))
print('suggested_type:', p.metadata.get('suggested_type'))
print('suggested_category:', p.metadata.get('suggested_category'))
"
```
**预期**：
- `pending: true`
- `pending_since`：ISO 8601 时间戳，非空
- `suggested_type`：有效类型值（pitfall/model 等）
- `suggested_category`：分类值（database/network 等）

---

## US3 — CLI 导入外部知识

### TC-US3-01：正常导入（LLM 自动分类）

**类型**：功能
**前置**：准备一份 ≥50 字符的故障描述文件：
```bash
cat > /tmp/test-import.md << 'EOF'
## 故障描述
Nginx 返回 502 Bad Gateway 错误，上游 Python 服务正常运行。
检查后发现 Nginx upstream timeout 配置过短（默认60s），
实际请求处理需要 90s，导致 Nginx 超时后断开连接。
解决：修改 proxy_read_timeout 为 120s。
EOF
```
**步骤**：
```bash
holmes import /tmp/test-import.md
```
**用户侧预期**：
- 输出识别结果（类型 pitfall、分类 network 或 application、标题、标签）
- 输出 pending ID 和路径
- 提示 `holmes kb confirm <ID>`

**数据模型验证**：
```bash
# 确认文件出现在 pending/
ls ~/holmes-kb/contributions/pending/

# 条目 frontmatter 完整性（DM-01 偏差重点）
python3 -c "
import frontmatter, glob
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
p = frontmatter.load(files[-1])
required = {'type','title','maturity','category','tags','created_at','updated_at'}
missing = required - set(p.metadata.keys())
print('Missing fields:', missing or 'None')
assert p['maturity'] == 'draft'
"
```

**DM-02 关键验证**：检查 LLM 生成的正文章节是否为英文（`## Symptoms`）——若 LLM 输出中文章节名，Gate 1 将在 confirm 时报错。

---

### TC-US3-02：`--dry-run` 仅预览不写入

**类型**：功能
**步骤**：
```bash
holmes import /tmp/test-import.md --dry-run
COUNT_BEFORE=$(ls ~/holmes-kb/contributions/pending/ | wc -l)
holmes import /tmp/test-import.md --dry-run
COUNT_AFTER=$(ls ~/holmes-kb/contributions/pending/ | wc -l)
echo "Before: $COUNT_BEFORE, After: $COUNT_AFTER"
```
**预期**：
- 终端展示结构化预览（类型、标题、标签）
- `COUNT_BEFORE == COUNT_AFTER`（文件数未增加）

---

### TC-US3-03：内容 < 50 字符直接拒绝

**类型**：边界（FR-006）
**步骤**：
```bash
echo "太短" | holmes import /dev/stdin
# 或
echo "短文本测试" > /tmp/short.txt && holmes import /tmp/short.txt
```
**预期**：
- 命令直接输出错误："内容过短，至少需要 50 字符"（或类似提示）
- 退出码非 0
- 不调用 LLM（无网络请求）
- pending/ 目录无新文件

---

### TC-US3-04：`--type` 覆盖自动推断

**类型**：功能
**步骤**：
```bash
holmes import /tmp/test-import.md --type guideline --category system
```
**预期**：
- 输出显示"已使用指定参数，跳过该字段的自动识别"
- pending 条目 frontmatter 中 `type=guideline`、`category=system`

---

### TC-US3-05：`--title` 和 `--tags` 选项覆盖自动提取（cli-schema.md）

**类型**：功能
**步骤**：
```bash
holmes import /tmp/test-import.md \
  --title "Nginx upstream 超时排查" \
  --tags "nginx,upstream,timeout,502"
```
**预期**：
- pending 条目 frontmatter 中 `title = "Nginx upstream 超时排查"`
- `tags` 包含 `["nginx","upstream","timeout","502"]`（不被 LLM 覆盖）
- 输出显示使用了指定 title 和 tags

---

### TC-US3-06：`--force` 选项覆盖同名条目（cli-schema.md）

**类型**：功能
**前置**：pending 区已有一条同类条目
**步骤**：
```bash
# 第一次导入
holmes import /tmp/test-import.md --title "重复标题测试"
# 第二次导入同一文件加 --force
holmes import /tmp/test-import.md --title "重复标题测试" --force
```
**预期**：
- 不加 `--force` 时第二次导入被拒绝或警告"已存在同名条目"
- 加 `--force` 后成功写入，退出码 0

---

### TC-US3-07：`holmes import` 错误退出码（cli-schema.md）

**类型**：边界
**子用例**：

```bash
# 退出码 1：文件不存在
holmes import /tmp/nonexistent.md
echo "exit: $?"   # 期望: 1

# 退出码 2：配置错误（未设置 KB 路径）
HOLMES_KB_PATH="" holmes import /tmp/test-import.md
echo "exit: $?"   # 期望: 2
```
**预期**：各场景退出码与 cli-schema.md 规范一致，并输出可读错误信息。

---

## US4 — KB CLI 运维

### TC-US4-01：Gate 1 — Schema 残缺条目被拦截

**类型**：边界（SC-002）
**前置**：手动写一条缺少必填字段的 pending 条目：
```bash
cat > ~/holmes-kb/contributions/pending/bad-entry.md << 'EOF'
---
type: pitfall
title: 测试残缺条目
---

## Symptoms
测试症状描述
EOF
```
**步骤**：
```bash
holmes kb confirm bad-entry.md
```
**预期**：
- 命令输出"Schema 校验失败"
- 列出缺失字段：`maturity`、`category`、`tags`、`created_at`、`updated_at`
- 条目保留在 pending/ 中（未被删除）
- 退出码非 0

**数据模型验证**：`contributions/pending/bad-entry.md` 仍存在。

---

### TC-US4-02：Gate 1 — 缺少必需章节被拦截

**类型**：边界
**前置**：
```bash
cat > ~/holmes-kb/contributions/pending/no-sections.md << 'EOF'
---
id: PT-DB-TEST
type: pitfall
title: 缺少章节测试
maturity: draft
category: database
tags: [test]
created_at: "2026-05-28"
updated_at: "2026-05-28"
---

只有内容，没有规定章节。
EOF
```
**步骤**：`holmes kb confirm no-sections.md`
**预期**：Gate 1 报"缺少必需章节：`## Symptoms`、`## Root Cause`、`## Resolution`"，条目留 pending。

**DM-02 重点**：确认此处校验的是英文章节名，不是中文。

---

### TC-US4-03：Gate 2 — 相似度 > 85% 重复被拦截

**类型**：边界（SC-002，FR-007）
**前置**：KB 中已有 PT-DB-001"Redis 连接池耗尽导致超时"。准备一条高度相似的 pending 条目：
```bash
cat > ~/holmes-kb/contributions/pending/dup-test.md << 'EOF'
---
type: pitfall
title: Redis 连接池耗尽超时问题
maturity: draft
category: database
tags: [redis, connection-pool]
created_at: "2026-05-28"
updated_at: "2026-05-28"
---

## Symptoms
Redis 超时错误

## Root Cause
连接池耗尽

## Resolution
调大连接池
EOF
```
**步骤**：`holmes kb confirm dup-test.md`
**预期**：
- Gate 2 输出"检测到相似条目：PT-DB-001（相似度 > 85%）"
- 命令拒绝写入，提示 `--force` 强制覆盖
- `dup-test.md` 仍在 pending/

**验证 `--force`**：
```bash
holmes kb confirm dup-test.md --force
# 预期：提示用户"相似条目已存在，强制写入"，进入 Gate 3
```

---

### TC-US4-04：Gate 2 — 标题相似度 < 85% 时不拦截

**类型**：功能
**步骤**：构造一条全新标题的 pending 条目，执行 `confirm`。
**预期**：Gate 2 输出"无重复条目"，进入 Gate 3。

---

### TC-US4-05：Gate 3 — 用户输入 `n` 时条目保留

**类型**：功能
**步骤**：执行 `holmes kb confirm <valid_entry>`，Gate 3 展示全文时输入 `n`。
**预期**：输出"已取消"，条目仍在 pending/，未移入正式目录。

---

### TC-US4-06：ID 自动生成格式正确性

**类型**：数据模型（FR-007）
**前置**：KB 中 pitfall/database/ 下已有 `PT-DB-001`
**步骤**：confirm 一条 `type=pitfall, category=database` 的 pending 条目
**预期**：新条目 frontmatter 中 `id = PT-DB-002`（递增+1）

**边界用例**：
- pitfall/network/ 为空时，第一条 network 条目应为 `PT-NET-001`
- model 无子分类时，ID 格式为 `MD-GEN-001`

---

### TC-US4-07：`holmes kb reject` 删除 pending 条目

**类型**：功能
**步骤**：
```bash
# 先确认 pending 条目存在
holmes kb pending
BEFORE=$(ls ~/holmes-kb/contributions/pending/ | wc -l)

holmes kb reject <pending_id> --reason "内容有误"

AFTER=$(ls ~/holmes-kb/contributions/pending/ | wc -l)
echo "Before: $BEFORE, After: $AFTER"
```
**预期**：
- `AFTER = BEFORE - 1`（条目被删除）
- `contributions/log.md` 末尾追加一行：时间戳 | reject | ID | 内容有误

**数据模型验证**：
```bash
tail -5 ~/holmes-kb/contributions/log.md
# 必须包含：| reject | <ID> | 内容有误
```

---

### TC-US4-08：`holmes kb merge` — 纯新增自动处理

**类型**：功能（SC-003）
**前置**：模拟 git pull 后新增条目冲突：
```bash
cd ~/holmes-kb
# 在另一分支创建新条目，制造 git conflict markers
cat > pitfall/network/dns-test.md << 'EOF'
<<<<<<< HEAD
（本地版本：空文件）
=======
---
type: pitfall
title: DNS 解析超时
maturity: draft
category: network
tags: [dns, network]
created_at: "2026-05-28"
updated_at: "2026-05-28"
---

## Symptoms
DNS 解析失败

## Root Cause
DNS 服务器不可达

## Resolution
切换 DNS 服务器
>>>>>>> origin/main
EOF
```
**步骤**：`holmes kb merge`
**预期**：
- 输出"自动处理：1 个纯新增条目"
- `dns-test.md` 冲突标记被清除，保留远端版本内容
- 退出码 0

---

### TC-US4-09：`holmes kb merge` — 内容矛盾隔离至 conflicts/

**类型**：功能（SC-003）
**前置**：为现有条目（如 PT-DB-001）制造内容矛盾的 git conflict markers
**步骤**：`holmes kb merge`
**预期**：
- 输出"⚠ 内容矛盾：PT-DB-001 → 已写入 contributions/conflicts/"
- `contributions/conflicts/` 出现对应冲突文件
- 退出码 1（需人工处理）

**数据模型验证（DM 规范）**：
```bash
python3 -c "
import frontmatter, glob
files = glob.glob('~/holmes-kb/contributions/conflicts/*.md')
if files:
    p = frontmatter.load(files[-1])
    assert 'conflict_id' in p.metadata
    assert p['status'] == 'pending_review'
    assert 'local_author' in p.metadata
    assert 'remote_author' in p.metadata
    print('ConflictEntry schema OK')
"
```

---

### TC-US4-10：`holmes kb resolve` 裁决冲突

**类型**：功能
**前置**：TC-US4-09 成功，conflicts/ 中有冲突文件
**步骤**：
```bash
holmes kb resolve <conflict_id> --keep A
```
**预期**：
- 冲突文件从 `contributions/conflicts/` 删除
- 选定版本写入正式目录
- `contributions/log.md` 追加记录
- 退出码 0

---

### TC-US4-11：`holmes kb lint` 健康报告

**类型**：功能
**步骤**：`holmes kb lint`
**预期**：输出包含：
- 总条目数（正式）
- pending 条目数
- 冲突数
- 各检查项状态（✓ 或 ⚠）

**`--fix` 验证**：
```bash
# 手动删除 _index.md 使其不一致
mv ~/holmes-kb/pitfall/_index.md ~/holmes-kb/pitfall/_index.md.bak

holmes kb lint --fix

# 预期：检测到不一致并自动重建 _index.md
ls ~/holmes-kb/pitfall/_index.md  # 必须重新存在
```

---

### TC-US4-12：成熟度降级检测 — proven → verified（365天）

**类型**：数据模型
**前置**：手动修改一条条目，设置 `last_referenced` 为 13 个月前：
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p['maturity'] = 'proven'
p['last_referenced'] = '2025-04-01T00:00:00+00:00'  # 13个月前
path.write_text(frontmatter.dumps(p))
"
```
**步骤**：`holmes kb lint`
**预期**：输出 `⚠ PT-DB-001 maturity is 'proven' but not referenced in NNN days (threshold: 365)`

**`--fix` 写回验证**：
```bash
holmes kb lint --fix
python3 -c "
import frontmatter
p = frontmatter.load('~/holmes-kb/pitfall/database/PT-DB-001.md')
assert p['maturity'] == 'verified', f'Expected verified, got {p[\"maturity\"]}'
print('OK: maturity decayed proven → verified')
"
```

---

### TC-US4-13：成熟度降级检测 — verified → draft（180天）

**类型**：数据模型
**前置**：设置 `last_referenced` 为 7 个月前：
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p['maturity'] = 'verified'
p['last_referenced'] = '2025-11-01T00:00:00+00:00'  # 7个月前
path.write_text(frontmatter.dumps(p))
"
```
**步骤**：`holmes kb lint`
**预期**：输出 `⚠ PT-DB-001 maturity is 'verified' but not referenced in NNN days (threshold: 180)`

**`--fix` 写回验证**：
```bash
holmes kb lint --fix
python3 -c "
import frontmatter
p = frontmatter.load('~/holmes-kb/pitfall/database/PT-DB-001.md')
assert p['maturity'] == 'draft', f'Expected draft, got {p[\"maturity\"]}'
print('OK: maturity decayed verified → draft')
"
```

---

### TC-US4-14：降级边界 — 未到阈值时不触发

**类型**：数据模型（边界）
**前置**：设 `maturity=proven`，`last_referenced` 为 **11个月**前（未到 365天）
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p['maturity'] = 'proven'
p['last_referenced'] = '2025-06-01T00:00:00+00:00'  # 约11个月前
path.write_text(frontmatter.dumps(p))
"
```
**步骤**：`holmes kb lint`
**预期**：**不**输出该条目的衰减警告

**另一边界**：`last_referenced` 为空（从未引用）的条目，`holmes kb lint` 也**不应**输出衰减警告（新条目保护）。

---

### TC-US4-15：成熟度升级 — draft → verified（1次引用）

**类型**：数据模型

**实现路径**：`/holmes-resolve` → `KbExtractAndSave(referenced_entry_ids=[...])` → `holmes kb update-refs --ids PT-DB-001` → `store.update_references()`

**前置**：PT-DB-001 的 `maturity=draft`，`reference_count=0`
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p['maturity'] = 'draft'
p['reference_count'] = 0
p['last_referenced'] = ''
path.write_text(frontmatter.dumps(p))
"
```

**步骤（CLI 直接测试）**：
```bash
holmes --kb-path ~/holmes-kb kb update-refs --ids PT-DB-001
```
**预期 stdout**：`{"updated": 1, "promoted": ["PT-DB-001"]}`

**数据模型验证**：
```bash
python3 -c "
import frontmatter
p = frontmatter.load('~/holmes-kb/pitfall/database/PT-DB-001.md')
assert p['maturity'] == 'verified', f'Expected verified, got {p[\"maturity\"]}'
assert p['reference_count'] == 1
assert p['last_referenced'] != ''
print('OK: draft → verified after 1 reference')
"
```

**Agent 集成测试**：在 `holmes-agent` 会话中完成排查后执行 `/holmes-resolve`，在权限确认后检查 PT-DB-001 的 `maturity` 和 `reference_count`。

---

### TC-US4-16：成熟度升级 — verified → proven（≥3次引用）

**类型**：数据模型

**前置**：PT-DB-001 的 `maturity=verified`，`reference_count=2`
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p['maturity'] = 'verified'
p['reference_count'] = 2
path.write_text(frontmatter.dumps(p))
"
```

**步骤**：第 3 次调用 `update-refs`：
```bash
holmes --kb-path ~/holmes-kb kb update-refs --ids PT-DB-001
```
**预期 stdout**：`{"updated": 1, "promoted": ["PT-DB-001"]}`

**数据模型验证**：
```bash
python3 -c "
import frontmatter
p = frontmatter.load('~/holmes-kb/pitfall/database/PT-DB-001.md')
assert p['maturity'] == 'proven', f'Expected proven, got {p[\"maturity\"]}'
assert p['reference_count'] == 3
print('OK: verified → proven after 3rd reference')
"
```

**阈值边界**：`reference_count=2`，`maturity=verified` 时调用一次 `update-refs` 应升级到 proven；`reference_count=1`，`maturity=draft` 时调用一次 `update-refs` 应升级到 verified 但**不跳级**到 proven。

---

### TC-US4-17：merge — 证据追加（自动合并 reference_count / last_referenced）

**类型**：功能（FR-008，SC-003）
**前置**：构造同一条目 PT-DB-001 的两个版本，仅 reference_count 和 last_referenced 不同：
```bash
cd ~/holmes-kb
# 模拟 git conflict：两方都更新了引用计数
cat > pitfall/database/PT-DB-001.md << 'CONFLICT'
<<<<<<< HEAD
---
id: PT-DB-001
maturity: draft
reference_count: 3
last_referenced: "2026-05-28T10:00:00+00:00"
---
body
=======
---
id: PT-DB-001
maturity: draft
reference_count: 2
last_referenced: "2026-05-27T08:00:00+00:00"
---
body
>>>>>>> origin/main
CONFLICT
```
**步骤**：`holmes kb merge`
**预期**：
- 自动合并：`reference_count` 取两者之和（或较大值，视实现），`last_referenced` 取较新值
- 输出"自动处理：证据追加"
- 退出码 0

---

### TC-US4-18：merge — 成熟度提升（取较高值）

**类型**：功能（FR-008，SC-003）
**前置**：构造同一条目两个版本，仅 maturity 不同（一方 draft，另一方 verified）：
```bash
# 构造 conflict markers（maturity 行不同）
```
**步骤**：`holmes kb merge`
**预期**：
- 自动合并：`maturity` 取较高值 `verified`
- 输出"自动处理：成熟度提升 PT-DB-001 → verified"
- 退出码 0

---

### TC-US4-19：merge — 成熟度冲突（取较低值 + contradiction 标签）

**类型**：功能（cli-schema.md merge 场景4）
**前置**：构造同一条目两个版本，maturity 一方 proven 一方 draft（非单调提升，存在争议）
**步骤**：`holmes kb merge`
**预期**：
- 自动处理：取较低成熟度值，并在 `tags` 中追加 `contradiction`
- 输出对应提示
- 退出码 0

---

### TC-US4-20：`holmes kb lint` — 超时 pending 条目警告（>30天）

**类型**：功能（FR-009）
**前置**：手动写入一条 created_at 超过 30 天的 pending 条目：
```bash
cat > ~/holmes-kb/contributions/pending/old-entry.md << 'EOF'
---
type: pitfall
title: 超时 pending 测试
maturity: draft
category: database
tags: [test]
created_at: "2026-02-01T00:00:00+00:00"
updated_at: "2026-02-01T00:00:00+00:00"
---

## Symptoms
测试超时检测
EOF
```
**步骤**：`holmes kb lint`
**预期**：输出 `⚠ Pending entry old-entry is >30 days old (created 2026-02-01)`

---

### TC-US4-21：`holmes kb lint` — contradiction 关键词扫描

**类型**：功能（FR-009）
**前置**：手动在正式条目中插入矛盾关键词：
```bash
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/pitfall/database/PT-DB-001.md')
p = frontmatter.load(str(path))
p.content = p.content + '\n\nNote: this is incorrect, do not use this approach.'
path.write_text(frontmatter.dumps(p))
"
```
**步骤**：`holmes kb lint`
**预期**：输出 `⚠ PT-DB-001 contains possible contradiction keyword: 'do not use'`

**清理**：测试后恢复原始内容。

---

### TC-US4-22：`holmes kb lint` — 重复相似条目报告

**类型**：功能（FR-009 + cli-schema.md lint 检查项）
**前置**：向正式目录写入一条与 PT-DB-001 高度相似（>85% Jaccard）的条目（直接写文件，绕过 confirm Gate 2）：
```bash
cat > ~/holmes-kb/pitfall/database/PT-DB-002.md << 'EOF'
---
id: PT-DB-002
type: pitfall
title: Redis 连接池耗尽超时问题
maturity: draft
category: database
tags: [redis, connection-pool]
created_at: "2026-05-28"
updated_at: "2026-05-28"
---

## Symptoms
Redis 超时

## Root Cause
连接池耗尽

## Resolution
调大连接池
EOF
```
**步骤**：`holmes kb lint`
**预期**：输出 `⚠ 重复相似条目：PT-DB-001 与 PT-DB-002 相似度 > 85%`（或类似提示）

**清理**：`rm ~/holmes-kb/pitfall/database/PT-DB-002.md`

---

### TC-US4-23：`holmes kb lint --report` JSON 输出（cli-schema.md）

**类型**：功能
**步骤**：
```bash
holmes kb lint --report
```
**预期**：
- 输出为合法 JSON
- 包含字段：总条目数、pending 数、冲突数、warnings 列表、errors 列表
- 可通过 `python3 -c "import json,sys; json.load(sys.stdin)"` 验证

---

### TC-US4-24：`holmes kb rebuild-index`（cli-schema.md）

**类型**：功能
**前置**：删除或损坏 index.json：
```bash
rm -f ~/holmes-kb/index.json
```
**步骤**：`holmes kb rebuild-index`
**预期**：
- 输出"索引重建完成（共 N 条目）"
- `~/holmes-kb/index.json` 重新生成
- JSON 格式合法，`entry_count` 与实际条目数一致

**数据模型验证**：
```bash
python3 -c "
import json
d = json.loads(open('~/holmes-kb/index.json').read())
assert 'version' in d
assert 'entry_count' in d
assert isinstance(d['entries'], list)
print('index.json OK, entries:', d['entry_count'])
"
```

---

### TC-US4-25：`holmes kb pending --show <ID>`（cli-schema.md）

**类型**：功能
**前置**：pending 区有至少一条条目
**步骤**：
```bash
# 获取 pending ID
PENDING_ID=$(holmes kb pending --json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
holmes kb pending --show "$PENDING_ID"
```
**预期**：
- 输出该条 pending 条目的完整 Markdown 内容（含 frontmatter）
- 不是列表格式，而是单条全文

---

### TC-US4-26：`holmes kb resolve --keep B`（cli-schema.md）

**类型**：功能
**前置**：TC-US4-09 成功，conflicts/ 中有冲突文件
**步骤**：
```bash
holmes kb resolve <conflict_id> --keep B
```
**预期**：
- 远端版本内容写入正式目录（而非本地版本）
- 冲突文件从 `contributions/conflicts/` 删除
- `contributions/log.md` 追加记录，标注 `keep=B`
- 退出码 0

---

### TC-US4-27：`holmes kb resolve --manual`（cli-schema.md）

**类型**：功能
**前置**：conflicts/ 中有冲突文件
**步骤**：
```bash
# 手动编辑冲突文件，清除冲突标记后标记解决
holmes kb resolve <conflict_id> --manual
```
**子用例 — 文件仍含冲突标记时**：
```bash
# 不清除 <<<<<<< 标记直接执行
holmes kb resolve <conflict_id> --manual
echo "exit: $?"  # 期望退出码 2
```
**预期**：文件仍有冲突标记时，退出码 2 并输出错误提示。

---

### TC-US4-28：`holmes kb list` 高级选项（cli-schema.md）

**类型**：功能
**子用例**：

```bash
# --category 过滤
holmes kb list --category database
# 预期：仅显示 category=database 的条目，无其他 category

# --query 关键词过滤
holmes kb list --query "Redis"
# 预期：仅显示标题/标签含 Redis 的条目

# --limit / --offset 分页
holmes kb list --limit 1 --offset 0
# 预期：仅输出 1 条；再用 --offset 1 得到下一条

# --format json
holmes kb list --format json | python3 -c "import json,sys; d=json.load(sys.stdin); print(type(d))"
# 预期：输出合法 JSON 数组

# --format id-only
holmes kb list --format id-only
# 预期：每行仅一个 ID，无其他列
```

---

### TC-US4-29：`holmes kb confirm --category` / `--type` 覆盖（cli-schema.md）

**类型**：功能
**前置**：pending 条目 `type=pitfall, category=database`
**步骤**：
```bash
holmes kb confirm <pending_id> --category network --type pitfall
# 输入 y
```
**预期**：
- 条目入库到 `pitfall/network/` 目录（而非 database）
- ID 格式为 `PT-NET-NNN`

---

### TC-US4-30：各命令错误退出码（cli-schema.md）

**类型**：边界
**子用例**：
```bash
# holmes kb show — ID 不存在，退出码 1
holmes kb show NONEXISTENT-001
echo "exit: $?"  # 期望: 1

# holmes kb confirm — ID 不存在，退出码 1
holmes kb confirm nonexistent-pending
echo "exit: $?"  # 期望: 1

# holmes kb confirm — 目标路径已存在同名文件，退出码 2
# （将正式条目同名文件提前放到目标路径后重新 confirm）
echo "exit: $?"  # 期望: 2

# holmes kb reject — ID 不存在，退出码 1
holmes kb reject nonexistent-pending
echo "exit: $?"  # 期望: 1

# holmes kb resolve — 冲突 ID 不存在，退出码 1
holmes kb resolve nonexistent-conflict --keep A
echo "exit: $?"  # 期望: 1
```

---

### TC-US4-31：`KbReadOverview` 工具（spec.md KB工具清单）

**类型**：Agent 集成
**步骤**：
```bash
holmes-agent --print "请调用 KbReadOverview 工具，告诉我当前知识库的整体结构和有哪些类型的条目"
```
**预期**：
- Agent 调用 `KbReadOverview`（工具调用日志可见）
- 返回内容包含 KB 根目录的 README.md 内容和各类型 `_index.md` 摘要
- 明确列出条目类型（pitfall/model/guideline 等）和条目数量

---

### TC-US4-32：`KbWriteEntry` 工具（spec.md KB工具清单）

**类型**：Agent 集成
**步骤**：
```bash
holmes-agent --print "请调用 KbWriteEntry 工具，直接将以下内容写入 pending 区：
---
type: pitfall
title: 测试直接写入
maturity: draft
category: system
tags: [test]
created_at: \"\"
updated_at: \"\"
---

## Symptoms
测试症状

## Root Cause
测试根因

## Resolution
测试解决方案"
```
**预期**：
- Agent 弹出权限确认（`isReadOnly: false` 触发）
- 用户确认后，`contributions/pending/` 出现新文件
- Agent 输出 pending ID

**对比 KbExtractAndSave**：KbWriteEntry 直接写入用户提供的内容，不从会话历史提取。

---

### TC-US4-33：`KbListPending` 作为 Agent 工具调用（spec.md KB工具清单）

**类型**：Agent 集成
**前置**：pending 区有至少一条条目
**步骤**：
```bash
holmes-agent --print "请调用 KbListPending 工具列出当前所有待审阅条目"
```
**预期**：
- Agent 调用 `KbListPending` 工具（非 CLI）
- 返回 pending 条目列表，含 ID、标题、类型
- 结果与 `holmes kb pending` CLI 输出一致

---

## US5 — KB 内容浏览

### TC-US5-01：`holmes kb list` 列出全部条目

**类型**：功能
**步骤**：`holmes kb list`
**预期**：
- 表格输出，含列：ID / 类型 / 成熟度 / 标题
- PT-DB-001 出现在列表中

---

### TC-US5-02：`holmes kb list --type pitfall` 过滤

**类型**：功能
**步骤**：`holmes kb list --type pitfall`
**预期**：仅显示 pitfall 类型条目，无其他类型。

---

### TC-US5-03：`holmes kb show <ID>` 显示全文

**类型**：功能
**步骤**：`holmes kb show PT-DB-001`
**预期**：终端展示 PT-DB-001 完整 Markdown（含 frontmatter）。

---

### TC-US5-04：Agent 浏览结果与 CLI 一致性

**类型**：一致性
**步骤**：
```bash
# CLI 结果
holmes kb list --type pitfall --json > /tmp/cli_list.json

# Agent 结果
holmes-agent --print "请调用 KbReadCategoryIndex 列出所有 pitfall 类条目"
```
**预期**：Agent 返回的条目集合与 CLI JSON 输出一致（ID 集合相同）。

---

### TC-US5-05：`/holmes-search` skill（plan.md skills 清单）

**类型**：Agent 集成（P2）
**步骤**：在 `holmes-agent` 交互会话中输入 `/holmes-search`
**预期**：
- skill 被展开为知识库检索提示
- Agent 调用 `KbSearch` 并等待用户输入检索关键词
- 返回匹配条目列表

**备注**：若 `/holmes-search` 尚未实现，此用例状态为"阻塞"，需先确认 `skills/holmes-search.md` 文件存在且已加载。

---

## 成功标准对应验证

| 标准 | 测试用例 | 验收方式 |
|------|---------|---------|
| SC-001：10 分钟内完成安装首次调用 | TC-US1-01 ~ TC-US1-03 | quickstart.md 流程计时 |
| SC-002：confirm 3-gate 100% 拦截 | TC-US4-01/02/03 | 各场景均被拦截，退出码非 0 |
| SC-003：merge 自动处理率 100% | TC-US4-08/09 | 纯新增自动处理，矛盾正确隔离 |
| SC-004：`/holmes-resolve` 30s 内完成 | TC-US2-01 | 写入 pending 的耗时（不含用户确认） |
| SC-005：`holmes import` 60s 内完成 | TC-US3-01 | 完整 LLM 调用 + pending 写入耗时 |

---

## 数据模型偏差专项验证

针对前言中列出的偏差，在 TC-US3-01 和 TC-US2-01 中额外执行以下检查：

### DM-01 字段名核对
```bash
python3 -c "
import frontmatter, glob
# 取最新 pending 条目
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
if files:
    p = frontmatter.load(files[-1])
    has_at = 'created_at' in p.metadata and 'updated_at' in p.metadata
    has_no_at = 'created' in p.metadata and 'updated' in p.metadata
    print('has created_at/updated_at:', has_at)  # 期望 True（与 schema.py 一致）
    print('has created/updated:', has_no_at)      # 期望 False
"
```

### DM-02 章节语言核对
```bash
python3 -c "
import frontmatter, glob
files = sorted(glob.glob('~/holmes-kb/contributions/pending/*.md'))
if files:
    p = frontmatter.load(files[-1])
    body = p.content
    has_english = '## Symptoms' in body and '## Root Cause' in body and '## Resolution' in body
    has_chinese = '## 问题描述' in body or '## 解决步骤' in body
    print('English sections:', has_english)  # 期望 True
    print('Chinese sections:', has_chinese)  # 期望 False（否则 Gate 1 会拦截）
"
```

---

## 数据模型验证规则专项

### TC-DM-01：frontmatter 约束规则（data-model.md §1 验证规则）

**类型**：数据模型
**子用例**：

```bash
# (a) title 超过 100 字符 → Gate 1 应拒绝
python3 -c "
import frontmatter
from pathlib import Path
path = Path('~/holmes-kb/contributions/pending/long-title.md')
content = '''---
type: pitfall
title: ''' + 'A' * 101 + '''
maturity: draft
category: database
tags: [test]
created_at: \"2026-05-28\"
updated_at: \"2026-05-28\"
---

## Symptoms
x

## Root Cause
x

## Resolution
x'''
path.write_text(content)
"
holmes kb confirm long-title.md
echo "exit: $?"   # 期望非 0，输出 title 过长错误

# (b) created_at > updated_at → Gate 1 应拒绝
# （将 created_at 设为未来日期，updated_at 为过去日期）

# (c) id 全局唯一 — confirm 一条与现有 PT-DB-001 id 重复的条目
# 预期：Gate 1 或 confirm 流程报"ID 已存在"

# (d) maturity 非法值（如 "unknown"）→ Gate 1 应拒绝
```
**预期**：各子用例 Gate 1 均输出具体约束违反信息，退出码非 0，条目留 pending。

---

### TC-DM-02：`index.json` 自动生成与格式（data-model.md §2）

**类型**：数据模型
**前置**：完成至少一次 `holmes kb confirm`
**步骤**：
```bash
python3 -c "
import json
d = json.loads(open('~/holmes-kb/index.json').read())
# 必填字段
assert 'version' in d
assert 'generated_at' in d
assert 'entry_count' in d
assert 'pending_count' in d
assert 'conflict_count' in d
assert isinstance(d['entries'], list)
# 每条 entry 字段
for e in d['entries']:
    assert 'id' in e
    assert 'title' in e
    assert 'type' in e
    assert 'category' in e
    assert 'maturity' in e
    assert 'file_path' in e
print('index.json schema OK, entries:', d['entry_count'])
"
```
**预期**：所有断言通过。

---

### TC-DM-03：条目文件路径规则（data-model.md §1 文件路径规则）

**类型**：数据模型
**前置**：TC-US2-03 成功，新条目已入库
**步骤**：
```bash
python3 -c "
import frontmatter, glob
# 验证路径格式: {kb_root}/{type}/{category}/{slug}.md
files = glob.glob('~/holmes-kb/**/*.md', recursive=True)
official = [f for f in files if 'pending' not in f and 'conflicts' not in f and '_index' not in f and 'HOLMES' not in f]
for f in official:
    parts = f.split('/')
    # 倒数3级：type/category/slug.md
    kb_root_idx = parts.index('holmes-kb')
    rel = parts[kb_root_idx+1:]
    assert len(rel) >= 3, f'Unexpected path depth: {f}'
    assert rel[0] in ['pitfall','model','guideline','process','decision'], f'Unknown type dir: {f}'
    print('OK:', '/'.join(rel))
"
```
**预期**：所有正式条目路径符合 `{type}/{category}/{slug}.md` 规则。

---

## 性能测试

### TC-PERF-01：KB 只读工具响应时间 < 200ms（FR-003）

**类型**：性能
**前置**：KB 中有至少 10 条正式条目（模拟中等规模）
**步骤**：
```bash
python3 -c "
import subprocess, time

def measure(cmd, label):
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = (time.time() - start) * 1000
    print(f'{label}: {elapsed:.0f}ms (exit={result.returncode})')
    assert elapsed < 200, f'{label} exceeded 200ms: {elapsed:.0f}ms'

measure(['holmes', '--kb-path', '~/holmes-kb', 'kb', 'search', 'Redis', '--json'], 'KbSearch')
measure(['holmes', '--kb-path', '~/holmes-kb', 'kb', 'show', 'PT-DB-001'], 'KbShow')
measure(['holmes', '--kb-path', '~/holmes-kb', 'kb', 'list', '--format', 'json'], 'KbList')
print('All under 200ms')
"
```
**预期**：每个命令耗时 < 200ms（纯文件系统，不含 LLM 调用）。

---

## 命令行界面完整性

### TC-CLI-01：`holmes config show` / `holmes config set`（cli-schema.md）

**类型**：功能（待确认是否实现）
**步骤**：
```bash
holmes config show
echo "exit: $?"
```
**预期**：
- 若已实现：输出当前 `~/.holmes/config.json` 的格式化内容
- 若未实现：退出码非 0，输出"未知命令"或类似提示

**处理方式**：执行后，根据结果将本用例归入「已覆盖」或追加到 DM-04 未实现命令排除列表。

---

## 执行顺序建议

```
Day 1：冒烟 + US1（含品牌/HOLMES.md）
  TC-US1-01/02/03/04/05/06/07/08

Day 2：US2（依赖 US1 环境）
  TC-US2-01/02/03/04/05/06
  + 数据模型偏差专项（DM-01/02）

Day 3：US3（含高级选项和退出码）
  TC-US3-01/02/03/04/05/06/07

Day 4：US4（Gate + merge 5类 + lint 全项 + maturity + 工具 + 高级选项 + 退出码）
  TC-US4-01~33（按编号顺序）

Day 5：US5（含 /holmes-search）+ 一致性
  TC-US5-01~05
  SC-001~SC-005 成功标准汇总

Day 6：专项验证
  TC-DM-01/02/03（数据模型验证规则）
  TC-PERF-01（性能）
  TC-CLI-01（config 命令确认）
```
