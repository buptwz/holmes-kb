# Quickstart: Import Pipeline v3 Bug 修复（Round 3）

## 前置条件

```bash
cd kb && python -m pytest tests/ -q   # 基线：656 passed
```

---

## Scenario 1: QA-18 — Skill run.sh 语法正确性

**目标**: 导入含参数化命令的事故报告，验证 run.sh 通过 bash 语法检查。

```bash
cat > /tmp/tc-qa18-test.md << 'EOF'
# TiKV Raft Log 磁盘 I/O 诊断

## 症状
TiDB 写入延迟突增，Raft Log fsync 延迟高。

## 根因
磁盘 I/O 路径出现瓶颈。

## 解决方案
iostat -x 1 10 | grep -E "Device|nvme|sda"
tikv-ctl --host $TIKV_HOST:20160 raft log
pd-ctl -u http://$PD_HOST:2379 store
EOF

holmes import /tmp/tc-qa18-test.md --no-interactive
```

**验证**:
```bash
SKILL_DIR=$(ls -d /home/wangzhi/holmes-kb/skills/skill-*/  2>/dev/null | tail -1)
bash -n "$SKILL_DIR/scripts/run.sh" && echo "PASS: bash syntax OK"
grep -c '{TIKV_HOST}\|{PD_HOST}' "$SKILL_DIR/scripts/run.sh" \
  && echo "FAIL: bare braces found" || echo "PASS: no bare braces"
grep "TIKV_HOST\|PD_HOST" "$SKILL_DIR/SKILL.md" && echo "PASS: params in SKILL.md"
```

**期望**: bash -n 无错误，无 `{PARAM}` 字面量，SKILL.md Parameters 章节列出参数。

---

## Scenario 2: TC-T-06 — 含真实故障分析的会议纪要被提取

会议纪要格式的文档，若包含客观可复用的技术故障分析，应被提取为 KB 条目。

```bash
cat > /tmp/tc-meeting-with-incident.md << 'EOF'
# SRE On-call 复盘会议 2026-06-05

## 与会人员
张三（SRE Lead）、李四（On-call）

## Redis 连接池耗尽事故复盘

**根因**: Redis 连接池上限配置为 10，高峰期并发请求达到 200，连接耗尽导致 `ConnectionError: max connections reached`。

**解决步骤**:
```
redis-cli -h $REDIS_HOST CONFIG SET maxclients 500
systemctl restart app-service
```

**预防措施**: 生产环境连接池上限不低于预期并发量的 3 倍；监控 `connected_clients` 指标，超过 80% 上限时告警。
EOF

holmes import /tmp/tc-meeting-with-incident.md --no-interactive; echo "exit: $?"
```

**期望**: `created >= 1`，故障知识被提取为 pitfall 类型条目，不因文档是会议纪要格式而被拒绝。

---

## Scenario 3: TC-T-06 — 纯行政会议纪要无知识价值被拒绝

```bash
cat > /tmp/tc-meeting-logistics.md << 'EOF'
# Q2 周会纪要 2026-06-09

## 与会人员
张三（SRE Lead）、李四（On-call）

## 议题
1. Redis 超时事件复盘（已有专项报告，此处不展开）
2. Q2 目标回顾

## 行动项
- 张三: 本周更新 Redis 连接池文档
- 李四: 下周参加培训
EOF

holmes import /tmp/tc-meeting-logistics.md --no-interactive; echo "exit: $?"
```

**期望**: `0 created` + 无知识价值提示（内容仅为行政/行动项，无客观可复用的技术知识）。

---

## Scenario 4: TC-E-06 — 服务目录（客观事实）被提取为 model

服务目录含有客观可复用的事实知识（服务名/端口/依赖），应被提取为 model 类型条目。

```bash
cat > /tmp/tc-service-catalog.md << 'EOF'
| Service | Port | Dependencies | Database |
|---------|------|--------------|----------|
| order-service | 8080 | payment-service:8082, user-service:8081 | orders_db |
| user-service  | 8081 | auth-service:8083 | users_db |
| payment-service | 8082 | — | payments_db |
EOF

holmes import /tmp/tc-service-catalog.md --no-interactive; echo "exit: $?"
```

**期望**: `created >= 1`，服务拓扑关系被提取为 model 类型条目，不因纯表格格式而被拒绝。

---

## Scenario 4b: 纯个人偏好/主观内容被拒绝

```bash
cat > /tmp/tc-subjective.md << 'EOF'
# Weekly SRE Meeting Notes 2026-06-09

## Attendees
Alice (SRE Lead), Bob (On-call), Charlie (DBA)

## Agenda
1. Redis timeout incident review (covered in separate RCA doc)
2. Q2 OKR check-in

## Action Items
- Alice: Update Redis connection pool documentation by Friday
- Bob: Investigate OOM alerts root cause next week
EOF

holmes import /tmp/tc-subjective.md --no-interactive; echo "exit: $?"
```

**期望**: `0 created` + 无知识价值提示（内容仅为行动项/OKR，无技术事实知识）。

---

## Scenario 5: TC-T-06 + --force — 强制导入无知识价值文档

```bash
holmes import /tmp/tc-meeting-logistics.md --force --no-interactive
```

**期望**: 条目被创建，输出 warning（non-kb document (--force bypassed)）但不阻止。

---

## Scenario 6: normalizer 语言检测 — 日文/韩文文档（单测）

端到端场景需要真实日韩文文档，通过单测验证：

```bash
cd kb && python -m pytest tests/test_normalizer.py -k "language" -v
```

**期望**: 日文文档 → `language: ja`，韩文文档 → `language: ko`，中文 → `language: zh` 不变。

---

## Scenario 7: QA-19 — --dry-run 展示条目详情

```bash
holmes import /tmp/tc-qa18-test.md --dry-run
```

**期望输出**（示意）:
```
[DRY RUN] Planned actions:
  Would create (est.): "TiKV Raft Log 磁盘 I/O 瓶颈" (pitfall/database)
[DRY RUN] No files written.
```

---

## Scenario 8: TC-I-07 — --dir 不存在目录返回 exit 1

```bash
holmes import --dir /nonexistent/; echo "exit: $?"
```

**期望**:
```
Directory does not exist: /nonexistent/
exit: 1
```

---

## Scenario 9: TC-S-02 — OPTIONAL Skill 路径（单测验证）

```bash
cd kb && python -m pytest tests/ -k "skill_candidate or optional" -v
```

**期望**: 相关单测通过，确认 1-2 命令条目产生 `skill candidate` suggestion。
