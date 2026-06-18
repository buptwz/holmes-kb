# Data Model: 修复 Holmes KB v2 报告缺陷

**Feature**: 006-fix-kb-v2-bugs | **Date**: 2026-06-06

---

## 1. Pending 内部字段生命周期（Fix 1 相关）

### PendingEntry 内部字段集合

这些字段仅在 pending 生命周期存在，进入正式 KB 必须清除：

| 字段 | 类型 | 写入时机 | 应清除的路径 |
|------|------|----------|-------------|
| `pending` | bool | `write_pending()` | 普通路径 ✅（已有）/ 纠错路径 ❌（缺失 → 本次修复）|
| `pending_since` | ISO datetime | `write_pending()` | 同上 |
| `source` | str | `write_pending()` | 同上 |
| `source_session` | str | `write_pending()` | 同上 |
| `suggested_type` | str | `write_pending()` | 同上 |
| `suggested_category` | str | `write_pending()` | 同上 |
| `corrects` | str (entry_id) | `write_pending()` | 纠错路径（`del post.metadata["corrects"]` 已有）|

### confirm 路径字段处理对比（修复前 vs 修复后）

```
普通路径（已正确）:
  pop("pending")         ✅
  pop("pending_since")   ✅
  pop("source_session")  ✅
  pop("source")          ✅
  pop("suggested_type")  ✅
  pop("suggested_category") ✅

纠错路径（修复前）:
  del corrects           ✅
  [其他字段残留]         ❌

纠错路径（修复后）:
  del corrects           ✅
  pop("pending")         ✅ NEW
  pop("pending_since")   ✅ NEW
  pop("source_session")  ✅ NEW
  pop("source")          ✅ NEW
  pop("suggested_type")  ✅ NEW
  pop("suggested_category") ✅ NEW
```

---

## 2. ConflictRecord（Fix 2 相关）

### ConflictRecord 结构

文件路径：`contributions/conflicts/<conflict-id>.json`

| 字段 | 类型 | 说明 |
|------|------|------|
| `conflict_id` | str | 唯一标识 |
| `status` | str | `"pending_review"` | `"resolved"` | 其他 |
| `entry_id` | str | 发生冲突的条目 ID |
| `local_content` | str | 本地版本内容 |
| `remote_content` | str | 远端版本内容 |
| `created_at` | ISO datetime | 冲突创建时间 |
| `resolved_at` | ISO datetime (optional) | 解决时间 |
| `resolution` | str (optional) | `"A"` | `"B"` | `"manual"` |

### conflict_count 计算规则（修复后）

```
conflict_count = count of ConflictRecord where status == "pending_review"
```

---

## 3. CommandCandidate（Fix 4 相关）

### CommandCandidate 结构

`detect_commands()` 的返回值：

| 字段 | 类型 | 说明 |
|------|------|------|
| `line` | str | 命令行文本（已去除 `$ `/`` ` ``/`> ` 前缀）|
| `suggested_name` | str | 基于前 3 个 token 生成的 slug |

### SQL 关键字黑名单（Fix 4 新增）

过滤规则：`first_word = line.split()[0].lower()` 如果在黑名单中则丢弃该行。

```python
_SQL_KEYWORDS = frozenset({
    "select", "show", "insert", "update", "delete",
    "drop", "create", "alter", "truncate", "replace",
    "describe", "explain",
})
```

适用范围：仅 `_extract_code_block_lines()`（代码块路径），不影响 `CMD_PATTERN` 路径。
