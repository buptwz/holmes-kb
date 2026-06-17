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
│       └── PT-<CAT>-NNN.md          # 已发布 pitfall 条目
├── model/
│   └── <category>/
│       └── MD-<CAT>-NNN.md          # 已发布 model 条目
├── guideline/
│   └── <category>/
│       └── GL-<CAT>-NNN.md          # 已发布 guideline 条目
├── process/
│   └── <category>/
│       └── PR-<CAT>-NNN.md          # 已发布 process 条目
├── decision/
│   └── <category>/
│       └── DC-<CAT>-NNN.md          # 已发布 decision 条目
├── skills/
│   └── <skill-name>/                # skill name = kebab-case，3-64 字符
│       ├── SKILL.md                 # 必须存在；agent instruction package
│       └── <optional-files>         # 脚本、参考资料等，无结构限制
├── contributions/
│   ├── pending/
│   │   └── pending-YYYYMMDD-HHMMSS-xxxx.md   # 待审核条目
│   ├── evidence/
│   │   └── <entry_id>/
│   │       └── <session_id>.json    # per-session evidence sidecar
│   └── log.md                       # append-only 操作日志
├── <type>/_index.md                 # 各类型目录下的 Markdown 索引表（自动生成）
└── index.json                       # 根目录 machine-readable 索引（自动生成）
```

**扫描规则**（来源：`store.py:87-89`）：
- `list_entries()` 对每个 type 目录执行 `rglob("*.md")`，递归扫描所有子目录
- 文件名以 `_` 开头的文件（如 `_index.md`）被跳过，不作为条目处理
- 条目的 ID 取自 frontmatter 中的 `id` 字段，不依赖文件名（`store.py:98`）
- `read_entry()` 进行大小写不敏感的 ID 匹配（`store.py:44`），**Bug-3 修复后**使用 `include_pending=True`，pending 条目 ID 也可被命中

---

## 2. Entry Frontmatter 字段

### 2.1 必填字段

所有 5 种 entry 类型均必须包含以下字段（来源：`schema.py:30-32`）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | string | 格式见 §5 | 唯一条目标识符 |
| `type` | string | 见有效值列表 | entry 类型 |
| `title` | string | 最长 100 字符 | 条目标题 |
| `maturity` | string | 见有效值列表 | 成熟度级别 |
| `category` | string | pitfall 有枚举限制；其他类型自由 | 分类 |
| `tags` | list[string] | 可为空列表 | 检索标签 |
| `created_at` | string | ISO8601 带时区，≤ `updated_at` | 创建时间 |
| `updated_at` | string | ISO8601 带时区，≥ `created_at` | 最后更新时间 |

**`type` 有效值**（来源：`schema.py:16,43`）：
```
pitfall | model | guideline | process | decision
```

**`maturity` 有效值**（来源：`schema.py:17,44`）：
```
draft | verified | proven | deprecated
```

**`title` 长度限制**（来源：`schema.py:52,117-121`）：最长 100 字符，超出报验证错误。

**`created_at` / `updated_at` 关系约束**（来源：`schema.py:123-140`）：
`created_at` 必须 ≤ `updated_at`，否则报验证错误。两者均需为可解析的 ISO8601 字符串。

### 2.2 可选字段

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `skill_refs` | list[string] | 每项匹配 skill name 格式（见 §5） | 关联的 skill 名称列表 |
| `contributors` | list[string] | 无格式约束 | 贡献者列表，由 `add_contributor()` 维护 |
| `evidence` | list[dict] | EvidenceRecord 格式（见 §7） | 遗留字段；新 evidence 存 sidecar |

**`skill_refs` 格式约束**（来源：`schema.py:148`）：
```python
skill_name_re = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]{1,2}$")
```
每个元素必须是符合该正则的字符串；若为 list 以外的类型，则报验证错误（`schema.py:145-153`）。

### 2.3 `category` 枚举约束

仅 `pitfall` 类型对 `category` 有枚举限制（来源：`schema.py:45-50`）：

```
network | system | application | database | kubernetes | messaging | cache | monitoring
```

`model`、`guideline`、`process`、`decision` 类型的 `category` 字段无枚举约束，可自由填写。

---

## 3. 各 Entry 类型必需 Body Sections

来源：`schema.py:35-41`，验证逻辑：`schema.py:107-114`（大小写不敏感匹配）。

| 类型 | 必需 Markdown sections |
|------|----------------------|
| `pitfall` | `## Symptoms`、`## Root Cause`、`## Resolution` |
| `model` | `## Definition` |
| `guideline` | `## Rule` |
| `process` | `## Steps` |
| `decision` | `## Context`、`## Decision` |

验证方式：`post.content.lower()` 中查找 `section.lower()`，缺失任一 section 即报错。

---

## 4. Entry 文件示例

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
created_at: "2024-01-15T08:00:00+00:00"
updated_at: "2024-03-20T12:30:00+00:00"
skill_refs:
  - redis-oom-recovery
---

## Symptoms

服务出现间歇性超时，Redis 日志中有 `NOEVICTION` 或 `maxmemory-policy` 相关告警。

## Root Cause

Redis 内存达到 `maxmemory` 上限，触发 key 驱逐或拒绝写入。

## Resolution

调整 `maxmemory` 配置或清理大 key，参见关联 skill `redis-oom-recovery`。
```

---

## 5. ID 格式规则

### 5.1 Entry ID

**格式**（来源：`mcp/tools.py:29`）：
```
^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$
```

**结构**：`{TYPE_PREFIX}-{CAT_ABBR}-{NNN}`

| 部分 | 规则 | 示例 |
|------|------|------|
| TYPE_PREFIX | 2-3 位大写字母 | `PT`（pitfall）、`MD`（model）、`GL`（guideline）、`PR`（process）、`DC`（decision） |
| CAT_ABBR | 2-3 位大写字母 | `DB`（database）、`NET`（network）、`SVC`（service） |
| NNN | 3 位数字，补零 | `001`、`042` |

**大小写匹配**：`read_entry()` 比较时使用 `.upper()`（`store.py:44`），存储时使用大写。

### 5.2 Skill Name

**格式**（来源：`skill/manager.py:17`）：
```
^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$   # 4-64 字符，包含连字符
|^[a-z0-9]{3,64}$                     # 3-64 字符，纯字母数字
```

**长度约束**（`skill/manager.py:18-19`）：最短 3 字符，最长 64 字符。

**规则**：纯小写字母、数字、连字符；首尾不得为连字符。

**示例**：`redis-oom-recovery`、`nginx-reload`、`db`

**与 Entry ID 的互斥性**：Entry ID 含大写字母，skill name 为纯小写，格式天然互斥，`kb_read` 路由无歧义。

### 5.3 Pending ID

**格式**（来源：`pending.py:24-28`）：
```python
f"pending-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{rand}"
# rand = 4 位随机小写字母+数字
```

**示例**：`pending-20240315-143022-a7bk`

**文件路径**：`contributions/pending/<pending_id>.md`

Pending ID 不匹配 Entry ID 正则（含小写前缀 `pending-`），也不匹配 skill name 规则（含数字日期段），三种 ID 格式天然互斥。

---

## 6. Maturity 级别与升级规则

### 6.1 级别定义

来源：`store.py:210-230`，`derive_maturity()` 函数。

| 级别 | 触发条件 | 说明 |
|------|---------|------|
| `draft` | 0 条 evidence | 初始状态，未经任何验证 |
| `verified` | ≥1 条 evidence | 至少一次有记录的实际使用 |
| `proven` | ≥2 个不同 `session_id` **且** ≥2 个不同 `contributor` | 多人多次独立验证 |
| `deprecated` | 手动设置 | 已过时，不参与 maturity 自动升级 |

**代码依据**（`store.py:223-230`）：
```python
def derive_maturity(evidence: list[dict]) -> str:
    if not evidence:
        return "draft"
    sessions = {str(e.get("session_id", "")) for e in evidence if e.get("session_id")}
    contributors = {str(e.get("contributor", "")) for e in evidence if e.get("contributor")}
    if len(sessions) >= 2 and len(contributors) >= 2:
        return "proven"
    return "verified"
```

### 6.2 升级规则

来源：`store.py:155-156,311-317`。

- **只升不降**：`append_evidence()` 仅在 `new_rank > current_rank` 时更新 frontmatter（`store.py:315`）
- **maturity 排序**：`draft=0 < verified=1 < proven=2`（`store.py:156`）；`deprecated` 不在排序表中，不参与自动升降
- **`deprecated` 豁免**：手动设置为 `deprecated` 的条目，`MATURITY_ORDER` 中查不到该值（rank=0），但由于只升不降，不会被 evidence 触发降级

### 6.3 并发冲突处理

来源：`store.py:346-364`，`resolve_maturity_conflict()`：

- 当两个 git branch 对同一 entry 写了不同 maturity 时，保留**更低（更保守）**的值
- 始终返回 `contradiction=True`，供维护者审查

---

## 7. Evidence Sidecar 格式

### 7.1 存储结构

来源：`store.py:158-159,301-305`。

```
contributions/evidence/<entry_id>/<session_id>.json
```

**设计原因**：每条 evidence 独立成文件，git merge 时只有 file addition，不产生 merge conflict。

### 7.2 EvidenceRecord 字段

来源：`schema.py:20-27`。

| 字段 | 是否必须 | 类型 | 说明 |
|------|---------|------|------|
| `session_id` | 必须 | string | 唯一会话标识符，用于去重 |
| `contributor` | 必须 | string | 用户/agent 标识（邮箱、用户名或 hostname） |
| `date` | 必须 | string | ISO8601 日期字符串（`YYYY-MM-DD`） |
| `project` | 可选 | string | 项目上下文 |
| `context` | 可选 | string | 该条目的具体使用方式 |

**文件内容**：单个 JSON 对象，`ensure_ascii=False`（`store.py:305`）。

**文件名**：`session_id` 中的 `/` 和 `\` 替换为 `-`（`store.py:303`），避免路径问题。

### 7.3 去重规则

来源：`store.py:291-298`。

`append_evidence()` 在写入前合并 frontmatter evidence 与 sidecar evidence，若相同 `session_id` 已存在，则静默返回 `False`（no-op）。两个不同 session_id 的 evidence 总是独立写入，互不干扰。

### 7.4 合并数据源顺序

来源：`store.py:188-206`，`load_evidence()`：

1. 先加载 frontmatter 中的 `evidence` 列表（历史数据来源）
2. 再加载 sidecar 目录中所有 `*.json` 文件（新数据来源）
3. 按 `session_id` 去重，sidecar 记录覆盖同 session_id 的 frontmatter 记录

---

## 8. Pending Entry 格式

### 8.1 Pending 专有 Frontmatter 字段

Pending entry 在标准 Entry 字段基础上额外包含（来源：`pending.py:81-96`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 临时 pending ID（格式见 §5.3），由系统赋值，覆盖 LLM 生成的 ID |
| `pending` | bool | 固定为 `True` |
| `pending_since` | string | 写入 pending 时的 ISO8601 时间戳 |
| `source` | string | `"auto"`（import pipeline）或 `"agent"`（KbExtractAndSave） |
| `source_session` | string | 调用方的 session 标识（时间戳或 session ID） |
| `suggested_type` | string | LLM 分类的 entry type，供人工审核参考 |
| `suggested_category` | string | LLM 分类的 category，供人工审核参考 |

**`maturity` 默认值**（`pending.py:65`）：写入时若缺失，自动补 `"draft"`。

### 8.2 Pending 与正式 Entry 的差异

| 维度 | Pending Entry | 正式 Entry |
|------|---------------|-----------|
| 存储路径 | `contributions/pending/<id>.md` | `<type>/<category>/<id>.md` |
| ID 格式 | `pending-YYYYMMDD-HHMMSS-xxxx` | `PT-DB-001`（大写前缀+数字） |
| 可被 `kb_confirm` 操作 | 否（`_is_entry_id()` 不匹配） | 是 |
| 可被 `list_entries()` 扫描 | 仅当 `include_pending=True` | 默认包含 |
| `append_evidence()` 是否有效 | 是（`include_pending=True` 扫描） | 是 |
| maturity 自动升级 | 是（evidence 写入后） | 是 |

### 8.3 Title 去重检查

来源：`pending.py:67-79`。

`write_pending()` 写入前检查 title 是否与已有 `verified`/`proven` 条目重复（`check_title_duplicate()`）。若重复，抛出 `DuplicateTitleError`。仅当提供 `corrects` 参数（指向已有条目 ID）时跳过此检查。

---

## 9. Skill 结构

### 9.1 目录布局

来源：`skill/manager.py:107`，`skill/template.py`。

```
skills/<skill-name>/
├── SKILL.md                  # 必须存在；agent instruction package
└── <optional subdirs/files>  # 脚本、参考资料等，无结构要求
```

**子目录无限制**（`skill/manager.py:244-245`）：`scripts/`、`references/`、`assets/` 等均可自由创建，`kb_read` 通过 `path` 参数读取任意子文件（文本文件过滤规则见 §9.4）。

### 9.2 SKILL.md Frontmatter 字段

来源：`skill/manager.py:22-24,120-178`，Anthropic Agent Skills 标准。

**允许的 frontmatter key**（`skill/manager.py:22-24`）：
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

来源：`skill/template.py`。

`create_skill()` 生成的默认 SKILL.md 模板：

```markdown
---
name: <skill-name>
description: <description>
---

# <skill-name>

## When to Use

Describe when an agent should use this skill. Include symptoms, conditions, and trigger events.

## Resolution Steps

1. First step: describe what to do and why.
2. Second step: describe what to do and why.
3. Third step: describe what to do and why.

## Key Points

- Important caveat or boundary condition.
- Common pitfall to avoid.
- Key thing to verify after resolution.
```

**Body 为 agent 指令**：body 是纯 Markdown，无强制 section 要求（与 entry 不同）；传入自定义 `instructions` 时，直接使用传入内容，不加默认模板（`skill/template.py:36`）。

### 9.4 Skill 子文件文本过滤规则

来源：`mcp/tools.py:22-27`（`_TEXT_EXTENSIONS`）。

`kb_read(skill_name, path=...)` 和 `files` 列表只返回以下扩展名的文件：

```
.sh .bash .py .rb .js .ts .go .rs .java
.md .txt .yaml .yml .json .toml .ini .conf .env
.sql .xml .html .css
```

其他扩展名（如 `.png`、`.bin`、`.zip`）被视为二进制文件，不可通过 MCP 读取，也不出现在 `files` 列表中。

### 9.5 SkillDefinition 与 SkillSummary 数据结构

来源：`skill/manager.py:186-193,427-433`。

**SkillDefinition**（`parse_skill_md()` 返回）：
| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 取自 frontmatter `name`；若缺失则回退到目录名 |
| `description` | string | 取自 frontmatter `description` |
| `content` | string | SKILL.md 完整原始文本（含 frontmatter） |

**SkillSummary**（`list_skills()` 返回）：
| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | skill 名称 |
| `description` | string | 触发描述 |
| `linked_entries` | list[string] | 所有 `skill_refs` 包含该 skill 的 entry ID 列表（动态计算） |

`linked_entries` 计算方式（`mcp/tools.py:_compute_linked_entries`）：扫描所有 5 种 entry 类型目录（`pitfall/model/guideline/process/decision/`）**以及** `contributions/pending/` 目录，收集 `skill_refs` 中包含该 skill name 的 entry ID 列表（Bug-3 修复：pending 条目在 confirm 前即可出现在 `linked_entries` 中）。格式保持 `list[str]`，向后兼容。

### 9.6 SkillMarker（FR-1，Feature 033）

来源：`kb/holmes/kb/skill/markers.py`，`extract_skill_markers()` 函数。

从 KB 条目 `## Resolution` 段落中解析 skill 调用标记，返回 `list[SkillMarker]`。

**两种标记语法**：

| 形式 | 语法 | 示例 |
|------|------|------|
| Blockquote | `> skill: <name>` （单独一行） | `> skill: e810-firmware-upgrade` |
| Inline | `` `[skill:<name>]` `` （行内任意位置） | `` 执行调参 → `[skill:e810-driver-tuning]` `` |

**SkillMarker 字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_name` | `str` | 已验证的 kebab-case skill 名称 |
| `step_heading` | `str` | 最近的上级 `##` / `###` 标题全文，若无则为空字符串 |
| `marker_type` | `str` | `"blockquote"` 或 `"inline"` |
| `line` | `int` | 标记所在行号（1-indexed） |

**规则**：不合规 skill name 静默跳过；返回列表按行号排序；同一 skill name 多次出现全部返回（调用方去重）。

### 9.7 `skill_invocations` MCP 响应字段（FR-5，Feature 033）

来源：`mcp/tools.py:_read_entry()`。

`kb_read(entry_id)` 响应中新增 `skill_invocations` 字段，列出 Resolution 中每个 skill 调用标记的位置和名称。

**格式**：

```json
{
  "skill_invocations": [
    {"step": "### Step 3：执行固件升级", "skill": "e810-firmware-upgrade"},
    {"step": "### Step 5：驱动调参",     "skill": "e810-driver-tuning"}
  ]
}
```

- 无标记时返回空列表 `[]`
- `step` 字段为 `SkillMarker.step_heading`（最近上级标题全文）
- `skill` 字段为 `SkillMarker.skill_name`
- 字段从 Resolution 实时解析，不缓存，不写入文件

---

## 10. 自动生成的索引文件

### 10.1 `_index.md`（各类型目录）

来源：`store.py:387-404`，`rebuild_index_files()`。

每个类型目录（`pitfall/`、`model/` 等）下的 `_index.md` 包含该类型所有条目的 Markdown 表格：

```
| ID | Title | Category | Maturity | Updated |
|----|-------|----------|----------|---------|
| PT-DB-001 | ... | database | verified | 2024-03-20 |
```

**注意**：`_index.md` 以 `_` 开头，`list_entries()` 扫描时跳过此文件（`store.py:88-89`）。

### 10.2 `index.json`（根目录）

来源：`store.py:406-427`。

根目录 `index.json` 包含所有已发布条目的机器可读摘要，字段：`generated_at`、`total_entries`、`entries`（数组，每项含 `id`、`type`、`title`、`maturity`、`category`、`tags`、`updated_at`、`file_path`、`pending`）。

---

## 11. 操作日志

来源：`pending.py:186-200`，`append_log()`。

`contributions/log.md` 以 append-only 方式记录所有操作：

```
<ISO8601 timestamp> | <action> | <entry_id> | <summary>
```

`action` 取值：`pending`（写入待审核）、`confirmed`（人工确认发布）、`rejected`（人工拒绝）等。

---

## 12. 关键常量速查

| 常量 | 值 | 来源 |
|------|-----|------|
| `REQUIRED_FRONTMATTER_FIELDS` | `{id, type, title, maturity, category, tags, created_at, updated_at}` | `schema.py:30-32` |
| `VALID_TYPES` | `pitfall\|model\|guideline\|process\|decision` | `schema.py:43` |
| `VALID_MATURITY` | `draft\|verified\|proven\|deprecated` | `schema.py:44` |
| `VALID_PITFALL_CATEGORIES` | 8 项（见 §2.3） | `schema.py:45-50` |
| `TITLE_MAX_LENGTH` | 100 | `schema.py:52` |
| `MATURITY_ORDER` | `draft=0, verified=1, proven=2` | `store.py:156` |
| `EVIDENCE_SIDECAR_DIR` | `contributions/evidence` | `store.py:159` |
| `PENDING_DIR` | `contributions/pending` | `pending.py:20` |
| `LOG_PATH` | `contributions/log.md` | `pending.py:21` |
| `SKILL_NAME_MIN` | 3 | `skill/manager.py:18` |
| `SKILL_NAME_MAX` | 64 | `skill/manager.py:19` |
| `ALLOWED_FRONTMATTER_KEYS`（SKILL.md） | `name, description, license, allowed-tools, metadata, compatibility` | `skill/manager.py:22-24` |
| Entry ID pattern | `^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$` | `mcp/tools.py:29` |
| Skill name pattern | `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$\|^[a-z0-9]{3,64}$` | `skill/manager.py:17` |
| Pending ID pattern | `pending-YYYYMMDD-HHMMSS-[a-z0-9]{4}` | `pending.py:24-28` |
| `_TEXT_EXTENSIONS`（MCP 文本过滤） | 22 项扩展名（见 §9.4） | `mcp/tools.py:22-27` |
