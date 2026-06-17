# KB 来源文档写法模板

本文档展示推荐的排查文档写法，适合导入 Holmes KB。

核心约定：
- `> **人工观察点**`：需要人眼读取输出、判断现象的步骤，agent 不能自动判断
- `> **人工操作点**`：需要物理操作或人工介入的步骤
- `> **人工判断点（分支 X）**`：根据观察结果选择后续路径
- `> **人工等待点**`：需要等待一段时间再继续
- 分支标签格式：`分支 A`、`分支 B1`、`分支 B2`，用于在文中交叉引用
- `（调用 <函数名>）`：需要在代码里调用某个函数或 API 来获取信息

---

# 示例文档：Kafka 消费者延迟全链路排查

## 适用场景

- Kafka consumer lag 持续增长，消费速率明显低于生产速率
- 告警：`consumer_lag > 100000` 且持续 10 分钟以上
- 服务：任意使用 Kafka 的 Java/Python consumer 服务

## 故障现象

消费者 lag 持续增长，业务侧出现消息处理延迟或积压。监控可见 lag 曲线单调上升，消费速率（records/sec）显著低于正常水位。

## 根因分类

根因可能为以下任一类：
- **A 类**：消费者进程本身性能瓶颈（CPU、内存、GC）
- **B 类**：业务处理逻辑阻塞（下游依赖慢、死锁、外部 API 超时）
- **C 类**：Kafka Broker 侧问题（分区 leader 切换、副本同步延迟）
- **D 类**：网络/连接层问题（consumer 与 broker 连接断断续续）
- **E 类**：消费者配置不合理（max.poll.records 过大、poll 间隔超时）

## 解决方案

---

### Step 1：确认 lag 的基本情况

```bash
# 查看指定 consumer group 的 lag 分布
kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe
```

> **人工观察点**：重点关注以下字段：
> - `LAG` 列：每个分区的 lag 值
> - `CONSUMER-ID` 列：是否有分区显示 `-`（无消费者分配）
> - lag 是否集中在某几个分区，还是全部分区均匀增长

---

### Step 2：判断 lag 增长模式

> **人工判断点（分支 A / 分支 B / 分支 C）**：
> - 若**所有分区** lag 均匀增长，且 `CONSUMER-ID` 正常 → 进入**分支 A：消费者性能排查**（Step 3）
> - 若**部分分区** lag 为 0，其他分区 lag 极大，且有分区 `CONSUMER-ID` 为 `-` → 进入**分支 B：Rebalance/分区分配异常**（Step 6）
> - 若**所有分区** `CONSUMER-ID` 正常，但 lag 突然从某个时间点开始激增 → 进入**分支 C：时间点关联排查**（Step 10）

---

## 分支 A：消费者性能排查

### Step 3：检查消费者进程资源使用

```bash
# 找到 consumer 进程 PID
ps aux | grep <service-name>

# CPU 和内存
top -p <pid> -b -n 3

# GC 情况（Java 服务）
jstat -gcutil <pid> 1000 10
```

> **人工观察点**：
> - CPU 使用率是否长期 > 80%
> - GC 时间占比（`O` 列 Old GC）是否 > 5%
> - 堆内存是否接近上限

> **人工判断点（分支 A1 / 分支 A2）**：
> - 若 CPU > 80% 或 GC 明显，进入**分支 A1：进程资源瓶颈**（Step 4）
> - 若资源正常，进入**分支 A2：业务处理阻塞排查**（Step 5）

---

### Step 4（分支 A1）：进程资源瓶颈处理

```bash
# 查看线程栈，找热点线程（Java）
jstack <pid> > /tmp/jstack-$(date +%s).txt
grep -A 5 "RUNNABLE" /tmp/jstack-*.txt | head -60

# 查看哪个线程占用 CPU 最高
top -H -p <pid> -b -n 1 | head -20
```

> **人工观察点**：
> - 是否有大量线程处于 `RUNNABLE` 且都在同一方法里（热点）
> - 是否有大量线程处于 `BLOCKED`（锁竞争）
> - CPU 热点是否在业务代码还是框架代码

> **人工操作点**：
> 1. 若发现 GC 压力：检查对象创建逻辑，临时可调大堆 `-Xmx`，重启服务
> 2. 若发现热点代码：记录方法名，提交给开发修复，临时扩容消费者实例
> 3. 扩容后检查 Kafka 分区数 ≥ 消费者实例数，否则扩容无效

```bash
# 扩容后验证 lag 是否下降
watch -n 5 "kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe | grep -v '^$'"
```

> **人工等待点**：观察 3 分钟，lag 斜率是否下降。若下降 → 跳转 Step 14（收尾验证）。若不下降 → 继续 Step 5。

---

### Step 5（分支 A2）：业务处理阻塞排查

```bash
# 查看 consumer 的 poll 耗时（应用日志）
grep -i "poll\|fetch\|commit" /var/log/<service>/<service>.log | tail -50

# 查看是否有下游调用超时
grep -iE "timeout|connection refused|slow" /var/log/<service>/<service>.log \
  | tail -30
```

> **人工观察点**：是否有反复出现的超时错误或慢调用日志。记录下游服务名和超时时长。

```bash
# 检查下游依赖（以 MySQL 为例）
mysql -h <db-host> -u <user> -p<pass> \
  -e "SHOW PROCESSLIST;" | grep -v Sleep
```

> **（调用 check_downstream_latency）**：若有监控 SDK，可调用 `check_downstream_latency(service_name, window_minutes=10)` 获取近 10 分钟各下游服务的 P99 延迟数据。

> **人工判断点（分支 A2a / 分支 A2b）**：
> - 若下游有明显延迟或报错 → 进入**分支 A2a：下游依赖修复**（Step 5a）
> - 若下游正常，消费者自身处理慢 → 进入**分支 A2b：消费逻辑优化**（Step 5b）

---

### Step 5a（分支 A2a）：下游依赖修复

> **人工操作点**：
> 1. 确认下游服务（DB/Redis/外部 API）是否有告警
> 2. 若是 DB 慢查询：执行 `SHOW PROCESSLIST` 找慢 SQL，`KILL <id>` 释放锁
> 3. 若是外部 API 超时：评估是否可临时降级（跳过该调用）
> 4. 修复后等待 consumer 自动恢复消费

```bash
# 确认下游恢复后 consumer 是否追上 lag
kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe
```

> **人工等待点**：等待 5 分钟观察 lag 是否稳定下降。若下降 → 跳转 Step 14（收尾验证）。若不下降 → 继续 Step 5b。

---

### Step 5b（分支 A2b）：消费逻辑优化

```bash
# 检查 max.poll.records 配置
grep -r "max.poll.records\|max_poll_records" /etc/<service>/ /opt/<service>/config/
```

> **人工判断点**：
> - 若 `max.poll.records` > 500，且单条处理耗时 > 10ms → 有超过 `max.poll.interval.ms` 的风险
> - 临时将 `max.poll.records` 调小至 100，重启服务，观察是否触发 Rebalance 减少

---

## 分支 B：Rebalance / 分区分配异常

### Step 6：确认 Rebalance 频率

```bash
# 查看 consumer group 状态
kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe

# 查看 coordinator 日志（在 broker 上）
grep "Preparing to rebalance group\|Member.*leaving group" \
  /var/log/kafka/server.log | grep <consumer-group-name> | tail -20
```

> **人工观察点**：
> - consumer group state 是否为 `PreparingRebalance` 或 `CompletingRebalance`
> - broker 日志里 rebalance 频率是否 > 1次/分钟

> **人工判断点（分支 B1 / 分支 B2）**：
> - 若 rebalance 频率高，且日志显示 member 因 `poll interval` 超时离组 → 进入**分支 B1：poll interval 超时**（Step 7）
> - 若有成员反复加入/离开，且时间点与部署或网络抖动吻合 → 进入**分支 B2：实例不稳定**（Step 8）

---

### Step 7（分支 B1）：poll interval 超时

```bash
# 确认 max.poll.interval.ms 配置
grep -r "max.poll.interval" /etc/<service>/ /opt/<service>/config/
```

> **人工操作点**：
> 1. 若 `max.poll.interval.ms` < 单次 poll 处理时间 × `max.poll.records`：
>    - 方案一：调大 `max.poll.interval.ms`（临时，最大 5 分钟）
>    - 方案二：调小 `max.poll.records` 减少单次处理量
> 2. 重启消费者服务
> 3. 观察 rebalance 是否停止

---

### Step 8（分支 B2）：实例不稳定

```bash
# 检查实例是否有 OOM kill 或重启
dmesg | grep -i "oom\|killed" | tail -20
journalctl -u <service-name> --since "1 hour ago" | grep -iE "start|stop|restart|failed"

# 检查网络连通性（consumer 到 broker）
nc -zv <broker-host> 9092
```

> **人工观察点**：是否有 OOM、服务重启、网络抖动的记录。记录故障时间点与 lag 增长起点是否吻合。

> **人工操作点**：根据原因修复（扩内存 / 修网络 / 修启动配置）。修复后跳转 Step 14（收尾验证）。

---

## 分支 C：时间点关联排查

### Step 10：定位 lag 开始激增的时间点

```bash
# 从监控系统获取 lag 历史曲线的起始时间（或从告警时间推算）
# 获取该时间点前后的 broker 日志
grep "$(date -d '<lag-start-time>' '+%Y-%m-%d %H:%M')" \
  /var/log/kafka/server.log | tail -30
```

> **（调用 get_deployment_events）**：可调用 `get_deployment_events(service=<consumer-name>, since=<lag-start-time>)` 查询该时间段内是否有发布、配置变更、或基础设施变更事件。

> **人工观察点**：时间点前后是否有：
> - consumer 服务发布
> - Kafka broker 滚动重启或 leader 切换
> - 上游生产者流量突增

> **人工判断点（分支 C1 / 分支 C2 / 分支 C3）**：
> - 若时间点与**发布**吻合 → 进入**分支 C1：发布引入问题**（Step 11）
> - 若时间点与**生产者流量突增**吻合 → 进入**分支 C2：流量突增**（Step 12）
> - 若时间点与**Broker 变更**吻合 → 进入**分支 C3：Broker 侧问题**（Step 13）

---

### Step 11（分支 C1）：发布引入问题

> **人工操作点**：
> 1. 对比本次发布的 diff，重点关注：消费逻辑变更、新增下游调用、配置变更
> 2. 若能快速定位问题代码 → 修复后重新发布
> 3. 若无法快速定位 → 回滚到上一个版本
> 4. 回滚后观察 lag 是否停止增长

```bash
# 回滚后确认服务版本
curl -s http://<service-host>:<port>/actuator/info | python3 -m json.tool | grep version
```

> **人工等待点**：等待 3 分钟，观察 lag 斜率。若变为负数（lag 在减少）→ 跳转 Step 14（收尾验证）。

---

### Step 12（分支 C2）：流量突增

```bash
# 确认当前生产速率
kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe

# 确认 topic 的 partition 数
kafka-topics.sh \
  --bootstrap-server <broker>:9092 \
  --describe \
  --topic <topic-name>
```

> **人工观察点**：
> - 当前 consumer 实例数是否 < partition 数（有空闲分区没人消费）
> - 生产速率是否超过当前消费能力上限

> **人工操作点**：
> 1. 若实例数 < partition 数：直接扩容消费者实例
> 2. 若实例数已等于 partition 数：扩 partition（需要评估 consumer 端是否支持动态扩 partition）
> 3. 临时方案：流量限速，联系上游生产者降低发送速率

---

### Step 13（分支 C3）：Broker 侧问题

```bash
# 检查 topic 的 under-replicated partitions
kafka-topics.sh \
  --bootstrap-server <broker>:9092 \
  --describe \
  --under-replicated-partitions

# 检查 broker 的 leader 分布是否均衡
kafka-topics.sh \
  --bootstrap-server <broker>:9092 \
  --describe \
  --topic <topic-name>
```

> **人工观察点**：
> - 是否有 under-replicated partition（副本未同步）
> - leader 是否集中在某个 broker（不均衡）

```bash
# 若 leader 不均衡，触发重新均衡
kafka-leader-election.sh \
  --bootstrap-server <broker>:9092 \
  --election-type PREFERRED \
  --all-topic-partitions
```

> **人工等待点**：等待 2 分钟，观察 leader 分布是否恢复均衡，consumer lag 是否停止增长。

---

## Step 14：收尾验证

所有分支处理完成后，执行以下验证步骤：

```bash
# 验证 lag 持续下降
watch -n 10 "kafka-consumer-groups.sh \
  --bootstrap-server <broker>:9092 \
  --group <consumer-group-name> \
  --describe | awk '{print \$5, \$6}'"
```

> **人工等待点**：持续观察 10 分钟，确认：
> 1. lag 值持续减少，斜率为负
> 2. 无分区 `CONSUMER-ID` 为 `-`
> 3. 消费速率 ≥ 生产速率

```bash
# 确认消费者无异常日志
tail -f /var/log/<service>/<service>.log | grep -iE "error|warn|timeout|exception" &
sleep 300 && kill %1
```

> **人工观察点**：5 分钟内无新增 ERROR/WARN 日志，lag 降至正常水位（< 1000）。

> **人工操作点**：
> 1. 若临时修改了 `max.poll.records` 或 `max.poll.interval.ms`，评估是否需要固化到配置文件
> 2. 若做了扩容，评估是否为长期方案或只是临时措施
> 3. 在监控系统关闭 lag 告警，确认恢复

---

## 写法说明

本文档包含以下结构元素，供参考：

| 元素 | 写法 | 含义 |
|------|------|------|
| 可执行命令 | ` ```bash ``` ` 代码块 | agent 可以直接执行 |
| 人工观察 | `> **人工观察点**` | 需要人眼读取输出并判断 |
| 人工操作 | `> **人工操作点**` | 需要物理操作或人工介入 |
| 分支判断 | `> **人工判断点（分支 X）**` | 根据观察结果选择路径 |
| 等待 | `> **人工等待点**` | 需要等待一段时间再继续 |
| 函数调用 | `> **（调用 <函数名>）**` | 调用调试函数/内部 API 获取信息 |
| 分支引用 | `进入**分支 A**（Step N）` | 跳转到文档内另一个分支 |
| 收尾跳转 | `→ 跳转 Step 14（收尾验证）` | 多分支共享的收尾步骤 |
