# 用户手册

## 目录

- [管理员安装](#管理员安装)
- [贡献者配置](#贡献者配置)
- [日常使用](#日常使用)
- [事件类型参考](#事件类型参考)
- [仪表板操作](#仪表板操作)
- [自定义采集](#自定义采集)
- [故障排查](#故障排查)

---

## 管理员安装

### 前置条件

- Docker >= 20.10
- docker compose v2（`docker compose version` 验证）
- 服务器对外开放 **4318**（贡献者上报）和 **3000**（Grafana）端口

### 安装 Docker（Ubuntu）

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录或执行 newgrp docker
```

### 启动服务栈

```bash
cd telemetry/
docker compose up -d
docker compose ps   # 确认 4 个服务全部 Up
```

### 修改 Grafana 默认密码

```bash
docker exec -it holmes-grafana \
  grafana-cli admin reset-admin-password <新密码>
```

### 调整数据保留时长（默认 90 天）

编辑 `loki-config.yml`：

```yaml
limits_config:
  retention_period: 180d
```

编辑 `docker-compose.yml`，prometheus 服务的 command：

```yaml
- "--storage.tsdb.retention.time=180d"
```

然后 `docker compose up -d` 重启生效。

### 端口冲突处理

在 `docker-compose.yml` 里修改宿主机端口映射：

```yaml
grafana:
  ports:
    - "3001:3000"   # 宿主机用 3001，容器内仍是 3000
```

---

## 贡献者配置

### 基础配置

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --otel-endpoint http://<服务器IP>:4318 \
  --contributor <你的标识符>
```

`--contributor` 建议使用可辨识的英文标识，如 `alice`、`zhang-wei`，会显示在 Grafana 贡献者面板中。省略时自动使用机器主机名。

### 查看当前配置

```bash
cat ~/.holmes/config.json
```

关键字段：

```json
{
  "contributor": "alice",
  "telemetry_enabled": true,
  "otel_collector_endpoint": "http://192.168.1.100:4318",
  "telemetry_enabled_events": null
}
```

`telemetry_enabled_events` 为 `null` 表示采集全部事件类型。

### 关闭遥测

```bash
holmes setup --kb-path ~/holmes-kb --no-telemetry
```

### 不修改配置文件的临时覆盖

```bash
HOLMES_TELEMETRY_ENABLED=false holmes confirm pending-xxx
HOLMES_OTEL_ENDPOINT=http://other:4318 holmes confirm pending-xxx
HOLMES_TELEMETRY_EVENTS="kb.confirm,kb.reject" holmes confirm pending-xxx
```

---

## 日常使用

配置完成后**正常使用 CLI 即可**，不需要任何额外操作。

每条命令执行成功后，系统在后台 fork 一个子进程，将事件写入本地缓冲文件（`~/.holmes/telemetry.jsonl`），并在满足条件时（距上次刷新超过 5 分钟）自动上报到 OTel Collector。

**会产生遥测事件的命令：**

```bash
holmes write-pending    # → kb.write_pending
holmes confirm          # → kb.confirm 或 kb.correction_applied
holmes reject           # → kb.reject
holmes decay            # → kb.decay（每条降级的entry一个事件）+ kb.health_snapshot
holmes archive-orphans  # → kb.archive_orphan
holmes update-refs      # → kb.update_refs
holmes health-export    # → kb.health_snapshot
```

> ⚠️ `holmes health-export` 该命令尚未实现，telemetry 上报接线为待办项（spec 043 T044 挂起）。

### 手动立即刷新

默认后台每 5 分钟最多刷新一次。如需立即看到数据：

```bash
python -m holmes.kb.telemetry_forwarder --once
```

### 查看本地缓冲状态

```bash
# 待上报事件数
wc -l ~/.holmes/telemetry.jsonl

# 已上报进度
echo "offset: $(cat ~/.holmes/telemetry.offset 2>/dev/null || echo 0) bytes"
echo "buffer: $(wc -c < ~/.holmes/telemetry.jsonl) bytes"
```

---

## 事件类型参考

Holmes 采集 9 种事件类型，覆盖 KB 的完整生命周期：

### `kb.write_pending` — 提交待审条目

**触发**：`holmes write-pending`

| 字段 | 值 |
|------|-----|
| `contributor` | 提交者标识 |
| `entry_id` | pending ID，如 `pending-20260604-153000-ab1f` |
| `metadata.corrects` | 被修正的原条目 ID（仅修正提交时有值） |

---

### `kb.confirm` — 审核通过

**触发**：`holmes confirm`（非修正路径）

| 字段 | 值 |
|------|-----|
| `contributor` | 审核者标识 |
| `entry_id` | 新条目 ID，如 `PT-DB-a3f8c2` |
| `metadata.pending_id` | 对应的 pending ID |

---

### `kb.correction_applied` — 修正通过

**触发**：`holmes confirm`（`--corrects` 路径）或 `holmes write-pending --corrects`

| 字段 | 值 |
|------|-----|
| `contributor` | 审核者标识 |
| `entry_id` | 被修正的原条目 ID |
| `metadata.pending_id` | pending ID |
| `metadata.snapshot` | 历史快照文件名 |

---

### `kb.reject` — 拒绝待审条目

**触发**：`holmes reject`

| 字段 | 值 |
|------|-----|
| `entry_id` | pending ID |
| `metadata.reason` | 拒绝原因（可为 null） |

---

### `kb.decay` — 条目成熟度降级

**触发**：`holmes decay`（每条降级的 entry 产生一个事件）

| 字段 | 值 |
|------|-----|
| `entry_id` | 降级的条目 ID |
| `metadata.old_maturity` | 降级前成熟度，如 `proven` |
| `metadata.new_maturity` | 降级后成熟度，如 `verified` |
| `metadata.months_unreferenced` | 未被引用的月数 |

---

### `kb.archive_orphan` — 归档孤儿草稿

**触发**：`holmes archive-orphans`

| 字段 | 值 |
|------|-----|
| `entry_id` | 被归档的条目 ID |

---

### `kb.update_refs` — 更新引用记录

**触发**：`holmes update-refs`（通常在 session 结束时由 agent 调用）

| 字段 | 值 |
|------|-----|
| `contributor` | 贡献者标识 |
| `session_id` | session 唯一标识 |
| `metadata.entry_ids` | 本次 session 引用的条目 ID 列表 |
| `metadata.updated_count` | 成功更新的条目数 |
| `metadata.promoted_count` | 因此次引用触发成熟度晋升的条目数 |

---

### `kb.health_snapshot` — KB 状态快照

**触发**：`holmes health-export`，或每次 `holmes decay` 完成后自动产生

> ⚠️ `holmes health-export` 该命令尚未实现，telemetry 上报接线为待办项（spec 043 T044 挂起）。

| 字段 | 值 |
|------|-----|
| `metadata.draft_count` | 当前草稿条目总数 |
| `metadata.verified_count` | 当前已验证条目总数 |
| `metadata.proven_count` | 当前已证明条目总数 |
| `metadata.pending_backlog` | 当前待审条目积压数 |

---

### `kb.buffer_overflow` — 本地缓冲溢出

**触发**：自动（本地缓冲超过 `telemetry_max_buffer_mb` 限制时）

表示最旧的一批事件已被丢弃以腾出空间。

| 字段 | 值 |
|------|-----|
| `metadata.dropped_count` | 被丢弃的事件数 |
| `metadata.buffer_size_bytes` | 丢弃前的文件大小 |

---

## 仪表板操作

### 进入仪表板

浏览器打开 `http://<服务器IP>:3000` → 左侧菜单 **Dashboards** → **Holmes KB Governance**

### 面板说明

**Contributor Activity 区域**

| 面板 | 说明 | 数据来源 |
|------|------|---------|
| Pending Submissions by Contributor | 各贡献者提交数趋势折线图 | Prometheus |
| Entries Confirmed by Contributor | 各贡献者通过数柱状图 | Prometheus |
| Confirmation Rate by Contributor | 各贡献者通过率（通过数/审核总数）| Prometheus |
| Sessions Referencing KB | 各贡献者的 KB 引用 session 数 | Prometheus |
| 四个统计卡片 | 全局总提交 / 总通过 / 总拒绝 / 总修正 | Prometheus |

**KB Health 区域**

| 面板 | 说明 |
|------|------|
| Event Type Distribution | 各事件类型占比饼图 |
| Decay & Archival Trend | 衰减和归档的时序趋势 |
| Corrections Applied Trend | 修正操作的时序趋势 |

**Audit Log 区域**

实时事件流，显示每条事件的时间、类型、贡献者和条目 ID。支持按关键字搜索。

### 修改时间范围

右上角时间选择器，常用选项：`Last 7 days` / `Last 30 days` / `Last 90 days` / 自定义。

### 自定义和添加面板

仪表板编辑后**会持久化保存**（不会被重启覆盖）：

1. 右上角点 **Edit** 进入编辑模式
2. 点任意面板 **⋮** → **Edit** 修改查询
3. 点 **Add panel** → **Add visualization** 添加新面板
4. 点 **Save dashboard** 保存

**常用查询示例（新增面板时使用）：**

```promql
# 过去 30 天，某贡献者提交的修正数
sum(increase(holmes_kb_holmes_kb_events_total{
  event_type="kb.correction_applied",
  contributor="alice"
}[30d]))

# 过去 7 天每天的 decay 数量
sum(increase(holmes_kb_holmes_kb_events_total{event_type="kb.decay"}[1d]))
```

Audit Log 的 LogQL 查询：

```logql
# 筛选特定贡献者的事件
{job="holmes-kb-cli"} | json | line_format "{{.body}}" | json
  | contributor="alice"

# 筛选特定事件类型
{job="holmes-kb-cli"} | json | line_format "{{.body}}" | json
  | event_type="kb.confirm"
```

---

## 自定义采集

### 只采集部分事件

```bash
# 只关注审核质量（适合普通贡献者）
holmes setup \
  --kb-path ~/holmes-kb \
  --otel-endpoint http://<服务器IP>:4318 \
  --events "kb.write_pending,kb.confirm,kb.reject,kb.correction_applied"

# 只关注 KB 健康（适合 SRE/维护员）
holmes setup \
  --kb-path ~/holmes-kb \
  --otel-endpoint http://<服务器IP>:4318 \
  --events "kb.decay,kb.archive_orphan,kb.health_snapshot"

# 恢复全量采集（不传 --events）
holmes setup --kb-path ~/holmes-kb --otel-endpoint http://<服务器IP>:4318
```

可用事件类型：`kb.write_pending` `kb.confirm` `kb.reject` `kb.correction_applied` `kb.decay` `kb.archive_orphan` `kb.update_refs` `kb.health_snapshot`

---

## 故障排查

### 数据没出现在 Grafana

按顺序逐步排查：

**1. 确认配置正确**
```bash
cat ~/.holmes/config.json | grep -E "telemetry|otel|contributor"
```

**2. 确认 buffer 有数据**
```bash
wc -l ~/.holmes/telemetry.jsonl
# 如果为 0，说明命令没有产生事件，检查命令是否执行成功
```

**3. 手动 flush，看是否报错**
```bash
python -m holmes.kb.telemetry_forwarder --once
# 正常时无输出；出错时会打印错误信息
```

**4. 验证 Collector 可达**
```bash
curl -s -o /dev/null -w "%{http_code}" http://<服务器IP>:4318/v1/logs \
  -X POST -H "Content-Type: application/json" -d '{}'
# 返回 200 或 400 均表示可达；超时或 connection refused 表示网络问题
```

**5. 查看 Collector 日志**
```bash
# 在服务器上执行
cd telemetry/
docker compose logs otel-collector --tail=20
```

**6. 检查 Grafana 时间范围**——右上角确认时间窗口包含数据产生的时间段。

### 常见错误

| 错误现象 | 原因 | 解决方法 |
|---------|------|---------|
| `connection refused` | Collector 未启动或端口不通 | `docker compose up -d`，检查防火墙 |
| `HTTP 400` 且日志显示 `timestamp too old` | buffer 里有很旧的事件（超过 1 小时） | `rm ~/.holmes/telemetry.jsonl ~/.holmes/telemetry.offset` |
| Grafana 登录失败 | 密码已被修改 | 见管理员安装中的密码重置方法 |
| 贡献者面板显示主机名而非名字 | 未设置 `--contributor` | 重新运行 `holmes setup --contributor <名字>` |
| 事件进了 Loki 但 Prometheus 无数据 | count_connector 未触发 | 查看 Collector 日志，确认 metrics pipeline 正常 |

### 运维命令速查

```bash
# 查看服务状态
docker compose ps

# 重启单个服务
docker compose restart otel-collector

# 停止（保留数据）
docker compose down

# 完全重置（清空所有历史数据）
docker compose down -v

# 清空本地 buffer（重新开始采集）
rm -f ~/.holmes/telemetry.jsonl \
      ~/.holmes/telemetry.offset \
      ~/.holmes/telemetry.sent_ids \
      ~/.holmes/telemetry.last_flush
```

---

## 环境变量速查

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOLMES_TELEMETRY_ENABLED` | `true` | 设为 `false` / `0` / `no` 关闭遥测 |
| `HOLMES_OTEL_ENDPOINT` | `http://localhost:4318` | OTel Collector 地址 |
| `HOLMES_TELEMETRY_BUFFER_PATH` | `~/.holmes/telemetry.jsonl` | 本地缓冲文件路径 |
| `HOLMES_TELEMETRY_EVENTS` | （空，采集全部） | 逗号分隔的事件白名单 |
