# Quickstart: 修复 Holmes KB v3 报告缺陷 — 验证场景

## 场景 1: US1 数字 tag 不崩溃

```bash
# 准备含数字 tag 的条目
cat > /tmp/test-numeric-tag.md << 'EOF'
---
id: PT-DB-999
type: pitfall
title: Test Numeric Tag
maturity: draft
category: database
tags: [502, redis, timeout]
created_at: "2024-01-01T00:00:00+00:00"
updated_at: "2024-01-01T00:00:00+00:00"
---
Test content.
EOF

# 验证: list --query 不崩溃
holmes --kb-path $KB_PATH kb list --query redis
# 期望: 显示结果，不抛出 AttributeError

holmes --kb-path $KB_PATH kb list --query 502
# 期望: 显示含数字 tag 502 的条目
```

## 场景 2: US2 dry-run 无 API Key

```bash
# 在无 API Key 环境验证
unset OPENAI_API_KEY
holmes import /tmp/test.md --dry-run
# 期望: 显示文件内容预览，不报认证错误
# 期望输出包含 "--- Preview (dry run) ---"
```

## 场景 3: US3+US4+US7 纠错 confirm 数据完整性

```bash
# 1. 创建原始条目（created_at 为历史时间，contributors 含 alice）
# 2. 创建纠错 pending
# 3. 执行 confirm
echo "y" | holmes --kb-path $KB_PATH kb confirm <correction-pending-id> --contributor bob

# 验证 created_at 继承
holmes --kb-path $KB_PATH kb show <corrected-id> | grep created_at
# 期望: 原始条目的历史时间，不是当前时间

# 验证 contributors 追加
holmes --kb-path $KB_PATH kb show <corrected-id> | grep -A5 contributors
# 期望: [alice, bob]

# 验证 maturity 降级警告
# 期望输出中包含: maturity: proven → verified
```

## 场景 4: US5 Gate 3 提示命令

```bash
# 对一个长条目（>800 字符）执行 confirm
holmes --kb-path $KB_PATH kb confirm <long-entry-id>
# Gate 3 输出期望:
#   Content exceeds 800 chars. To review full content:
#     holmes kb pending --show <id>
#   Proceed with confirm? [y/N]
```

## 场景 5: US6 空 ID pending list

```bash
# 创建 id 为空的 pending 条目（手动写文件 stem 为 MY-STEM-001）
# 验证列表显示
holmes --kb-path $KB_PATH kb pending
# 期望: 显示 MY-STEM-001，不显示空白
```
