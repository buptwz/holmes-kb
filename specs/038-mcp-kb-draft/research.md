# Research: M9 — MCP 接口重构

## 决策 1: kb_draft title 安全处理

**Decision**: 仅过滤路径分隔符（`/`、`\`、`..`），用 `_` 替换非法字符，保留用户提供的可读名称。不做 slug 化（保留中文、空格等）。

**Rationale**: brief.md 明确"agent 提供合法文件名"，工程师可读性优先。仅防路径穿越即可，不需要全量 slug。

**Alternatives considered**: 全量 slug（kebab-case）— 会破坏用户提供的精确文件名。

---

## 决策 2: atomic_write 位置

**Decision**: 使用 `holmes.kb.store` 中已有的 `atomic_write` 函数。

**Rationale**: 该函数已在 store.py 中实现并在现有 pipeline 中使用，无需重复实现。

**Alternatives considered**: 直接 `Path.write_text()` — 非原子写入，进程中断可能留下半写文件。

---

## 决策 3: session_id 在日志中的传递

**Decision**: MCP 工具（`kb_search`/`kb_read`/`kb_confirm`）的日志中 session_id 由调用方传入（server.py 层面通过参数传递），`kb_draft` 额外接收可选 `session_id` 参数用于日志的 `session` 字段。

**Rationale**: brief.md 中 `kb_draft` 日志示例含 `"session":"session-a3f1"` 字段，说明 `kb_draft` 知道当前 session。agent 在调用 `kb_draft` 时已有 `session_id`（来自 `kb_overview` 响应），可作为可选参数传入。

**Alternatives considered**: 全局 session 状态 — 违反单一职责，MCP 是无状态协议，不适合全局状态。

---

## 决策 4: holmes import 草稿移动时机

**Decision**: 在 `import_cmd` 中，`runner.run()` 成功返回（无 errors、非 dry-run）后，检测源文件是否在 `_drafts/` 下，若是则调用 `shutil.move`。

**Rationale**: brief.md 明确 `--dry-run` 不触发移动；`runner.run()` 异常时不应移动（文件可能未成功 import）。

**Alternatives considered**: 在 runner 内部移动 — 违反单一职责，runner 不应知道 CLI 的文件布局。

---

## 决策 5: HolmesLogger 实例化位置

**Decision**: 在 `tools.py` 模块级别创建 `_logger` 实例（`~/.holmes/logs/` 目录），MCP 工具函数直接调用 `_logger.write_span(...)`。

**Rationale**: MCP server 生命周期内 logger 实例不变，模块级实例化简单直接，避免每次工具调用重复初始化。

**Alternatives considered**: 每次调用时初始化 — 多余开销，且无状态。通过参数注入 — 增加复杂度，而 MCP tools 是叶节点函数。
