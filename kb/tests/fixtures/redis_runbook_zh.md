# Redis 主从同步延迟排查手册

**类型**: pitfall | **类别**: database | **语言**: zh

## 问题描述

Redis 主从同步出现延迟，从节点数据滞后主节点，导致读取从节点的应用获取到过期数据。

告警信息：
```
ALERT: Redis replication lag > 10 seconds on replica redis-replica-01:6380
Current lag: 45 seconds (master_repl_offset - slave_repl_offset = 2048000 bytes)
```

## 根因

Redis 主从同步延迟的常见原因包括：

1. **网络带宽不足**: 主节点写入量超过主从之间的网络带宽
2. **从节点负载过高**: 从节点 CPU 繁忙，无法及时处理复制缓冲区中的命令
3. **复制积压缓冲区溢出**: `repl-backlog-size` 设置过小，导致全量重同步
4. **慢查询阻塞**: 从节点上执行耗时的 KEYS 或 SMEMBERS 命令阻塞主线程
5. **大 key 复制**: 超大 hash/list/set 的写入产生巨量复制流量

## 诊断步骤

执行以下命令诊断 Redis 主从同步问题：

```bash
redis-cli INFO replication
```

重点关注以下字段：
- `master_repl_offset`: 主节点当前复制偏移量
- `slave_repl_offset`: 从节点已复制到的偏移量
- `master_link_status`: 主从连接状态（up/down）
- `slave_repl_offset` vs `master_repl_offset` 的差值即为延迟字节数

```bash
redis-cli DEBUG SLEEP 0
```

此命令用于测试 Redis 是否响应正常（SLEEP 0 立即返回），可快速排查主线程是否被阻塞。

```bash
# 检查从节点复制延迟
redis-cli -h redis-replica-01 -p 6380 INFO replication | grep -E "lag|offset|status"

# 检查主节点复制缓冲区大小
redis-cli INFO replication | grep -E "repl_backlog|master_repl_offset"

# 检查网络传输速率
redis-cli INFO stats | grep -E "instantaneous_output_kbps|total_net_output_bytes"

# 查看最近的慢查询
redis-cli SLOWLOG GET 10

# 检查大 key（可能导致复制流量突增）
redis-cli --bigkeys --sleep 0.01
```

## 解决方案

根据诊断结果，按以下步骤处理：

```bash
# 步骤1: 确认主从复制状态
redis-cli INFO replication | grep -E "role|connected_slaves|master_link_status|lag"

# 步骤2: 如果从节点复制缓冲区溢出，增大 repl-backlog-size
redis-cli CONFIG SET repl-backlog-size 67108864  # 设置为 64MB

# 步骤3: 检查并清理慢查询
redis-cli SLOWLOG RESET
# 等待 30 秒后再次查看
redis-cli SLOWLOG GET 20

# 步骤4: 如需强制全量重同步（从节点数据可能不一致时使用）
redis-cli -h redis-replica-01 -p 6380 REPLICAOF NO ONE
redis-cli -h redis-replica-01 -p 6380 REPLICAOF redis-primary 6379

# 步骤5: 验证同步已恢复（延迟应降至 0）
watch -n 1 'redis-cli -h redis-replica-01 -p 6380 INFO replication | grep lag'
```

## 预防措施

- 设置 `repl-backlog-size` 至少为 64MB（默认 1MB 过小）
- 禁止在从节点执行耗时命令（通过 `rename-command` 限制 KEYS 命令）
- 监控 `master_repl_offset - slave_repl_offset` 超过 10MB 时告警
- 定期检查大 key 并进行拆分或压缩

## 相关

- Redis 内存溢出（entry: kb-redis-oom-001）
- Redis 持久化最佳实践（entry: kb-redis-persistence-001）
