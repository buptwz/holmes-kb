# IPC 协议规范：TUI ↔ Python Agent

**版本**：1.0 | **日期**：2026-05-26

---

## 概述

TUI（TypeScript）与 Python Agent 通过 **JSON-RPC 2.0 over Unix domain socket** 通信。

- Socket 路径：`/tmp/holmes-agent-{pid}.sock`（由 TUI 启动 agent 子进程时传入）
- 编码：UTF-8，换行符 `\n` 分隔消息帧
- TUI 为客户端，Python Agent 为服务端

---

## 方法一览

| 方法名 | 方向 | 说明 |
|--------|------|------|
| `session.create` | TUI → Agent | 创建新会话 |
| `session.resume` | TUI → Agent | 恢复历史会话 |
| `session.list` | TUI → Agent | 获取历史会话列表 |
| `session.get` | TUI → Agent | 获取单个会话完整记录 |
| `session.resolve` | TUI → Agent | 标记会话为已解决，触发知识提取 |
| `chat.send` | TUI → Agent | 发送用户消息（流式响应） |
| `kb.list` | TUI → Agent | 获取知识库条目列表 |
| `kb.get` | TUI → Agent | 获取单个知识条目内容 |
| `agent/token` | Agent → TUI | 流式 token 推送（通知） |
| `agent/done` | Agent → TUI | 本轮响应完成（通知） |
| `agent/error` | Agent → TUI | 错误通知 |

---

## 方法详情

### `session.create`

创建新的排查会话。

**请求 params**：
```json
{}
```

**响应 result**：
```json
{
  "session_id": "sess-20260526-143022",
  "created_at": "2026-05-26T14:30:22Z"
}
```

---

### `session.resume`

恢复指定的历史会话。

**请求 params**：
```json
{
  "session_id": "sess-20260526-143022"
}
```

**响应 result**：
```json
{
  "session_id": "sess-20260526-143022",
  "title": "Redis 连接池耗尽排查",
  "status": "active",
  "message_count": 6
}
```

---

### `session.list`

获取历史会话列表，按更新时间倒序。

**请求 params**：
```json
{
  "limit": 20,
  "offset": 0
}
```

**响应 result**：
```json
{
  "sessions": [
    {
      "session_id": "sess-20260526-143022",
      "title": "Redis 连接池耗尽排查",
      "status": "resolved",
      "created_at": "2026-05-26T14:30:22Z",
      "updated_at": "2026-05-26T14:45:11Z",
      "message_count": 12
    }
  ],
  "total": 42
}
```

---

### `session.get`

获取单个会话的完整消息记录。

**请求 params**：
```json
{
  "session_id": "sess-20260526-143022"
}
```

**响应 result**：
```json
{
  "session_id": "sess-20260526-143022",
  "title": "Redis 连接池耗尽排查",
  "status": "resolved",
  "created_at": "2026-05-26T14:30:22Z",
  "messages": [
    {
      "role": "user",
      "content": "Redis 连接报错...",
      "timestamp": "2026-05-26T14:30:25Z"
    },
    {
      "role": "assistant",
      "content": "让我们逐步排查...",
      "timestamp": "2026-05-26T14:30:28Z",
      "kb_refs": ["PT-DB-001"]
    }
  ]
}
```

---

### `session.resolve`

用户标记当前会话为已成功解决，触发自动知识提取和保存。

**请求 params**：
```json
{
  "session_id": "sess-20260526-143022"
}
```

**响应 result**：
```json
{
  "session_id": "sess-20260526-143022",
  "kb_entry_id": "PT-DB-003",
  "kb_entry_path": "pitfall/database/redis-connection-pool-exhausted.md",
  "summary_preview": "Redis 连接池耗尽问题：根因为连接未及时释放，解决方案为..."
}
```

**错误**：
- `-32001`: 会话不存在
- `-32002`: 会话已解决（重复操作）
- `-32003`: 知识提取失败（LLM 错误）

---

### `chat.send`

向当前会话发送用户消息，响应通过流式通知推送。

**请求 params**：
```json
{
  "session_id": "sess-20260526-143022",
  "content": "Redis 连接一直报 max clients reached 错误",
  "request_id": "req-uuid-1234"
}
```

**响应 result**（立即返回，表示已接收）：
```json
{
  "accepted": true,
  "request_id": "req-uuid-1234"
}
```

**后续流式通知**（服务端主动推送，无 id）：

```json
// token 推送
{
  "jsonrpc": "2.0",
  "method": "agent/token",
  "params": {
    "request_id": "req-uuid-1234",
    "token": "这通常是",
    "accumulated": "这通常是连接池耗尽"
  }
}

// 完成
{
  "jsonrpc": "2.0",
  "method": "agent/done",
  "params": {
    "request_id": "req-uuid-1234",
    "full_content": "这通常是连接池耗尽导致的，让我们逐步排查...",
    "kb_refs": ["PT-DB-001"],
    "session_title": "Redis 连接池耗尽排查"
  }
}
```

---

### `kb.list`

获取知识库条目列表，支持按分类/关键词过滤。

**请求 params**：
```json
{
  "type": "pitfall",
  "category": "database",
  "query": "redis",
  "limit": 20,
  "offset": 0
}
```

**响应 result**：
```json
{
  "entries": [
    {
      "id": "PT-DB-001",
      "title": "Redis 连接超时排查",
      "type": "pitfall",
      "tags": ["redis", "timeout", "database"],
      "updated": "2026-05-26"
    }
  ],
  "total": 5
}
```

---

### `kb.get`

获取单个知识条目的完整内容。

**请求 params**：
```json
{
  "entry_id": "PT-DB-001"
}
```

**响应 result**：
```json
{
  "id": "PT-DB-001",
  "title": "Redis 连接超时排查",
  "type": "pitfall",
  "tags": ["redis", "timeout"],
  "created": "2026-05-20",
  "updated": "2026-05-26",
  "content": "## 问题描述\n\n..."
}
```

---

## 错误码

| 错误码 | 含义 |
|--------|------|
| `-32700` | 解析错误（JSON 无效） |
| `-32600` | 无效请求 |
| `-32601` | 方法不存在 |
| `-32602` | 参数无效 |
| `-32001` | 会话不存在 |
| `-32002` | 操作重复（如重复解决） |
| `-32003` | LLM 调用失败 |
| `-32004` | 知识库不可用 |
| `-32005` | 配置错误 |
