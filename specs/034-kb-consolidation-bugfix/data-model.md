# Data Model: KB 包整合与 Bug 修复

**Feature**: 034-kb-consolidation-bugfix | **Date**: 2026-06-17

本 feature 不引入新的数据实体或持久化格式变更，所有改动均在代码层面（API 迁移 + Bug 修复）。

---

## 1. 包结构变更

### 1.1 Before（双包并存）

```text
holmes/
├── holmes/
│   ├── kb/                    ← 旧包（holmes-agent 安装时包含）
│   │   ├── conflict.py
│   │   ├── importer.py
│   │   ├── index_builder.py
│   │   ├── linter.py
│   │   ├── merger.py
│   │   ├── pending.py
│   │   ├── store.py
│   │   └── validator.py
│   ├── agent_server.py        ← IPC 死代码
│   └── agent/
│       ├── ipc_server.py      ← IPC 死代码
│       └── tools/
│           ├── kb_read.py     ← IPC 死代码
│           └── kb_write.py    ← IPC 死代码
└── pyproject.toml             ← 只安装 holmes-agent，无 holmes-kb 依赖
```

### 1.2 After（单包）

```text
holmes/
├── holmes/
│   ├── kb/                    ← 目录已删除
│   └── agent/
│       └── tools/             ← kb_read.py、kb_write.py 已删除
└── pyproject.toml             ← 新增 "holmes-kb @ file:///./kb" 依赖

kb/                            ← 唯一的 holmes.kb 实现
└── holmes/kb/
    ├── agent/                 ← ImportAgentRunner、pipeline、extractor 等
    ├── mcp/                   ← MCP server
    ├── skill/                 ← SkillAdvisor、markers
    ├── store.py               ← 主存储 API（EntryMeta、read_entry 等）
    ├── pending.py             ← 待确认条目管理
    ├── validator.py           ← schema + 去重检查 + generate_id
    ├── linter.py              ← KB 健康检查（返回 LintReport）
    ├── merger.py              ← 新增 merge_pending_entry()
    └── conflict.py            ← 冲突管理
```

---

## 2. 关键 API 类型变更

### 2.1 EntryMeta（替代 KnowledgeEntry）

```python
# 旧（holmes/holmes/kb/store.py）
@dataclass
class KnowledgeEntry:
    id: str
    type: KBType
    title: str
    maturity: Maturity
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    body: str                  # 完整 Markdown body
    # 提供 to_frontmatter_str() 序列化方法

# 新（kb/holmes/kb/store.py）
@dataclass
class EntryMeta:
    id: str
    type: str                  # 改为 str（不再是 Literal 枚举）
    title: str
    maturity: str              # 改为 str
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    file_path: str             # 新增：指向实际文件路径
    pending: bool = False      # 新增：区分 pending 条目
    # 无 body 字段；无序列化方法
    # 完整内容通过 read_entry(kb_root, id) 获取
```

### 2.2 LintReport（替代 dict）

```python
# 旧：返回 dict
results = lint(kb_root, fix)
results["total_entries"]     # int
results["pending_count"]     # int
results["conflict_count"]    # int
results["warnings"]          # list[str]
results["errors"]            # list[str]
results["fixes_applied"]     # list[str]

# 新：返回 LintReport dataclass
report = lint(kb_root, fix)
report.total_entries         # int
report.pending_count         # int
report.conflict_count        # int
report.warnings              # list[str]
report.errors                # list[str]
report.fixes_applied         # list[str]
```

### 2.3 ValidationResult + DuplicateResult（替代 validate_entry 返回 dict）

```python
# 旧：单一函数返回嵌套 dict
validation = validate_entry(kb_root, content)
validation["errors"]                              # list[str]
validation["duplicates"]["similar_entries"]       # list[dict]

# 新：两个独立函数
schema_result: ValidationResult = validate_schema(content, kb_root)
schema_result.valid          # bool
schema_result.errors         # list[str]

dup_result: DuplicateResult = check_duplicate(kb_root, content)
dup_result.blocked           # bool
dup_result.similar_entries   # list[dict] — 字段：id, title, similarity
```

### 2.4 ConflictEntry（替代 conflict dict）

```python
# 旧：list_conflicts 返回 list[dict]
conflicts = list_conflicts(kb_root)
conflict["id"]               # conflict_id

# 新：list_conflicts 返回 list[ConflictEntry]
conflicts = list_conflicts(kb_root)
conflict.conflict_id         # str
conflict.entry_id            # str
conflict.path                # str
conflict.created_at          # str
```

---

## 3. Bug-4 数据流变更（Skill 命名）

### 3.1 旧流程

```
advise(entry_id="pending-20260617-xxx", description="Redis OOM 恢复", kb_root=...)
    ↓
_make_slug("pending-20260617-xxx")
    ↓
re.sub(r"[^a-z0-9]", "", "pending-20260617-xxx".lower())[:20]
    = "pending202606170402"
    ↓
suggested_name = "skill-pending202606170402"   ← 不可读
```

### 3.2 新流程

```
advise(entry_id="pending-20260617-xxx", description="Redis OOM 恢复", kb_root=...)
    ↓
_make_slug("pending-20260617-xxx", title="Redis OOM 恢复")
    ↓
title → re.sub(r"[^a-z0-9]+", "-", "redis oom 恢复".lower()).strip("-")[:40]
    = "redis-oom"   （中文部分被替换后为 "-"，collapse 后去除）

    # 若 len(slug) >= 3 → "redis-oom"
    ↓
suggested_name = "redis-oom"   ← 可读
```

---

## 4. Bug-5 数据流变更（Extractor type-section）

### 4.1 旧流程（有缺陷）

```
Extractor LLM 看到 prompt 中只有 pitfall 模板：
  ## Symptoms / ## Root Cause / ## Resolution

LLM 判断 type: decision，但仍使用 pitfall 模板：
  type: decision
  ## Symptoms        ← WRONG（decision 不应有此 section）
  ## Root Cause      ← WRONG
  ## Resolution      ← WRONG（decision 应该是 ## Decision）
```

### 4.2 新流程

```
Extractor LLM 看到 TYPE-SECTION MAPPING：
  decision → ## Context | ## Decision

LLM 生成：
  type: decision
  ## Context         ← CORRECT
  ## Decision        ← CORRECT

Normalizer 验证：
  type=decision + sections={Context, Decision}  → PASS

若仍出现 decision + ## Resolution（未修复 prompt 的旧模型）：
  Normalizer 检测 → warning + rename ## Resolution → ## Decision
```

---

## 5. 无变更的持久化格式

以下内容在本 feature 中不变：
- KB 条目文件格式（YAML frontmatter + Markdown body）
- pending 条目存储路径（`contributions/pending/{id}.md`）
- skill 文件结构（`skills/{name}/SKILL.md`）
- 证据文件结构（`{type}/{cat}/{id}.evidence.json`）
- MCP server 接口（6 个工具的 input/output schema）
