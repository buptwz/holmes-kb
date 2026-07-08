---
brief: Samsung DDR5 DIMM 颗粒缺陷导致 ECC 错误累积，48h burn-in 后触发服务器重启
category: memory
id: samsung-ddr5-dimm-ecc-error-burn-in-reboot
language: zh
tags:
- samsung
- ddr5
- dimm
- ecc
- burn-in
- sapphire-rapids
- memory-error
- npi
title: Samsung DDR5 DIMM ECC 错误累积导致 burn-in 重启
type: pitfall
---

## Symptoms

- 服务器运行 48-72 小时后自动重启，无 kernel panic
- BMC SEL 日志中 `Memory ECC Error` 事件从 slot A1/DIMM 0 开始递增
- `mcelog` 报告 corrected error count 超过 2000/小时
- 重启后短时内运行正常，但错误重新累积

## Root Cause

该批次 Samsung DDR5 DIMM 存在个别颗粒缺陷。在持续高温高负载下 single-bit error 率超出正常范围，累积为 uncorrectable error 触发系统重启。

**环境配置：**
- 平台：Intel Sapphire Rapids 双路服务器
- 内存：Samsung DDR5-4800 RDIMM 32GB × 16
- BIOS 版本：2.1.0-rc3
- BMC 固件版本：1.05.02

**排查过程：**

BMC 日志显示内存 ECC 错误计数快速递增，最终触发 BIOS 的 uncorrectable error 阈值。SEL 日志一致指向 CPU0 Channel A / DIMM slot 0。将 CPU0-A0 的 DIMM 与 CPU0-B0 的 DIMM 对调后，ECC 错误跟随 DIMM 迁移到新 slot，确认为 DIMM 本体故障。

## Resolution

### DIMM 本体故障 — 更换 DIMM 并执行 72h burn-in 验证

1. [api] 确认 ECC 错误位置：
   ```bash
   ipmitool sel list | grep -i "memory"
   ipmitool sdr type "Memory" | grep -i "ecc"
   mcelog --client
   ```

2. [decide] 若 SEL 日志一致指向同一 DIMM slot，执行 DIMM 交叉换位以区分 slot 问题与 DIMM 本体问题；否则排查其他原因。

3. [physical] 关机并断电，等待 30 秒。将疑故障 DIMM（如 CPU0-A0）与相邻 slot 的正常 DIMM（如 CPU0-B0）对调位置。

4. [physical] 重新上电，进入 BIOS 确认内存拓扑已变化。

5. [api] 运行压力测试 24 小时，观察 ECC 错误是否跟随 DIMM 迁移：
   ```bash
   memtester 28G 3
   stress-ng --vm 4 --vm-bytes 80% --timeout 86400
   ```

6. [decide] 若 ECC 错误跟随 DIMM 迁移到新 slot → 确认为 DIMM 本体故障，执行步骤 7；若错误仍停留在原 slot → 排查主板或 CPU 内存通道问题。

7. [physical] 更换故障 DIMM（从备件库取同批次 DIMM）。

8. [api] 清除 BMC SEL 日志：
   ```bash
   ipmitool sel clear
   ```

9. [api] 运行完整 burn-in 测试 72 小时，同时每小时监控 ECC 错误计数：
   ```bash
   stress-ng --vm 4 --vm-bytes 80% --timeout 259200 &
   watch -n 3600 'mcelog --client | tail -5'
   ```

10. [decide] 72 小时后确认 ECC 错误为 0 → 问题解决。若仍有错误，重复排查流程。

**经验总结：**
- NPI 阶段 burn-in 时间不应少于 72 小时，48 小时不足以暴露间歇性内存问题。
- ECC corrected error > 500/小时即应标记为可疑，不要等到 uncorrectable 才处理。
- DIMM 交叉换位是区分 slot 问题 vs DIMM 本体问题的标准方法。