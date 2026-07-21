# NPI 实验室工作日志 2026-W28

本周三个不相关的事项记录在一起，归档时按需拆分。

# 主题一：DDR5 Training 失败（pitfall 类问题）

DVT-0155 板在 memory test 阶段报 DDR5 training failure，失败率在
冷启动时约 30%，热启动基本能过。

排查过程：

```bash
mbist-cli run --test ddr_training --verbose
# 输出: rank 0 CA training FAIL, rank 1 PASS
dmesg | grep -i "ddr\|edac"
```

根因定位：CA（Command/Address）训练在低温下失败。量测 VDDQ 发现
冷启动时上升过慢，标称 1.1V 实际 80ms 才到 1.05V（spec 要求
50ms 内到 99%）。内存控制器在 VDDQ 未到位的窗口内发起 training
导致失败。

修复：把 DDR 控制器的 training 延时参数从 50ms 改为 120ms：

```bash
i2cset -y 1 0x4c 0x22 0x78
mbist-cli run --test ddr_training
# 连续冷启动 10 次全部 PASS
```

物理验证：[物理] 用示波器点测 TP55（VDDQ），确认 120ms 后电压
稳定在 1.1V ±2%。长期措施是电源组优化 VDDQ 的软启动。

# 主题二：烧录站固件更新流程（process 类流程）

烧录站 flash-station-03 升级后的标准烧录流程：

1. 登录烧录站：`ssh flash-station-03`，确认磁盘空间
   `df -h /images` 剩余 > 20G。
2. 上传固件：`scp retimer-fw-2.3.5.bin flash-station-03:/images/`。
3. 校验：`md5sum /images/retimer-fw-2.3.5.bin`，与发布页的
   md5 比对，不一致禁止烧录。
4. 烧录：`flash-tool --target retimer --image /images/retimer-fw-2.3.5.bin --verify`，
   约 90 秒，期间禁止断电。
5. 复核：`retimer-cli version` 显示 2.3.5。
6. 登记烧录记录表（站号、板号、固件版本、操作人、时间）。

# 主题三：实验室 ESD 防护提醒（guideline 类规范）

近期湿度低，静电风险高，重申规范：

- 必须佩戴腕带并每天开工前量测接地电阻，必须 < 1MΩ。
- 禁止在防静电垫以外的地方裸手拿板卡。
- 板卡转运必须使用防静电周转箱，禁止用普通纸箱。
- 插拔任何连接器前必须先断电。
- 冬季供暖期（11 月-3 月）加湿器必须常开，湿度保持 40%-60%。
