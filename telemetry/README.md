# Holmes KB 可观测性平台

让团队负责人实时掌握**谁在贡献知识、贡献质量如何、知识库是否健康**。

Holmes 的每一次 KB 操作（提交、审核、拒绝、衰减……）都会自动上报到中心化看板，无需贡献者做任何额外操作。

---

## 能看到什么

| 看板区域 | 关键问题 |
|---------|---------|
| **贡献者活跃度** | 谁提交了多少条？谁的通过率最高？谁在持续贡献？ |
| **KB 健康状态** | 待审积压多少？衰减了多少条？最近有无批量修正？ |
| **完整事件审计** | alice 在什么时间 confirm 了哪条 entry？有无异常操作？ |

![dashboard-preview](https://placeholder/grafana-preview.png)

---

## 5 分钟快速开始

### 管理员：启动服务栈（只做一次）

```bash
cd telemetry/
docker compose up -d
```

访问 **http://\<服务器IP\>:3000**，账号 `admin`，密码 `holmes`，进入 **Dashboards → Holmes KB Governance**。

### 贡献者：配置一次，之后自动上报

```bash
holmes setup \
  --kb-path ~/holmes-kb \
  --otel-endpoint http://<服务器IP>:4318 \
  --contributor alice        # 换成自己的标识符
```

配置完成后**正常使用 CLI 即可**，遥测在后台静默运行，不影响任何操作。

---

## 详细文档

| 文档 | 内容 |
|------|------|
| [USER_GUIDE.md](USER_GUIDE.md) | 完整用户手册——安装、配置、事件参考、自定义、故障排查 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构说明——数据流、组件设计、本地缓冲机制 |
