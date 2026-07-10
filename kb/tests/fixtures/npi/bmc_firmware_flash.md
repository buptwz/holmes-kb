# BMC 固件在线刷写操作流程

## 目的

本文档描述 OpenBMC 固件的在线刷写（不关机状态下刷写 BMC）标准操作流程。适用于 NPI 阶段批量升级 BMC 固件版本。

## 适用范围

- 平台：Intel Granite Rapids / Sierra Forest 系列
- BMC：OpenBMC v2.x
- 目标版本：v2.14 → v2.16

## 前置条件

- 已获取目标固件文件 `obmc-phosphor-image-*.static.mtd.tar`（约 32MB）
- BMC 网络可达（IPMI LAN 通道已配置）
- 服务器当前运行负载可以容忍 BMC 短暂不可达（刷写过程约 5-8 分钟）
- **必须确认当前 BMC 版本不低于 v2.10**（v2.10 之前的版本在线刷写有已知 bug，可能导致 BMC 变砖）

## 操作步骤

### Step 1: 备份当前 BMC 配置

```bash
# 导出当前 BMC 配置（包括网络设置、用户账户、传感器阈值）
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 raw 0x32 0x82
ssh admin@10.0.1.101 'busybox tar czf /tmp/bmc-backup.tar.gz /etc/network/ /etc/ipmi/'
scp admin@10.0.1.101:/tmp/bmc-backup.tar.gz ./bmc-backup-$(date +%Y%m%d).tar.gz
```

### Step 2: 检查当前 BMC 版本

```bash
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 mc info
```

预期输出中关注 `Firmware Revision` 字段，确认当前版本 ≥ 2.10。

如果版本 < 2.10，**停止操作**，必须使用离线刷写方式（通过 JTAG 或 SPI flash programmer）。

### Step 3: 上传固件文件

```bash
scp obmc-phosphor-image-*.static.mtd.tar admin@10.0.1.101:/tmp/
```

确认文件完整性：

```bash
ssh admin@10.0.1.101 'md5sum /tmp/obmc-phosphor-image-*.static.mtd.tar'
```

与发布包中的 md5 校验值比对。

### Step 4: 执行刷写

**⚠️ 警告：刷写过程中切勿断电或重启 BMC。中断刷写将导致 BMC 无法启动（变砖），需要物理拆机通过 SPI 恢复。**

```bash
ssh admin@10.0.1.101 'busybox nohup /usr/bin/phosphor-bmc-code-mgmt update /tmp/obmc-phosphor-image-*.static.mtd.tar &'
```

刷写过程约 5-8 分钟。期间 BMC 网络连接可能短暂中断（30-60 秒），这是正常现象。

### Step 5: 等待并验证

等待 10 分钟后，检查 BMC 是否恢复：

```bash
# 持续 ping BMC 直到恢复
ping -c 1 10.0.1.101 && echo "BMC is back" || echo "BMC still rebooting"
```

BMC 恢复后验证版本：

```bash
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 mc info
```

确认 `Firmware Revision` 显示目标版本 2.16。

### Step 6: 验证传感器和功能

```bash
# 检查传感器读数是否正常
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sdr list full

# 检查 SOL (Serial Over LAN) 是否工作
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sol activate

# 检查电源控制是否正常
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 chassis power status

# 检查风扇控制是否正常
ipmitool -I lanplus -H 10.0.1.101 -U admin -P admin123 sdr type Fan | head -5
```

如果传感器读数异常（显示 "No Reading" 或 "ns"）：

```bash
# 重启 BMC 传感器服务
ssh admin@10.0.1.101 'systemctl restart phosphor-hwmon@*.service'
```

等待 30 秒后重新检查。

### Step 7: 恢复配置（如需要）

如果刷写后 BMC 配置被重置（网络 IP 变化、用户账户丢失）：

```bash
scp bmc-backup-*.tar.gz admin@10.0.1.101:/tmp/
ssh admin@10.0.1.101 'cd / && busybox tar xzf /tmp/bmc-backup-*.tar.gz'
ssh admin@10.0.1.101 'systemctl restart xyz.openbmc_project.Network.service'
```

## 回滚方案

如果新版本有兼容性问题需要回滚：

1. 重复上述步骤，使用旧版本固件文件进行刷写
2. 如果 BMC 已无法访问（变砖），需要：
   - 拆开服务器机箱
   - 找到 BMC SPI flash 芯片（通常在主板正面靠近 BMC 芯片的位置）
   - 使用 SPI flash programmer（如 CH341A）连接并刷入恢复固件
   - 这需要硬件工程师操作，预计耗时 30 分钟

## 批量操作注意事项

- 同一机柜内的服务器**不要并行刷写**，逐台进行，每台确认成功后再刷下一台
- 建议每 10 台做一次检查点，确认无异常后继续
- 保留至少 1 台未升级的服务器作为对照
