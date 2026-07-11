---
brief: 'PCIe Link Training fails in 15% of GPU cards; three root causes: physical
  connection (60%), signal integrity (25%), electrical compatibility (15%).'
category: pcie/link-training
decision_map:
- branch: 路径 A：物理连接问题
  symptom: lspci 完全看不到设备
- branch: 路径 B：信号完整性问题
  symptom: 设备可见但 link speed/width 降级（如 Gen3 x4 而非 Gen5 x16）
- branch: 路径 C：电气兼容性问题
  symptom: 设备可见且 link 正常，但持续出现 AER 错误
id: gpu-accelerator-card-pcie-link-training-failure
language: zh
tags:
- pcie
- gen5
- link-training
- gpu
- riser-card
- aer
- signal-integrity
title: GPU 加速卡 PCIe Link Training 失败多路径排查
type: pitfall
---

## Contents

```
PCIe link training failure
├─ lspci cannot see device? ─→ [A] Physical connection problem
│   ├─ Recognized after slot change ─→ ✓ Riser card or slot damaged, replace Riser
│   └─ Not recognized in any slot ─→ ✓ GPU card fault, RMA
├─ Device visible but link degraded? ─→ [B] Signal integrity problem
│   ├─ Gen4 stable, Gen5 unstable ─→ ✓ Signal integrity margin insufficient, review PCB layout
│   └─ Gen4 also unstable ─→ 转 [A] Physical connection problem
└─ Device visible but AER error storm? ─→ [C] Electrical compatibility problem
    ├─ Power/ripple normal but AER persists ─→ ✓ Firmware upgrade
    └─ Power or ripple abnormal ─→ ✓ Check power supply issue
```

## Context

NPI 验证阶段，新设计的自研 AI 推理卡 v2.0（PCIe Gen5 x16）在部分服务器上出现 PCIe link training 失败。故障率约 15%，且同一张卡在不同服务器上表现不一致。涉及的服务器平台为混合使用的 Platform-A（AMD EPYC）和 Platform-B（Intel SPR），Riser card 版本为 Rev 1.2。

## Symptoms

- `lspci` 无法识别 GPU 卡，或识别为 unknown device
- 服务器 BIOS POST 阶段 PCIe 初始化超时警告
- `dmesg` 中出现 `pcieport: AER: Corrected error` 或 `link training failed`
- 部分情况下卡能识别但 link speed 降级为 Gen3 x4（期望 Gen5 x16）
- `lspci` 完全看不到 GPU 设备（路径 A 触发条件）
- 设备可见但 link speed 降级为 Gen3 x4（期望 Gen5 x16）（路径 B 触发条件）
- 设备可见且 link 正常，但持续出现 AER 错误风暴（路径 C 触发条件）

## Root Cause

PCIe link training 失败是一个多因素问题，根据排查数据统计有三种根因：

- **物理连接不良（占比 60%）**：Riser card Rev 1.2 的卡扣设计有缺陷，导致接触不良，已推动 Rev 1.3 修复。这是最主要的故障原因。
- **信号完整性问题（占比 25%）**：Platform-B 的 slot 3/4 trace 过长，Gen5 margin 不足。
- **电气兼容性问题（占比 15%）**：GPU 卡 v2.0 固件的 PCIe equalization 参数需要针对 AMD 平台调优。

## Resolution

### 第一步：采集 PCIe 链路状态

根据现象分类，首先收集 PCIe link 状态信息：

| 你看到的现象 | 对应分支 |
|---|---|
| `lspci` 完全看不到设备 | 路径 A：物理连接问题 |
| 设备可见但 link speed/width 降级（如 Gen3 x4 而非 Gen5 x16） | 路径 B：信号完整性问题 |
| 设备可见且 link 正常，但持续 AER 错误 | 路径 C：电气兼容性问题 |

1. [api:read] 查看 PCIe 链路能力和协商状态：
   ```bash
   lspci -vvv -s <BDF> | grep -E "LnkCap|LnkSta|Width|Speed"
   ```
   Expected: Displays link capabilities, status, negotiated width and speed. Empty output indicates device not detected.

2. [api:read] 检查内核 PCIe 相关日志：
   ```bash
   dmesg | grep -iE "pcie|aer|link"
   ```
   Expected: Shows PCIe-related kernel messages. Presence of 'link training failed' or AER errors indicates failure.

3. [api:read] 读取 sysfs 中的链路速度：
   ```bash
   cat /sys/bus/pci/devices/<BDF>/link_speed
   ```
   Expected: Outputs current link speed in GT/s. Empty or file not found means device not present.

4. [api:read] 读取 sysfs 中的链路宽度：
   ```bash
   cat /sys/bus/pci/devices/<BDF>/link_width
   ```
   Expected: Outputs current link width, e.g., x16, x8, x4. Smaller width indicates degradation.

根据采集结果，故障分为三种情况，选择对应诊断路径。

---

### 路径 A：物理连接问题

当 `lspci` 完全看不到设备时，通常是物理层问题。

1. [physical] 关机断电，重新拔插 GPU 卡，确认金手指无氧化。
2. [physical] 检查 Riser card 连接器，确认卡扣完全锁定。
3. [physical] 用放大镜检查 PCIe 金手指是否有划痕或污染。
4. [api:read] 更换到其他 PCIe slot 测试设备是否可识别：
   ```bash
   lspci -nn | grep -i "accelerator\|gpu\|unknown"
   ```
   Expected: 输出为空则设备完全不可见（路径 A）；输出 accelerator/gpu 但为 unknown device 则需进一步判断
5. [decide] 判断结果：
   - 换 slot 后可识别 → Riser card 或原 slot 损坏，更换 Riser card
   - 所有 slot 均不识别 → GPU 卡本体故障，送回硬件团队 RMA

---

### 路径 B：信号完整性问题

设备可见但 link 降级（如 Gen3 x4），通常是信号质量不达标。

1. [api:read] 确认 BIOS 中 PCIe 速率未被手动限制：
   ```bash
   dmidecode -t 9 | grep -A5 "Slot"
   ```
   Expected: 显示 PCIe slot 信息和能力，确认 BIOS 是否限制了速率
2. [physical] 检查 PCIe trace 长度是否超规格（查阅 platform 设计文档）。
3. [physical] 尝试在 BIOS 中手动降速到 Gen4，观察是否稳定：

   进入 BIOS → Advanced → PCIe Configuration → Max Link Speed → Gen4

4. [api:read] 运行 PCIe 链路眼图测试（需要 platform debug 工具）：
   ```bash
   pcieye --slot <BDF> --gen 5 --lanes 0-15 --output eye_diagram.png
   ```
   Expected: 生成 PCIe 链路眼图，评估信号完整性 margin
5. [decide] 判断结果：
   - 若 Gen4 稳定但 Gen5 不稳定 → 信号完整性 margin 不足，需要硬件团队评估 PCB layout
   - 若 Gen4 也不稳定 → 走路径 A 检查物理连接

---

### 路径 C：电气兼容性问题

设备可见且 link 正常，但持续 AER 错误。

1. [api:read] 采集 AER 错误详细信息：
   ```bash
   setpci -s <BDF> CAP_EXP+0x10.l
   cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable
   cat /sys/bus/pci/devices/<BDF>/aer_dev_fatal
   ```
   Expected: setpci 显示 PCIe 设备能力寄存器值，用于分析 AER 能力；aer_dev_correctable 显示可纠正 AER 错误计数；aer_dev_fatal 显示致命 AER 错误计数
2. [api:read] 检查 GPU 卡功耗是否超标：
   ```bash
   ipmitool sdr | grep -i "pcie\|gpu\|power"
   ```
   Expected: 显示 GPU 功耗读数，判断是否超标
3. [physical] 用示波器测量 12V 辅助供电纹波，确认 < 50mV。
4. [decide] 判断结果：
   - 如果功耗/纹波正常但 AER 持续 → 检查 GPU 固件版本，升级至最新
   - 如果功耗或纹波异常 → 检查电源供应问题
5. [api:read] 查询当前 GPU 固件版本：
   ```bash
   gpu-flash --query
   ```
   Expected: 显示当前 GPU 固件版本
6. [api:danger] 升级 GPU 固件到最新版本（需确认后执行）：
   ```bash
   gpu-flash --update firmware_v2.1.bin --slot <BDF>
   ```
   Expected: 刷写 GPU 固件到指定版本；成功后需重启
7. [api:read] 固件升级后重启并监控 24 小时：
   ```bash
   watch -n 60 'cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable'
   ```
   Expected: 每 60 秒监控一次 AER 可纠正错误计数，观察趋势