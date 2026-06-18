# Quickstart: KB Skill Mounting

**Date**: 2026-05-29 | **Branch**: `002-kb-skill-mount`

## 场景 1: 手动为现有条目添加 Skill

**背景**: 条目 `PT-DB-001`（Redis 连接池耗尽）的 Resolution 中有诊断命令，想将其封装为可执行 Skill。

```bash
# Step 1: 创建 Skill 文件夹
holmes --kb-path ~/holmes-kb kb skill create check-redis \
  --desc "检查 Redis 当前连接数及连接池状态"
# 输出: ✓ Skill created: skills/check-redis/

# Step 2: 编辑 SKILL.md，声明参数
# 文件: ~/holmes-kb/skills/check-redis/SKILL.md
# 在 frontmatter 添加:
#   params:
#     - name: host
#       description: Redis 主机地址
#       required: false
#       default: "127.0.0.1"
#     - name: port
#       description: Redis 端口
#       required: false
#       default: "6379"

# Step 3: 编写入口脚本
cat > ~/holmes-kb/skills/check-redis/scripts/run.sh << 'EOF'
#!/usr/bin/env bash
HOST="${SKILL_PARAM_HOST:-127.0.0.1}"
PORT="${SKILL_PARAM_PORT:-6379}"
echo "=== Redis Connection Status: ${HOST}:${PORT} ==="
redis-cli -h "$HOST" -p "$PORT" info | grep -E "connected_clients|maxclients|blocked_clients"
EOF
chmod +x ~/holmes-kb/skills/check-redis/scripts/run.sh

# Step 4: 验证脚本可运行
holmes --kb-path ~/holmes-kb kb skill run check-redis
# 输出:
# === Redis Connection Status: 127.0.0.1:6379 ===
# connected_clients:5
# maxclients:100

# Step 5: 挂载到条目
holmes --kb-path ~/holmes-kb kb skill link PT-DB-001 check-redis
# 输出: ✓ Linked skill 'check-redis' to PT-DB-001.

# Step 6: 验证挂载
holmes --kb-path ~/holmes-kb kb show PT-DB-001 | head -15
# 输出的 frontmatter 中包含:
# skill_refs:
#   - check-redis

# Step 7: 推送到远端
cd ~/holmes-kb && git add skills/ pitfall/database/PT-DB-001.md && git commit -m "feat: add check-redis skill to PT-DB-001"
git push
```

---

## 场景 2: Agent 排查时使用 Skill

**背景**: 用户向 agent 描述 Redis 连接超时问题，agent 找到 PT-DB-001 并发现 `skill_refs`。

```
用户: Redis 连接超时怎么排查？

Agent: 找到相关条目 PT-DB-001（Redis 连接池耗尽导致超时）。
       此条目关联了一个可执行诊断脚本: check-redis

       脚本说明: 检查 Redis 当前连接数及连接池状态
       将执行: bash scripts/run.sh
       参数: host=127.0.0.1, port=6379

       是否立即运行诊断？

用户: 是，运行

Agent: [执行 KbRunSkill("check-redis", {"host": "127.0.0.1", "port": "6379"})]

       执行结果:
       === Redis Connection Status: 127.0.0.1:6379 ===
       connected_clients:94
       maxclients:100

       分析: 当前连接数 94/100，已达连接池上限的 94%。
       根据 PT-DB-001 的 Resolution，建议将 maxclients 设置为 200。

       请在 redis.conf 中修改:
       maxclients 200
       然后执行: redis-cli config set maxclients 200
```

---

## 场景 3: Agent 沉淀时自动生成 Skill

**背景**: 用户成功排查了 Nginx 502 问题，agent 准备沉淀经验到 KB。

```
用户: 问题解决了，刚才加了 proxy_read_timeout 60s 就好了

Agent: 好的，将此次排查经验保存到 KB。

       生成的 Resolution 包含以下可执行命令，可封装为 Skill:

       1. curl -I http://backend-server/health  (检查 upstream 健康)
       2. nginx -t && nginx -s reload           (验证配置并重载)

       是否为这些命令创建 Skill？
       建议名称: check-nginx-upstream, reload-nginx

       [Y/n]

用户: Y

Agent: ✓ 创建 skills/check-nginx-upstream/
       ✓ 创建 skills/reload-nginx/
       ✓ KB 条目 PT-NET-002 已写入 pending，引用以上两个 Skill

       运行 `holmes kb confirm <pending_id>` 发布条目。
```

---

## 场景 4: CLI 管理 Skill 库

```bash
# 列出所有 Skill
holmes --kb-path ~/holmes-kb kb skill list
# NAME                     DESCRIPTION                      REFS
# check-redis              检查 Redis 连接数                PT-DB-001
# check-nginx-upstream     检查 Nginx upstream 状态         PT-NET-001
# reload-nginx             验证配置并重载 Nginx             PT-NET-002

# 查看某条目的 Skill
holmes --kb-path ~/holmes-kb kb skill list PT-DB-001
# NAME          DESCRIPTION        VERSION
# check-redis   检查 Redis 连接数  1.0.0

# 带自定义参数运行
holmes --kb-path ~/holmes-kb kb skill run check-redis \
  --param host=192.168.1.100 \
  --param port=6380

# 解除挂载（Skill 文件夹保留）
holmes --kb-path ~/holmes-kb kb skill unlink PT-DB-001 check-redis
```

---

## 集成测试验证点

| 测试场景 | 预期结果 |
|----------|----------|
| `skill create check-redis --desc "..."` | 创建 SKILL.md 模板 + scripts/run.sh |
| `skill link PT-DB-001 check-redis` | PT-DB-001.md frontmatter 含 `skill_refs: [check-redis]` |
| `kb show PT-DB-001` | 输出中含 "Skill: check-redis [可执行]" |
| `skill run check-redis` | 执行 run.sh，返回 exit_code=0 |
| `skill run nonexistent` | 报错 "Skill not found" |
| `skill link PT-DB-001 nonexistent` | 报错 "Skill not found. Run: holmes kb skill create..." |
| 旧条目（无 skill_refs）`kb show` | 正常显示，无报错 |
| KbReadEntry("PT-DB-001") | 返回含 `skill_refs` 的 frontmatter |
| KbReadSkill("check-redis") | 返回 SKILL.md JSON |
| KbRunSkill("check-redis", {}) | 返回 stdout + exit_code JSON |
