# 网络交换机故障切换排查

## 背景

数据中心核心交换机在业务高峰期出现链路故障，触发主备切换。切换后部分业务流量仍然中断，需要人工介入排查。

## 症状

- 监控告警：核心交换机 SW-CORE-01 与 SW-CORE-02 之间 uplink 丢包率 > 30%
- 部分服务器无法访问外网，内网延迟从 0.5ms 升至 80ms
- BGP session 状态不稳定，路由表频繁刷新

---

## 排查步骤

### 第一步：确认主备切换状态

登录监控平台或通过 SSH 检查当前主设备：

```bash
$ ssh admin@10.0.0.1 "show vrrp brief"
$ ssh admin@10.0.0.1 "show spanning-tree summary"
```

查看输出结果：
- 如果主备状态已切换到 SW-CORE-02 → 继续排查切换原因
- 如果主备仍在 SW-CORE-01 → 检查 SW-CORE-01 端口状态

### 检查 SW-CORE-01 端口状态

通过 SNMP 或 SSH 查询端口状态：

```bash
$ ssh admin@10.0.0.1 "show interface status | grep -E 'down|err'"
$ snmpwalk -v2c -c public 10.0.0.1 ifOperStatus
```

分析结果：
- 发现 uplink 端口处于 err-disabled 状态 → 进入端口 err-disabled 修复流程
- 端口状态正常但流量异常 → 检查 SFP 光模块

### 检查 SFP 光模块

**必须到机房现场操作**：

1. 查看机架上 SW-CORE-01 对应端口的光模块指示灯
   - 绿色常亮：光信号正常
   - 橙色/红色闪烁：光功率异常，需要更换光模块
   - 不亮：光模块未插好或已损坏
2. 用光功率计测量接收光功率（RX），正常范围 -10dBm 到 -20dBm
3. 如果光功率异常 → 更换 SFP 光模块

### 更换 SFP 光模块

**必须断业务或切换到备路后操作**：

1. 确认备用链路已承载流量（通过监控验证）
2. 拔出故障光模块（热插拔，无需断电）
3. 插入同型号备用光模块（注意收发方向）
4. 确认端口 UP 后重新检查光功率

更换完成后，运行以下命令确认链路恢复：

```bash
$ ssh admin@10.0.0.1 "show interface GigabitEthernet0/1"
$ ssh admin@10.0.0.1 "show ip bgp summary"
```

---

### 端口 err-disabled 修复流程

通过 SSH 执行修复操作：

```bash
$ ssh admin@10.0.0.1 "configure terminal"
$ ssh admin@10.0.0.1 "interface GigabitEthernet0/1 ; shutdown ; no shutdown"
$ ssh admin@10.0.0.1 "show interface GigabitEthernet0/1 | include err"
```

端口恢复后，验证 BGP 邻居关系：

```bash
$ ssh admin@10.0.0.1 "show ip bgp neighbors 10.0.1.2 | include BGP state"
```

结果判断：
- BGP state = Established → 链路恢复，继续观察 30 分钟
- BGP state = Idle/Active → BGP 建联失败，进入 BGP 排查流程

---

### BGP 排查流程

依次执行以下诊断命令：

```bash
$ ssh admin@10.0.0.1 "show ip bgp neighbors 10.0.1.2"
$ ssh admin@10.0.0.1 "debug ip bgp 10.0.1.2 events"
$ ping 10.0.1.2 source 10.0.0.1 count 100
$ traceroute 10.0.1.2 source 10.0.0.1
```

分析诊断结果：
- 路由策略冲突（AS-path filter 拒绝）→ 修改 route-map 配置
- TCP 连接建立失败（端口 179 不通）→ 检查 ACL 配置
- 路由通告数量异常（>10000 条）→ 进入路由震荡抑制流程
- 以上检查均正常但 BGP 仍不 Established → 重启 BGP 进程，如果失败则回退到人工处理

如果重启 BGP 进程后仍不 Established，**可以回退到检查 SW-CORE-01 端口状态**重新排查物理层。

---

### 路由震荡抑制流程

执行以下命令查看路由震荡来源：

```bash
$ ssh admin@10.0.0.1 "show ip bgp dampening flap-statistics"
$ ssh admin@10.0.0.1 "show ip bgp 0.0.0.0/0 longer-prefixes"
$ ssh admin@10.0.0.2 "show ip route summary"
```

如果确认路由震荡来源：
- 上游 ISP 侧路由不稳定 → 配置 BGP dampening 抑制参数，等待稳定
- 本地配置问题（redistribute 范围过大）→ 修改 redistribute 配置后重新宣告

---

### 切换原因分析与回切流程

当备用链路稳定运行后，分析切换原因并评估是否需要回切：

```bash
$ ssh admin@10.0.0.1 "show logging | grep 'VRRP\|link\|err'"
$ ssh admin@10.0.0.2 "show vrrp"
```

评估结果：
- SW-CORE-01 已完全恢复 → 人工确认后执行回切（更改 VRRP 优先级）
- SW-CORE-01 仍有隐患 → 保持当前主备状态，提交变更申请后再回切

执行回切：

```bash
$ ssh admin@10.0.0.1 "configure terminal ; interface vlan1 ; vrrp 1 priority 200"
$ ssh admin@10.0.0.1 "show vrrp brief"
```

回切后确认流量已迁移回 SW-CORE-01，业务监控绿灯。
