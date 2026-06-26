# GPU 初始化失败排查

## 背景

某 AI 训练集群在重启后出现 GPU 初始化失败问题。本文档记录完整排查链路。

## 症状

机器重启后，`nvidia-smi` 报错 "No devices were found"，训练任务无法启动。
dmesg 日志中出现 `NVRM: GPU at PCI:0000:3b:00 has fallen off the bus` 错误。

## 排查步骤

### 第一步：检查电源指示灯

观察 GPU 卡背板的 LED 指示灯颜色：
- 红色：供电异常，进入固件修复流程
- 不亮：电源线可能松动
- 绿色：供电正常，继续检查启动日志

### 固件修复流程

如果 LED 为红色，执行以下步骤：

```bash
$ sudo nvidia-smi -pm 1
$ sudo nvidia-smi --gpu-reset -i 0
$ sudo systemctl restart nvidia-persistenced
```

等待 30 秒后重新检查：
- 如果 `nvidia-smi` 恢复正常 → 问题解决
- 如果仍然报错 → 需要硬件更换

### 硬件更换流程

联系数据中心运维团队，提交工单：

```bash
$ dcctl ticket create --type hardware --component gpu \
    --node $(hostname) --description "GPU fell off bus after reboot"
```

确认备件到位后执行更换：
1. 关机并断电
2. 拔出故障 GPU 卡
3. 插入新 GPU 卡
4. 上电开机
5. 运行 `nvidia-smi` 验证

### 检查启动日志

如果 LED 为绿色，检查内核日志：

```bash
$ dmesg | grep -i nvidia
$ cat /var/log/nvidia-installer.log | tail -50
```

查看 POST 阶段是否有异常：
- 如果出现 "GPU POST failure" → 进入 POST 诊断流程
- 如果日志正常但 nvidia-smi 仍报错 → 检查驱动版本

### POST 诊断流程

运行 GPU 自检工具：

```bash
$ sudo nvidia-smi -q -d ECC
$ sudo dcgmi diag -r 3 -j
```

分析诊断结果：
- ECC 错误计数异常 → 需要 RMA
- 温度异常 → 检查散热
- PCIe 链路降速 → 重新插拔或更换 riser card
