# Quickstart: 修复验证场景

**Feature**: 006-fix-kb-v2-bugs | **Date**: 2026-06-06

---

## 场景 1: 验证纠错路径字段清理 (BUG-NEW-1)

```bash
cd ~/holmes-kb

# 1. 确认一个真实存在的条目 ID（如 PT-DB-001）
holmes kb show PT-DB-001

# 2. 写入纠错 pending
holmes kb write-pending --content "$(cat <<'EOF'
---
type: pitfall
title: Redis connection timeout under load
category: database
tags: [redis]
created_at: "2026-01-01T00:00:00+00:00"
updated_at: "2026-01-01T00:00:00+00:00"
---

## Symptoms
Timeout.

## Root Cause
Pool size too small.

## Resolution
Increase maxclients setting.
EOF
)" --corrects PT-DB-001

# 3. 确认纠错提案（替换 PENDING_ID）
PENDING_ID="<output from step 2>"
echo "y" | holmes kb confirm "$PENDING_ID"

# 4. 验证正式条目不含 pending 内部字段
holmes kb show PT-DB-001
# 期望输出：不含 pending/pending_since/source/source_session/suggested_type/suggested_category

# 5. 用 grep 断言（期望无匹配）
holmes kb show PT-DB-001 | grep -E "^pending:|source:|suggested_type:|suggested_category:"
# 期望：无任何输出
```

---

## 场景 2: 验证 lint conflict_count 准确性 (BUG-NEW-2)

```bash
cd ~/holmes-kb

# 1. 查看当前冲突状态
holmes kb lint

# 2. 如有未解决冲突，解决其中一个
holmes kb list-conflicts   # 或 ls contributions/conflicts/
holmes kb resolve <conflict-id> --keep B

# 3. 再次 lint，验证 Conflicts 计数减少 1
holmes kb lint
# 期望：Conflicts 比步骤 1 少 1

# 4. 用 --report 验证 JSON 输出
holmes kb lint --report
# 期望：conflict_count 与实际 pending_review 文件数一致
```

---

## 场景 3: 验证 skill run --json 退出码 (BUG-NEW-3)

```bash
cd ~/holmes-kb

# 1. 创建一个会失败的测试 skill
holmes kb skill create test-fail-skill --desc "Always fails"
# 编辑 skills/test-fail-skill/scripts/run.sh 让其 exit 1

# 2. 测试非 JSON 模式（对照组，应已正常）
holmes kb skill run test-fail-skill
echo "Non-JSON exit code: $?"   # 期望: 1

# 3. 测试 JSON 模式（修复验证）
holmes kb skill run test-fail-skill --json
echo "JSON exit code: $?"       # 期望: 1（修复前为 0）

# 4. 验证 JSON 输出中的 exit_code 字段与 CLI 退出码一致
OUTPUT=$(holmes kb skill run test-fail-skill --json 2>/dev/null; echo $?)
# 验证两者均为 1

# 5. 成功场景对照：成功 skill 仍返回 0
holmes kb skill run check-redis --json
echo "Success exit code: $?"    # 期望: 0
```

---

## 场景 4: 验证 detect-commands SQL 过滤 (BUG-NEW-4)

```bash
cd ~/holmes-kb

# 1. 测试 SQL 语句不被提取
RESOLUTION='## Resolution

Run these commands:

```bash
SHOW SLAVE STATUS\G
SELECT * FROM information_schema.processlist;
mysqladmin stop-slave
mysqladmin start-slave
```
'

holmes kb skill detect-commands --json --content "$RESOLUTION"
# 期望：只包含 mysqladmin 命令，不含 SHOW/SELECT

# 2. 验证大小写不敏感
RESOLUTION2='```bash
show slave status\G
SELECT count(*) from users;
systemctl restart mysql
```'

holmes kb skill detect-commands --json --content "$RESOLUTION2"
# 期望：只有 systemctl 命令被返回

# 3. 纯 shell 内容不受影响
RESOLUTION3='```bash
redis-cli info replication
kubectl get pods -n production
```'

holmes kb skill detect-commands --json --content "$RESOLUTION3"
# 期望：两个命令均正常返回
```

---

## 自动化验证（全套回归）

```bash
cd ~/project/projectTmp/holmes/holmes/kb

# 运行全部测试（期望 280+ 全通过）
python -m pytest tests/ -v

# 运行新增测试（4 个修复的专项测试）
python -m pytest tests/test_integration.py::TestCorrectionFieldCleanup -v
python -m pytest tests/test_linter.py -v -k "conflict_count"
python -m pytest tests/test_skill_manager.py -v -k "sql"
python -m pytest tests/ -v -k "exit_code"
```
