---
brief: 自研 AI 推理卡 v2.0 PCIe Gen5 link training 失败（故障率 15%），分物理连接/信号完整性/电气兼容性三路径排查
category: pcie/link-training
id: ai-inference-card-v2-pcie-gen5-link-training-failure
language: zh
tags:
- pcie-gen5
- link-training
- gpu-accelerator
- amd-epyc
- intel-spr
- riser-card
- aer
- signal-integrity
title: AI 推理卡 v2.0 PCIe Gen5 link training 失败排查
type: pitfall
---

## Symptoms

- `lspci` 无法识别 GPU 卡，或识别为 `unknown device`
- 服务器 BIOS POST 阶段 PCIe 初始化超时警告
- `dmesg` 中出现 `pcieport: AER: Corrected error` 或 `link training failed`
- 部分情况下卡能识别但 link speed 降级为 Gen3 x4（期望 Gen5 x16）

同一张卡在不同服务器上表现不一致。服务器混合使用 Platform-A (AMD EPYC) 和 Platform-B (Intel SPR)。GPU 加速卡为**自研 AI 推理卡 v2.0 (PCIe Gen5 x16)**，搭配 Riser card Rev 1.2。

## Root Cause

新设计的 GPU 加速卡在部分服务器上出现 PCIe link training 失败，故障率约 15%。故障分布和根因如下：

| 故障分类 | 占比 | 根因 |
|---|---|---|
| **物理连接不良** | 60% | Riser card Rev 1.2 的卡扣设计有缺陷，导致 GPU 卡插入后未能完全锁定，接触不良。已推动 Riser card Rev 1.3 修复该问题。 |
| **信号完整性不足** | 25% | Platform-B (Intel SPR) 的 slot 3/4 PCIe trace 过长，Gen5 margin 不足，导致 link training 失败或降级。 |
| **电气兼容性问题** | 15% | GPU 卡 v2.0 固件的 PCIe equalization 参数需要针对 AMD 平台调优，否则在 Platform-A 上易触发 AER 错误风暴。 |

## Resolution

根据 `lspci` 和设备状态选择对应的排查路径：

| 你看到的现象 | 对应分支 |
|---|---|
| `lspci` 完全看不到设备 | 路径 A：物理连接问题 |
| 设备可见但 link speed/width 降级 | 路径 B：信号完整性问题 |
| 设备可见但出现 AER 错误风暴 | 路径 C：电气兼容性问题 |

### 路径 A：物理连接问题

1. [physical] 关机断电，重新拔插 GPU 卡，确认金手指无氧化。
2. [physical] 检查 Riser card 连接器，确认卡扣完全锁定。
3. [physical] 用放大镜检查 PCIe 金手指是否有划痕或污染。
   ```bash
   lspci -nn | grep -i "accelerator\|gpu\|unknown"
   ```
4. [decide] 如果换 slot 后可识别 → Riser card 或原 slot 损坏，更换 Riser card。
5. [decide] 如果所有 slot 均不识别 → GPU 卡本体故障，送回硬件团队 RMA。
   ```bash
   dmidecode -t 9 | grep -A5 "Slot"
   ```

### 路径 B：信号完整性问题

1. [api] 确认 BIOS 中 PCIe 速率未被手动限制。
   ```bash
   lspci -vvv -s <BDF> | grep -E "LnkCap|LnkSta|Width|Speed"
   cat /sys/bus/pci/devices/<BDF>/link_speed
   cat /sys/bus/pci/devices/<BDF>/link_width
   ```
2. [api] 检查 PCIe trace 长度是否超规格——查阅 platform 设计文档。
3. [api] 在 BIOS 中手动降速到 Gen4，观察是否稳定。
4. [decide] 若 Gen4 稳定但 Gen5 不稳定 → 信号完整性 margin 不足，需要硬件团队评审 PCB layout。
   ```bash
   pcieye --slot <BDF> --gen 5 --lanes 0-15 --output eye_diagram.png
   setpci -s <BDF> CAP_EXP+0x10.l
   ```
5. [decide] 若 Gen4 也不稳定 → 走路径 A 检查物理连接。

### 路径 C：电气兼容性问题

1. [api] 采集 AER 错误详细信息。
   ```bash
   dmesg | grep -iE "pcie|aer|link"
   cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable
   cat /sys/bus/pci/devices/<BDF>/aer_dev_fatal
   ```
2. [api] 检查 GPU 卡功耗是否超标。
   ```bash
   ipmitool sdr | grep -i "pcie\|gpu\|power"
   ```
3. [physical] 用示波器测量 12V 辅助供电纹波，确认 < 50mV。
4. [decide] 如果功耗/纹波正常但 AER 持续 → 检查 GPU 固件版本，升级至最新。
   ```bash
   gpu-flash --query
   gpu-flash --update firmware_v2.1.bin --slot <BDF>
   ```
5. [api] 固件升级后需重启并监控 24 小时。
   ```bash
   watch -n 60 'cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable'