---
brief: ESD 防护操作规范：未接地操作导致器件隐性损伤，需腕带检测、台垫接地、离子风扇等预防措施
category: esd
id: esd-protection-operation-standard
language: zh
tags:
- esd
- wristband
- grounding
- ionizer
- ddr5
- pcb
- packaging
- compliance
title: 实验室 ESD 防护操作规范
type: pitfall
---

## Symptoms

- 被 ESD 损伤的器件通过初始功能测试，但在客户现场数周后出现间歇性故障，导致高昂的 RMA 成本

## Root Cause

ESD（静电放电）是导致器件隐性损伤的首要原因。被 ESD 损伤的器件可能通过出厂前的初始功能测试，但内部已形成微小的物理损伤（如栅氧化层击穿、PN 结漏电路径），在客户现场经过若干次温度循环或电压波动后发展为间歇性故障甚至完全失效。NPI 实验室频繁处理裸板、未封装芯片和高敏感器件（如 DDR5 DIMM、SSD、GPU 模组），这些器件对 ESD 极为敏感，即使是人体无法感知的静电压（< 3,000V）也足以造成不可逆损伤。

## Resolution

### ESD 防护规范 — 按违规次数分级处理

#### 1. 人体接地（每日自检）

[physical] 操作任何电子器件前，必须佩戴防静电腕带。腕带电阻必须在 1MΩ ± 10% 范围内，每日早班用腕带测试仪校验。

[physical] 腕带鳄鱼夹必须连接到工作台的接地柱，而非机箱外壳。

[physical] 无线防静电腕带不被接受——其放电速度不足以保护 Gen5 速率器件。

[api] 每日腕带检测通过后，将结果记录到质检系统：

```bash
holmes-qa log-esd-check --operator "$USER" --wristband-id WB-$(hostname) --result pass
```

#### 2. 工作台面防护

[physical] ESD 工作台垫必须覆盖整个操作区域，不允许裸板直接接触金属台面。

[physical] 台垫接地线与腕带接地线应连接到同一公共接地点（star grounding）。

[physical] 操作非导电材料（如亚克力治具、塑料包装）时，必须开启离子风扇。离子风扇校验标准（每周由实验室管理员检测）：正极衰减时间 < 2 秒，负极衰减时间 < 2 秒，残余电压 < ±25V。

#### 3. 器件搬运与拿取

[physical] 所有 PCB、DIMM、SSD 必须在 ESD 防护袋中搬运，不允许裸手手握非边缘区域。

[physical] 拿取 DIMM 时只能持握两端边缘，不可触碰金手指和颗粒。

[physical] 拿取 PCB 时持握板边或使用专用防静电托盘。

[physical] 从 ESD 袋取出器件后，在 5 秒内放置到接地的 ESD 工作台面上。

#### 4. 拍照取证

[physical] 拍照取证前先触摸接地柱放电。

[physical] 相机镜头距器件不小于 15cm（避免镜头产生的静电影响）。

[physical] 禁止使用闪光灯直射裸露芯片表面。

#### 5. 包装拆封

[physical] 新器件到货拆封时在 ESD 保护区内拆封，不在走廊或会议室。

[physical] 先拆外层纸箱，再在 ESD 台面上拆内层防静电袋。

[physical] 干燥剂和缓冲材料立即放入回收桶，不留在工作台面。

#### 6. 违规处理

[decide] 一次违规：口头提醒 + QA 系统记录。

[decide] 两次违规：强制重新参加 ESD 培训。

[decide] 三次违规：暂停实验室准入权限，主管复核后恢复。

#### 7. 周期性检查

| 检查项目 | 频率 | 负责人 |
|---|---|---|
| 腕带电阻测试 | 每日 | 操作人员自检 |
| 台垫接地连续性 | 每周 | 实验室管理员 |
| 离子风扇校验 | 每周 | 实验室管理员 |
| 湿度监控（40-60% RH） | 持续 | 自动传感器 |
| ESD 培训更新 | 每年 | 质量部 |