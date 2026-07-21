# Research: KB 包整合与 Bug 修复

**Feature**: 034-kb-consolidation-bugfix | **Date**: 2026-06-17

---

## R-1：pyproject.toml 本地依赖格式

**Decision**: 使用 PEP 508 `file://` 协议引用 `kb/` 子目录

**Rationale**:
- setuptools >=61（已满足）支持 `file:///` 相对路径
- `pip install -e .`（可编辑模式）会同时安装 `holmes-kb`，无需单独 `pip install -e kb/`
- 安装后 Python 包名为 `holmes-kb`，命名空间仍为 `holmes.kb`，与现有代码兼容

```toml
dependencies = [
    ...
    "holmes-kb @ file:///./kb",
]
```

**Alternatives considered**:
- `path = "kb"` （hatch 语法）：主 pyproject.toml 用 setuptools，不适用
- workspace 方案：需 pip 22+ + pyproject.toml [tool.pip] 配置，过于复杂
- PYTHONPATH 继续手动设置：用户体验差，是当前已知 Bug-2 的根源，不接受

---

## R-2：LintReport 字段确认

**Decision**: 从 `kb/holmes/kb/linter.py` 中读取 `LintReport` 定义，CLI 适配字段访问

```python
@dataclass
class LintReport:
    total_entries: int = 0
    pending_count: int = 0
    conflict_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fixes_applied: list[str] = field(default_factory=list)
```

所有字段名与旧 dict 的 key 名称一一对应，只需将 `results["xxx"]` 改为 `report.xxx`。

---

## R-3：新包 conflict.py 接口确认

**Decision**: `list_conflicts()` 返回 `list[ConflictEntry]`；`resolve_conflict()` 签名有差异

`ConflictEntry` 字段：

```python
@dataclass
class ConflictEntry:
    conflict_id: str    # 与旧 dict["id"] 对应
    entry_id: str
    path: str
    created_at: str
```

CLI `kb_resolve` 命令只使用 `conflict_id` 字段。新包的 `resolve_conflict(kb_root, conflict_id, kept="local")` 有 `kept` 参数（默认 "local"），旧版无此参数。CLI 调用时使用默认值即可，行为不变。

---

## R-4：entry 文件路径推算规则

**Decision**: 通过分析 `list_entries()` 的实现，确认路径规则

```python
# 新包 store.py list_entries() 扫描以下目录
for kb_type in ("pitfall", "model", "guideline", "process", "decision"):
    type_dir = kb_root / kb_type
    # pitfall: kb_root/pitfall/{category}/{id}.md
    # 其他:    kb_root/{type}/{id}.md
```

`kb_confirm` 中写 entry 的路径构造：

```python
import frontmatter
post = frontmatter.loads(new_content)
kb_type = str(post.metadata.get("type", "pitfall"))
category = post.metadata.get("category")

if kb_type == "pitfall" and category:
    entry_path = kb_root / kb_type / category / f"{new_id}.md"
else:
    entry_path = kb_root / kb_type / f"{new_id}.md"
```

---

## R-5：merge_pending_entry() 5 场景逻辑

**Decision**: 在新包中新增 `merge_pending_entry()` 函数，复用旧 `merge_entry()` 5 场景逻辑，但使用新包 API

5 个场景及对应处理：

| 场景 | 判断条件 | 处理方式 |
|------|---------|---------|
| `pure_add` | entry_id 不在已有 KB 中 | `write_entry(path, content)` + `rebuild_index_files()` |
| `evidence_append` | 同 ID，maturity 兼容（incoming ≤ existing） | 追加 evidence block 到现有文件 |
| `maturity_upgrade` | 同 ID，incoming maturity > existing maturity | 更新 maturity 字段后 `write_entry()` |
| `maturity_conflict` | 同 ID，maturity 不兼容（无法判断高低） | 保留较低 maturity，追加 contradiction tag |
| `content_contradiction` | 同 ID，content 语义矛盾 | 写入 `contributions/conflicts/`，不覆盖现有 |

新包已有 `write_conflict_entry()` 函数（`kb/holmes/kb/conflict.py`），可直接使用。

---

## R-6：Bug-4 slug 生成规则验证

**Decision**: 以下规则生成的 slug 符合现有 3-64 字符、kebab-case 格式约束

示例验证：

| title | slug |
|-------|------|
| `Redis Connection Pool Exhausted` | `redis-connection-pool-exhausted` |
| `PostgreSQL Autovacuum Blocking Writes` | `postgresql-autovacuum-blocking-writes` |
| `E810 固件升级流程` | `e810` （太短，回退到 entry_id 逻辑）|
| `   !!!  ` | `""` （空，回退到 entry_id 逻辑） |

边界处理：
- 纯中文 title → slug 为空（中文字符被 `[^a-z0-9]+` 替换），自动回退到 entry_id 逻辑
- title 长度 < 3 → 回退到 entry_id 逻辑
- 重名：追加 `-2`、`-3` 直至不重名

---

## R-7：Bug-5 type-section mapping 标准

**Decision**: 基于现有 `kb/holmes/kb/schema.py` 中的 schema 定义确认 type→section 映射

从 schema 验证逻辑推导出的必需 sections：

| type | required sections |
|------|------------------|
| pitfall | Symptoms, Root Cause, Resolution |
| model | When to Use, Structure, Example |
| guideline | Guideline, Rationale, Examples |
| process | Purpose, Steps, Verification |
| decision | Context, Decision |

自动修正策略：
- decision + `## Resolution` → rename 为 `## Decision`（最常见的 Bug-5 表现）
- 其他 type 的 forbidden sections → 只记 warning，不自动 rename（避免语义损失）
- Verifier prompt 不修改（改 Normalizer 即可，prompt 改动影响面更大）
