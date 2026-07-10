---
brief: Granite-X 服务器 NVMe SSD 间歇性掉盘，根因为散热设计缺陷 + Samsung PM9A3 固件 GDC7302Q 热保护阈值 70°C
  过激
category: storage/nvme
decision_map:
- branch: 路径 A：散热导致的热保护掉盘
  symptom: 掉盘集中在特定 slot 位置（slot 9-12 或 21-24），且伴随温度过高
- branch: 路径 B：PCIe Switch 链路稳定性问题
  symptom: 掉盘随机分布且伴随 PCIe AER 错误
- branch: 路径 C：SSD 固件导致的异常掉盘
  symptom: 掉盘前 SMART critical_warning 非零
id: granite-x-nvme-ssd-intermittent-loss
language: zh
tags:
- granite-x
- nvme
- samsung-pm9a3
- heat-protection
- pcie-switch
- pex89048
- ssd-firmware
- burn-in
title: Granite-X 服务器 NVMe SSD 间歇性掉盘
type: pitfall
---

## Contents

```
NVMe SSD 间歇性掉盘
├─ 掉盘集中在特定 slot（9-12/21-24）且温度高? ─→ [路径 A：散热导致的热保护掉盘]
│   ├─ 全速风扇 72h 无掉盘 ─→ ✓ 确认散热问题，优化风道/调整风扇曲线
│   └─ 仍掉盘 ─→ A 不是唯一原因，继续排查
├─ 掉盘随机分布且伴 PCIe AER 错误? ─→ [路径 B：PCIe Switch 链路稳定性问题]
│   ├─ Surprise Link Down 与升温时间点吻合 ─→ 转 [路径 A]
│   ├─ Link Down 伴 Switch 固件 assertion ─→ ✓ PCIe Switch 固件 bug，联系 Broadcom
│   └─ Link Down 集中在特定端口 ─→ ✓ backplane 信号质量问题，需 SI 测试
└─ 掉盘前 SMART critical_warning 非零? ─→ [路径 C：SSD 固件导致的异常掉盘]
    ├─ bit 4 (volatile memory backup) 非零 ─→ ✓ 联系 Samsung FAE，确认电容批次问题
    └─ bit 0 (spare space) 非零 ─→ ✓ SSD 写入寿命问题，检查压测写入量
```

## Symptoms

- 压力测试运行 72-96 小时后，1-3 块 NVMe SSD 突然从系统中消失，无法通过 `lsblk` 或 `nvme list` 检测到
- `dmesg` 出现 `'nvme nvmeX: I/O timeout'` 和 `'nvme nvmeX: Controller not ready; aborting reset'` 错误
- `nvme smart-log` 在掉盘前显示 `critical_warning` 字段非零（bit 4: volatile memory backup device failed）
- BMC 传感器日志记录到 NVMe backplane 区域温度达到 72°C（阈值 70°C）
- 掉盘现象集中在 backplane 的 slot 9-12 和 slot 21-24（靠近电源模块侧）
- 重启后所有 NVMe 盘恢复正常，SMART 数据无永久性错误标记
- PCIe Switch 的 event log 中记录了 Surprise Link Down 事件

## Root Cause

该问题由两个因素叠加造成：

1. **散热设计缺陷（主因，占比 70%）**：Granite-X 的 NVMe backplane 风道设计不合理，slot 9-12 和 21-24 位于电源模块热辐射区域，长时间满负载运行时 SSD 表面温度超过 70°C 触发固件的热保护掉盘。增加导风罩后 slot 间温差从 12°C 降至 4°C，问题消除。

2. **SSD 固件热保护阈值过于激进（次因，占比 30%）**：Samsung PM9A3 固件版本 GDC7302Q 的 composite temperature 热保护阈值设为 70°C，数据手册标称工作温度为 0-70°C，在高密度部署场景中过于激进。升级至 GDC7502Q 后阈值调整为 75°C，并增加了渐进式降速策略（70°C 开始降速，75°C 才掉盘）。

**环境详情**：Granite-X 双路服务器（Intel Emerald Rapids 平台，CPU Intel Xeon w9-3595X × 2），Samsung PM9A3 3.84TB × 24（U.2 接口，固件 GDC7302Q），NVMe backplane Rev 2.1（支持 24 × U.2 热插拔），PCIe Switch Broadcom PEX89048（48-lane PCIe Gen4 switch，每个管理 12 块 NVMe 盘，共 2 个 Switch 覆盖 24 块盘，通过 PCIe Gen4 x16 上联至 CPU），Ubuntu 22.04 LTS（kernel 5.15.0-91），BIOS 1.3.2-beta，BMC OpenBMC 2.12.0，散热方案为前端 6 × 8038 风扇 + 后端 2 × 6038 风扇。

## Resolution

| 你看到的现象 | 对应分支 |
|---|---|
| 掉盘集中在特定 slot 位置（slot 9-12 或 21-24），且伴随温度过高 | 路径 A：散热导致的热保护掉盘 |
| 掉盘随机分布且伴随 PCIe AER 错误 | 路径 B：PCIe Switch 链路稳定性问题 |
| 掉盘前 SMART critical_warning 非零 | 路径 C：SSD 固件导致的异常掉盘 |

先进行初步信息采集，确认掉盘模式后再选择对应分支。

### 初步信息采集

1. [api:read] 列出当前所有 NVMe 设备：
   ```bash
   nvme list -o json
   ```
   Expected: 列出所有已识别的 NVMe 设备，包括 model、firmware version、serial number

2. [api:read] 查看每块 NVMe 的 PCIe 链路状态：
   ```bash
   for dev in /sys/class/nvme/nvme*; do echo "=== $(basename $dev) ==="; cat $dev/address; lspci -vvv -s $(cat $dev/address) | grep -E "LnkSta|Speed|Width"; done
   ```
   Expected: 列出每块 NVMe 的 BDF 地址和当前 PCIe link speed/width

3. [api:read] 检查 dmesg 中 NVMe 相关的错误历史：
   ```bash
   dmesg -T | grep -iE "nvme|pcie.*error|aer" | tail -50
   ```
   Expected: 查看最近 50 条 NVMe 和 PCIe 错误日志，定位掉盘时间点和受影响设备

4. [api:read] 查看 BMC 传感器中 NVMe backplane 温度历史：
   ```bash
   ipmitool sdr list | grep -iE "nvme|backplane|ssd"
   ```
   Expected: 查看 NVMe backplane 区域的温度传感器读数

5. [api:read] 获取 PCIe Switch 的事件日志：
   ```bash
   switchtec log-dump /dev/switchtec0 -o switch0_log.txt && tail -100 switch0_log.txt
   ```
   Expected: 导出 PCIe Switch 事件日志，查看是否有 Surprise Link Down 记录

6. [api:read] 持续监控 NVMe 盘面温度，识别热点：
   ```bash
   while true; do for dev in /dev/nvme*n1; do echo -n "$(basename $dev): "; nvme smart-log $dev | grep "temperature"; done; echo "---$(date)---"; sleep 60; done
   ```
   Expected: 每 60 秒轮询所有 NVMe 盘面温度，识别持续高温的盘位

7. [decide] 分析掉盘模式：
   - 掉盘集中在特定 slot 位置（slot 9-12 或 21-24）→ 走路径 A（散热问题）
   - 掉盘随机分布且伴随 PCIe AER 错误 → 走路径 B（PCIe Switch 问题）
   - 掉盘前 SMART critical_warning 非零 → 走路径 C（SSD 固件问题）

---

### 路径 A：散热导致的热保护掉盘

8. [api:read] 查看风扇转速和散热策略：
   ```bash
   ipmitool sdr list | grep -i fan
   ```
   Expected: 查看所有风扇的 RPM

   ```bash
   ipmitool raw 0x30 0x70 0x66 0x01 0x00
   ```
   Expected: 查看当前散热策略模式（手动/自动/全速）

9. [api:write] 临时将风扇设为全速模式，验证是否为散热问题：
   ```bash
   ipmitool raw 0x30 0x70 0x66 0x01 0x01 0x64
   ```
   Expected: 将风扇设置为 100% 全速运转

10. [api:write] 在全速风扇模式下重新运行 72 小时压力测试：
    ```bash
    fio --name=nvme-stress --ioengine=libaio --direct=1 --rw=randrw --rwmixread=70 --bs=4k --iodepth=64 --numjobs=4 --runtime=259200 --time_based --group_reporting --filename=/dev/nvme0n1:/dev/nvme1n1:/dev/nvme2n1 --output=fio_result_fullspeed.json --output-format=json
    ```
    Expected: 运行 72 小时 NVMe 混合读写压力测试，验证全速风扇下是否仍然掉盘

11. [verify] 72 小时后检查结果：
    - 无掉盘 → 确认散热问题，优化风道设计或调整风扇曲线
    - 仍有掉盘 → 散热不是唯一原因，继续排查

12. [physical] 如果确认散热问题，用热成像仪拍摄 backplane 区域温度分布图。关注 slot 9-12 和 21-24 与其他 slot 的温差。若温差 > 8°C，需要请机构团队增加导风罩或调整 backplane 布局。

13. [api:write] 部署自动温度监控脚本，全程记录 burn-in 温度曲线：
    ```bash
    cat > /tmp/nvme_temp_monitor.sh << 'SCRIPT'
    #!/bin/bash
    LOG_FILE="/var/log/nvme_temp_$(date +%Y%m%d_%H%M%S).csv"
    echo "timestamp,device,temperature,critical_warning,available_spare" > $LOG_FILE
    while true; do
        for dev in /dev/nvme*n1; do
            SMART=$(nvme smart-log $dev 2>/dev/null)
            TEMP=$(echo "$SMART" | grep "^temperature" | awk '{print $3}')
            WARN=$(echo "$SMART" | grep "critical_warning" | awk '{print $3}')
            SPARE=$(echo "$SMART" | grep "available_spare " | awk '{print $3}')
            echo "$(date +%Y-%m-%d_%H:%M:%S),$(basename $dev),$TEMP,$WARN,$SPARE" >> $LOG_FILE
        done
        sleep 300
    done
    SCRIPT
    ```
    Expected: 创建温度监控脚本，每 5 分钟记录所有 NVMe 盘的温度、critical warning 和 available spare 到 CSV 文件

    ```bash
    chmod +x /tmp/nvme_temp_monitor.sh && nohup /tmp/nvme_temp_monitor.sh &
    ```
    Expected: 使脚本可执行并在后台持续运行

---

### 路径 B：PCIe Switch 链路稳定性问题

14. [api:read] 查看 PCIe Switch 端口状态：
    ```bash
    switchtec status /dev/switchtec0 | grep -A3 "Port"
    ```
    Expected: 查看每个 Switch 下游端口的链路状态

    ```bash
    switchtec port-bind-info /dev/switchtec0
    ```
    Expected: 查看 Switch 端口绑定信息

15. [api:read] 查看 Switch 固件版本和制造信息：
    ```bash
    switchtec mfg info /dev/switchtec0
    ```
    Expected: 查看 Switch 制造信息

    ```bash
    switchtec fw-info /dev/switchtec0
    ```
    Expected: 查看 Switch 固件版本

16. [api:read] 检查 Switch 上游链路（到 CPU）的状态：
    ```bash
    lspci -vvv -s $(switchtec status /dev/switchtec0 | grep "Upstream" -A1 | grep "BDF" | awk '{print $NF}') | grep -E "LnkSta|Speed|Width|UESta|CESta"
    ```
    Expected: 查看 Switch 上游链路的 PCIe 状态和错误寄存器

17. [api:danger] 重置 PCIe Switch 的错误计数器，开始新一轮观察：
    ```bash
    switchtec event-ctl /dev/switchtec0 ALL -CE
    ```
    Expected: 清除 Switch 所有事件计数器

18. [api:write] 运行 24 小时压力测试，同时持续记录 Switch 事件：
    ```bash
    switchtec event-wait /dev/switchtec0 --timeout 86400 >> switch_events.log &
    ```
    Expected: 在后台记录 Switch 事件，持续 24 小时

    ```bash
    fio --name=nvme-stress --ioengine=libaio --direct=1 --rw=randrw --bs=4k --iodepth=64 --numjobs=4 --runtime=86400 --time_based --filename=/dev/nvme0n1 --output=fio_switch_test.json --output-format=json
    ```
    Expected: 运行 24 小时 NVMe 压力测试，同时持续记录 Switch 事件

19. [verify] 分析 switch_events.log：
    - 如果 Surprise Link Down 事件与温度升高时间点吻合 → 回到路径 A
    - 如果 Link Down 伴随 Switch 固件 assertion → PCIe Switch 固件 bug，联系 Broadcom 获取 hotfix
    - 如果 Link Down 集中在特定端口 → 可能是 backplane 信号质量问题，需要 SI 测试

20. [api:read] 查看 Switch 各端口带宽利用率和内部温度，辅助诊断：
    ```bash
    switchtec status /dev/switchtec0
    ```
    Expected: 显示所有端口的状态概览，包括 link speed、link width、LTSSM state

    ```bash
    switchtec bw /dev/switchtec0 --type raw
    ```
    Expected: 显示各端口的实时带宽利用率（raw 模式显示绝对数值而非百分比）

    ```bash
    switchtec temp /dev/switchtec0
    ```
    Expected: 显示 Switch 芯片的内部温度，正常工作范围应在 85°C 以下

    ```bash
    switchtec log-dump /dev/switchtec0 -t flash -o switch_flash_log.bin
    ```
    Expected: 从 Switch 的 flash 中导出完整的历史事件日志（二进制格式），供 Broadcom FAE 分析

---

### 路径 C：SSD 固件导致的异常掉盘

21. [api:read] 批量检查所有 NVMe 盘的 SMART critical_warning 字段：
    ```bash
    for dev in /dev/nvme*n1; do echo "=== $dev ==="; nvme smart-log $dev | grep -E "critical_warning|temperature|available_spare"; done
    ```
    Expected: 批量查看所有 NVMe 盘的 critical warning、温度和备用空间

22. [api:read] 查看 SSD 固件版本和序列号，确认是否在已知问题批次内：
    ```bash
    nvme id-ctrl /dev/nvme0n1 | grep -E "^fr|^sn|^mn"
    ```
    Expected: 显示 SSD 的固件版本(fr)、序列号(sn)和型号(mn)

23. [api:read] 拉取 Samsung NVMe 的厂商特定 SMART 日志，查看内部诊断数据：
    ```bash
    nvme get-log /dev/nvme0n1 --log-id=0xCA --log-len=512 --raw-binary | hexdump -C | head -20
    ```
    Expected: 读取 Samsung 厂商特定日志页(0xCA)的原始数据，包含内部电容健康度和历史错误计数

24. [api:danger] 对出现 critical_warning 的 SSD 进行固件在线升级到 GDC7502Q：
    ```bash
    nvme fw-download /dev/nvme0n1 --fw=PM9A3_GDC7502Q.bin
    ```
    Expected: 下载新固件到 SSD（GDC7502Q）

    ```bash
    nvme fw-activate /dev/nvme0n1 --slot=1 --action=1
    ```
    Expected: 激活固件到 slot 1（action=1 表示下次重启激活）

25. [verify] 固件升级后运行 72 小时 burn-in 测试，确认 critical_warning 为 0 且无掉盘。

26. [decide] 如果批量 SSD 都有 critical_warning：
    - bit 4（volatile memory backup）非零 → 联系 Samsung FAE，确认是否为已知电容批次问题
    - bit 0（spare space）非零 → SSD 写入寿命问题，检查压测的写入量是否超出规格

27. [api:read] 查看 SSD 完整 NVMe 控制器标识信息，辅助 FAE 定位：
    ```bash
    nvme id-ctrl /dev/nvme0n1 -H
    ```
    Expected: 以人类可读格式显示 NVMe 控制器的完整标识信息，包括 vendor ID、serial number、firmware revision、supported features 等

28. [api:read] 查看 namespace 详细信息：
    ```bash
    nvme id-ns /dev/nvme0n1 -n 1 -H
    ```
    Expected: 显示 namespace 1 的详细信息，包括 LBA 格式、容量、利用率、数据保护设置等

29. [api:read] 查看 NVMe subsystem 拓扑：
    ```bash
    nvme list-subsys /dev/nvme0n1
    ```
    Expected: 显示 NVMe subsystem 拓扑，包括所有关联的控制器和 namespace 关系

30. [api:read] 查看 SMART 完整健康信息：
    ```bash
    nvme smart-log /dev/nvme0n1
    ```
    Expected: 显示 SMART/Health Information log page，包括 critical_warning、temperature、available_spare、percentage_used、data_units_read/written、host_read/write_commands、power_on_hours 等关键指标

31. [api:read] 查看 SSD 错误日志：
    ```bash
    nvme error-log /dev/nvme0n1 --log-entries=20
    ```
    Expected: 显示最近 20 条错误日志条目，每条包含 error count、submission queue ID、command ID、status field、LBA 等诊断信息

32. [api:read] 查看 Changed Namespace List：
    ```bash
    nvme get-log /dev/nvme0n1 --log-id=6 --log-len=512 -H
    ```
    Expected: 读取 Changed Namespace List log (log page 6)，显示自上次读取后发生变更的 namespace 列表

33. [api:read] 测试单次 I/O 延迟：
    ```bash
    nvme io-passthru /dev/nvme0n1 --opcode=0x02 --data-len=4096 --read --latency
    ```
    Expected: 发送一个 NVMe Read 命令并显示 I/O 延迟，用于诊断单次 I/O 的响应时间

34. [api:read] 查看 Temperature Threshold feature：
    ```bash
    nvme get-feature /dev/nvme0n1 --feature-id=0x04 -H
    ```
    Expected: 查看 Temperature Threshold feature，显示当前配置的 over/under temperature threshold 值

35. [api:read] 查看 Arbitration feature：
    ```bash
    nvme get-feature /dev/nvme0n1 --feature-id=0x01 -H
    ```
    Expected: 查看 Arbitration feature，显示 high/medium/low priority weight 和 burst size 配置

### 经验教训

- **高密度 NVMe 平台必须做散热仿真**：在 24 盘位 U.2 平台中，靠近电源模块的 slot 位温度会比中间位高 8-15°C。NPI 阶段应在 full-load burn-in 前完成 CFD 仿真和实测温度 mapping。
- **SSD 固件版本管理**：NPI 阶段应锁定 SSD 固件版本，并与 SSD 厂商确认已知问题列表。PM9A3 的 GDC7302Q 固件已知在高温场景有误触发热保护的问题，GDC7502Q 已修复。
- **PCIe Switch 日志是重要诊断信息源**：PCIe Switch 的 Surprise Link Down 事件可以帮助区分 SSD 故障 vs 链路层故障 vs 热保护。应在 burn-in 流程中加入 Switch 事件日志的自动采集和分析。
- **burn-in 监测应包含温度趋势**：热相关问题往往需要 48-96 小时才会暴露。建议 burn-in 流程增加全程温度曲线记录，对斜率异常的 slot 位提前预警。