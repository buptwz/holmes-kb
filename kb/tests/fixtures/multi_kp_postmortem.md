# 多服务故障后复盘报告：Redis、MySQL、Nginx 三层问题分析

**事件日期**: 2024-03-20 | **影响时长**: 45分钟 | **严重级别**: P1

## 概述

本次故障涉及三个相互独立的系统层面问题，在同一时间窗口内相继触发，导致部分用户
无法正常访问服务。经过深入排查，三个问题的根因完全不同，需分别处理和复盘。

---

## Redis 连接池耗尽导致请求超时

### 症状

应用服务器日志出现大量以下报错：

```
redis.exceptions.ConnectionError: Error 111 connecting to redis-primary:6379. Connection refused.
redis.exceptions.TimeoutError: Timeout reading from socket
ERROR: Failed to get connection from pool after 5.0s
```

监控指标：
- Redis 连接数从正常 200 个骤升至 1024（上限）
- 应用层接口 P99 延迟从 50ms 上升至 8000ms
- Redis `rejected_connections` 计数器每秒递增 50+

### 根因

Redis 连接池耗尽的根本原因是应用服务在处理大批量请求时，
每个请求独立创建 Redis 连接但未正确归还到连接池。

触发链路：
1. 营销活动推送导致流量突增 5 倍（QPS: 2000 → 10000）
2. 应用代码使用 `redis.Redis()` 直接实例化而非从连接池获取
3. 每个请求结束时连接没有被正确 close/release
4. 连接数快速增长，达到 Redis `maxclients = 1024` 上限
5. 新请求无法建立连接，返回 ConnectionError

### 解决方案

```bash
# 1. 临时增大 Redis 最大连接数（应急）
redis-cli CONFIG SET maxclients 2048

# 2. 查看当前连接来源分布
redis-cli CLIENT LIST | awk -F'addr=' '{print $2}' | cut -d: -f1 | sort | uniq -c | sort -rn | head 10

# 3. 关闭空闲连接（IDLE 超过 300 秒）
redis-cli CLIENT NO-EVICT off
redis-cli CLIENT NO-TOUCH off

# 4. 强制断开所有非 admin 来源的空闲连接（谨慎操作）
redis-cli CLIENT KILL ID $(redis-cli CLIENT LIST | awk '/idle=3[0-9]{2,}/ {match($0, /id=([0-9]+)/, a); print a[1]}')

# 5. 长期修复：修改应用代码使用连接池
# Python 示例（修改前后对比）
# 修改前（错误）: client = redis.Redis(host='redis-primary', port=6379)
# 修改后（正确）: pool = redis.ConnectionPool(host='redis-primary', max_connections=50)
#                client = redis.Redis(connection_pool=pool)
```

### 预防措施

- 在所有微服务中统一使用连接池单例（ConnectionPool singleton）
- 设置连接池大小上限：`max_connections = 50`（每实例）
- 配置连接泄漏检测：`socket_timeout=5, socket_connect_timeout=2`
- 添加监控告警：当 Redis 连接数 > 80% maxclients 时触发警告

---

## MySQL 慢查询引发主从延迟

### 症状

MySQL 监控面板显示：

```
Slave_IO_Running: Yes
Slave_SQL_Running: Yes
Seconds_Behind_Master: 45678
```

应用报错：
```
ERROR 1290 (HY000): The MySQL server is running with the --read-only option so it cannot execute this statement
StaleDataException: Data read from replica is 45678 seconds behind primary
```

### 根因

主从延迟的根本原因是在主库上执行了一个未加索引的大表 UPDATE 语句，
导致全表扫描，产生大量 binlog row event，Replica SQL 线程无法及时消费。

```sql
-- 问题 SQL（执行时间 120 秒）
UPDATE user_activities SET status = 'archived'
WHERE created_at < '2024-01-01'
AND user_id NOT IN (SELECT id FROM active_users);
```

该 SQL 存在以下问题：
1. `user_activities` 表无 `created_at` 索引（1.2 亿行，全表扫描）
2. `NOT IN (subquery)` 子查询每行都需执行一次
3. 单次事务锁定行数超过 500 万，产生 binlog 约 3GB
4. Replica SQL 线程回放速度约 0.5GB/分钟，需约 6 分钟才能追上

### 解决方案

```sql
-- 步骤1: 终止问题查询（先查 PID）
SHOW PROCESSLIST;
-- 找到状态为 "Updating" 的长时间运行查询，记录 ID
KILL QUERY <PROCESS_ID>;

-- 步骤2: 等待主从延迟恢复（监控 Seconds_Behind_Master）
-- 在 replica 上执行
SHOW SLAVE STATUS\G

-- 步骤3: 添加缺失索引
ALTER TABLE user_activities ADD INDEX idx_created_at_status (created_at, status);

-- 步骤4: 改写 SQL 为分批更新
DELIMITER //
CREATE PROCEDURE batch_archive_activities()
BEGIN
  DECLARE done INT DEFAULT FALSE;
  REPEAT
    UPDATE user_activities SET status = 'archived'
    WHERE created_at < '2024-01-01'
      AND status != 'archived'
    LIMIT 10000;
    SET done = (ROW_COUNT() = 0);
    DO SLEEP(0.1);
  UNTIL done END REPEAT;
END //
DELIMITER ;

CALL batch_archive_activities();
```

### 预防措施

- 所有 DDL/DML 变更必须通过 `pt-query-digest` 或 `EXPLAIN` 审查
- 大批量更新必须使用 `LIMIT` 分批执行，并加入 `SLEEP` 间隔
- 设置 `long_query_time = 2` 并开启慢查询日志
- 主从延迟监控告警阈值设置为 60 秒

---

## Nginx upstream 配置错误导致 502

### 症状

客户端收到大量 `502 Bad Gateway` 响应：

```
GET /api/v1/user/profile HTTP/1.1
< HTTP/1.1 502 Bad Gateway
< Server: nginx/1.24.0
```

Nginx 错误日志：

```
2024/03/20 14:23:11 [error] 1234#1234: *56789 connect() failed (111: Connection refused)
while connecting to upstream, client: 10.0.1.100, server: api.example.com,
request: "GET /api/v1/user/profile HTTP/1.1", upstream: "http://10.0.2.50:8080/api/v1/user/profile",
host: "api.example.com"
```

### 根因

Nginx upstream 配置错误导致请求转发到了已下线的后端实例 IP。
具体原因是在扩缩容操作后，Nginx 配置文件未同步更新，仍然包含旧实例的 IP 地址。

问题配置：
```nginx
upstream api_backend {
    server 10.0.2.50:8080;  # 已下线，不再存在
    server 10.0.2.51:8080;  # 正常运行
    server 10.0.2.52:8080;  # 正常运行
}
```

由于没有配置健康检查（`health_check` 需要 Nginx Plus），
Nginx 持续将 1/3 的请求转发到已下线的实例。

### 解决方案

```bash
# 步骤1: 定位问题 upstream 配置
nginx -T | grep -A 10 "upstream api_backend"

# 步骤2: 修改 nginx.conf，移除已下线 IP
vim /etc/nginx/conf.d/api.conf
# 删除 server 10.0.2.50:8080; 这一行

# 步骤3: 验证配置语法
nginx -t

# 步骤4: 热重载 Nginx（不中断现有连接）
nginx -s reload

# 步骤5: 验证 502 消失
curl -s -o /dev/null -w "%{http_code}" https://api.example.com/api/v1/user/profile
# 预期输出: 200

# 步骤6: 验证 upstream 状态（需 stub_status 或 Nginx Plus）
curl http://127.0.0.1/nginx_status

# 步骤7: 检查访问日志确认无更多 502
tail -f /var/log/nginx/access.log | grep " 502 "
```

### 预防措施

- 引入服务注册与发现（如 Consul），Nginx 配置通过模板自动生成，避免手动维护 IP
- 配置 Nginx 被动健康检查（开源版）：
  ```nginx
  upstream api_backend {
      server 10.0.2.51:8080 max_fails=3 fail_timeout=30s;
      server 10.0.2.52:8080 max_fails=3 fail_timeout=30s;
  }
  ```
- 扩缩容变更操作标准流程中增加"更新 Nginx 配置并 reload"步骤
- 部署 Prometheus + nginx_exporter 监控 upstream 响应状态

---

## 总结

| 问题 | 根因类型 | 影响范围 | 恢复时间 |
|------|---------|---------|---------|
| Redis 连接池耗尽 | 应用代码缺陷 | 全部服务 | 15 分钟 |
| MySQL 主从延迟 | 慢查询+无索引 | 读取接口 | 30 分钟 |
| Nginx 502 | 配置过时 | API 网关 | 5 分钟 |

三个问题的共同教训：缺乏完善的变更管理和自动化检查机制。
