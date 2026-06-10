# MySQL 主库磁盘满导致写入阻塞

**类型**: pitfall | **类别**: database | **语言**: zh

## Symptoms

生产环境 MySQL 主库出现写入阻塞，应用程序日志中大量报错：

```
ERROR 1290 (HY000): The MySQL server is running with the --read-only option
ERROR 1005 (HY000): Can't create table `mydb`.`orders` (errno: 28 "No space left on device")
java.sql.SQLException: Deadlock found when trying to get lock; try restarting transaction
```

监控告警：
- MySQL 写入 QPS 从正常值 2000/s 下降至 0
- 磁盘使用率从 80% 突增至 100%
- 主从延迟从 0ms 上升至 120,000ms（2分钟）
- 应用层订单创建接口返回 500 错误率达 100%

受影响服务：订单服务、库存服务、支付服务（均依赖 MySQL 主库写入）

## Background

该 MySQL 实例承载核心交易数据库，规格为 32C 128G，磁盘为 2TB SSD RAID10 阵列。
数据库版本：MySQL 8.0.31。正常情况下磁盘使用率维持在 60-75%，每日增量约 5GB。

事件发生于周五晚 22:30（业务低峰期），但因为当天有大批量数据迁移任务在后台运行，
磁盘写入量异常增大。运维团队在 22:45 收到磁盘告警后介入处理。

## Timeline

- **22:30** 批量数据迁移任务启动，预计迁移 800GB 历史订单数据到归档表
- **22:45** 磁盘使用率告警触发（阈值 90%）
- **22:48** 应用监控报警，写入错误率上升
- **22:50** DBA 介入，发现磁盘已满（100%）
- **22:52** 紧急停止迁移任务
- **22:55** 清理 binlog 释放磁盘空间，MySQL 恢复写入
- **23:10** 主从延迟恢复正常
- **23:30** 完整功能验证通过，事件结束

## Root Cause

根本原因是批量数据迁移任务在执行过程中，未对磁盘剩余空间进行预检查，
也未设置磁盘空间阈值熔断机制。具体触发链路：

1. 数据迁移任务通过 `INSERT INTO archive_orders SELECT ... FROM orders WHERE ...` 批量写入，
   每次事务涉及约 10,000 行数据
2. MySQL 在迁移过程中产生大量 binlog（row-based replication），
   binlog 文件以每分钟约 2GB 的速度增长
3. 同时，InnoDB undo log 和 redo log 也因大事务持续膨胀
4. 操作系统层面未对 MySQL 数据目录设置独立磁盘分区限额
5. 当磁盘使用率达到 100% 时，MySQL 无法写入任何数据文件，触发全库只读模式

## Impact Analysis

- **直接影响**: 所有写操作失败，影响约 3,200 名在线用户的交易操作
- **数据安全**: 无数据丢失，已提交事务均已持久化
- **业务损失**: 30 分钟写入中断，估计影响约 150 笔订单创建失败
- **SLA 违约**: 写入可用性 SLA（99.9%）本月累计已受损

## Detailed Analysis

### MySQL Disk Space Consumers

When MySQL runs out of disk space, it is critical to understand which components consume the most space.
This section provides a deep-dive analysis of each disk space consumer and how to monitor them.

#### Binary Log (binlog) Growth Analysis

Binary logs record all DDL and DML operations performed on the database server.
With row-based replication format (`binlog_format=ROW`), every row change is recorded individually,
which can cause binlog files to grow much faster than with statement-based replication.

During a large batch migration (`INSERT ... SELECT`), the binlog grows proportionally to the number
of rows inserted. In this incident, the migration inserted approximately 100 million rows,
each averaging 200 bytes, resulting in approximately 20GB of binlog data.

Key metrics to monitor:
- `Com_insert`: cumulative insert count since server start
- `Bytes_sent` and `Bytes_received`: network throughput can correlate with binlog growth
- `Binlog_cache_disk_use`: indicates transactions that overflowed the in-memory binlog cache

```sql
-- Monitor binlog growth rate in real-time
SHOW MASTER STATUS;
SHOW BINARY LOGS;

-- Check binlog cache hit rate (low rate = large transactions)
SHOW GLOBAL STATUS LIKE 'Binlog_cache%';
-- If Binlog_cache_disk_use > 0, consider increasing binlog_cache_size
SHOW VARIABLES LIKE 'binlog_cache_size';
```

#### InnoDB Undo Log Analysis

The InnoDB undo log stores the "before image" of each modified row to support:
- Transaction rollback
- MVCC (Multi-Version Concurrency Control) for consistent reads
- Crash recovery

During long-running transactions, the undo log can grow significantly. In this incident,
the batch migration ran for approximately 20 minutes before being killed, and the undo log
grew to over 5GB during that time.

Key MySQL 8.0 undo log settings:
- `innodb_undo_tablespaces`: number of undo tablespace files (recommend >= 2 for truncation)
- `innodb_undo_log_truncate`: enable automatic undo log truncation
- `innodb_max_undo_log_size`: maximum size before truncation is triggered

```sql
-- Check undo tablespace usage
SELECT TABLESPACE_NAME, FILE_NAME,
       ROUND(FILE_SIZE / 1024 / 1024, 1) AS size_mb,
       ROUND(ALLOCATED_SIZE / 1024 / 1024, 1) AS allocated_mb
FROM information_schema.FILES
WHERE FILE_TYPE = 'UNDO LOG';

-- Monitor active undo log history length (higher = more old versions retained)
SELECT count AS history_length
FROM information_schema.INNODB_METRICS
WHERE NAME = 'trx_rseg_history_len';
```

#### InnoDB Redo Log Analysis

Redo logs (ib_logfile0, ib_logfile1) record all changes to InnoDB data pages for crash recovery.
Unlike binlog and undo log, redo log size is fixed and configured via `innodb_log_file_size`.
However, insufficient redo log capacity can cause checkpointing delays.

During high write throughput, InnoDB may need to checkpoint (flush dirty pages) more frequently
to reuse redo log space. This causes write amplification and can degrade performance significantly.

Recommended redo log sizing: 25% of the `innodb_buffer_pool_size`.
For a 64GB buffer pool, configure `innodb_log_file_size = 16G`.

### Capacity Planning Model

To prevent disk space exhaustion, implement a capacity planning model:

| Metric | Current | Target | Action Threshold |
|--------|---------|--------|-----------------|
| Disk usage % | 85% | <70% | Alert at 75%, page at 85% |
| Daily data growth | 5GB | <8GB | Review if >10GB sustained |
| Binlog retention | 7 days | 3 days | Reduce if disk > 70% |
| Active transactions | 50 | <100 | Alert if long txn > 5min |

Capacity formula:
```
safe_migration_size = (free_disk_space - 10GB_buffer) / binlog_amplification_factor
# For row-based replication: binlog_amplification_factor ≈ 2.5x data size
# For statement-based: binlog_amplification_factor ≈ 0.3x data size
```

### Diagnostic Checklist

Before starting any large batch operation, verify:

- [ ] Current disk usage < 60% (leaving 40% headroom)
- [ ] Estimated data size * 3 < available free space (accounting for binlog and undo log)
- [ ] No existing long-running transactions (check `innodb_trx` table)
- [ ] `binlog_expire_logs_seconds` is configured (recommendation: 259200 = 3 days)
- [ ] Disk usage monitoring alert is active and properly routed
- [ ] Rollback plan documented and tested

### Monitoring and Alerting Setup

To ensure you receive timely warnings about disk space exhaustion, configure the following:

#### Prometheus + Alertmanager Rules

```yaml
# prometheus/rules/mysql_disk.yml
groups:
  - name: mysql_disk_space
    rules:
      - alert: MySQLDiskUsageWarning
        expr: |
          (node_filesystem_size_bytes{mountpoint="/var/lib/mysql"} -
           node_filesystem_free_bytes{mountpoint="/var/lib/mysql"}) /
          node_filesystem_size_bytes{mountpoint="/var/lib/mysql"} > 0.75
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL disk usage above 75%"
          description: "{{ $labels.instance }} disk usage is {{ $value | humanizePercentage }}"

      - alert: MySQLDiskUsageCritical
        expr: |
          (node_filesystem_size_bytes{mountpoint="/var/lib/mysql"} -
           node_filesystem_free_bytes{mountpoint="/var/lib/mysql"}) /
          node_filesystem_size_bytes{mountpoint="/var/lib/mysql"} > 0.90
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "MySQL disk usage above 90% — IMMEDIATE ACTION REQUIRED"
          description: "{{ $labels.instance }} disk usage is {{ $value | humanizePercentage }}"

      - alert: MySQLBinlogGrowthAnomaly
        expr: |
          rate(mysql_global_status_binlog_cache_disk_use[10m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MySQL binlog cache disk use rate elevated"
          description: "Large transactions detected on {{ $labels.instance }}"
```

#### Grafana Dashboard Panels

Key panels to include in the MySQL operations dashboard:

1. **Disk Usage Trend**: Line chart showing disk usage % over 7 days with forecast
2. **Binlog Size Growth**: Area chart of total binlog size (bytes) over time
3. **Active Long Transactions**: Gauge showing count of transactions running > 60 seconds
4. **Undo Log History Length**: Single stat showing InnoDB trx_rseg_history_len

#### mysqld_exporter Configuration

Enable the following collectors for comprehensive MySQL disk space monitoring:

```ini
# /etc/default/prometheus-mysqld-exporter
ARGS="--collect.info_schema.tables \
      --collect.info_schema.tablestats \
      --collect.binlog_size \
      --collect.global_status \
      --collect.global_variables \
      --collect.slave_status \
      --collect.engine_innodb_status"
```

### Runbook for On-Call Engineers

When paged for `MySQLDiskUsageCritical`:

**Step 1: Assess severity** (< 2 minutes)
```bash
# SSH to the affected host
ssh mysql-primary-01

# Check current disk usage
df -h /var/lib/mysql

# Check what's consuming the most space
du -sh /var/lib/mysql/* 2>/dev/null | sort -rh | head -10
```

**Step 2: Quick wins** (binlog cleanup, < 5 minutes)
```bash
# Check binlog files and their dates
mysql -e "SHOW BINARY LOGS;"

# Purge binlogs older than 2 days (safe if replicas are not lagging)
# First verify replica is not lagging behind binlog you want to purge
mysql -e "SHOW SLAVE HOSTS;"
mysql -e "SHOW SLAVE STATUS\G" | grep -E "Master_Log_File|Read_Master_Log_Pos"

# If safe, purge
mysql -e "PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 2 DAY);"
```

**Step 3: Identify and stop runaway processes** (if binlog cleanup insufficient)
```bash
# Find large active transactions
mysql -e "
SELECT p.ID, p.USER, p.HOST, p.DB, p.TIME, p.STATE, p.INFO,
       t.trx_rows_modified
FROM information_schema.PROCESSLIST p
JOIN information_schema.INNODB_TRX t ON p.ID = t.trx_mysql_thread_id
WHERE t.trx_rows_modified > 10000
ORDER BY t.trx_rows_modified DESC;"

# Kill the problematic process (record the process ID first for incident report)
mysql -e "KILL <process_id>;"
```

**Step 4: Verify and document**
```bash
# Confirm disk space recovered
df -h /var/lib/mysql

# Verify MySQL is accepting writes
mysql -e "INSERT INTO _ops_health (ts, note) VALUES (NOW(), 'disk_incident_recovery_test');"

# Log incident details
echo "$(date): Disk incident on mysql-primary-01. Used purge binlogs / killed pid X. Recovered Y GB." >> /var/log/mysql/ops-incidents.log
```

## Resolution

处理磁盘满导致 MySQL 写入阻塞的完整步骤：

```bash
# 步骤1: 立即停止正在运行的迁移任务
# 找到迁移进程的 MySQL 连接 ID
mysql -e "SHOW PROCESSLIST;" | grep -i "INSERT INTO archive"

# 步骤2: 终止占用资源的大事务（替换 <PROCESS_ID> 为实际 ID）
mysql -e "KILL <PROCESS_ID>;"

# 步骤3: 清理过期 binlog 释放磁盘空间
mysql -e "PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 3 DAY);"

# 步骤4: 验证磁盘空间已释放
df -h /var/lib/mysql

# 步骤5: 确认 MySQL 写入已恢复（测试插入）
mysql -e "INSERT INTO health_check (ts) VALUES (NOW()); SELECT * FROM health_check ORDER BY ts DESC LIMIT 1;"

# 步骤6: 检查主从复制状态是否正常
mysql -e "SHOW SLAVE STATUS\G" | grep -E "Seconds_Behind_Master|Running"

# 步骤7: 重启迁移任务（使用分批控制，每批 1000 行，间隔 1 秒）
python3 migrate_orders.py --batch-size 1000 --sleep-interval 1 --disk-threshold 80
```

验证命令：
```bash
# 验证写入功能恢复
mysql -e "SELECT COUNT(*) FROM orders WHERE created_at > DATE_SUB(NOW(), INTERVAL 5 MINUTE);"

# 验证主从延迟恢复
mysql -h replica-host -e "SHOW SLAVE STATUS\G" | grep "Seconds_Behind_Master"
```

处理磁盘满导致 MySQL 写入阻塞的完整步骤：

```bash
# 步骤1: 立即停止正在运行的迁移任务
# 找到迁移进程的 MySQL 连接 ID
mysql -e "SHOW PROCESSLIST;" | grep -i "INSERT INTO archive"

# 步骤2: 终止占用资源的大事务（替换 <PROCESS_ID> 为实际 ID）
mysql -e "KILL <PROCESS_ID>;"

# 步骤3: 清理过期 binlog 释放磁盘空间
mysql -e "PURGE BINARY LOGS BEFORE DATE_SUB(NOW(), INTERVAL 3 DAY);"

# 步骤4: 验证磁盘空间已释放
df -h /var/lib/mysql

# 步骤5: 确认 MySQL 写入已恢复（测试插入）
mysql -e "INSERT INTO health_check (ts) VALUES (NOW()); SELECT * FROM health_check ORDER BY ts DESC LIMIT 1;"

# 步骤6: 检查主从复制状态是否正常
mysql -e "SHOW SLAVE STATUS\G" | grep -E "Seconds_Behind_Master|Running"

# 步骤7: 重启迁移任务（使用分批控制，每批 1000 行，间隔 1 秒）
python3 migrate_orders.py --batch-size 1000 --sleep-interval 1 --disk-threshold 80
```

验证命令：
```bash
# 验证写入功能恢复
mysql -e "SELECT COUNT(*) FROM orders WHERE created_at > DATE_SUB(NOW(), INTERVAL 5 MINUTE);"

# 验证主从延迟恢复
mysql -h replica-host -e "SHOW SLAVE STATUS\G" | grep "Seconds_Behind_Master"
```

## Prevention

为防止此类问题再次发生，需实施以下预防措施：

### 短期措施（1周内）

1. **磁盘分区隔离**: 将 MySQL 数据目录、binlog 目录、undo log 分别挂载到独立磁盘分区
2. **告警阈值调整**: 将磁盘使用率告警阈值从 90% 降低至 75%，预警阈值设置为 60%
3. **binlog 自动清理**: 设置 `binlog_expire_logs_seconds = 259200`（3天）

```sql
SET GLOBAL binlog_expire_logs_seconds = 259200;
```

### 中期措施（1月内）

1. **迁移任务框架改造**: 增加磁盘空间预检查，实现动态限速，支持断点续传
2. **容量规划**: 建立磁盘容量趋势预测模型，设置容量不足 30 天的自动扩容工单触发

#### 安全迁移脚本示例

下面是一个实现了磁盘预检、分批写入和断点续传的迁移脚本框架：

```python
#!/usr/bin/env python3
"""safe_migrate.py — disk-space-aware batch migration utility."""

import time
import shutil
import argparse
import mysql.connector

DISK_THRESHOLD_PCT = 80  # stop if disk usage exceeds this

def check_disk_space(mysql_datadir="/var/lib/mysql"):
    usage = shutil.disk_usage(mysql_datadir)
    used_pct = usage.used / usage.total * 100
    free_gb = usage.free / (1024 ** 3)
    return used_pct, free_gb

def migrate_batch(conn, last_id, batch_size):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO archive_orders "
        "SELECT * FROM orders WHERE id > %s AND id <= %s + %s",
        (last_id, last_id, batch_size)
    )
    rows = cur.rowcount
    conn.commit()
    return last_id + batch_size, rows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--sleep-interval", type=float, default=1.0)
    parser.add_argument("--disk-threshold", type=int, default=DISK_THRESHOLD_PCT)
    args = parser.parse_args()

    conn = mysql.connector.connect(host="localhost", user="migrator", database="mydb")
    last_id = 0  # load from checkpoint file in production

    while True:
        used_pct, free_gb = check_disk_space()
        if used_pct > args.disk_threshold:
            print(f"[ABORT] Disk usage {used_pct:.1f}% > threshold {args.disk_threshold}%")
            break

        last_id, rows = migrate_batch(conn, last_id, args.batch_size)
        print(f"Migrated to id={last_id}, rows={rows}, disk={used_pct:.1f}%")

        if rows == 0:
            print("Migration complete.")
            break

        time.sleep(args.sleep_interval)

if __name__ == "__main__":
    main()
```

### 长期措施（季度内）

1. **存储架构升级**: 将 binlog 迁移到独立的高速 NVMe 存储，减少 binlog 和数据文件对磁盘 I/O 的竞争
2. **数据生命周期管理**: 建立自动归档和冷热分离机制，避免主库数据无限增长
3. **混沌工程演练**: 定期模拟磁盘满场景，验证告警和应急响应流程的有效性
4. **容量 SLO**: 将"磁盘剩余空间 > 30天预测增量"纳入服务健康度 SLO 指标

## Related

- MySQL 慢查询引发主从延迟（entry: kb-mysql-replication-lag-001）
- InnoDB undo log 过度膨胀（entry: kb-mysql-undo-log-bloat-001）
- 数据库容量规划最佳实践（entry: kb-db-capacity-planning-001）
- 大批量数据迁移操作手册（entry: kb-db-batch-migration-ops-001）
- MySQL binlog 管理与清理策略（entry: kb-mysql-binlog-management-001）

---

*Note: This runbook was created as part of post-incident review following the 2024-03-15 production incident.
All commands have been tested against MySQL 8.0.31 on Ubuntu 22.04 LTS.
Last updated: 2024-03-20 by SRE team. Review cycle: quarterly or after any disk incident.
For questions contact: #db-oncall Slack channel or dba-team@example.com.*


- MySQL 慢查询引发主从延迟（entry: kb-mysql-replication-lag-001）
- InnoDB undo log 过度膨胀（entry: kb-mysql-undo-log-bloat-001）
- 数据库容量规划最佳实践（entry: kb-db-capacity-planning-001）
