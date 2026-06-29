# Data Model: M9 — MCP 接口重构

## Draft 文件

**路径**: `<kb_root>/_drafts/<title>.md`

**Frontmatter 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `author` | string | `config.username` |
| `saved_at` | ISO 8601 string | UTC 时间戳，如 `2026-06-23T10:06:00+00:00` |
| `source` | string | 固定值 `mcp.draft` |

**Body**: agent 提供的原始自然语言内容，不做任何 LLM 处理。

**示例**:
```markdown
---
author: wangzhi
saved_at: 2026-06-23T10:06:00+00:00
source: mcp.draft
---

## 症状
Redis OOM 错误频繁出现...

## 根因
maxmemory 未配置...

## 解决
设置 maxmemory-policy allkeys-lru...
```

---

## _drafts/ 目录布局

```text
_drafts/
├── redis-oom-2026-06-23.md          # 待 import 草稿
├── nginx-timeout-2026-06-20.md      # 待 import 草稿
└── _imported/
    ├── postgres-deadlock-2026-06-01.md  # 已 import 归档
    └── ...
```

---

## Session Trace 日志记录

**MCP 读操作 span 名称**:

| 工具 | span | trace_id | 关键 extra 字段 |
|------|------|----------|----------------|
| `kb_overview` | `mcp.kb_overview` | `session-<id>` | — |
| `kb_list` | `mcp.kb_list` | `session-<id>` | `type`, `total` |
| `kb_search` | `mcp.kb_search` | `session-<id>` | `query`, `results` |
| `kb_read` | `mcp.kb_read` | `session-<id>` | `entry_id` |
| `kb_confirm` | `mcp.kb_confirm` | `session-<id>` | `entry_id`, `promoted` |
| `kb_draft` | `mcp.draft` | `<filename_stem>` | `file`, `session` |

---

## 状态转换：Draft 生命周期

```
[created]  _drafts/<name>.md
    │
    │  holmes import _drafts/<name>.md (非 dry-run, 成功)
    ▼
[archived] _drafts/_imported/<name>.md
```
