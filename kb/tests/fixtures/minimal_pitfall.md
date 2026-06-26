# 磁盘空间不足导致服务启动失败

## 背景

生产服务器上的应用服务无法正常启动，日志中提示磁盘空间不足。

## 症状

- 服务启动失败，systemd 报错 `No space left on device`
- `df -h` 显示根分区使用率 100%

## 排查步骤

### 第一步：确认磁盘使用情况

```bash
$ df -h
$ du -sh /var/log/* | sort -rh | head -10
```

查看输出：
- `/var/log` 占用超过 10GB → 进入日志清理流程
- 其他目录异常增长 → 人工检查对应目录

### 日志清理流程

执行以下命令清理过期日志：

```bash
$ journalctl --vacuum-time=7d
$ find /var/log -name "*.gz" -mtime +30 -delete
$ systemctl restart rsyslog
```

清理后验证磁盘空间是否恢复正常：

```bash
$ df -h
```

- 使用率 < 80% → 重启服务，问题解决
- 使用率仍 > 90% → 提交扩容工单，临时迁移数据到备用挂载点
