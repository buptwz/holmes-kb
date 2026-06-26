# GPU 集群健康检查与诊断 API 排查手册

## 背景

AI 训练集群提供了完整的 REST API 用于远程诊断，绝大多数排查步骤可以通过 API 调用完成，无需登录物理机器。本文档记录标准诊断流程。

## 症状

- 训练任务提交后长时间处于 `PENDING` 状态
- 集群监控 dashboard 显示部分节点 `health_status: degraded`
- API 调用返回 503 或响应延迟超过 5 秒

---

## 排查步骤

### 第一步：获取集群整体健康状态

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    https://api.cluster.internal/v1/health/summary
```

期望响应：
```json
{
  "status": "ok",
  "node_count": 64,
  "healthy_nodes": 64,
  "degraded_nodes": 0
}
```

根据 `degraded_nodes` 数量：
- `degraded_nodes == 0` → 集群健康，排查调度器
- `degraded_nodes > 0` → 进入节点健康检查流程
- 接口返回 503 → 进入 API 服务诊断流程

---

### 节点健康检查流程

查询所有降级节点列表：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/nodes?status=degraded" \
    | jq '.nodes[] | {id, hostname, degraded_reason}'
```

对每个降级节点执行深度诊断：

```bash
$ curl -s -X POST \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_id": "NODE_ID", "mode": "full", "include": ["gpu", "network", "storage"]}' \
    https://api.cluster.internal/v1/diagnostic/node
```

期望响应格式：
```json
{
  "node_id": "node-042",
  "gpu_health": "ok",
  "network_health": "degraded",
  "storage_health": "ok",
  "errors": ["network: packet_loss=12%"]
}
```

根据诊断结果路由：
- `gpu_health: degraded` → 进入 GPU 深度诊断流程
- `network_health: degraded` → 进入网络诊断流程
- `storage_health: degraded` → 进入存储诊断流程
- 所有健康但仍有问题 → 进入调度器诊断流程

---

### GPU 深度诊断流程

调用 GPU 诊断 API（可能耗时 2-5 分钟）：

```bash
$ curl -s -X POST \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_id": "NODE_ID", "diag_level": 3, "ecc_check": true}' \
    https://api.cluster.internal/v1/diagnostic/gpu
```

轮询诊断结果（异步 API）：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/diagnostic/gpu/status?job_id=JOB_ID"
```

当 `status: completed` 时获取报告：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/diagnostic/gpu/report?job_id=JOB_ID" \
    | jq '.results[] | select(.severity != "ok")'
```

根据报告内容：
- `ecc_uncorrectable > 0` → GPU 存在不可纠正 ECC 错误，提交 RMA 申请
- `temperature > 85` → GPU 过热，检查散热（需要人工到机柜确认风扇状态）
- `pcie_link_speed: degraded` → PCIe 链路降速，提交节点下线申请后更换 riser card

提交 RMA 申请：

```bash
$ curl -s -X POST \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_id": "NODE_ID", "component": "gpu", "diag_job_id": "JOB_ID", "priority": "high"}' \
    https://api.cluster.internal/v1/maintenance/rma
```

---

### 网络诊断流程

执行网络连通性测试：

```bash
$ curl -s -X POST \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"source_node": "NODE_ID", "targets": ["10.0.0.1", "10.0.0.2"], "protocol": "icmp", "count": 100}' \
    https://api.cluster.internal/v1/diagnostic/network/ping
```

查询 RoCE (RDMA over Converged Ethernet) 带宽：

```bash
$ curl -s -X POST \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_id": "NODE_ID", "test_type": "bandwidth", "duration_sec": 10}' \
    https://api.cluster.internal/v1/diagnostic/network/roce
```

分析结果：
- 丢包率 > 1% → 提交网络组工单
- RoCE 带宽 < 80Gbps（期望 200Gbps）→ 进入 RoCE 配置诊断
- 网络正常 → 进入调度器诊断流程

---

### RoCE 配置诊断

查询 RoCE 配置状态：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/nodes/NODE_ID/network/roce/config" \
    | jq '{priority_flow_control, ecn_enabled, mtu}'
```

查询 DCQCN 参数：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/nodes/NODE_ID/network/roce/dcqcn"
```

判断：
- PFC 未启用 → 调用配置修复 API 启用 PFC
- ECN 未启用 → 调用配置修复 API 启用 ECN
- DCQCN 参数异常 → 重置为集群默认参数

修复配置：

```bash
$ curl -s -X PUT \
    -H "Authorization: Bearer $CLUSTER_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"node_id": "NODE_ID", "config": {"priority_flow_control": true, "ecn_enabled": true, "mtu": 4200}}' \
    https://api.cluster.internal/v1/nodes/NODE_ID/network/roce/config
```

---

### 存储诊断流程

检查节点本地 NVMe 健康状态：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/nodes/NODE_ID/storage/nvme/health" \
    | jq '.drives[] | {device, health_status, available_spare_pct, media_errors}'
```

检查分布式存储挂载点：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/nodes/NODE_ID/storage/mounts" \
    | jq '.[] | select(.status != "ok")'
```

根据结果：
- NVMe `available_spare_pct < 10` → 提交磁盘更换工单
- 分布式存储 mount 失败 → 联系存储团队（需要人工操作存储集群）
- 存储正常 → 进入调度器诊断流程

---

### 调度器诊断流程

查询任务调度队列状态：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/scheduler/queue?status=pending&limit=20" \
    | jq '.tasks[] | {id, submit_time, wait_reason}'
```

查询资源分配情况：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/scheduler/resources/utilization" \
    | jq '{gpu_utilization, memory_utilization, pending_requests}'
```

根据 `wait_reason`：
- `insufficient_gpu` → GPU 资源不足，等待或扩容
- `node_affinity_failed` → 节点亲和性策略过严，调整任务提交参数
- `quota_exceeded` → 用户配额用尽，联系管理员申请临时配额

---

### API 服务诊断流程

检查 API 服务健康端点：

```bash
$ curl -sv https://api.cluster.internal/healthz
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    https://api.cluster.internal/v1/internal/metrics \
    | jq '{request_rate, error_rate, p99_latency_ms}'
```

查询 API 服务日志（最近 100 条错误）：

```bash
$ curl -s -H "Authorization: Bearer $CLUSTER_TOKEN" \
    "https://api.cluster.internal/v1/internal/logs?level=error&limit=100&since=1h" \
    | jq '.[] | {timestamp, component, message}'
```

判断：
- `error_rate > 5%` → 检查下游依赖服务（etcd/数据库）
- `p99_latency_ms > 2000` → 查询慢请求来源，可能是某个诊断 API 超时
- 日志中出现 `etcd: connection refused` → 联系平台团队处理 etcd 异常
