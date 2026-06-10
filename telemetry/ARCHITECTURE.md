# 架构说明

## 整体数据流

```
贡献者机器                              中心服务器
┌──────────────────────────────────┐   ┌─────────────────────────────────────┐
│  CLI 命令执行                     │   │                                     │
│  (confirm / reject / write ...)  │   │  OTel Collector (:4318)             │
│            │                     │   │    receivers: otlp/http             │
│            ▼                     │   │    ┌──────────────────────────────┐ │
│  emit_event()                    │   │    │ processors: batch (5s/512条) │ │
│  · 同步写入本地 JSONL buffer     │   │    └──────────┬───────────────────┘ │
│  · 检查缓冲区大小，超限则裁剪     │   │               │                     │
│  · fork 子进程异步 flush          │   │        ┌──────┴──────┐             │
│            │                     │   │        ▼             ▼             │
│  ~/.holmes/telemetry.jsonl       │   │    Loki             count          │
│  ~/.holmes/telemetry.offset  ─── ┼───┼──▶ (原始日志)      connector      │
│  ~/.holmes/telemetry.sent_ids    │   │    (:3100)               │         │
│  ~/.holmes/telemetry.last_flush  │   │        │                 ▼         │
└──────────────────────────────────┘   │        │          Prometheus       │
                                        │        │          (:9090)          │
                                        │        └──────────────┐           │
                                        │                       ▼           │
                                        │              Grafana (:3000)      │
                                        │              Holmes KB Governance │
                                        └─────────────────────────────────────┘
```

---

## 组件职责

### 本地缓冲层（贡献者机器）

**文件清单：**

| 文件 | 职责 |
|------|------|
| `telemetry.jsonl` | append-only 事件缓冲，每行一条 KBEvent JSON |
| `telemetry.offset` | 已成功上报的字节偏移量，实现断点续传 |
| `telemetry.sent_ids` | 已发送的 event_id 集合（最多 50000 条），防止重复发送 |
| `telemetry.last_flush` | 上次成功 flush 的 Unix 时间戳，实现冷却控制 |
| `telemetry.lock` | `fcntl.flock` 互斥锁，防止裁剪时并发写入 |

**关键设计决策：**

- **同步写缓冲，异步刷新**：`emit_event()` 直接 append 到 JSONL（毫秒级），通过 `os.fork()` + `os.execv()` 启动独立进程刷新，CLI 进程立即返回，不等待网络
- **5 分钟冷却**：通过 `telemetry.last_flush` 控制刷新频率，避免每条命令都触发进程 fork
- **at-least-once + 去重**：offset 文件保证断网时不丢失数据；`sent_ids` 文件防止重传导致的重复计数
- **缓冲溢出保护**：超过 `max_buffer_bytes` 时，后台线程裁剪最旧的行，并写入 `kb.buffer_overflow` 哨兵事件

### 遥测核心（`kb/holmes/kb/telemetry.py`）

```
emit_event(event_type, contributor, ...)
    │
    ├─ load_telemetry_config()          # 读 HolmesConfig + 环境变量覆盖
    ├─ is_event_enabled(event_type)     # 事件白名单过滤
    ├─ get_contributor_identity()       # 读 config.contributor，fallback 到 hostname
    ├─ KBEvent.model_dump_json()        # Pydantic 序列化为 JSON 行
    ├─ append to telemetry.jsonl        # 同步写文件
    └─ if buffer > max_bytes:
           threading.Thread(_trim_buffer)   # 非阻塞后台裁剪

trigger_flush_async()
    ├─ check telemetry.last_flush       # 5 分钟冷却
    ├─ check buffer size > offset       # 有数据才 fork
    └─ os.fork() + os.execv(           # 独立进程，不依赖父进程存活
           telemetry_forwarder --once)
```

### 转发器（`kb/holmes/kb/telemetry_forwarder.py`）

独立运行的 Python 模块，生命周期：启动 → 读 pending 数据 → 发送 → 更新状态文件 → 退出。

```
flush_once()
    │
    ├─ _read_pending_lines(buf, offset)     # 从 offset 读未发数据
    ├─ filter by sent_ids                   # 去掉已发的
    ├─ for batch in chunks(new_events, 500):
    │       payload = _build_otlp_payload(batch)
    │       status = _post_batch(endpoint, payload)
    │       · 200 → 记录 sent_ids
    │       · 429/5xx → 指数退避重试（1s/2s/4s，最多 3 次）
    │       · 400 → 跳过该批次（bad payload）
    │       · 其他 → 停止处理
    │
    ├─ _save_sent_ids(...)                  # 持久化已发 ID
    └─ _write_offset(end_offset)            # 仅全部成功才推进 offset
```

### OTel Collector（容器）

接收 OTLP/HTTP → 双路转发：

- **Loki exporter**：将每条 log record 原样推送到 Loki，log body 为完整 KBEvent JSON。stream label 为 `job=holmes-kb-cli`
- **count connector**：按 `event_type` × `contributor` 聚合计数，转为 Prometheus 指标 `holmes_kb_holmes_kb_events_total`

---

## OTLP 负载格式

转发器构造标准 OTLP/HTTP JSON，每个 KBEvent 对应一条 log record：

```json
{
  "resourceLogs": [{
    "resource": {
      "attributes": [
        {"key": "service.name", "value": {"stringValue": "holmes-kb-cli"}},
        {"key": "holmes.version", "value": {"stringValue": "0.1.0"}}
      ]
    },
    "scopeLogs": [{
      "logRecords": [{
        "timeUnixNano": "1717430400000000000",
        "severityText": "INFO",
        "body": {"stringValue": "<KBEvent JSON string>"},
        "attributes": [
          {"key": "event_id",    "value": {"stringValue": "uuid"}},
          {"key": "event_type",  "value": {"stringValue": "kb.confirm"}},
          {"key": "contributor", "value": {"stringValue": "alice"}},
          {"key": "entry_id",    "value": {"stringValue": "PT-DB-003"}}
        ]
      }]
    }]
  }]
}
```

---

## Grafana 数据查询

Loki 存储的日志行格式为 `{"body": "<KBEvent JSON>", ...}`，需要两步解析：

```logql
{job="holmes-kb-cli"}
| json                          -- 解析外层，得到 body 字段
| line_format "{{.body}}"       -- 用 body 替换当前行
| json                          -- 解析 KBEvent JSON
| line_format "[{{.event_type}}] {{.contributor}}"
```

Prometheus 指标名：`holmes_kb_holmes_kb_events_total`，labels：`event_type`、`contributor`、`service_name`、`holmes_version`。

---

## 安全考虑

- **不采集敏感内容**：事件只记录操作元数据（entry ID、贡献者标识），不记录 KB 条目正文
- **contributor 标识符**：由贡献者自己配置，不绑定任何账号系统，可以是匿名 ID
- **本地缓冲**：数据先落本地文件再上报，不在内存中暂留
- **网络传输**：默认 HTTP；生产环境建议在服务器前加 nginx/反向代理，启用 TLS
