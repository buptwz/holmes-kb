# Data Model: 修复 Holmes KB 核心工作流缺陷

**Branch**: `005-fix-kb-workflow-bugs` | **Phase**: 1 — Design

---

## Pending Entry 字段生命周期（修复后）

### write_pending() 写入字段（来自调用方内容 + 自动注入）

| 字段 | 来源 | 状态 | 备注 |
|------|------|------|------|
| `id` | 自动生成 | 必须 | `pending-YYYYMMDD-HHMMSS-xxxx` |
| `type` | 调用方传入 | 必须 | 写入后存于 `suggested_type` |
| `title` | 调用方传入 | 必须 | |
| `maturity` | `setdefault("maturity", "draft")` | 必须 | **新增**：调用方未传时自动注入 `draft` |
| `category` | 调用方传入 | 可选 | 写入后存于 `suggested_category` |
| `tags` | 调用方传入 | 可选 | |
| `created_at` | 自动生成 | 必须 | ISO8601 |
| `updated_at` | 自动生成 | 必须 | ISO8601 |
| `pending` | 自动注入 | pending 专用 | `true` |
| `pending_since` | 自动注入 | pending 专用 | ISO8601 |
| `source` | 参数传入 | pending 专用 | `"auto"` 或 `"agent"` |
| `source_session` | 参数传入 | pending 专用 | 调用方 session ID |
| `suggested_type` | 自动注入 | pending 专用 | 来自 `type` 字段 |
| `suggested_category` | 自动注入 | pending 专用 | 来自 `category` 字段 |
| `corrects` | 可选传入 | pending 专用 | 修正提案目标 entry ID |

### confirm() 确认后正式条目字段（修复后）

| 字段 | 状态 | 备注 |
|------|------|------|
| `id` | 必须 | 生成永久 ID（如 `PT-DB-003`） |
| `type` | 必须 | 来自 pending 的 `type` 或 CLI override |
| `title` | 必须 | |
| `maturity` | 必须 | 设为 `draft`（可通过 update-refs 升级） |
| `category` | 必须 | |
| `tags` | 必须 | |
| `created_at` | 必须 | 保留原 pending 时间戳 |
| `updated_at` | 必须 | 更新为确认时间 |
| `evidence` | 必须 | 初始化为 `[]`，确认动作本身追加第一条 |
| `contributors` | 必须 | 初始化为 `[]` |
| ~~`pending`~~ | **删除** | **修复**：原代码已 pop，保持不变 |
| ~~`pending_since`~~ | **删除** | **修复**：原代码已 pop，保持不变 |
| ~~`source`~~ | **删除** | **修复新增**：原代码遗漏，本次 pop |
| ~~`source_session`~~ | **删除** | **修复**：原代码已 pop，保持不变 |
| ~~`suggested_type`~~ | **删除** | **修复新增**：原代码遗漏，本次 pop |
| ~~`suggested_category`~~ | **删除** | **修复新增**：原代码遗漏，本次 pop |

---

## detect_commands() 输入输出模型（修复后）

### 输入
- `resolution_text: str` — KB 条目的 Resolution 段落文本，可包含多段落、代码块、中文说明

### 处理逻辑（修复后）
```
1. 提取 triple-backtick 代码块内容（```lang\n...\n```）
   - 逐行处理：去掉 "$ " / "# " / "> " 前缀
   - 跳过空行和 "#" 开头的注释行
   - 长度 ≥ 5 字符的行视为命令候选

2. 对 resolution_text 全文运行 CMD_PATTERN（现有逻辑不变）
   - 匹配 "$ command"
   - 匹配 `backtick command`
   - 匹配行首已知工具名命令

3. 合并去重，返回 CommandCandidate 列表
```

### 输出
- `list[CommandCandidate]` — 每项含 `line`（命令行）和 `suggested_name`（建议 skill 名）

---

## 受影响文件清单

| 文件 | 变更性质 | 涉及函数 |
|------|---------|---------|
| `kb/holmes/kb/pending.py` | Bug fix | `write_pending()` |
| `kb/holmes/kb/skill/manager.py` | Bug fix + Enhancement | `detect_commands()` |
| `kb/holmes/kb/store.py` | Bug fix | `read_entry()` |
| `kb/holmes/cli.py` | Bug fix | `kb_confirm()` |
| `README.md` | Doc fix | — |
| `kb/tests/test_pending.py` | New tests | — |
| `kb/tests/test_skill_manager.py` | New tests | — |
| `kb/tests/test_store.py` | New tests | — |
| `kb/tests/test_integration.py` | New tests | — |
