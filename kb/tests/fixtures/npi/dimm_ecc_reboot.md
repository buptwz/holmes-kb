# DIMM ECC 错误累积导致服务器重启 — 排查与定位

## 背景

2026-05-15，某客户 NPI 阶段 Granite Rapids 平台（Intel Xeon 6900P 双路，Samsung DDR5-5600 RDIMM 32GB × 32）burn-in 测试中，3 台服务器在运行 48-72 小时后自动重启，无 kernel panic 日志。

## 现象

- 服务器在 burn-in 48-72h 后突然重启，无任何操作系统层面的 crash dump
- BMC SEL（System Event Log）中记录了大量 Memory ECC Error 事件，集中在 CPU0 Channel A / DIMM 0（slot A1）
- 重启前最后 1 小时，ECC correctable error 速率从正常的 < 10/h 飙升到 2000+/h
- BMC Web 界面显示 DIMM A1 健康状态变为 "Critical"
- 操作系统 `dmesg` 中可见：`EDAC MC0: 1 CE memory read error on CPU_SrcID#0_Ha#0_Chan#0_DIMM#0`
- 重启后系统能正常启动，但 burn-in 持续运行后问题在 24-48h 内复现

## 排查过程

### 第一步：确认 ECC 错误分布

登录 BMC，查看 SEL：

```bash
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sel list | grep -i "memory"
```

预期输出包含类似：
```
   7f | 05/15/2026 | 14:23:05 | Memory #0x53 | Correctable ECC | Asserted
   80 | 05/15/2026 | 14:23:06 | Memory #0x53 | Correctable ECC | Asserted
```

确认错误是否集中在同一个 sensor（#0x53 对应 CPU0 Ch.A DIMM0）：

```bash
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sel list | grep "Memory" | awk '{print $NF}' | sort | uniq -c | sort -rn
```

操作系统侧也可确认：

```bash
edac-util -s
edac-util -l
cat /sys/devices/system/edac/mc/mc0/csrow0/ch0_ce_count
```

若 ECC 错误集中在单一 DIMM/channel，进入第二步。

### 第二步：判断是 DIMM 本体故障还是 slot/通道故障

关键诊断方法：**DIMM 交换法**

1. 记录当前 DIMM A1（slot A1）的序列号：

```bash
dmidecode -t memory | grep -A 20 "Locator: A1"
```

关注 Serial Number 和 Part Number。

2. 将 DIMM A1 与同 channel 的另一个 slot（如 A2）互换：
   - 关机，断电，等待 30 秒
   - 佩戴 ESD 腕带
   - 将 slot A1 的 DIMM 移到 slot A2，slot A2 的 DIMM 移到 slot A1
   - 上电开机

3. 再次运行 burn-in 24 小时，观察 ECC 错误位置：

```bash
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sel list | tail -50 | grep "Memory"
```

**结果判断：**

- **情况 A：ECC 错误跟随 DIMM 移到了 A2 slot** → 确认 DIMM 本体故障（颗粒缺陷）
  - 动作：更换该 DIMM，使用同批次新 DIMM 替换
  - 更换后运行 72h burn-in 验证

- **情况 B：ECC 错误仍然出现在 A1 slot（新插入的 DIMM）** → slot 或 CPU IMC 通道故障
  - 进入第三步进一步定位

- **情况 C：交换后两个 slot 都不再报错** → 接触不良（重新插拔解决了问题）
  - 运行 72h burn-in 确认
  - 检查 DIMM 金手指是否有氧化痕迹

### 第三步：区分 slot 物理故障 vs CPU IMC 通道故障（仅情况 B）

1. 在故障 slot A1 中换入一根已知好的 DIMM（从正常服务器取来的）：

```bash
# 更换前记录好 DIMM 的序列号用于追踪
dmidecode -t memory | grep -A 20 "Locator: A1"
```

2. 运行 24h burn-in，如果仍然报错：

   - 检查 slot 物理状况：
     - 目视检查 DIMM slot 是否有弯针、异物、氧化
     - 使用放大镜检查 slot 金手指触点

   - 通过 BIOS/BMC 禁用故障 channel，测试其他 channel 是否正常：

```bash
# 通过 BIOS Setup → Advanced → Memory Configuration → Channel A: Disabled
# 或通过 BMC raw command（具体命令因平台而异）
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 raw 0x30 0x70 0x0c 0x01 0x00
```

3. 如果禁用 Channel A 后其他 channel 正常工作 → CPU IMC 的 Channel A 控制器可能有缺陷
   - 这种情况需要更换 CPU 或主板
   - 上报 RMA 流程

## 经验总结

1. ECC correctable error 速率 > 500/h 应视为异常，> 2000/h 通常意味着即将触发 uncorrectable error
2. BIOS 默认的 uncorrectable error 阈值通常在 correctable error 累积到一定数量后触发系统重启
3. burn-in 时间不应少于 72 小时，前 48h 很多问题不会暴露
4. DIMM 交换法是最可靠的定位手段，不要跳过这一步直接更换 DIMM
5. 同批次 DIMM 如果出现多个故障，需要向供应商反馈批次质量问题

## 环境信息

- 平台：Intel Granite Rapids (Xeon 6900P)
- BIOS：AMI Aptio V, v2.1.0
- BMC：OpenBMC v2.14
- 内存：Samsung DDR5-5600 RDIMM 32GB (M321R4GA3BB6-CQKOD), 32 条
- 操作系统：Ubuntu 22.04 LTS (kernel 5.15.0-91-generic)
- 测试工具：StressAppTest v1.0.9
