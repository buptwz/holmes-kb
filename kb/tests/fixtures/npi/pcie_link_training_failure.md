# PCIe Link Training 失败排查 — GPU 卡在 NPI 平台上无法识别或降速

## 背景

NPI 阶段验证 Granite Rapids 平台与 NVIDIA A100/H100 GPU 卡的兼容性时，发现部分 slot 出现 PCIe link training 失败或降速现象。

## 现象

两种典型表现：

**表现一：设备完全不可见**
- `lspci` 输出中看不到 GPU 设备
- BMC SEL 中记录 `PCI Express Fatal Error` 或 `Slot X Power Fault`
- 物理上 GPU 卡的电源 LED 不亮或闪烁

**表现二：设备可见但降速**
- `lspci` 能看到 GPU 设备，但速率降级
- 预期 Gen5 x16，实际显示 Gen3 x8 或更低
- GPU 计算性能下降 50% 以上
- `dmesg` 中可能有 `PCIe Bus Error: severity=Corrected, type=Physical Layer` 警告

## 排查步骤

### Step 1: 确认 PCIe 拓扑和当前链路状态

```bash
# 查看完整 PCIe 拓扑
lspci -tv

# 查看 GPU 设备详细信息（如果可见）
lspci -vvv -s $(lspci | grep -i nvidia | awk '{print $1}') 2>/dev/null

# 检查链路速率和宽度
lspci -vvv | grep -E "(LnkCap|LnkSta)" | head -20

# 通过 setpci 直接读取 PCIe capability
# 首先找到 GPU 的 bus:dev.fn
GPU_BDF=$(lspci | grep -i nvidia | head -1 | awk '{print $1}')
if [ -n "$GPU_BDF" ]; then
    # 读取 Link Status Register (offset 0x12 in PCIe Capability)
    setpci -s $GPU_BDF CAP_EXP+0x12.w
fi
```

Link Status Register 解读：
- Bits [3:0] = Current Link Speed (1=Gen1, 2=Gen2, 3=Gen3, 4=Gen4, 5=Gen5)
- Bits [9:4] = Negotiated Link Width (x1=01, x4=04, x8=08, x16=10)

### Step 2: 根据现象分支处理

**如果 lspci 完全看不到 GPU → 进入分支 A（设备不可见）**

**如果 lspci 能看到但速率/宽度不对 → 进入分支 B（降速）**

---

### 分支 A：设备完全不可见

#### A-1: 检查物理连接

- 关机断电
- 检查 GPU 卡是否完全插入 PCIe slot（金手指完全没入，卡扣锁定）
- 检查 GPU 辅助供电线缆是否连接（8-pin 或 12-pin 电源接口）
- 检查 GPU 卡的电源 LED 状态：
  - 不亮：供电问题
  - 红色常亮：硬件故障
  - 绿色常亮：正常
- 目视检查 PCIe slot 金手指是否有弯针或异物

#### A-2: 换 slot 测试

将 GPU 卡移到另一个已知工作的 PCIe slot（建议使用 CPU direct-attached slot，避免 PCH downstream slot）：

```bash
# 重新上电后检查
lspci | grep -i nvidia
dmesg | grep -iE "(pci|nvidia|gpu)" | tail -20
```

- 换 slot 后 GPU 可见 → 原 slot 有问题（可能是 slot 物理损坏或 BIOS 中该 slot 被 disable）
  - 检查 BIOS Setup → Advanced → PCI Configuration → Slot X: Enabled
  - 如果 BIOS 中已 enable 但仍不工作 → 主板 slot 故障，上报 RMA

- 换 slot 后仍不可见 → GPU 卡本身问题
  - 在另一台已知正常的服务器上测试该 GPU 卡
  - 如果在正常服务器上也不工作 → GPU 卡故障，上报 RMA
  - 如果在正常服务器上工作 → 回到原服务器继续排查 BIOS/固件问题

#### A-3: 检查 BIOS PCIe 配置

```bash
# 通过 BMC 查看 BIOS 配置（部分平台支持）
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 raw 0x30 0x70 0x0c 0x03 0x01

# 或者进入 BIOS Setup:
# Advanced → PCI Configuration → PCIe Speed: Auto
# Advanced → PCI Configuration → Slot X Bifurcation: x16
# Advanced → PCI Configuration → Above 4G Decoding: Enabled
# Advanced → PCI Configuration → SR-IOV Support: Enabled (if needed)
```

确认 Bifurcation 设置与物理卡匹配（x16 GPU 需要 x16 bifurcation，不能设成 x4x4x4x4）。

---

### 分支 B：设备可见但降速

#### B-1: 确认期望速率

```bash
# 查看设备能力（LnkCap）vs 实际状态（LnkSta）
lspci -vvv -s $GPU_BDF | grep -E "(LnkCap|LnkSta)"
```

典型输出：
```
LnkCap: Port #0, Speed 32GT/s (Gen5), Width x16
LnkSta: Speed 8GT/s (Gen3), Width x8 (downgraded)
```

如果 LnkCap 显示 Gen5 x16 但 LnkSta 显示更低，说明 link training 落回到了低速模式。

#### B-2: 强制重新 link training

```bash
# 通过 setpci 触发 link retrain
# 找到上游 Root Port 的 BDF
ROOT_BDF=$(lspci -t -vv | grep -B5 "$GPU_BDF" | grep "Root Port" | head -1 | grep -oP '\d+:\d+\.\d+')

# 设置 Link Control Register 的 Retrain Link bit (bit 5)
setpci -s $ROOT_BDF CAP_EXP+0x10.w=0020:0020

# 等待 2 秒让 link training 完成
sleep 2

# 重新检查 link status
lspci -vvv -s $GPU_BDF | grep LnkSta
```

如果 retrain 后速率恢复 → 可能是一次性的 link training 问题，继续 burn-in 观察稳定性。

#### B-3: 检查信号质量

如果 retrain 后仍然降速，可能是信号完整性问题：

```bash
# 检查 PCIe AER (Advanced Error Reporting) 计数
cat /sys/bus/pci/devices/0000:$GPU_BDF/aer_dev_correctable 2>/dev/null
cat /sys/bus/pci/devices/0000:$GPU_BDF/aer_dev_fatal 2>/dev/null

# 查看 dmesg 中的 PCIe 错误
dmesg | grep -i "pcie.*error\|aer\|link" | tail -20
```

常见原因：
- Riser card 接触不良 → 重新插拔 riser card
- PCIe slot 金手指氧化 → 用橡皮擦清洁
- PCIe retimer/redriver 配置不匹配 → 需要检查 BIOS retimer 配置或更新 retimer 固件
- 电磁干扰（EMI）→ 确认机箱屏蔽、线缆走线

#### B-4: 降级测试

如果无法在 Gen5 稳定运行，可以尝试锁定到 Gen4：

```bash
# 在 BIOS 中设置：
# Advanced → PCI Configuration → PCIe Speed: Gen4

# 或通过 setpci 设置 Target Link Speed
setpci -s $ROOT_BDF CAP_EXP+0x30.w=0004:000f  # 4=Gen4
setpci -s $ROOT_BDF CAP_EXP+0x10.w=0020:0020   # retrain
sleep 2
lspci -vvv -s $GPU_BDF | grep LnkSta
```

如果 Gen4 稳定 → 记录为 Gen5 兼容性问题，上报给平台和 GPU 供应商联合排查。

## 经验总结

1. Granite Rapids 平台 Gen5 目前在部分 slot（尤其是通过 PCH 下行的 slot 3-6）存在 15% 左右的 link training 失败率，建议 GPU 优先使用 CPU direct-attached slot（slot 1-2）
2. 如果必须使用 slot 3-6，建议 BIOS 中将 PCIe Speed 锁定为 Gen4，牺牲约 3% 带宽换取稳定性
3. Riser card 的接触不良是最常见的物理层原因，拔插一次解决 60% 的问题
4. NVIDIA H100 比 A100 对信号质量更敏感（Gen5 vs Gen4），切换卡型时要重新验证
