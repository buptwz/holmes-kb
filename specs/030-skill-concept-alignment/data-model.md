# Data Model: Skill Concept Alignment

## 核心实体变更

### SkillDefinition（简化）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | skill 名称（kebab-case） |
| `description` | `str` | 触发描述（≤1024 字符） |
| `content` | `str` | 完整 SKILL.md 原始文本 |

**移除字段**: `version`、`platforms`、`timeout`、`params`（`list[SkillParam]`）、`prerequisites`

**`SkillParam` 类**: 随 `params` 字段一起删除

---

### SkillSummary（简化）

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | skill 名称 |
| `description` | `str` | 触发描述 |
| `linked_entries` | `list[str]` | 关联的 entry ID 列表 |

**移除字段**: `version`、`platforms`

---

### SKILL.md 文件结构

**Frontmatter（仅两个必填字段）**:
```yaml
---
name: check-redis-pool
description: Diagnose and resolve Redis connection pool exhaustion. Use when Redis
  operations time out and logs show ERR max number of clients reached.
---
```

**Body（三节结构）**:
```markdown
# check-redis-pool

## When to Use

When Redis client connections are exhausted and new connections are refused.
Symptoms include timeout errors and "ERR max number of clients reached" in logs.

## Resolution Steps

1. Check current connection limit: `redis-cli CONFIG GET maxclients`
2. Temporarily increase the limit: `redis-cli CONFIG SET maxclients 10000`
3. Make the change permanent in `redis.conf`: add `maxclients 10000`
4. Restart Redis to apply the config file change: `systemctl restart redis`

## Key Points

- Always verify the root cause (connection leak vs low limit) before raising the limit.
- The CONFIG SET change is not persistent across restarts — always update redis.conf.
- Monitor connected_clients after the change: `redis-cli info clients`.
```

---

### validate_skill_md() 输出

```python
(valid: bool, error: str)
# valid=True  → ("", "")
# valid=False → (False, "Unexpected key(s) in SKILL.md frontmatter: version, timeout. Allowed: ...")
```

---

### Skill 目录结构（新）

```
skills/<name>/
└── SKILL.md              # 必须存在
# scripts/, references/, assets/ 可选，不自动生成
```

**旧结构（废弃）**:
```
skills/<name>/
├── SKILL.md
└── scripts/
    └── run.sh            # 不再自动生成
```

---

### create_skill() 签名变更

```python
# 旧
def create_skill(
    kb_root: Path,
    name: str,
    description: str,
    platforms: str = "linux,macos",
    commands: Optional[list[str]] = None,
    param_names: Optional[list[str]] = None,
) -> Path: ...

# 新
def create_skill(
    kb_root: Path,
    name: str,
    description: str,
    instructions: str = "",
) -> Path: ...
```

---

### create_skill_for_entry tool 参数变更

```python
# 旧 tool input
{
    "name": str,
    "entry_id": str,
    "description": str,
    "link_only": bool,
    "resolution_commands": list[str],  # 删除
    "param_names": list[str],          # 删除
}

# 新 tool input
{
    "name": str,
    "entry_id": str,
    "description": str,
    "instructions": str,   # 新增：LLM 生成的 agent 指令 markdown body
    "link_only": bool,
}
```

---

### _generate_skill_instructions() 接口

```python
def _generate_skill_instructions(
    self,
    entry_content: str,    # 完整 entry markdown（含 frontmatter）
    resolution_text: str,  # 已提取的 Resolution 段落文本
) -> tuple[str, str]:      # (description, instructions_body)
```

返回值：
- `description`: LLM 生成的 skill description（≤1024 字符，含触发时机）
- `instructions_body`: 完整 markdown body（含三节）

失败时返回 `("", "")` → `create_skill()` 使用默认占位 body。

---

## 状态流转（不变）

```
detect_commands(resolution_text) → count
count ≥ 3 → RECOMMENDED → _generate_skill_instructions() → create_skill(instructions)
count 1-2 → OPTIONAL   → suggestion only
count 0   → SKIP
has skill_refs → LINK
```
