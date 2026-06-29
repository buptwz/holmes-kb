# MCP Tool Contracts: M9

## 删除: kb_submit

从 `server.py` 和 `tools.py` 完全移除，无向后兼容。

---

## 新增: kb_draft

**签名**: `kb_draft(content: str, title: str | None = None, session_id: str | None = None) -> dict`

**成功返回**:
```json
{
  "saved": "_drafts/<filename>.md",
  "next_step": "holmes import _drafts/<filename>.md"
}
```

**错误返回（username 未配置）**:
```json
{
  "error": "config.username not set, run: holmes config set username <name>"
}
```

**行为**:
1. 检查 `config.username`，未配置返回 error（不写文件）
2. 生成文件名：`title` 有值则 `<title>.md`，否则 `<YYYY-MM-DD-HHMMSS>.md`
3. title 安全处理：过滤 `/`、`\`、`..`（替换为 `_`）
4. 创建 `_drafts/` 目录（若不存在）
5. atomic_write：frontmatter `author/saved_at/source` + body `content`
6. 写日志：`write_span(stem, "mcp.draft", "INFO", "draft saved", file=..., session=session_id or "")`
7. 返回 saved + next_step

---

## 更新: kb_overview

**日志新增**:
```python
_logger.write_span(f"session-{session_id}", "mcp.kb_overview", "INFO", "ok")
```

**hint 字段更新**（移除 kb_submit 引用，改为 kb_draft）:
```
Save session_id='<id>' — pass it to kb_confirm. Use kb_draft to save notes for later import.
```

---

## 更新: kb_list

**日志新增**:
```python
_logger.write_span(session_id or "session-unknown", "mcp.kb_list", "INFO", "ok", type=type, total=total)
```

注：kb_list 无 session_id 参数，session_id 由 server.py 传入（或记录为 "session-unknown"）。

---

## 更新: kb_search

**日志新增**:
```python
_logger.write_span(session_id or "session-unknown", "mcp.kb_search", "INFO", "ok", query=query, results=len(items))
```

---

## 更新: kb_read

**日志新增**:
```python
_logger.write_span(session_id or "session-unknown", "mcp.kb_read", "INFO", "ok", entry_id=entry_id)
```

**children 字段**：M1 已在 `_read_entry` 中实现，`handle_kb_read` 直接透传，无需修改逻辑。

---

## 更新: kb_confirm

**日志新增**:
```python
_logger.write_span(session_id, "mcp.kb_confirm", "INFO", "ok", entry_id=entry_id, promoted=result.get("promoted", False))
```
