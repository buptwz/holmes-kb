# Research: 修复 Holmes KB 核心工作流缺陷

**Branch**: `005-fix-kb-workflow-bugs` | **Phase**: 0 — Research

## 决策 1：write_pending() maturity 字段默认值

**Decision**: 在 `write_pending()` 中使用 `post.metadata.setdefault("maturity", "draft")`，在解析内容之后、写文件之前注入。

**Rationale**:
- 使用 `setdefault` 而非强制赋值，保证调用方若已明确传入 `maturity`（如 `maturity: verified`）不会被覆盖。
- `importer.py` 通过 LLM Prompt 显式指定 `maturity: draft`，该路径行为不变；`write_pending()` 兜底确保 Agent 路径也一致。
- 修复位置：`pending.py` 第 62 行 `post = frontmatter.loads(content)` 之后。

**Alternatives considered**:
- 在 Gate 1（`validate_schema`）之前自动注入：过于靠后，会让 Agent 写入的数据在中间状态不完整。
- 在 `KbExtractAndSave` TypeScript 工具层注入：违反单一职责原则，Python 层应自我完整。

---

## 决策 2：detect_commands() 多行文本支持

**Decision**: 在 `detect_commands()` 中增加 triple-backtick 代码块预提取步骤，将代码块内的非注释非空行作为额外候选命令送入现有逻辑。

**Rationale**:
- 当前 `CMD_PATTERN` 对多行文本的第三分支（`^PREFIX_TOOLS`）依赖行首工具名，但代码块内命令通常有 `$ ` 前缀或直接是命令行，会被第一/第三分支匹配。
- 真正的盲区是：代码块中不以已知工具名开头且无 `$` 前缀的命令（如 `jstat`, `java`, `python` 等未列出的工具）。
- 最简有效方案：用正则提取所有 triple-backtick 块内容，逐行处理，长度 ≥5 且非注释行视为命令候选，直接加入结果（不走前缀过滤）。

**Code block extraction pattern**:
```python
_CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
```

每行预处理：去掉 `$ `、`# ` 等提示符前缀；跳过空行和 `#` 开头的注释行；最小长度 5 字符。

**Alternatives considered**:
- 扩展 `_CMD_PREFIXES` 列表：维护负担重，且仍无法覆盖用户自定义工具。
- 完全放弃前缀过滤改用启发式"命令形态"识别：误报率高，超出 bug fix 范围。

---

## 决策 3：Gate 2 跳过修正提案

**Decision**: 在 `kb_confirm()` 中，解析 pending 内容后立即检查 `corrects` 字段；若存在则跳过 `check_duplicate()` 调用，直接输出 `✓ Skipped (correction proposal)`。

**Rationale**:
- 修正提案的标题与被修正条目高度相似（通常 >85% Jaccard 相似度）是预期行为而非异常。
- 现有 Gate 2 逻辑无条件运行，与 `corrects` 字段语义冲突。
- 跳过而非降低阈值：修正提案的身份由 `corrects` 字段决定，而非相似度。

**Implementation note**: `post = fm.loads(raw)` 需要在 Gate 2 之前执行（当前在 Gate 3 之后），或做一次提前的轻量解析。推荐将 `post` 解析提前到 Gate 1 之后。

---

## 决策 4：confirm 后清理 pending 内部字段

**Decision**: 在 `kb_confirm()` 正式条目写入路径中，新增 pop 三个字段：`source`、`suggested_type`、`suggested_category`。

**Rationale**:
- 现有代码已 pop `pending`、`pending_since`、`source_session`，但遗漏了这三个同属 pending 状态元数据的字段。
- 这三个字段对正式条目无语义意义，且会污染 frontmatter 并可能干扰 lint 检查。

**Fields to remove on confirm**:
```
pending, pending_since, source, source_session, suggested_type, suggested_category
```

---

## 决策 5：read_entry() 大小写不敏感

**Decision**: 将 `store.py` 中 `read_entry()` 的 `meta.id == entry_id` 比较改为 `meta.id.upper() == entry_id.upper()`。

**Rationale**:
- KB entry ID 格式为全大写（`PT-DB-002`），工程师终端输入习惯用小写。
- 仅改查询逻辑，存储格式保持不变（条目仍以原始大写 ID 存储和展示）。
- 同样需要在 CLI `kb_show()` 的 JSON 输出中保持原始 ID。

**Alternatives considered**:
- 在 CLI 层 normalize 输入：不如在 store 层统一处理，减少重复。

---

## 决策 6：README 文档修复方向

**Decision**: 修改 README 以匹配现有实现，代码参数名保持不变。

**具体修改**:
| 原文档（错误） | 实际实现（正确） | 修改操作 |
|--------------|----------------|---------|
| `holmes kb resolve <id> --side A` | `holmes kb resolve <id> --keep A` | 更新文档 |
| `holmes kb lint --report report.json` | `holmes kb lint --report`（flag） | 更新文档 |
| `holmes kb skill list --entry PT-DB-001` | `holmes kb skill list PT-DB-001`（位置参数） | 更新文档 |
| `holmes session list` / `holmes session show` | 命令不存在 | 删除相关文档 |

**Rationale**: 现有代码设计合理，更改参数名会破坏已有用户脚本，文档修复风险最低。
