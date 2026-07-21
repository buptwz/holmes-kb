# Quickstart: 验证修复效果

**Branch**: `005-fix-kb-workflow-bugs`

## 验证 Fix 1：Agent 写入知识闭环（P0）

```bash
# 1. 构造一个缺少 maturity 字段的内容（模拟 Agent 写入）
cat > /tmp/test-entry.md << 'EOF'
---
type: pitfall
title: Redis 连接池耗尽导致超时
category: database
tags: [redis, connection-pool, timeout]
---

## Symptoms
Redis 操作超时，大量连接处于 CLOSE_WAIT 状态。

## Root Cause
连接池上限设置过低，高并发时连接耗尽。

## Resolution
增大 `maxclients` 配置并重启服务。
EOF

# 2. 写入 pending
holmes kb write-pending --content "$(cat /tmp/test-entry.md)"
# 期望输出: {"pending_id": "pending-XXXXXXXX-XXXXXX-xxxx"}
PENDING_ID=$(holmes kb write-pending --content "$(cat /tmp/test-entry.md)" | python3 -c "import sys,json; print(json.load(sys.stdin)['pending_id'])")

# 3. 验证 pending 条目包含 maturity 字段
holmes kb pending --show $PENDING_ID | grep "maturity:"
# 期望输出: maturity: draft

# 4. 确认入库（Gate 1 应通过）
echo "y" | holmes kb confirm $PENDING_ID
# 期望: Gate 1: ✓ Schema valid（不再出现 "Missing required frontmatter field: 'maturity'"）
```

---

## 验证 Fix 2：正式条目字段清洁（P1）

```bash
# 接上一步，确认成功后查看正式条目
NEW_ID=$(holmes kb list | grep "Redis 连接池" | awk '{print $1}')
holmes kb show $NEW_ID | head -30

# 期望：frontmatter 中不含以下字段
# pending, pending_since, source, source_session, suggested_type, suggested_category
```

---

## 验证 Fix 3：修正工作流一次确认（P1）

```bash
# 1. 准备修正内容
cat > /tmp/corrected.md << 'EOF'
---
type: pitfall
title: Redis 连接池耗尽导致超时
category: database
tags: [redis, connection-pool, timeout, maxclients]
---

## Symptoms
Redis 操作超时，大量连接处于 CLOSE_WAIT 状态，日志出现 ERR max number of clients reached。

## Root Cause
连接池上限设置过低（默认 10000），高并发时连接耗尽。

## Resolution
执行 `redis-cli CONFIG SET maxclients 50000` 并在 redis.conf 中持久化配置。
EOF

# 2. 提交修正提案
CORR_ID=$(holmes kb write-pending --content "$(cat /tmp/corrected.md)" --corrects $NEW_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['pending_id'])")

# 3. 一次确认即完成（修复前需要两次 y）
echo "y" | holmes kb confirm $CORR_ID
# 期望：Gate 2 输出 "✓ Skipped (correction proposal)"，整个流程只需一次 y
```

---

## 验证 Fix 4：detect_commands 多行文本（P0）

```bash
# 传入包含代码块的 Resolution 文本
holmes kb skill detect-commands --json --content "
## Resolution

检查连接池配置：

\`\`\`bash
redis-cli CONFIG GET maxclients
redis-cli CONFIG SET maxclients 50000
\`\`\`

然后重启服务：

\`\`\`bash
systemctl restart redis
\`\`\`
"
# 期望：返回非空数组，包含 redis-cli 和 systemctl 的命令
# [{"line": "redis-cli CONFIG GET maxclients", ...}, ...]
```

---

## 验证 Fix 5：ID 大小写不敏感（P2）

```bash
# 用全小写 ID 查询
holmes kb show pt-db-001
# 期望：返回条目内容（而非 "Entry not found"）

holmes kb show PT-DB-001
# 期望：返回相同条目内容
```

---

## 运行测试套件

```bash
cd kb
pytest tests/ -v
# 期望：所有测试通过，新增测试覆盖以上修复点
```
