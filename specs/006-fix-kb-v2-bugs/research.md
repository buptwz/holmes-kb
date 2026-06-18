# Research: 修复 Holmes KB v2 报告缺陷

**Feature**: 006-fix-kb-v2-bugs | **Date**: 2026-06-06

---

## Decision 1: 纠错路径字段清理的位置

**Decision**: 在纠错路径的 `write_entry()` 之前、`del post.metadata["corrects"]` 之后统一清理，与普通路径保持代码对称。

**Rationale**: 纠错路径和普通路径均需要清理相同的 pending 内部字段集合。将清理逻辑提取为内联 for loop（不抽象为函数）保持简单性；`pop(..., None)` 对不存在字段静默跳过，保证向后兼容。

**Alternatives considered**:
- 提取为共享辅助函数：过度抽象，当前只有 2 处调用，内联更清晰
- 在 `write_pending()` 阶段不写入内部字段到 corrects 条目：需要改动数据模型，影响更大

---

## Decision 2: lint conflict_count 的过滤策略

**Decision**: 逐文件解析 JSON，只统计 `status == "pending_review"` 的记录，捕获所有异常静默跳过损坏文件。

**Rationale**: `contributions/conflicts/` 中已有明确的 `status` 字段区分冲突生命周期状态。逐文件解析是唯一准确方案；`try/except Exception: pass` 防止损坏文件中断统计，与 linter 其他容错逻辑一致。

**Alternatives considered**:
- 按文件名前缀区分已解决/未解决：不可靠，文件名格式不包含状态信息
- 添加独立的 "resolved" 子目录：需要修改 resolve 命令逻辑，影响范围过大

---

## Decision 3: skill run --json 退出码传播方案

**Decision**: 在 `--json` 分支末尾（`click.echo(json.dumps(output))` 之后）添加 `if result.exit_code != 0: sys.exit(result.exit_code)`，与非 JSON 分支的现有行为完全一致。

**Rationale**: 非 JSON 分支（`else` 块）已有 `if result.exit_code != 0: sys.exit(result.exit_code)`，两者应对称。在打印 JSON 输出后再 exit，保证 JSON 内容始终完整输出（即使 exit_code != 0），调用方既能解析 JSON 又能检查 `$?`。

**Alternatives considered**:
- 始终 exit 0（保持现状）：不修复 bug，Agent 无法通过 `$?` 判断结果
- 始终传播（无论 `--json`）：这正是我们的方案
- 添加 `--propagate-exit-code` 标志：不必要的复杂化，统一行为更好

---

## Decision 4: SQL 关键字过滤的范围和实现

**Decision**: 在 `_extract_code_block_lines()` 中添加大小写不敏感的 SQL 关键字黑名单过滤，作用于代码块提取路径；`CMD_PATTERN` 路径不变（其要求 `$` 前缀或已知 CLI 工具名，SQL 本身不满足这些条件）。

**SQL 关键字黑名单**: `{select, show, insert, update, delete, drop, create, alter, truncate, replace, describe, explain}` — 12 个关键字，覆盖 DML + DDL + 查询类语句。

**Rationale**: `_extract_code_block_lines()` 是代码块提取的入口，所有从代码块识别出的命令都经过这里。在入口处过滤 SQL 比在调用方过滤更符合单一职责。使用 `frozenset` 实现 O(1) 查找。

**Alternatives considered**:
- 在 `detect_commands()` 出口过滤：逻辑分散，不如在入口处集中处理
- 基于正则匹配 SQL 语法：过于复杂，关键字黑名单足够精确
- 仅过滤 SHOW/DESCRIBE：覆盖不全，DML 语句也可能出现在代码块中
