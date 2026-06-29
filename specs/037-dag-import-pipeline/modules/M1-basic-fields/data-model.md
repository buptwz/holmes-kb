# Data Model: M1 — 基础字段与过滤

**Date**: 2026-06-23

## 新增类型定义（schema.py）

### KBStatus

```python
KBStatus = Literal["pending", "active", "deprecated"]
```

| 值 | 语义 | 过滤行为 |
|----|------|---------|
| `active` | 当前有效，参与 agent 检索 | 默认可见 |
| `pending` | 待审核（import 后未 approve 的草稿） | 默认隐藏 |
| `deprecated` | 已被新版本替代 | 默认隐藏；`--all` 时可见 |

**向后兼容规则**: 缺省 `kb_status` 字段的 entry 视为 `active`。

---

## EntryFrontmatter 新增字段

在现有字段（`id`, `type`, `title`, `maturity`, `category`, `tags`, `created_at`, `updated_at`）基础上，新增以下可选字段：

| 字段 | Python 类型 | 必填 | 说明 |
|------|------------|------|------|
| `kb_status` | `KBStatus` | 否（缺省=active） | KB 管理工作流状态 |
| `source_file` | `str` | 否 | 相对于 KB root 的源文档路径 |
| `source_hash` | `str` | 否 | 源文档内容 sha256 前缀 |
| `description` | `str` | 否 | 1-2 句话的条目摘要 |
| `import_trace_id` | `str` | 否 | 源文档文件名 stem，用于日志关联 |
| `pitfall_structure` | `Literal["tree", "flat"]` | 否（缺省=flat） | 新式树形/旧式扁平 pitfall |
| `child_entry_ids` | `list[str]` | 否 | 树结构子节点 ID 列表 |
| `parent_id` | `str` | 否 | 父 entry ID（process sub-entry 专用） |

---

## EntryMeta 更新（store.py）

在现有 `EntryMeta` 数据类基础上，新增字段：

```python
@dataclass
class EntryMeta:
    # 现有字段（不变）
    id: str
    type: str
    title: str
    maturity: str
    category: Optional[str]
    tags: list[str]
    created_at: str
    updated_at: str
    file_path: str
    pending: bool = False

    # 新增字段
    kb_status: str = "active"    # 缺省 active（向后兼容）
    parent_id: Optional[str] = None  # process sub-entry 的父节点 ID
```

---

## list_entries() 接口变更

```python
def list_entries(
    kb_root: Path,
    kb_type: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 0,
    offset: int = 0,
    include_pending: bool = False,
    # 新增参数
    kb_status: Optional[str] = "active",       # None = 不过滤状态
    exclude_sub_entries: bool = True,           # True = 过滤 process sub-entries
) -> list[EntryMeta]:
```

**过滤逻辑**:
1. `kb_status` 过滤：`meta.get("kb_status", "active") == kb_status`（当 `kb_status` 非 None 时）
2. `exclude_sub_entries` 过滤：`not (meta.get("type") == "process" and meta.get("parent_id"))`

---

## find_entry() 新增函数

```python
def find_entry(kb_root: Path, entry_id: str) -> Optional[Path]:
    """通过文件系统扫描查找 entry，返回文件路径。
    支持新旧两种 ID 格式，大小写不敏感。
    扫描范围：所有类型目录 + contributions/pending/
    """
```

**查找策略**:
1. 扫描 `kb_root.rglob("*.md")`（跳过 `_` 开头的文件）
2. 读取 frontmatter，比较 `meta.get("id", "")` 与 `entry_id`（大小写不敏感）
3. 若 frontmatter 无 `id` 字段，比较文件名 stem

---

## read_entry() children 附加

**触发条件**: frontmatter 中 `child_entry_ids` 非空列表

**附加格式**（追加到 Markdown body 末尾）:

```markdown

## Children

| ID | Title |
|----|-------|
| <child-id-1> | <child-title-1> |
| <child-id-2> | <child-title-2> |
```

**实现**:
- 对每个 `child_id`，调用 `find_entry()` 找到文件路径
- 读取 frontmatter 中的 `title` 字段
- 若 child entry 不存在，输出 `| <child-id> | (not found) |`

---

## MCP 工具层变更（mcp/tools.py）

### `handle_kb_list()` 调用更新

```python
# 修改前
all_entries = list_entries(kb_root, kb_type=type, category=category)
# 修改后
all_entries = list_entries(
    kb_root, kb_type=type, category=category,
    kb_status="active", exclude_sub_entries=True
)
```

### `handle_kb_read()` 路由更新

**问题**: `_ENTRY_ID_PATTERN = re.compile(r"^[A-Z]{2,3}-[A-Z]{2,3}-\d{3}$")` 不匹配新格式 ID。

**修改后路由逻辑**:
```python
def handle_kb_read(kb_root, entry_id, path=None):
    from holmes.kb.store import find_entry  # M1 新增
    if find_entry(kb_root, entry_id) is not None:
        return _read_entry(kb_root, entry_id)
    if entry_id.startswith("pending-"):
        return _read_entry(kb_root, entry_id)
    return _read_skill(kb_root, entry_id, path)
```

### `_read_entry()` children 字段

当 entry frontmatter 包含 `child_entry_ids` 且非空时，在返回 dict 中增加 `children` 字段：

```python
{
    "content": "...",
    "type": "pitfall",
    "maturity": "draft",
    "skill_refs": [],
    "children": [
        {"id": "child-id-1", "title": "子节点标题 1"},
        {"id": "child-id-2", "title": "子节点标题 2"},
    ],
    "pending": False,
}
```

---

## HolmesConfig 变更（config.py）

新增 `username` 字段：

```python
@dataclass
class HolmesConfig:
    kb_path: str = ""
    model: str = "gpt-4o"
    api_base_url: str = ""
    api_key: str = ""
    log_level: str = "WARNING"
    max_tokens: int = 4096
    provider: str = "openai"
    username: str = ""    # 新增：import 时写入 contributors 的用户名
```

`from_dict()` 新增: `username=data.get("username", "")`

---

## 状态机：Process Sub-entry 可见性

```
                      find_entry() / kb show
                      ↓ (任何 ID 均可访问)
[process sub-entry]
  ↑ parent_id             ↓ child_entry_ids
[pitfall root]  ←→  [process sub-entry]

list_entries() 默认行为:
  - pitfall root    → 显示（无 parent_id）
  - process 无 parent_id → 显示（顶层 process）
  - process 有 parent_id → 隐藏（sub-entry，默认过滤）

list_entries(exclude_sub_entries=False):
  - 所有类型均显示
```
