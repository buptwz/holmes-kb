# KB Data Model Reference

**Purpose**: 权威参考文档，用于后续自动化质量验证和开发理解。所有规则均从源代码反向提取，每条规则注明对应来源文件及行号。

**Source files**:
- `kb/holmes/kb/schema.py` — 字段定义、验证规则、section 约束
- `kb/holmes/kb/store.py` — EntryMeta 结构、maturity 升级、evidence sidecar
- `kb/holmes/kb/pending.py` — pending entry 格式、临时 ID 生成
- `kb/holmes/kb/skill/manager.py` — SkillDefinition、SkillSummary、名称规则
- `kb/holmes/kb/skill/template.py` — SKILL.md 模板格式

---

## 1. 文件系统布局

```
<kb_root>/
├── pitfall/
│   └── <category>/
│       └── <entry-id>.md             # 已发布 pitfall 条目
├── process/
│   └── <category>/
│       └── <entry-id>.md             # 已发布 process 条目
├── model/
│   └── <category>/
│       └── <entry-id>.md             # 已发布 model 条目
├── guideline/
│   └── <category>/
│       └── <entry-id>.md             # 已发布 guideline 条目
├── decision/
│   └── <category>/
│       └── <entry-id>.md             # 已发布 decision 条目
├── _pending/                          # import pipeline 输出，待人工审批
│   └── <type>/<category>/
│       └── <entry-id>.md
├── _drafts/                           # agent 通过 kb_draft 保存的草稿
├── skills/
│   └── <skill-name>/                  # skill name = kebab-case，3-64 字符
│       ├── SKILL.md                   # 必须存在；agent instruction package
│       └── <optional-files>           # 脚本、参考资料等，无结构限制
├── contributions/
│   ├── evidence/
│   │   └── <entry_id>/
│   │       └── <session_id>.json      # per-session evidence sidecar
│   ├── archive/                       # 归档的过期条目
│   └── log.md                         # append-only 操作日志
├── <type>/_index.md                   # 各类型目录下的 Markdown 索引表（自动生成）
└── index.json                         # 根目录 machine-readable 索引（自动生成）
```

**扫描规则**：
- `list_entries()` 对每个 type 目录及 `_pending/<type>/` 执行 `rglob("*.md")`，递归扫描所有子目录
- 文件名以 `_` 开头的文件（如 `_index.md`）被跳过，不作为条目处理
- `_should_skip()` 排除 `.history`、`_trash`、`_drafts`、`kb-template`、`.git`、`.claude` 目录
- 条目 ID 取自 frontmatter `id` 字段，不依赖文件名；缺失时回退到文件名 stem
- `find_entry()` 使用 `kb_root.rglob("*.md")` 全局扫描，大小写不敏感匹配，同时覆盖 `_pending/` 目录

---

## 2. Entry Frontmatter 字段

### 2.1 必填字段

所有 5 种 entry 类型均必须包含以下字段：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | string | 格式见 §5 | 唯一条目标识符 |
| `type` | string | 见有效值列表 | entry 类型 |
| `title` | string | 最长 100 字符 | 条目标题 |
| `maturity` | string | 见有效值列表 | 成熟度级别 |
| `category` | string | 自由格式 slug | 分类 |
| `tags` | list[string] | 可为空列表 | 检索标签 |
| `created_at` | string | ISO8601 带时区，≤ `updated_at` | 创建时间 |
| `updated_at` | string | ISO8601 带时区，≥ `created_at` | 最后更新时间 |

**`type` 有效值**：
```
pitfall | model | guideline | process | decision
```

**`maturity` 有效值**：
```
draft | verified | proven | deprecated
```

**`title` 长度限制**：最长 100 字符，超出报验证错误。

**`created_at` / `updated_at` 关系约束**：
`created_at` 必须 ≤ `updated_at`，否则报验证错误。两者均需为可解析的 ISO8601 字符串。

### 2.2 可选字段

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `kb_status` | string | `draft|pending|active|deprecated` | 生命周期状态；缺失默认 `active` |
| `brief` | string | 一句话摘要 | kb_browse 预览文本 |
| `decision_map` | list[dict] | symptom→branch 映射 | 复杂分支 pitfall 的诊断路由表 |
| `source_hash` | string | SHA-256 前 16 hex 字符 | 源文档指纹（import 幂等性） |
| `source_file` | string | 相对路径 | 源文档路径 |
| `import_trace_id` | string | — | import 批次追踪 ID |
| `contributors` | list[string] | 无格式约束 | 贡献者列表，由 `add_contributor()` 维护 |
| `evidence` | list[dict] | EvidenceRecord 格式（见 §7） | 遗留字段；新 evidence 存 sidecar |

### 2.3 `category` 格式约束

Category 为自由格式 slug，仅校验非空 + slug 格式（来源：`schema.py`）。

支持层级结构（`/` 分隔）：
```
database | network | hardware/gpu | pcie/link-training | memory
```

正则校验：`^[a-z0-9][a-z0-9_/-]*[a-z0-9]$|^[a-z0-9]$`

### 2.4 `decision_map` 格式

用于复杂分支 pitfall 条目（≥3 条诊断路径），提供 symptom → branch 路由映射：

```yaml
decision_map:
  - symptom: "LED 不亮"
    branch: "电源子系统"
  - symptom: "LED 闪烁但无输出"
    branch: "信号链路"
  - symptom: "偶发性重启"
    branch: "散热/功耗"
```

每条 `decision_map` 条目的 `branch` 字段对应 `## Resolution` 下的 `### Branch` 子标题。

---

## 3. 各 Entry 类型必需 Body Sections

验证逻辑：大小写不敏感匹配，缺失则报验证错误。

| 类型 | 必需 Markdown sections（校验门控） | 建议补充 sections |
|------|-------------------------------------|-------------------|
| `pitfall` | `## Symptoms`、`## Root Cause`、`## Resolution` | — |
| `model` | `## Overview` | `## Key Concepts`、`## Usage` |
| `guideline` | `## Guideline` | `## Context`、`## Rationale` |
| `process` | `## Steps` | `## Purpose`、`## Outcome` |
| `decision` | `## Context`、`## Decision` | `## Rationale` |

**向后兼容别名**（由 normalizer 自动转换，`normalizer.py:HEADER_MAP`）：
- `## Definition` → `## Overview`（旧 model section）
- `## Rule` → `## Guideline`（旧 guideline section）

---

## 4. Entry 文件示例

### 4.1 简单 pitfall（单分支）

```markdown
---
id: PT-DB-001
type: pitfall
title: Redis OOM 触发驱逐导致服务抖动
maturity: verified
category: database
tags:
  - redis
  - memory
  - oom
brief: Redis maxmemory 达上限触发 key 驱逐或拒绝写入
created_at: "2024-01-15T08:00:00+00:00"
updated_at: "2024-03-20T12:30:00+00:00"
---

## Symptoms

服务出现间歇性超时，Redis 日志中有 `NOEVICTION` 或 `maxmemory-policy` 相关告警。

## Root Cause

Redis 内存达到 `maxmemory` 上限，触发 key 驱逐或拒绝写入。

## Resolution

1. [api:read] 检查当前 maxmemory 设置
   ```bash
   redis-cli CONFIG GET maxmemory
   ```

2. [api:write] 调整 maxmemory
   ```bash
   redis-cli CONFIG SET maxmemory 4gb
   ```
```

### 4.2 复杂 pitfall（多分支 + decision_map）

```markdown
---
id: PT-HW-003
type: pitfall
title: 板卡上电后无输出
maturity: draft
category: hardware/power
tags: [power, led, boot-failure]
brief: 板卡上电后无输出，需按 LED 状态分支诊断
decision_map:
  - symptom: "LED 不亮"
    branch: "电源子系统"
  - symptom: "LED 闪烁但无输出"
    branch: "信号链路"
created_at: "2024-06-01T08:00:00+00:00"
updated_at: "2024-06-01T08:00:00+00:00"
---

## Symptoms

板卡插入机箱后无任何输出信号。

## Root Cause

可能为电源子系统故障或信号链路异常。

## Diagnostic Flow

观察 LED 状态 → LED 不亮 → 电源子系统 | LED 闪烁但无输出 → 信号链路

## Resolution

### 电源子系统

1. [physical] 检查电源 LED 状态
2. [api:read] 读取电压监测
   ...

### 信号链路

1. [api:read] 检查 PCIe link status
   ...
```

---

## 5. ID 格式规则

### 5.1 Entry ID

支持两种格式：

**旧格式（legacy）**：`{TYPE_PREFIX}-{CAT_ABBR}-{NNN}`
```
^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$
```

| 部分 | 规则 | 示例 |
|------|------|------|
| TYPE_PREFIX | 2-3 位大写字母 | `PT`（pitfall）、`MD`（model）、`GL`（guideline）、`PR`（process）、`DC`（decision） |
| CAT_ABBR | 2-3 位大写字母 | `DB`（database）、`NET`（network）、`SVC`（service） |
| NNN | 3 位数字，补零 | `001`、`042` |

**新格式（import pipeline）**：由 import pipeline 生成，格式灵活。

**ID 查找**：`find_entry()` 使用 `kb_root.rglob("*.md")` + frontmatter `id` 字段大小写不敏感匹配，支持任意 ID 格式。

### 5.2 Skill Name

**格式**：
```
^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$   # 4-64 字符，包含连字符
|^[a-z0-9]{3,64}$                     # 3-64 字符，纯字母数字
```

**长度约束**：最短 3 字符，最长 64 字符。

**规则**：纯小写字母、数字、连字符；首尾不得为连字符。

**示例**：`redis-oom-recovery`、`nginx-reload`、`db`

**与 Entry ID 的互斥性**：Entry ID 含大写字母，skill name 为纯小写，格式天然互斥，`kb_read` 路由无歧义。

### 5.3 Pending ID

**格式**：
```python
f"pending-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"
# rand = 4 位随机小写字母+数字
```

**示例**：`pending-20240315-143022-a7bk`

---

## 6. Maturity 级别与升级规则

### 6.1 级别定义

来源：`store.py`，`derive_maturity()` 函数。

| 级别 | 触发条件 | 说明 |
|------|---------|------|
| `draft` | 0 条 solved evidence | 初始状态，未经任何验证 |
| `verified` | ≥1 条 solved evidence | 至少一次确认解决 |
| `proven` | ≥2 个不同 `session_id` **且** ≥2 个不同 `contributor` | 多人多次独立验证 |
| `deprecated` | 手动设置 | 已过时，不参与 maturity 自动升级 |

**代码依据**：
```python
def derive_maturity(evidence: list[dict]) -> str:
    solved = [e for e in evidence if e.get("outcome") == "solved"]
    if not solved:
        return "draft"
    sessions = {str(e.get("session_id", "")) for e in solved if e.get("session_id")}
    contributors = {str(e.get("contributor", "")) for e in solved if e.get("contributor")}
    if len(sessions) >= 2 and len(contributors) >= 2:
        return "proven"
    return "verified"
```

### 6.2 升级规则

- **只升不降**：`append_evidence()` 仅在 `new_rank > current_rank` 时更新 frontmatter
- **maturity 排序**：`draft=0 < verified=1 < proven=2`；`deprecated` 不在排序表中，不参与自动升降
- **`deprecated` 豁免**：手动设置为 `deprecated` 的条目不会被 evidence 触发降级

### 6.3 Decay 规则

| 级别 | Decay 条件 | 结果 |
|------|-----------|------|
| `proven` | 最后引用距今 > 12 个月 | 降为 `verified` |
| `verified` | 最后引用距今 > 6 个月 | 降为 `draft` |
| `draft` | 条目年龄 > 30 天 **且** 最后引用距今 > 3 个月 | 归档到 `contributions/archive/` |

**引用来源**（按优先级）：
1. `max(evidence[*].date)` — 含 `kb_read(full)` 产生的 `referenced` 记录
2. `last_referenced` — 遗留字段
3. `updated_at` — 兜底

---

## 7. Evidence Sidecar 格式

### 7.1 存储结构

```
contributions/evidence/<entry_id>/<session_id>.json
```

**设计原因**：每条 evidence 独立成文件，git merge 时只有 file addition，不产生 merge conflict。

### 7.2 EvidenceRecord 字段

| 字段 | 是否必须 | 类型 | 说明 |
|------|---------|------|------|
| `session_id` | 必须 | string | 唯一会话标识符，用于去重 |
| `contributor` | 必须 | string | 用户/agent 标识（邮箱、用户名或 hostname） |
| `date` | 必须 | string | ISO8601 日期字符串（`YYYY-MM-DD`） |
| `outcome` | 必须 | string | `"solved"` 或 `"not_solved"` 或 `"referenced"` |
| `project` | 可选 | string | 项目上下文 |
| `context` | 可选 | string | 该条目的具体使用方式 |
| `notes` | 可选 | string | 自由文本反馈 |

**`outcome` 值含义**：
- `"solved"` — 条目帮助解决了问题，驱动 maturity 升级
- `"not_solved"` — 条目未能帮助解决，中立记录
- `"referenced"` — `kb_read(full)` 自动记录的轻量引用，仅重置 decay 计时器

**文件内容**：单个 JSON 对象，`ensure_ascii=False`。

**文件名**：`session_id` 中的 `/` 和 `\` 替换为 `-`，避免路径问题。

### 7.3 去重规则

`append_evidence()` 在写入前合并 frontmatter evidence 与 sidecar evidence，若相同 `session_id` 已存在，则静默返回 `False`（no-op）。两个不同 session_id 的 evidence 总是独立写入，互不干扰。

### 7.4 合并数据源顺序

1. 先加载 frontmatter 中的 `evidence` 列表（历史数据来源）
2. 再加载 sidecar 目录中所有 `*.json` 文件（新数据来源）
3. 按 `session_id` 去重，sidecar 记录覆盖同 session_id 的 frontmatter 记录

---

## 8. Pending Entry 格式

### 8.1 Pending 专有 Frontmatter 字段

Pending entry 在标准 Entry 字段基础上额外包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 临时 pending ID（格式见 §5.3），由系统赋值 |
| `pending` | bool | 固定为 `True` |
| `pending_since` | string | 写入 pending 时的 ISO8601 时间戳 |
| `source` | string | `"auto"`（import pipeline）或 `"agent"`（kb_draft） |
| `source_session` | string | 调用方的 session 标识 |
| `suggested_type` | string | LLM 分类的 entry type，供人工审核参考 |
| `suggested_category` | string | LLM 分类的 category，供人工审核参考 |

**`maturity` 默认值**：写入时若缺失，自动补 `"draft"`。

### 8.2 审批流程

```bash
holmes pending           # 列出所有待审核条目
holmes approve <id>      # 从 _pending/ 移至正式目录
holmes delete <id>       # 删除待审核条目
```

---

## 9. Skill 结构

### 9.1 目录布局

```
skills/<skill-name>/
├── SKILL.md                  # 必须存在；agent instruction package
└── <optional subdirs/files>  # 脚本、参考资料等，无结构要求
```

### 9.2 SKILL.md Frontmatter 字段

Anthropic Agent Skills 标准。

**允许的 frontmatter key**：
```
name | description | license | allowed-tools | metadata | compatibility
```

出现允许列表之外的 key 将导致验证失败（`validate_skill_md()`）。

| 字段 | 是否必须 | 约束 | 说明 |
|------|---------|------|------|
| `name` | 必须 | ≤64 字符，kebab-case | skill 唯一名称 |
| `description` | 必须 | ≤1024 字符，不含 `<` `>` | 触发描述；agent 据此判断何时调用 |
| `license` | 可选 | 无格式约束 | 许可证信息 |
| `allowed-tools` | 可选 | 无格式约束 | 允许使用的工具列表 |
| `metadata` | 可选 | 无格式约束 | 自定义元数据 |
| `compatibility` | 可选 | 无格式约束 | 兼容性说明 |

### 9.3 SKILL.md Body 格式

`create_skill()` 生成的默认 SKILL.md 模板：

```markdown
---
name: <skill-name>
description: <description>
---

# <skill-name>

## When to Use

Describe when an agent should use this skill.

## Resolution Steps

1. First step: describe what to do and why.
2. Second step: describe what to do and why.

## Key Points

- Important caveat or boundary condition.
- Common pitfall to avoid.
```

**Body 为 agent 指令**：body 是纯 Markdown，无强制 section 要求；传入自定义 `instructions` 时，直接使用传入内容，不加默认模板。

---

## 10. 自动生成的索引文件

### 10.1 `_index.md`（各类型目录）

每个类型目录（`pitfall/`、`model/` 等）下的 `_index.md` 包含该类型所有条目的 Markdown 表格：

```
| ID | Title | Category | Maturity | Updated |
|----|-------|----------|----------|---------|
| PT-DB-001 | ... | database | verified | 2024-03-20 |
```

**注意**：`_index.md` 以 `_` 开头，`list_entries()` 扫描时跳过此文件。

### 10.2 `index.json`（根目录）

根目录 `index.json` 包含所有已发布条目的机器可读摘要，字段：`generated_at`、`total_entries`、`entries`（数组，每项含 `id`、`type`、`title`、`maturity`、`category`、`tags`、`updated_at`、`file_path`、`pending`）。

---

## 11. 操作日志

`contributions/log.md` 以 append-only 方式记录所有操作：

```
<ISO8601 timestamp> | <action> | <entry_id> | <summary>
```

`action` 取值：`pending`（写入待审核）、`confirmed`（人工确认发布）、`rejected`（人工拒绝）、`archived`（归档）、`decay`（maturity 降级）等。

---

## 12. 关键常量速查

| 常量 | 值 | 来源 |
|------|-----|------|
| `REQUIRED_FRONTMATTER_FIELDS` | `{id, type, title, maturity, category, tags, created_at, updated_at}` | `schema.py` |
| `VALID_TYPES` | `pitfall|model|guideline|process|decision` | `schema.py` |
| `VALID_MATURITY` | `draft|verified|proven|deprecated` | `schema.py` |
| `_CATEGORY_RE` | `^[a-z0-9][a-z0-9_/-]*[a-z0-9]$` | `schema.py` |
| `TITLE_MAX_LENGTH` | 100 | `schema.py` |
| `MATURITY_ORDER` | `draft=0, verified=1, proven=2` | `store.py` |
| `EVIDENCE_SIDECAR_DIR` | `contributions/evidence` | `store.py` |
| `SKILL_NAME_MIN` | 3 | `skill/manager.py` |
| `SKILL_NAME_MAX` | 64 | `skill/manager.py` |
| `ALLOWED_FRONTMATTER_KEYS`（SKILL.md） | `name, description, license, allowed-tools, metadata, compatibility` | `skill/manager.py` |
| Skill name pattern | `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$|^[a-z0-9]{3,64}$` | `skill/manager.py` |
