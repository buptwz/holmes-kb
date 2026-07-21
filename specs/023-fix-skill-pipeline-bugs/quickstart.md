# Quickstart / Integration Test Scenarios: 023-fix-skill-pipeline-bugs

**Date**: 2026-06-10

每个 Scenario 对应一个 User Story，可独立验证。

---

## Scenario 1 — US1: Skill run.sh 不含裸文本步骤行

**验证目标**: `_extract_code_block_lines()` 过滤编号步骤行，run.sh 可执行。

```bash
# 准备含编号步骤的测试文档
cat > /tmp/s1-bare-text.md << 'EOF'
# TiKV Raft Log 磁盘 I/O 诊断

## Resolution

```bash
1. 确认磁盘 I/O 瓶颈
iostat -x 1 10 | grep -E "Device|nvme|sda"
2. 检查 TiKV Raft Log 积压情况
tikv-ctl --host $TIKV_HOST:20160 raft log
```
EOF

# 导入（会生成 Skill）
holmes import /tmp/s1-bare-text.md --no-interactive

# 验证生成的 run.sh 不含编号行
SKILL_DIR=$(ls ~/.holmes-kb/skills/ | head -1)
bash -n ~/.holmes-kb/skills/$SKILL_DIR/run.sh
echo "EXIT:$?"  # 期望 EXIT:0

# 确认 run.sh 不含 "1. " "2. " 等裸文本
grep -n '^\d\+\.' ~/.holmes-kb/skills/$SKILL_DIR/run.sh && echo "FAIL: bare text found" || echo "PASS: no bare text"
```

**期望结果**:
- `bash -n run.sh` 退出码 0
- run.sh 中不含 `1. 确认磁盘` 等裸文本行
- run.sh 包含 `iostat` 和 `tikv-ctl` 命令

---

## Scenario 2 — US2: 同根因文档走 UPDATE 路径

**验证目标**: `update_kb_entry` 被正确调用，输出 `0 created, 1 updated`。

```bash
# 先导入原始文档
cat > /tmp/s2-original.md << 'EOF'
# MySQL 主从复制延迟根因分析

## Root Cause
主库写入速度超过从库重放能力，导致 Seconds_Behind_Master 持续增长。

## Resolution
```bash
SHOW SLAVE STATUS\G
```
EOF
holmes import /tmp/s2-original.md --no-interactive
# 期望: 1 created

# 导入同根因更新版文档
cat > /tmp/s2-update.md << 'EOF'
# MySQL 复制延迟：优化方案（v2）

## Root Cause
主库写入速度超过从库重放能力，binlog 积压，Seconds_Behind_Master 持续增长。

## Resolution
```bash
SHOW SLAVE STATUS\G
SET GLOBAL slave_parallel_workers = 4;
```
EOF
holmes import /tmp/s2-update.md --no-interactive
echo "EXIT:$?"
# 期望输出: 0 created, 1 updated, 0 skipped
```

**期望结果**:
- 第二次导入: `✓ 0 created, 1 updated, 0 skipped`
- KB 中不新增重复条目

---

## Scenario 3 — US3: Update 路径输出 OPTIONAL Skill 候选提示

**验证目标**: update 路径文档含 1-2 条命令时，报告含 `skill candidate`。

```bash
# 先建立 entry（确保走 update 路径）
cat > /tmp/s3-base.md << 'EOF'
# Redis 内存溢出排查

## Root Cause
Redis maxmemory 设置过低，触发 OOM。

## Resolution
检查内存使用情况。
EOF
holmes import /tmp/s3-base.md --no-interactive
# 期望: 1 created

# 导入含 1 条命令的同根因更新文档
cat > /tmp/s3-update.md << 'EOF'
# Redis OOM 修复步骤（更新版）

## Root Cause
Redis maxmemory 设置过低，触发 OOM，需调整配置并重启。

## Resolution
```bash
redis-cli config set maxmemory 4gb
```
EOF
holmes import /tmp/s3-update.md --no-interactive
# 期望报告含: "skill candidate: ..."
```

**期望结果**:
- 第二次导入: `✓ 0 created, 1 updated | skill: 0 generated, 0 linked | 1 suggestion(s): skill candidate: ...`
- report.suggestions 含 `skill candidate`

---

## Scenario 4 — 回归：US1 不影响无编号步骤的正常文档

```bash
cat > /tmp/s4-normal.md << 'EOF'
# Nginx 502 排查

## Resolution
```bash
curl -v http://backend-host:8080/health
journalctl -u nginx --since "5 minutes ago"
```
EOF
holmes import /tmp/s4-normal.md --no-interactive
# 期望: 正常创建条目，Skill 含 curl 和 journalctl 两条命令
```

**期望结果**: `1 created`，生成的 run.sh 包含两条命令，语法检查通过。
