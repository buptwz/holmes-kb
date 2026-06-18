# Implementation Plan: 修复 Holmes KB v2 报告缺陷

**Branch**: `006-fix-kb-v2-bugs` | **Date**: 2026-06-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-fix-kb-v2-bugs/spec.md`

---

## Summary

修复 v2 使用报告中发现的 4 个缺陷：
1. **BUG-NEW-1** (P1): 纠错路径 `confirm` 不清除 pending 内部字段 → 在纠错路径写入条目前补充字段清理逻辑
2. **BUG-NEW-2** (P2): `lint` 的 `conflict_count` 含已解决冲突 → 过滤 `status != "pending_review"` 的冲突文件
3. **BUG-NEW-3** (P2): `skill run --json` 模式始终退出 0 → 输出 JSON 后传播实际 exit code
4. **BUG-NEW-4** (P3): `detect_commands` 不过滤 SQL 关键字 → 在代码块提取路径中添加 SQL 黑名单过滤

每个修复均有对应自动化测试。

---

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: Click 8.x, python-frontmatter, pytest（均为已有依赖）

**Storage**: 文件系统（Markdown + JSON），无数据库

**Testing**: pytest（`kb/tests/`）

**Target Platform**: Linux CLI（`holmes kb ...` 命令）

**Project Type**: CLI tool / Python package

**Performance Goals**: N/A（bug fix，无性能目标变化）

**Constraints**: 修复不引入新依赖；保持现有 280 个测试全通过

**Scale/Scope**: 4 个文件（`cli.py`, `linter.py`, `skill/manager.py`, `tests/`）

---

## Constitution Check

| 原则 | 状态 | 说明 |
|------|------|------|
| 开闭原则 | ✅ | 均为现有函数内部修复，不新增模块 |
| 单一职责原则 | ✅ | 每处修复职责明确，不引入跨模块副作用 |
| 验证原则 | ✅ | 每个修复点至少 2 个自动化测试 |
| 渐进式实现原则 | ✅ | 最小修改，无抽象层设计 |
| 代码规范 | ✅ | 遵循 Google Python style，max-line-length=100 |
| 质量标准 | ✅ | 修复后 280 个原有测试继续通过 |

**结论**：无 Constitution 违规，可直接进入实现。

---

## Fix Specifications

### Fix 1 — BUG-NEW-1: 纠错路径字段清理

**文件**: `kb/holmes/cli.py`

**位置**: `kb_confirm()` 函数的纠错路径（`if corrects_id:` 块），`del post.metadata["corrects"]` 之后、`write_entry()` 之前

**修改内容**: 添加与普通路径相同的字段清理逻辑：
```python
for _f in ("pending", "pending_since", "source_session", "source",
           "suggested_type", "suggested_category"):
    post.metadata.pop(_f, None)
```

---

### Fix 2 — BUG-NEW-2: lint conflict_count 过滤

**文件**: `kb/holmes/kb/linter.py`

**位置**: `lint()` 函数中统计冲突数量的代码块（约 67-69 行）

**修改内容**: 将 `len(list(conflicts_dir.glob("*.json")))` 替换为逐文件解析 status 字段、只计 `status == "pending_review"` 的记录，损坏文件静默跳过：
```python
count = 0
for p in conflicts_dir.glob("*.json"):
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("status") == "pending_review":
            count += 1
    except Exception:
        pass
report.conflict_count = count
```

---

### Fix 3 — BUG-NEW-3: skill run --json 退出码

**文件**: `kb/holmes/cli.py`

**位置**: `skill_run()` 函数，`if as_json:` 分支末尾（`click.echo(json.dumps(output))` 之后）

**修改内容**: 在 `--json` 分支中补充 `sys.exit`：
```python
if result.exit_code != 0:
    sys.exit(result.exit_code)
```

---

### Fix 4 — BUG-NEW-4: detect_commands SQL 过滤

**文件**: `kb/holmes/kb/skill/manager.py`

**位置**: `_extract_code_block_lines()` 函数，已有的 `if len(line) >= 5 and not line.startswith("#"):` 条件之前

**修改内容**: 添加 SQL 关键字黑名单集合和过滤条件：
```python
_SQL_KEYWORDS = frozenset({
    "select", "show", "insert", "update", "delete", "drop",
    "create", "alter", "truncate", "replace", "describe", "explain",
})

# 在过滤条件中添加：
first_word = line.split()[0].lower() if line.split() else ""
if first_word in _SQL_KEYWORDS:
    continue
```

---

## Project Structure

### Documentation (this feature)

```text
specs/006-fix-kb-v2-bugs/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-contracts.md
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (affected files)

```text
kb/
├── holmes/
│   ├── cli.py                     # Fix 1 (correction path) + Fix 3 (skill run exit code)
│   └── kb/
│       ├── linter.py              # Fix 2 (conflict_count)
│       └── skill/
│           └── manager.py         # Fix 4 (SQL filtering)
└── tests/
    ├── test_integration.py        # Tests for Fix 1 (correction path clean)
    ├── test_linter.py             # Tests for Fix 2 (conflict count)
    ├── test_skill_manager.py      # Tests for Fix 4 (SQL filtering)
    └── test_skill_runner.py       # Tests for Fix 3 (exit code) — via CLI invoke
```

**Structure Decision**: Single Python package, all fixes in existing files. No new modules needed.

---

## Complexity Tracking

No Constitution violations — no complexity justification needed.
