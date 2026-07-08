# PCIe Link Training 失败的多路径排查

## 背景

NPI 验证阶段，新设计的 GPU 加速卡在部分服务器上出现 PCIe link training 失败。
故障率约 15%，且同一张卡在不同服务器上表现不一致。

## 环境

- GPU 加速卡: 自研 AI 推理卡 v2.0 (PCIe Gen5 x16)
- 服务器平台: 混合使用 Platform-A (AMD EPYC) 和 Platform-B (Intel SPR)
- Riser card: Rev 1.2

## 症状

- `lspci` 无法识别 GPU 卡，或识别为 unknown device
- 服务器 BIOS POST 阶段 PCIe 初始化超时告警
- dmesg 中出现 `pcieport: AER: Corrected error` 或 `link training failed`
- 部分情况下卡能识别但 link speed 降级为 Gen3 x4（期望 Gen5 x16）

## 排查过程

### 第一步：采集 PCIe 链路状态

```bash
$ lspci -vvv -s <BDF> | grep -E "LnkCap|LnkSta|Width|Speed"
$ dmesg | grep -iE "pcie|aer|link"
$ cat /sys/bus/pci/devices/<BDF>/link_speed
$ cat /sys/bus/pci/devices/<BDF>/link_width
```

根据采集结果，故障分为三种情况：

| 现象 | 分类 |
|------|------|
| lspci 完全看不到设备 | → 路径 A：物理连接问题 |
| 设备可见但 link speed/width 降级 | → 路径 B：信号完整性问题 |
| 设备可见但出现 AER 错误风暴 | → 路径 C：电气兼容性问题 |

---

### 路径 A：物理连接问题

当 `lspci` 完全看不到设备时，通常是物理层问题：

1. [physical] 关机断电，重新拔插 GPU 卡，确认金手指无氧化
2. [physical] 检查 Riser card 连接器，确认卡扣完全锁定
3. [physical] 用放大镜检查 PCIe 金手指是否有划痕或污染
4. 更换到其他 PCIe slot 测试：

```bash
$ lspci -nn | grep -i "accelerator\|gpu\|unknown"
```

5. 如果换 slot 后可识别 → Riser card 或原 slot 损坏，更换 Riser card
6. 如果所有 slot 均不识别 → GPU 卡本体故障，送回硬件团队 RMA

### 路径 B：信号完整性问题

设备可见但 link 降级（如 Gen3 x4），通常是信号质量不达标：

1. 确认 BIOS 中 PCIe 速率未被手动限制：

```bash
$ dmidecode -t 9 | grep -A5 "Slot"
```

2. [physical] 检查 PCIe trace 长度是否超规格（查阅 platform 设计文档）
3. 尝试在 BIOS 中手动降速到 Gen4，观察是否稳定：

进入 BIOS → Advanced → PCIe Configuration → Max Link Speed → Gen4

4. 运行 PCIe 链路眼图测试（需要 platform debug 工具）：

```bash
$ pcieye --slot <BDF> --gen 5 --lanes 0-15 --output eye_diagram.png
```

5. 若 Gen4 稳定但 Gen5 不稳定 → 信号完整性 margin 不足，需要硬件团队评审 PCB layout
6. 若 Gen4 也不稳定 → 走路径 A 检查物理连接

### 路径 C：电气兼容性问题

设备可见且 link 正常，但持续 AER 错误：

1. 采集 AER 错误详细信息：

```bash
$ setpci -s <BDF> CAP_EXP+0x10.l
$ cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable
$ cat /sys/bus/pci/devices/<BDF>/aer_dev_fatal
```

2. 检查 GPU 卡功耗是否超标：

```bash
$ ipmitool sdr | grep -i "pcie\|gpu\|power"
```

3. [physical] 用示波器测量 12V 辅助供电纹波，确认 < 50mV
4. 如果功耗/纹波正常但 AER 持续 → 检查 GPU 固件版本，升级至最新：

```bash
$ gpu-flash --query
$ gpu-flash --update firmware_v2.1.bin --slot <BDF>
```

5. 固件升级后重启并监控 24 小时：

```bash
$ watch -n 60 'cat /sys/bus/pci/devices/<BDF>/aer_dev_correctable'
```

## 根因总结

PCIe link training 失败是一个多因素问题：
- 物理连接不良（占比 60%）：Riser card Rev 1.2 的卡扣设计有缺陷，已推动 Rev 1.3 修复
- 信号完整性（占比 25%）：Platform-B 的 slot 3/4 trace 过长，Gen5 margin 不足
- 电气兼容性（占比 15%）：GPU 卡 v2.0 固件的 PCIe equalization 参数需要针对 AMD 平台调优
