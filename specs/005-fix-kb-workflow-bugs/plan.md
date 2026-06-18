# Implementation Plan: 修复 Holmes KB 核心工作流缺陷

**Branch**: `005-fix-kb-workflow-bugs` | **Date**: 2026-06-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-fix-kb-workflow-bugs/spec.md`

## Summary

修复 Holmes KB 六处确认的缺陷，恢复"Agent 自动提取知识 → 入库"的核心闭环，并修正 CLI 文档与实现的不一致。所有修改均为定点 bug fix，不引入新抽象或架构变更。

## Technical Context

**Language/Version**: Python 3.x

**Primary Dependencies**: click, python-frontmatter, pydantic, pytest

**Storage**: Markdown 文件 + YAML frontmatter（文件系统）

**Testing**: pytest（现有测试套件：`kb/tests/`）

**Target Platform**: Linux CLI tool

**Project Type**: CLI library (bug fix)

**Performance Goals**: detect_commands 文本解析 < 100ms（典型 KB 条目大小）

**Constraints**: 所有修复向后兼容；不改变任何 CLI 参数接口；存储格式不变

**Scale/Scope**: 6 个定点修复（5 个代码改动 + 1 个文档更新）

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | ✅ | 定点函数修复，不重构周边结构 |
| 单一职责原则 | ✅ | 每个函数职责不变，仅修正错误行为 |
| 依赖倒置原则 | ✅ | 无新依赖引入 |
| 验证原则 | ✅ | 每处修复配对测试用例 |
| 渐进式实现原则 | ✅ | 最小化改动，无过度抽象 |
| 可观测性原则 | ✅ | 无需新增日志（修复后行为符合预期） |
| 环境配置原则 | ✅ | 无硬编码 |

**无 Constitution 违规。**

## Project Structure

### Documentation (this feature)

```text
specs/005-fix-kb-workflow-bugs/
├── plan.md              # 本文件
├── research.md          # Phase 0 — 设计决策记录
├── data-model.md        # Phase 1 — 字段生命周期模型
├── quickstart.md        # Phase 1 — 验证指南
├── contracts/
│   └── cli-contracts.md # Phase 1 — CLI 接口变更说明
└── tasks.md             # Phase 2 输出（/speckit-tasks 生成）
```

### Source Code (repository root)

```text
kb/holmes/kb/
├── pending.py           # Fix 1: write_pending() + maturity setdefault
├── skill/
│   └── manager.py       # Fix 2: detect_commands() + 代码块提取
├── store.py             # Fix 5: read_entry() 大小写不敏感
└── (schema.py)          # 不变

kb/holmes/
└── cli.py               # Fix 3: kb_confirm() Gate 2 bypass for corrections
                         # Fix 4: kb_confirm() 清理残留 pending 字段

README.md                # Fix 6: 文档修正（4 处）

kb/tests/
├── test_pending.py      # 新增：maturity 自动注入测试
├── test_skill_manager.py # 新增：detect_commands 代码块测试
├── test_store.py        # 新增：大小写不敏感查询测试
└── test_integration.py  # 新增：完整写入→确认→入库闭环测试
```

**Structure Decision**: 单项目结构，所有修复在现有文件中定点修改，无新文件创建（测试文件扩展现有文件）。

## Fix Details

### Fix 1 — write_pending() 自动注入 maturity（pending.py）

**位置**: `pending.py` L62，`post = frontmatter.loads(content)` 之后

**改动**:
```python
# 在 frontmatter.loads 之后添加一行
post.metadata.setdefault("maturity", "draft")
```

**验证**: Gate 1 通过率从 0% 提升到 100%（Agent 写入路径）

---

### Fix 2 — detect_commands() 支持代码块（skill/manager.py）

**位置**: `manager.py`，在 `CMD_PATTERN` 定义后添加辅助正则，修改 `detect_commands()` 函数

**改动摘要**:
```python
_CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)

def _extract_code_block_lines(text: str) -> list[str]:
    lines = []
    for m in _CODE_BLOCK_RE.finditer(text):
        for line in m.group(1).splitlines():
            line = line.strip()
            for prefix in ("$ ", "# ", "> "):
                if line.startswith(prefix):
                    line = line[len(prefix):]
                    break
            if len(line) >= 5 and not line.startswith("#"):
                lines.append(line)
    return lines

# detect_commands() 中：先提取代码块行，加入候选池，再运行 CMD_PATTERN
```

**验证**: 传入含代码块的 Resolution 文本，返回非空命令列表

---

### Fix 3 — Gate 2 跳过修正提案（cli.py kb_confirm）

**位置**: `cli.py`，`kb_confirm()` 函数，Gate 2 之前

**改动摘要**:
- 将 `post = fm.loads(raw)` 移至 Gate 1 之后（提前解析）
- Gate 2 前检查 `post.metadata.get("corrects")`
- 若 corrects 存在，跳过 `check_duplicate()` 并输出 `✓ Skipped (correction proposal)`

---

### Fix 4 — 清理 pending 内部字段（cli.py kb_confirm）

**位置**: `cli.py`，`kb_confirm()` 正常确认路径，现有 pop 语句之后

**改动**:
```python
post.metadata.pop("source", None)
post.metadata.pop("suggested_type", None)
post.metadata.pop("suggested_category", None)
```

---

### Fix 5 — read_entry() 大小写不敏感（store.py）

**位置**: `store.py`，`read_entry()` 函数

**改动**:
```python
# 修改前
if meta.id == entry_id:
# 修改后
if meta.id.upper() == entry_id.upper():
```

---

### Fix 6 — README 文档修正

**位置**: `README.md`（需在实施时定位具体行）

**改动**:
- `--side A|B` → `--keep A|B`（resolve 命令）
- `lint --report report.json` → `lint --report`（flag，输出 JSON 到 stdout）
- `skill list --entry PT-DB-001` → `skill list PT-DB-001`（位置参数）
- 删除 `session list` 和 `session show` 相关文档段落
