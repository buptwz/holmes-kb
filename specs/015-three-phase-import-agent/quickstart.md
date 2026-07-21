# Quickstart: Three-Phase Import Agent

**Feature**: 015-three-phase-import-agent
**Date**: 2026-06-08

---

## Scenario 1: Import a Large Document (>8000 chars)

```bash
# Before this feature: "Source truncated" warning + fields falsely cleared
# After this feature: full document processed, all fields populated

holmes import /path/to/large-runbook.md --verbose
```

**Expected outcome**:
```
✓ created: MySQL 主库磁盘满导致写入阻塞
  title       ← line 1 of document
  root_cause  ← ## 根因分析 section
  resolution  ← ## 解决方案 section (was previously truncated)

Would create skill: skill-ptdb001 (3 steps detected)
```

**No warnings** about truncation. All `##` sections in the document are accessible to the pipeline.

---

## Scenario 2: Import a Multi-Knowledge-Point Document

```bash
holmes import /path/to/incident-postmortem.md --verbose
```

A postmortem covering three distinct incidents (Redis, MySQL, Nginx).

**Expected outcome**:
```
✓ created: Redis 连接池耗尽导致请求超时           (kp-1)
✓ created: MySQL 慢查询引发主从延迟               (kp-2)
✓ created: Nginx upstream 配置错误导致 502        (kp-3)

Reader: 3 knowledge points identified, 100% coverage, 1 reading pass
Extractor: 3/3 knowledge points extracted (serial)
```

Each entry contains **only** its own incident's content. Entry for kp-1 (Redis) does not mention MySQL or Nginx.

---

## Scenario 3: Chinese Runbook with Skill Generation

```bash
holmes import /path/to/redis-ops-runbook-zh.md --verbose
```

Runbook with a `## 诊断步骤` section containing `redis-cli INFO replication` and `redis-cli DEBUG SLEEP 0`.

**Expected outcome**:
```
✓ created: Redis 主从同步延迟排查手册

verbose trace:
  title        ← frontmatter 第一行
  root_cause   ← ## 根因 section
  resolution   ← ## 诊断步骤 section  ← (was failing before C-2a fix)

skill candidate: skill-ptredis001 (2 steps detected)
```

In interactive mode, user is prompted:
```
Create skill 'skill-ptredis001'? (2 command steps detected) [Y/n]:
```

---

## Scenario 4: Dry Run — No Duplicate Output

```bash
holmes import /path/to/sharding-incident.md --dry-run
```

**Expected outcome**:
```
[DRY RUN] Planned actions:
  Would create: ShardingSphere 影子库路由失效导致压测数据写入生产库

[DRY RUN] No files written.
```

Only **one** `Would create:` line (was appearing twice before W6-F1 fix).

---

## Scenario 5: Batch Import with Verbose

```bash
holmes import --dir /path/to/runbooks/ --verbose
```

**Expected outcome (after L-W4 fix)**:
```
[1/3] runbook-redis.md — ✓ created (Redis 连接池耗尽)
  title       ← ...
  root_cause  ← ...
  resolution  ← ...

[2/3] runbook-mysql.md — ✓ created (MySQL 锁等待超时)
  title       ← ...
  root_cause  ← ...

[3/3] runbook-short.md — ✗ error: content too short (12 chars)

Batch summary: 2 created, 0 updated, 0 skipped | 1 error(s)
```

Each entry now gets its own verbose trace block (was suppressed before).

---

## Integration Test Matrix

| Test Case | Document Size | Language | KPs | Expected |
|-----------|--------------|----------|-----|----------|
| T-01 | < 3K chars | EN | 1 | Entry created, no warnings |
| T-02 | 10K chars | EN | 1 | Full resolution, no CLEARED |
| T-03 | 15K chars | ZH | 1 | Full resolution, Chinese section found |
| T-04 | 8K chars | EN | 3 | 3 entries, no cross-contamination |
| T-05 | 6K chars | ZH | 1 | Skill recommendation present |
| T-06 | Any | EN | 1 | Dry-run: exactly 1 `Would create:` line |
| T-07 | Batch (3 docs) | Mixed | 1 each | Verbose trace per entry |
