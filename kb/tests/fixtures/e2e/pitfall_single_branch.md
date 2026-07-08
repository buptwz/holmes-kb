# DIMM ECC 单比特错误导致服务器间歇性重启

## 背景

某数据中心 NPI 验证阶段，新批次服务器在 burn-in 压力测试 48 小时后出现间歇性重启。
BMC 日志显示内存 ECC 错误计数快速递增，最终触发 BIOS 的 uncorrectable error 阈值。

## 环境

- 平台: Intel Sapphire Rapids 双路服务器
- 内存: Samsung DDR5-4800 RDIMM 32GB × 16
- BIOS 版本: 2.1.0-rc3
- BMC 固件: 1.05.02

## 症状

- 服务器运行 48-72 小时后自动重启，无 kernel panic
- BMC SEL 日志中 `Memory ECC Error` 事件从 slot A1/DIMM 0 开始递增
- `mcelog` 报告 corrected error count 超过 2000/小时
- 重启后短时间内运行正常，但错误重新累积

## 排查过程

### 第一步：确认 ECC 错误位置

通过 BMC 命令行确认具体 DIMM 位置：

```bash
$ ipmitool sel list | grep -i "memory"
$ ipmitool sdr type "Memory" | grep -i "ecc"
$ mcelog --client
```

SEL 日志一致指向 CPU0 Channel A / DIMM slot 0。

### 第二步：验证是否为 DIMM 硬件问题

将疑似故障 DIMM 与相邻 slot 的正常 DIMM 交换位置：

1. [physical] 关机并断电，等待 30 秒
2. [physical] 将 CPU0-A0 的 DIMM 与 CPU0-B0 的 DIMM 对调
3. 重新上电，进入 BIOS 确认内存拓扑已变化
4. 运行压力测试 24 小时

```bash
$ memtester 28G 3
$ stress-ng --vm 4 --vm-bytes 80% --timeout 86400
```

结果：ECC 错误跟随 DIMM 迁移到新 slot → 确认为 DIMM 本体故障。

### 第三步：更换 DIMM 并验证

1. [physical] 更换故障 DIMM（从备件库取同批次 DIMM）
2. 清除 BMC SEL 日志：

```bash
$ ipmitool sel clear
```

3. 运行完整 burn-in 测试 72 小时：

```bash
$ stress-ng --vm 4 --vm-bytes 80% --timeout 259200 &
$ watch -n 3600 'mcelog --client | tail -5'
```

4. 72 小时后确认 ECC 错误为 0，问题解决。

## 根因

该批次 Samsung DDR5 DIMM 存在个别颗粒缺陷，在持续高温高负载下 single-bit error 率
超出正常范围，最终累积为 uncorrectable error 触发系统重启。

## 经验总结

- NPI 阶段 burn-in 时间不应少于 72 小时，48 小时不足以暴露间歇性内存问题
- ECC corrected error > 500/小时即应标记为可疑，不要等到 uncorrectable 才处理
- DIMM 交叉换位是区分 slot 问题 vs DIMM 本体问题的标准方法
