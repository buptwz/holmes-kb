# Data Model: KB Skill Mounting

**Date**: 2026-05-29 | **Branch**: `002-kb-skill-mount`

## Entities

### KbEntry (已有，扩展)

**文件路径**: `$HOLMES_KB_PATH/<type>/<category>/<ID>.md`

**YAML Frontmatter 字段**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 条目 ID，如 `PT-DB-001` |
| type | string | ✅ | pitfall / model / guideline / process / decision |
| title | string | ✅ | 条目标题（≤100字符） |
| maturity | string | ✅ | draft / verified / proven / deprecated |
| category | string | ✅ | 条目子分类 |
| tags | list[string] | ✅ | 标签列表 |
| created_at | date | ✅ | 创建日期 YYYY-MM-DD |
| updated_at | date | ✅ | 更新日期 YYYY-MM-DD |
| **skill_refs** | list[string] | ❌ | **新增**：引用的 Skill 名称列表，值为 `skills/` 下的子目录名 |

**约束**:
- `skill_refs` 中每个名称必须在 `$HOLMES_KB_PATH/skills/` 下有对应子目录（软约束，link 时校验，show 时警告）
- 同一 skill 名称在 `skill_refs` 中不重复
- 不含 `skill_refs` 的条目格式完全不变（向后兼容）

**示例**:
```yaml
---
id: PT-DB-001
type: pitfall
title: Redis 连接池耗尽导致超时
maturity: verified
category: database
tags: [redis, connection-pool]
created_at: "2026-05-28"
updated_at: "2026-05-29"
skill_refs:
  - check-redis-connections
---
```

---

### SkillDefinition (新增)

**文件路径**: `$HOLMES_KB_PATH/skills/<name>/`

**目录结构**:
```
skills/<name>/
├── SKILL.md          ← 元数据 + 描述（YAML frontmatter + Markdown body）
└── scripts/
    ├── run.sh        ← 固定约定入口脚本（唯一执行入口）
    └── *.sh          ← 可选辅助脚本（由 run.sh 调用）
```

**SKILL.md frontmatter 字段**:

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | ✅ | Skill 名称（与目录名一致，kebab-case，全局唯一） |
| description | string | ✅ | 一句话描述 |
| version | string | ✅ | 语义化版本 `x.y.z` |
| platforms | list[string] | ✅ | `[linux]` / `[macos]` / `[linux, macos]` |
| timeout | integer | ❌ | 执行超时秒数（默认 30） |
| params | list[SkillParam] | ❌ | 参数声明列表 |
| prerequisites.commands | list[string] | ❌ | 运行前检查是否存在的命令 |

**SKILL.md body 约定章节**:
- `## 用途` — 什么场景使用
- `## 执行说明` — 脚本做什么
- `## 参数`（有 params 时必须）— 参数说明

---

### SkillParam (新增，嵌套在 SKILL.md frontmatter)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | ✅ | 参数名（snake_case） |
| description | string | ✅ | 参数说明 |
| required | boolean | ✅ | 是否必填 |
| default | string | ❌ | 默认值（required=false 时建议提供） |

**参数传递约定**: runner.py 将参数以环境变量形式注入 run.sh，格式为 `SKILL_PARAM_<NAME_UPPERCASE>`。

示例：param `host` → 环境变量 `SKILL_PARAM_HOST`。

---

### SkillExecution (运行时，不持久化)

| 字段 | 类型 | 说明 |
|------|------|------|
| skill_name | string | 执行的 Skill 名称 |
| params | dict[str, str] | 实际传入的参数值 |
| command | string | 实际执行的命令（`bash scripts/run.sh`） |
| stdout | string | 标准输出（截断到 10KB） |
| stderr | string | 标准错误（截断到 2KB） |
| exit_code | integer | 退出码（0=成功） |
| duration_ms | integer | 执行耗时毫秒 |
| truncated | boolean | stdout 是否被截断 |

---

### SkillLibrary (目录级别)

**路径**: `$HOLMES_KB_PATH/skills/`

- 所有 SkillDefinition 的集合
- 随 KB 仓库 git 管理
- `holmes kb skill list` 枚举此目录

---

## 状态转换

### SkillDefinition 生命周期

```
[不存在]
   │ holmes kb skill create <name>
   │ 或 agent 沉淀时自动生成
   ▼
[已创建] ── holmes kb skill link <entry-id> <name> ──► [已挂载到条目]
   │                                                         │
   │ holmes kb skill unlink <entry-id> <name>               │
   │◄────────────────────────────────────────────────────────┘
   │
   │ rm -rf skills/<name>/  (手动或 git 操作)
   ▼
[已删除] ── 遗留悬空引用（holmes kb show 时警告）
```

### KbEntry.skill_refs 生命周期

```
条目创建时: skill_refs 为空 或 由 agent 沉淀时填充
    │ holmes kb skill link
    ▼
skill_refs 新增 skill 名称
    │ holmes kb skill unlink
    ▼
skill_refs 移除 skill 名称
    │ holmes kb confirm
    ▼
条目从 pending 发布到正式 KB
```

---

## 文件系统约束

- `skills/<name>/` 目录名：kebab-case，仅含 `[a-z0-9-]`，长度 3-64
- `skills/<name>/SKILL.md`：必须存在，否则 `holmes kb skill list/read/run` 报错
- `skills/<name>/scripts/run.sh`：`KbRunSkill` 执行时必须存在；`create` 时生成模板
- `skill_refs` 中的名称不包含路径分隔符，单纯 skill 名称
