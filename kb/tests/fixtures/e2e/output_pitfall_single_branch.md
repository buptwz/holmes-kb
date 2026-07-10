---
brief: Samsung DDR5 DIMM 颗粒缺陷导致 ECC 单比特错误累积，48h burn-in 后触发系统重启，交叉换位确认硬件故障后更换 DIMM
  并 72h burn-in 验证通过
category: memory
id: samsung-ddr5-ecc-single-bit-error-server-reboot
language: zh
tags:
- samsung
- ddr5
- ecc
- dimm
- burn-in
- memory-error
- sapphire-rapids
title: Samsung DDR5 DIMM ECC 单比特错误累积导致服务器重启
type: pitfall
---

## Contents

| Section | Description |
|---|---|
| Context | Intel Sapphire Rapids 双路平台，Samsung DDR5-4800 32GB×16，BIOS 2.1.0-rc3，BMC 1.05.02 |
| Symptoms | 4 个可观测现象：48-72h 自动重启、BMC SEL 递增、mcelog >2000/h、重启后重现 |
| Root Cause | Samsung DDR5 颗粒缺陷，高温高负载下单比特错误累积导致系统重启 |
| Resolution | 3 步排查：确认位置(ipmitool/mcelog)、交叉换位验证、更换 DIMM 后 72h burn-in |
| Lessons | 3 条经验：burn-in≥72h、ECC>500/h 可疑、交叉换位法 |

## Context

- **平台**: Intel Sapphire Rapids 双路服务器
- **内存**: Samsung DDR5-4800 RDIMM 32GB × 16
- **BIOS 版本**: 2.1.0-rc3
- **BMC 固件版本**: 1.05.02
- **现象**: 该服务器在 burn-in 压力测试 48 小时后出现间歇性重启。BMC 日志显示内存 ECC 错误计数快速递增，最终触发 BIOS 的 uncorrectable error 阈值。

## Symptoms

- 服务器运行 48-72 小时后自动重启，**无 kernel panic**
- BMC SEL 日志中 `Memory ECC Error` 事件从 slot A1/DIMM 0 开始递增
- `mcelog` 报告 corrected error count 超过 **2000/小时**
- 重启后短时间内运行正常，但错误重新累积

## Root Cause

该批次 Samsung DDR5 DIMM 存在个别颗粒缺陷，在持续高温高负载下 single-bit error 率超出正常范围，最终累积为 uncorrectable error 触发系统重启。

SEL 日志一致指向 **CPU0 Channel A / DIMM slot 0**。交换 DIMM 后 ECC 错误跟随 DIMM 迁移到新 slot，确认为 DIMM 本体故障，而非 slot 或主板问题。

## Resolution

### 第一步：确认 ECC 错误位置

1. [api:read] 查看 SEL 日志中的内存相关事件：
   ```bash
   ipmitool sel list | grep -i "memory"
   ```
   Expected: 显示内存相关的 SEL 事件；如有 Memory ECC Error 则输出事件行，空输出表示无相关事件

2. [api:read] 查看内存传感器中 ECC 状态：
   ```bash
   ipmitool sdr type "Memory" | grep -i "ecc"
   ```
   Expected: 显示内存传感器中 ECC 相关的状态信息

3. [api:read] 查看 machine check 日志中的 corrected error 计数：
   ```bash
   mcelog --client
   ```
   Expected: 输出 machine check 日志，包括 corrected error 计数；持续增长表明问题

4. [decide] 观察输出是否一致指向同一 DIMM slot。若 SEL 日志指向 CPU0 Channel A / DIMM slot 0，则进入第二步。

### 第二步：交叉换位验证——区分 slot 问题 vs DIMM 本体问题

1. [physical] 关机并断电，等待 30 秒。
2. [physical] 将疑似故障 DIMM 与相邻 slot 的正常 DIMM 对调位置。
3. 确认内存拓扑已变化后，运行快速内存测试：
   ```bash
   memtester 28G 3
   ```
   Expected: 分配 28GB 内存运行 3 次测试，正常通过时输出 pass 信息，失败则报告错误

4. [api:write] 运行 24 小时压力测试，监控 ECC 错误是否随 DIMM 迁移：
   ```bash
   stress-ng --vm 4 --vm-bytes 80% --timeout 86400
   ```
   Expected: 24 小时内存压力测试，期间监控 ECC 错误是否随 DIMM 迁移

5. [verify] ECC 错误跟随 DIMM 迁移到新 slot → 确认为 DIMM 本体故障；若错误停留在原 slot → 排查主板或 CPU 通道问题。

### 第三步：更换 DIMM 并 72h burn-in 验证

1. [physical] 更换故障 DIMM（从备件库取同批次 DIMM）。
2. [api:write] 清除 BMC SEL 日志，为后续验证提供干净基线：
   ```bash
   ipmitool sel clear
   ```
   Expected: 清除所有 SEL 日志，为后续验证提供干净基线

3. [api:write] 后台运行 72 小时压力测试，用于 burn-in 验证：
   ```bash
   stress-ng --vm 4 --vm-bytes 80% --timeout 259200 &
   ```
   Expected: 后台运行 72 小时压力测试，用于 burn-in 验证

4. [api:read] 每小时自动检查一次 mcelog，监控 ECC 错误计数变化：
   ```bash
   watch -n 3600 'mcelog --client | tail -5'
   ```
   Expected: 每小时自动检查一次 mcelog 最新 5 行，监控 ECC 错误计数变化

5. [verify] 72 小时后确认 ECC 错误为 0 → 问题解决；仍有错误 → 返回第一步排查。

## Lessons

1. **Burn-in 时间不应少于 72 小时**：NPI 阶段 48 小时不足以暴露间歇性内存问题。本案例中错误在 48-72 小时窗口才触发 uncorrectable 导致重启。
2. **ECC corrected error > 500/小时即应标记为可疑**：不要等到 uncorrectable 才处理。本案例中错误率高达 2000/小时才被注意到，早期发现可避免系统重启。
3. **DIMM 交叉换位是区分 slot 问题 vs DIMM 本体问题的标准方法**：交换后错误跟随 DIMM 迁移即可确认 DIMM 故障，避免误换主板或 CPU。