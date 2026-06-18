# CLI 命令规范：Holmes Agent

**版本**：1.0 | **日期**：2026-05-26

---

## 入口命令

```
holmes <子命令> [选项]
```

---

## 子命令一览

| 子命令 | 说明 |
|--------|------|
| `holmes` / `holmes tui` | 启动 TUI 交互界面 |
| `holmes config init` | 初始化配置 |
| `holmes config show` | 查看当前配置 |
| `holmes config set <键> <值>` | 修改单项配置 |
| `holmes import <文件路径>` | 导入知识文件到本地暂存区 |
| `holmes kb list` | 列出知识库条目 |
| `holmes kb show <ID>` | 查看知识条目详情 |
| `holmes kb rebuild-index` | 重建知识库索引 |
| `holmes kb pending` | 查看暂存区待审阅条目列表 |
| `holmes kb pending show <ID>` | 查看某条暂存条目详情 |
| `holmes kb confirm <ID>` | 确认并将暂存条目移入正式目录 |
| `holmes kb reject <ID>` | 拒绝并删除暂存条目 |
| `holmes kb merge` | 智能处理 git pull 后的知识库冲突 |
| `holmes kb resolve <冲突ID>` | 裁决并解除内容矛盾冲突 |
| `holmes kb lint` | 运行知识库健康检查 |
| `holmes session list` | 列出历史会话 |
| `holmes session show <ID>` | 查看会话详情 |

---

## `holmes config init`

交互式初始化配置文件 `~/.holmes/config.json`。

```
用法：holmes config init [--kb-path <路径>] [--non-interactive]

选项：
  --kb-path <路径>      直接指定知识库本地 clone 路径（跳过交互提问）
  --non-interactive     非交互模式，所有选项必须通过参数提供
  --force               覆盖已存在的配置文件

输出：
  成功：✓ 配置已保存至 ~/.holmes/config.json
  失败：详细错误信息（如路径不存在、非 git 仓库等）
```

---

## `holmes import`

将知识文件导入到本地知识库。

```
用法：holmes import <文件路径> [选项]

参数：
  <文件路径>            要导入的文件路径（支持 .md、.txt）

选项：
  --type <类型>         "pitfall" | "model" | "guideline" | "process" | "decision"
                        省略时由 LLM 自动识别（推荐）
  --category <分类>     目标分类目录（如 "network"、"database"）
                        省略时由 LLM 自动推断
  --title <标题>        条目标题（省略时从文件内容自动提取）
  --tags <标签>         逗号分隔的标签列表（省略时自动提取，可追加）
  --dry-run             预览识别结果和目标路径，不实际写入
  --force               覆盖已存在的同名条目

自动识别流程：
  1. LLM 读取文件全文
  2. 推断 type / category / title / tags
  3. 展示识别结果，请用户确认后写入暂存区

输出示例（自动识别，成功）：
  [识别结果]
    类型：pitfall（已知风险/排查步骤）
    分类：database
    标题：Redis 连接池耗尽排查
    标签：redis, connection-pool, database, timeout
  ✓ 已写入暂存区
    ID：PT-DB-003
    路径：contributions/pending/local-20260526-redis-pool.md
  提示：运行 `holmes kb confirm PT-DB-003` 移入正式目录

输出示例（--dry-run）：
  [识别结果 - 预览模式，不写入]
    类型：pitfall
    分类：database
    标题：Redis 连接池耗尽排查
    标签：redis, connection-pool, database
    目标路径：pitfall/database/redis-connection-pool-exhausted.md
  运行不带 --dry-run 的命令以实际导入。

输出示例（手动指定覆盖自动识别）：
  holmes import ./doc.md --type model --category networking
  [已跳过自动识别，使用指定参数]
  ✓ 已写入暂存区

退出码：
  0  成功
  1  文件不存在或格式不支持
  2  配置错误（知识库路径未设置）
  3  写入失败（权限问题等）
```

---

## `holmes kb list`

列出知识库中的条目。

```
用法：holmes kb list [选项]

选项：
  --type <类型>         按类型过滤："pitfall" | "model" | "guideline" | "process" | "decision"
  --category <分类>     按分类目录过滤
  --query <关键词>      按关键词过滤（扫描 index.json）
  --limit <数量>        每页显示数量（默认：20）
  --offset <偏移>       分页偏移（默认：0）
  --format <格式>       输出格式："table"（默认）| "json" | "id-only"

输出示例（table 格式）：
  ID              类型         标题                          更新日期
  ──────────────────────────────────────────────────────────────────
  PT-DB-001       pitfall      Redis 连接超时排查             2026-05-26
  PT-NET-001      pitfall      TCP 连接超时排查               2026-05-20
  MD-DB-001       model        Redis 基础概念                 2026-05-18
```

---

## `holmes kb show`

查看单个知识条目的完整内容。

```
用法：holmes kb show <ID>

参数：
  <ID>      知识条目 ID（如 ts-redis-001）

输出：以 Markdown 格式在终端渲染条目内容

退出码：
  0  成功
  1  条目不存在
  2  配置错误
```

---

## `holmes kb rebuild-index`

从知识库文件重建 `index.json` 索引。

```
用法：holmes kb rebuild-index

说明：
  当手动编辑或删除知识库文件后，需要运行此命令重建索引。
  git pull 后如有新增/删除条目，也建议运行此命令。

输出：
  正在扫描知识库...
  ✓ 索引重建完成（共 42 条目）
  已写入：/path/to/kb/index.json
```

---

## `holmes session list`

列出历史排查会话。

```
用法：holmes session list [选项]

选项：
  --status <状态>     "active" | "resolved" | "archived"（默认：全部）
  --limit <数量>      每页显示数量（默认：20）
  --format <格式>     "table"（默认）| "json"

输出示例：
  ID                      状态       标题                          更新时间
  ──────────────────────────────────────────────────────────────────────────
  sess-20260526-143022    resolved   Redis 连接池耗尽排查           2026-05-26 14:45
  sess-20260525-092011    active     Nginx 502 Bad Gateway 排查    2026-05-25 10:30
```

---

## `holmes session show`

查看单个会话的完整对话记录。

```
用法：holmes session show <会话ID>

参数：
  <会话ID>    会话 ID（如 sess-20260526-143022）

输出：在终端中渲染对话历史（用户消息/助手消息分色显示）

退出码：
  0  成功
  1  会话不存在
```

---

## `holmes kb pending`

查看暂存区中待审阅的知识条目列表（agent 自动写入 + CLI 导入的未确认条目）。

```
用法：holmes kb pending [--show <ID>]

选项：
  --show <ID>   直接查看某条暂存条目的完整内容

输出示例（列表）：
  ID              来源     标题                              暂存时间
  ────────────────────────────────────────────────────────────────────
  PT-DB-003       auto     Redis 连接池耗尽排查              2026-05-26 14:45（来自 sess-xxx）
  PT-NET-002      import   DNS 解析失败排查                  2026-05-26 15:00
```

---

## `holmes kb confirm`

将暂存区条目确认后移入正式目录，开始参与检索。

```
用法：holmes kb confirm <ID> [选项]

参数：
  <ID>            暂存条目 ID

选项：
  --category <分类>   指定目标分类目录（覆盖自动推断）
  --type <类型>       指定知识类型（覆盖自动推断）

流程：
  1. 从 contributions/pending/ 读取条目
  2. 移动至 {type}/{category}/{slug}.md
  3. 更新 contributions/log.md
  4. 重建 index.json 和 {type}/_index.md

退出码：
  0  成功
  1  ID 不存在于暂存区
  2  目标路径已存在同名文件（提示使用 --force 覆盖）
```

---

## `holmes kb reject`

拒绝并删除暂存区中的条目。

```
用法：holmes kb reject <ID>

退出码：
  0  成功
  1  ID 不存在于暂存区
```

---

## `holmes kb merge`

在 `git pull --rebase` 产生冲突后，执行智能知识库合并，处理 5 种冲突场景。

```
用法：holmes kb merge

说明：
  自动处理以下场景（无需人工介入）：
    ✓ 纯新增条目      → 两条都保留
    ✓ 证据追加        → 合并 reference_count 和 last_referenced
    ✓ 成熟度提升      → 取较高成熟度
    ✓ 成熟度冲突      → 取较低成熟度，追加 contradiction 标签

  需要人工介入：
    ⚠ 内容矛盾       → 写入 contributions/conflicts/，提示运行 holmes kb resolve

输出示例：
  ✓ 场景 1：自动合并 2 个新增条目
  ✓ 场景 3：PT-NET-001 成熟度提升至 proven
  ⚠ 内容矛盾：PT-DB-003
    → 已写入 contributions/conflicts/PT-DB-003-conflict-20260526.md
    → 运行 `holmes kb resolve PT-DB-003-conflict-20260526 --keep A|B|manual` 后重试推送

退出码：
  0  所有冲突已自动解决，可继续 git push
  1  存在内容矛盾，需人工裁决（阻止 push）
```

---

## `holmes kb resolve`

裁决 `contributions/conflicts/` 中的内容矛盾冲突。

```
用法：holmes kb resolve <冲突ID> --keep <A|B|manual>

参数：
  <冲突ID>    冲突文件标识（如 PT-DB-003-conflict-20260526）

选项：
  --keep A        保留本地版本
  --keep B        保留远端版本
  --manual        手动编辑冲突文件后标记为已解决

流程（--keep A 为例）：
  1. 从 contributions/conflicts/ 读取冲突文件
  2. 以版本 A 内容写入正式路径
  3. 删除 contributions/conflicts/ 中的冲突文件
  4. 追加 contributions/log.md
  5. 重建索引

退出码：
  0  成功，冲突已解除，可继续 git push
  1  冲突 ID 不存在
  2  --manual 模式但文件仍有冲突标记
```

---

## `holmes kb lint`

运行知识库健康检查，检测并修复常见问题。

```
用法：holmes kb lint [--fix] [--report]

选项：
  --fix       自动修复可程序化处理的问题（索引不一致、成熟度衰减等）
  --report    输出 JSON 格式报告（用于 CI 集成）

检查项与处理：
  ✅ 自动修复（--fix）：
    - index.json 与文件不一致 → 重建索引
    - _index.md 与文件不一致  → 重建分类清单
    - 成熟度自动衰减           → 降级并记录
    - 孤儿 pending 条目（>30天）→ 警告提示
  ⚠ 需人工处理：
    - contradiction 标签条目   → 报告列表，提示 holmes kb resolve
    - 重复相似条目（>85%）     → 报告列表，提示合并
    - contributions/conflicts/ 未解决冲突 → 阻止推送警告

输出示例：
  [lint] 检查中...
  ✓ index.json：已同步（42 条正式条目，3 条 pending）
  ✓ _index.md：已同步（5 个分类）
  ⚠ 成熟度衰减：PT-SYS-002 proven → verified（距上次引用 13 个月）
  ⚠ 待裁决冲突：1 个（contributions/conflicts/PT-DB-003-conflict-20260526.md）
  ✓ 无重复条目
  [lint] 完成。1 项需人工处理。

退出码：
  0  全部通过（或可自动修复项已修复）
  1  存在需人工处理的问题
```
