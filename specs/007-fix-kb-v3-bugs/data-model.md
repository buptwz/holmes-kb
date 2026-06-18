# Data Model: 修复 Holmes KB v3 报告缺陷

本次修复不引入新实体，仅修正现有字段的处理逻辑。

## 受影响字段

### KB Entry（正式条目）

| 字段 | 类型 | 变更说明 |
|------|------|----------|
| `tags` | `List[Any]` → 搜索时转 `str` | US1: 允许数字类型 tag，搜索时 `str(t).lower()` |
| `created_at` | `str` (ISO 8601) | US3: 纠错 confirm 时从原始条目继承，不使用当前时间 |
| `contributors` | `List[str]` | US4: 纠错 confirm 时追加 `--contributor` 参数值，去重保序 |
| `maturity` | `str` (draft/verified/proven) | US7: confirm 后输出变更信息（无字段结构变化）|

### Pending Entry

| 字段 | 类型 | 变更说明 |
|------|------|----------|
| `id` | `str` | US6: 显示时若为空字符串，fallback 到文件名 stem |

### Import Result（内存对象）

| 字段 | 类型 | 变更说明 |
|------|------|----------|
| `content_preview` | `str` | US2: dry-run 时预览原始文件内容（非 LLM 输出） |
| `pending_id` | `str` | US2: dry-run 时保持 `"(dry-run)"`，不生成真实 ID |

## 字段约束

- `tags` 写入时不限制类型（YAML 原生类型保留），仅在搜索时做类型转换
- `contributors` 去重规则：大小写敏感的字符串相等性检查，使用 `dict.fromkeys()` 保持顺序
- `created_at` 在纠错路径中：若原始条目有此字段则继承，否则用当前时间（降级处理）
