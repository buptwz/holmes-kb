"""Comprehensive tests for 039 — Universal Import Pipeline.

Organized by requirement (R1–R12) from spec §9, covering:
  - Unit tests: deterministic logic, no LLM
  - Data quality tests: fidelity checks, normalization, schema validation
  - E2E integration tests: full pipeline flows with mock LLM
  - Agent usage tests: MCP compatibility, progress callbacks

Test naming convention:
  test_R{N}_{scenario}  — traces to spec requirement R{N}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

import frontmatter as fm

from holmes.kb.agent.fidelity import verify_content_fidelity
from holmes.kb.agent.interactive_review import (
    review_drafts,
    review_knowledge_points,
    _extract_title,
    _extract_type,
)
from holmes.kb.agent.knowledge_map import KnowledgeMap, KnowledgePoint
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.phases.classifier import (
    ClassificationResult,
    DiagnosticComplexity,
    DocumentClassifier,
    DocumentType,
)
from holmes.kb.agent.phases.reader import build_document_map
from holmes.kb.agent.pipeline import ThreePhaseImportPipeline
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

_SIMPLE_PITFALL_ZH = """\
# Redis 连接池耗尽

## 现象

服务日志出现 `JedisConnectionException: Could not get a resource from the pool`，
QPS 超过 5000 时触发，超时阈值 200ms。

## 根因

`maxTotal` 默认值 8 不够用，连接池在高并发下耗尽。

## 解决方案

```bash
redis-cli CONFIG SET maxTotal 256
redis-cli CONFIG SET maxIdle 64
```

确认连接数：
```bash
redis-cli INFO clients | grep connected_clients
```
"""

_GUIDELINE_EN = """\
# Logging Standards

## Context

All production services must follow a consistent logging format to enable
centralized search and alerting via ELK stack.

## Guideline

1. Use structured JSON logging (not plain text).
2. Always include `timestamp`, `level`, `service`, `trace_id`.
3. Log levels: DEBUG for dev, INFO for business events, WARN for recoverable,
   ERROR for failures requiring intervention.
4. Maximum log line size: 4096 bytes.

## Rationale

Unstructured logs are unsearchable. The 4096 byte limit prevents OOM in
Logstash pipelines (observed at 16KB lines causing heap exhaustion).
"""

_DECISION_EN = """\
# ADR-007: PostgreSQL over MySQL

## Context

We need to choose a primary RDBMS for the new billing microservice.
Requirements: JSONB support, row-level security, partitioning.

## Decision

Use PostgreSQL 15 with TimescaleDB extension.

## Rationale

- PostgreSQL has native JSONB with GIN indexes (MySQL JSON is virtual-column only).
- Row-level security is a first-class feature in PG; MySQL requires app-layer enforcement.
- TimescaleDB gives hypertable partitioning automatically.
- Team has 3+ years PG production experience.
"""

_MIXED_DOC_ZH = """\
# Q2 数据库迁移复盘

## 故障概述

2024-06-15 执行 MySQL → PostgreSQL 迁移时，DNS 缓存导致应用仍连旧库。

## 根因分析

应用使用了 JVM DNS 缓存（默认 TTL=30s），迁移后 DNS 切换延迟 45 秒。

## 解决方案

```bash
# 设置 JVM DNS 缓存 TTL 为 0
java -Dsun.net.inetaddressCachePolicy=0 -jar app.jar
```

## 迁移前检查清单（最佳实践）

1. 验证 DNS TTL 设置
2. 确认数据同步延迟 < 100ms
3. 准备回滚脚本
4. 通知所有下游服务

## 为什么选择 PostgreSQL

团队在 2024-Q1 评估后决定从 MySQL 迁移到 PostgreSQL。
主要原因：JSONB 原生支持、行级安全、分区功能。
"""

_COMPLEX_DIAGNOSTIC = """\
# 交换机故障切换失败排查

## 概述

主交换机故障时，备用交换机未能自动切换。

## 排查步骤

### 第一步：检查 SSH/SNMP 连通性

登录备用交换机：
```bash
ssh admin@switch-backup
snmpwalk -v2c -c public switch-backup .1.3.6.1
```

如果连接正常 → 第二步
如果连接超时 → 检查物理链路

### 第二步：检查 SFP 模块

查看光模块状态：
```bash
show interface transceiver
```

- 如果 RX power < -30dBm → 更换 SFP 模块
- 如果 RX power 正常 → 第三步

### 第三步：验证 VRRP 配置

```bash
show vrrp brief
```

确认 priority 值和 preempt 设置。

## 最佳实践

- 每季度做一次故障切换演练
- SFP 模块使用原厂认证型号
- VRRP priority 主备差值建议 ≥ 20
"""


def _make_cfg(tmp_path: Path):
    cfg = MagicMock()
    cfg.model = "test-model"
    cfg.provider = "openai"
    cfg.api_key = "test-key"
    cfg.api_base_url = "http://localhost"
    cfg.kb_path = str(tmp_path)
    return cfg


def _noop_provider() -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.complete.return_value = (True, [], [{"role": "assistant", "content": "done"}], {})
    provider.append_tool_results.side_effect = lambda msgs, results: msgs
    return provider


def _make_pipeline(
    tmp_path: Path,
    dry_run: bool = True,
    no_interactive: bool = True,
    use_dag: bool = False,
    force_type: Optional[str] = None,
    **kwargs,
) -> ThreePhaseImportPipeline:
    cfg = _make_cfg(tmp_path)
    return ThreePhaseImportPipeline(
        kb_root=tmp_path,
        cfg=cfg,
        dry_run=dry_run,
        no_interactive=no_interactive,
        use_dag=use_dag,
        force_type=force_type,
        _provider=_noop_provider(),
        **kwargs,
    )


def _classification(
    doc_type: DocumentType,
    complexity: DiagnosticComplexity = DiagnosticComplexity.simple,
    reason: str = "test",
) -> ClassificationResult:
    return ClassificationResult(
        doc_type=doc_type,
        reason=reason,
        granularity_hint="",
        complexity=complexity,
    )


def _make_km(kps: list[KnowledgePoint], coverage: float = 95.0) -> KnowledgeMap:
    total = max(kp.section_end for kp in kps) if kps else 1000
    return KnowledgeMap(
        knowledge_points=kps,
        total_chars=total,
        chars_read=int(total * coverage / 100),
        reading_passes=1,
        diminishing_returns=True,
    )


def _make_draft(
    kp_id: str,
    type_: str = "pitfall",
    category: str = "database",
    title: str = "Test Entry",
    language: str = "en",
    body: str = "## Symptoms\nTest\n\n## Root Cause\nTest\n\n## Resolution\nTest\n",
) -> str:
    return (
        f"---\nid: {kp_id}\ntype: {type_}\ncategory: {category}\n"
        f"title: {title}\ntags: [test]\nlanguage: {language}\n---\n\n{body}"
    )


# ===========================================================================
# R1: All 5 types importable
# ===========================================================================


class TestR1AllTypesImportable:
    """R1: pitfall, process, model, guideline, decision — all can be extracted."""

    @pytest.mark.parametrize("type_hint", [
        "pitfall", "process", "model", "guideline", "decision",
    ])
    def test_R1_extractor_type_section_table_covers_all_types(self, type_hint):
        """Extractor prompt TYPE-SECTION TABLE has entries for all 5 types."""
        from holmes.kb.agent.phases.extractor import EXTRACTOR_SYSTEM_PROMPT
        assert f"| {type_hint}" in EXTRACTOR_SYSTEM_PROMPT

    @pytest.mark.parametrize("type_hint", [
        "pitfall", "process", "model", "guideline", "decision",
    ])
    def test_R1_reader_prompt_mentions_all_types(self, type_hint):
        """Reader prompt multi-type awareness mentions all 5 types."""
        from holmes.kb.agent.phases.reader import READER_SYSTEM_PROMPT
        assert type_hint in READER_SYSTEM_PROMPT.lower()

    def test_R1_classifier_covers_incident_runbook_guideline_mixed(self):
        """Classifier DocumentType enum has all required values."""
        assert DocumentType.incident.value == "incident"
        assert DocumentType.runbook.value == "runbook"
        assert DocumentType.guideline.value == "guideline"
        assert DocumentType.mixed.value == "mixed"
        assert DocumentType.non_kb.value == "non_kb"

    def test_R1_normalizer_handles_all_categories(self):
        """DraftNormalizer can normalize entries of all types without error."""
        norm = DraftNormalizer()
        for type_ in ("pitfall", "process", "model", "guideline", "decision"):
            draft = _make_draft("test", type_=type_, body=f"## Symptoms\nTest\n")
            result, warnings = norm.normalize(draft, kb_type=type_)
            assert result  # non-empty output


# ===========================================================================
# R2: Metadata auto-fill
# ===========================================================================


class TestR2MetadataAutoFill:
    """R2: type, category, language, confidence filled automatically."""

    def test_R2_kp_has_type_hint_category_language(self):
        """KnowledgePoint carries type_hint, category_hint, language."""
        kp = KnowledgePoint(
            id="kp-1", description="test",
            section_start=0, section_end=100,
            type_hint="guideline", category_hint="application", language="zh",
        )
        assert kp.type_hint == "guideline"
        assert kp.category_hint == "application"
        assert kp.language == "zh"

    def test_R2_kp_confidence_default_1(self):
        """KP confidence defaults to 1.0."""
        kp = KnowledgePoint(id="kp-1", description="test", section_start=0, section_end=100)
        assert kp.confidence == 1.0

    def test_R2_kp_parent_kp_optional(self):
        """parent_kp is optional, defaults to None."""
        kp = KnowledgePoint(id="kp-1", description="test", section_start=0, section_end=100)
        assert kp.parent_kp is None

        kp2 = KnowledgePoint(
            id="kp-2", description="child", section_start=100, section_end=200,
            parent_kp="kp-1",
        )
        assert kp2.parent_kp == "kp-1"


# ===========================================================================
# R5: DAG quality not degraded
# ===========================================================================


class TestR5DagQualityNotDegraded:
    """R5: DAG pipeline code is untouched; routing is the only change."""

    def test_R5_dag_flag_routes_to_dag_pipeline(self, tmp_path):
        """--dag bypasses Classifier and calls _run_dag_pipeline."""
        pipeline = _make_pipeline(tmp_path, use_dag=True)
        with patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag, \
             patch.object(pipeline, "_run_complementary_extraction"), \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            pipeline.run(_SIMPLE_PITFALL_ZH)
        mock_dag.assert_called_once()
        mock_cls.assert_not_called()

    def test_R5_complex_incident_auto_routes_to_dag(self, tmp_path):
        """Classifier: incident + complex → DAG pipeline."""
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag, \
             patch.object(pipeline, "_run_complementary_extraction"):
            mock_cls.return_value.classify.return_value = _classification(
                DocumentType.incident, DiagnosticComplexity.complex_branching,
            )
            pipeline.run(_COMPLEX_DIAGNOSTIC)
        mock_dag.assert_called_once()

    def test_R5_simple_incident_does_not_route_to_dag(self, tmp_path):
        """Classifier: incident + simple → Classic, NOT DAG."""
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag:
            mock_cls.return_value.classify.return_value = _classification(
                DocumentType.incident, DiagnosticComplexity.simple,
            )
            pipeline.run(_SIMPLE_PITFALL_ZH)
        mock_dag.assert_not_called()

    def test_R5_type_pitfall_alone_does_not_force_dag(self, tmp_path):
        """--type pitfall alone uses Classic, not DAG (requires --dag)."""
        pipeline = _make_pipeline(tmp_path, force_type="pitfall")
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag:
            mock_cls.return_value.classify.return_value = _classification(
                DocumentType.incident, DiagnosticComplexity.simple,
            )
            pipeline.run(_SIMPLE_PITFALL_ZH)
        mock_dag.assert_not_called()


# ===========================================================================
# R6: Accuracy — 11-layer guarantee chain
# ===========================================================================


class TestR6AccuracyChain:
    """R6: 11-layer accuracy chain tests (layers 1-11 from spec §6)."""

    # Layer 1: Classifier complexity judgment
    def test_R6_L1_classifier_returns_complexity(self):
        """Layer 1: Classifier outputs complexity field."""
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"incident","complexity":"complex","reason":"multi-branch"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify("some text")
        assert result.complexity == DiagnosticComplexity.complex_branching
        assert result.needs_dag is True

    # Layer 2: --dag manual override
    def test_R6_L2_dag_flag_overrides_classifier(self, tmp_path):
        """Layer 2: --dag bypasses Classifier entirely."""
        pipeline = _make_pipeline(tmp_path, use_dag=True)
        with patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)), \
             patch.object(pipeline, "_run_complementary_extraction"), \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            pipeline.run("text")
        mock_cls.assert_not_called()

    # Layer 3: Document Map
    def test_R6_L3_document_map_extracts_headings(self):
        """Layer 3: build_document_map generates TOC from Markdown headings."""
        text = "# Title\n\nIntro\n\n## Section A\n\nContent\n\n### Subsection\n\nMore"
        dm = build_document_map(text)
        assert "Title" in dm
        assert "Section A" in dm
        assert "Subsection" in dm
        assert "char 0" in dm

    def test_R6_L3_document_map_empty_for_no_headings(self):
        """Layer 3: No headings → empty map."""
        dm = build_document_map("Just plain text with no headings")
        assert dm == ""

    # Layer 6: review_knowledge_points
    def test_R6_L6_review_kp_non_interactive_passes_all(self):
        """Layer 6: non-interactive mode accepts all KPs."""
        kps = [
            KnowledgePoint(id="kp-1", description="test", section_start=0, section_end=100),
            KnowledgePoint(id="kp-2", description="low conf", section_start=100, section_end=200,
                           confidence=0.5),
        ]
        km = _make_km(kps)
        report = ImportReport(dry_run=True)
        result = review_knowledge_points(km, no_interactive=True, report=report)
        assert len(result.knowledge_points) == 2
        # Low confidence KP triggers warning
        assert any("low confidence" in w for w in report.warnings)

    # Layer 10: verify_content_fidelity
    def test_R6_L10_fidelity_detects_missing_numbers(self):
        """Layer 10: Fidelity check catches missing numbers."""
        source = "Set maxTotal to 256, timeout to 200ms, port 6379."
        draft = "Set maxTotal, adjust timeout."  # numbers missing
        warnings = verify_content_fidelity(source, draft)
        assert any("数字丢失" in w for w in warnings)

    def test_R6_L10_fidelity_detects_missing_code(self):
        """Layer 10: Fidelity check catches dropped code fragments."""
        source = "Run `redis-cli INFO` then `redis-cli CONFIG SET maxmemory 1gb`."
        draft = "Run redis commands to configure."  # code lost
        warnings = verify_content_fidelity(source, draft)
        assert any("代码片段丢失" in w for w in warnings)

    def test_R6_L10_fidelity_detects_missing_terms(self):
        """Layer 10: Fidelity check catches dropped proper nouns."""
        source = "Use PostgreSQL with TimescaleDB extension on Kubernetes."
        draft = "Use the database extension on the platform."
        warnings = verify_content_fidelity(source, draft)
        assert any("术语丢失" in w for w in warnings)

    def test_R6_L10_fidelity_clean_when_all_preserved(self):
        """Layer 10: No warnings when all content preserved."""
        source = "Set `maxTotal` to 256 on Redis cluster."
        draft = "Set `maxTotal` to 256 on Redis cluster."
        warnings = verify_content_fidelity(source, draft)
        assert warnings == []

    # Layer 11: review_drafts
    def test_R6_L11_review_drafts_non_interactive_logs_warnings(self):
        """Layer 11: non-interactive mode logs fidelity warnings."""
        drafts = {"kp-1": _make_draft("kp-1")}
        fidelity = {"kp-1": ["数字丢失: 256"]}
        report = ImportReport(dry_run=True)
        result = review_drafts(drafts, fidelity, no_interactive=True, report=report)
        assert len(result) == 1
        assert any("数字丢失" in w for w in report.warnings)


# ===========================================================================
# R7: Agentic problems — Document Map, coverage, isolation
# ===========================================================================


class TestR7AgenticProblems:
    """R7: Document Map, multi-pass coverage, forked isolation."""

    def test_R7_document_map_char_positions_correct(self):
        """Document Map reports correct character positions."""
        text = "# A\n\nSome content.\n\n# B\n\nMore content."
        dm = build_document_map(text)
        lines = dm.strip().split("\n")
        assert len(lines) == 2
        # First heading at char 0
        assert "char 0" in lines[0]
        # Second heading after "# A\n\nSome content.\n\n"
        expected_pos = len("# A\n\nSome content.\n\n")
        assert f"char {expected_pos}" in lines[1]

    def test_R7_extractor_sibling_injection(self):
        """Extractor appends sibling briefs when multiple KPs exist."""
        from holmes.kb.agent.phases.extractor import ExtractorAgent

        provider = MagicMock(spec=LLMProvider)
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": _make_draft("kp-1")}],
            {},
        )

        extractor = ExtractorAgent(provider=provider, model="test")
        km = _make_km([
            KnowledgePoint(id="kp-1", description="First", section_start=0, section_end=100,
                           type_hint="pitfall"),
            KnowledgePoint(id="kp-2", description="Second", section_start=100, section_end=200,
                           type_hint="guideline"),
        ])
        ctx = {"source_text": "x" * 200}
        extractor.run(km.knowledge_points[0], km, ctx)

        # Check that the user message contains sibling info
        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        user_msg = messages[0]["content"]
        assert "kp-2" in user_msg
        assert "guideline" in user_msg

    def test_R7_kp_serialization_roundtrip(self):
        """KnowledgePoint with parent_kp + confidence survives to_dict/from_dict."""
        kp = KnowledgePoint(
            id="kp-1", description="test", section_start=0, section_end=100,
            type_hint="process", parent_kp="kp-0", confidence=0.7,
        )
        d = kp.to_dict()
        assert d["parent_kp"] == "kp-0"
        assert d["confidence"] == 0.7

        kp2 = KnowledgePoint.from_dict(d)
        assert kp2.parent_kp == "kp-0"
        assert kp2.confidence == 0.7


# ===========================================================================
# R8: MCP compatibility
# ===========================================================================


class TestR8McpCompatibility:
    """R8: Produced entries are compatible with existing MCP tools."""

    @pytest.mark.parametrize("type_,expected_sections", [
        ("pitfall", ["## Symptoms", "## Root Cause", "## Resolution"]),
        ("guideline", ["## Context", "## Guideline", "## Rationale"]),
        ("decision", ["## Context", "## Decision", "## Rationale"]),
        ("process", ["## Purpose", "## Steps", "## Outcome"]),
        ("model", ["## Overview", "## Key Concepts", "## Usage"]),
    ])
    def test_R8_draft_structure_matches_type_section_table(self, type_, expected_sections):
        """Draft structure for each type has the correct required sections."""
        body = "\n\n".join(f"{s}\n\nContent here." for s in expected_sections)
        draft = _make_draft("test", type_=type_, body=body)
        post = fm.loads(draft)
        assert post.metadata["type"] == type_
        for section in expected_sections:
            assert section in post.content

    def test_R8_draft_has_valid_frontmatter(self):
        """Generated drafts have valid YAML frontmatter parseable by python-frontmatter."""
        draft = _make_draft("test-001", type_="pitfall", category="database",
                            title="Redis OOM", language="zh")
        post = fm.loads(draft)
        assert post.metadata["id"] == "test-001"
        assert post.metadata["type"] == "pitfall"
        assert post.metadata["category"] == "database"
        assert post.metadata["language"] == "zh"
        assert "tags" in post.metadata


# ===========================================================================
# R11: Idempotent import
# ===========================================================================


class TestR11IdempotentImport:
    """R11: source_hash dedup; --dag + --force can override."""

    def test_R11_same_hash_skips(self, tmp_path):
        """Exact duplicate source_hash → skip without starting pipeline."""
        pipeline = _make_pipeline(tmp_path, dry_run=False)
        source = "# Test\n\n" + "x" * 200

        with patch("holmes.kb.agent.pipeline.compute_source_hash", return_value="abc123"), \
             patch("holmes.kb.store.list_entries") as mock_list:
            mock_entry = MagicMock()
            mock_entry.id = "existing-001"
            mock_entry.source_hash = "abc123"
            mock_entry.file_path = str(tmp_path / "pitfall" / "existing.md")
            mock_list.return_value = [mock_entry]
            report = pipeline.run(source)

        assert "existing-001" in report.skipped
        assert any("已存在" in w for w in report.warnings)

    def test_R11_force_bypasses_hash_check(self, tmp_path):
        """--force bypasses source_hash dedup."""
        pipeline = _make_pipeline(tmp_path, dry_run=True, force=True)
        source = "# Test\n\n" + "x" * 200

        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch("holmes.kb.agent.pipeline.compute_source_hash", return_value="abc123"):
            mock_cls.return_value.classify.return_value = _classification(DocumentType.incident)
            report = pipeline.run(source)

        # Should not skip — force=True bypasses hash check
        assert not any("已存在" in w for w in report.warnings)


# ===========================================================================
# R12: Progress & UX
# ===========================================================================


class TestR12ProgressAndUx:
    """R12: Unified progress_callback, two confirmations, fidelity visibility."""

    def test_R12_progress_callback_receives_messages(self, tmp_path):
        """progress_fn receives extraction progress messages."""
        messages = []
        (tmp_path / "contributions" / "pending").mkdir(parents=True)
        pipeline = _make_pipeline(tmp_path, dry_run=False, progress_fn=messages.append)

        km = _make_km([
            KnowledgePoint(id="kp-1", description="Test", section_start=0, section_end=100),
        ])

        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch("holmes.kb.agent.phases.reader.ReaderAgent.run", return_value=km), \
             patch("holmes.kb.agent.phases.extractor.ExtractorAgent.run",
                   return_value=_make_draft("kp-1")), \
             patch("holmes.kb.agent.phases.extractor.ExtractorAgent._validate_and_repair_draft",
                   return_value=(_make_draft("kp-1"), None)), \
             patch("holmes.kb.agent.tools.write_pending",
                   return_value="pending-test-001"), \
             patch("holmes.kb.agent.runner.ImportAgentRunner"):
            mock_cls.return_value.classify.return_value = _classification(DocumentType.incident)
            pipeline.run("x" * 200)

        # Should have progress messages for extraction and write
        assert any("Extracting" in m for m in messages)
        assert any("kp-1" in m for m in messages)

    def test_R12_non_interactive_skips_prompts(self, tmp_path):
        """no_interactive=True never calls click.prompt."""
        km = _make_km([
            KnowledgePoint(id="kp-1", description="test", section_start=0, section_end=100),
        ])
        report = ImportReport(dry_run=True)

        with patch("holmes.kb.agent.interactive_review.click") as mock_click:
            review_knowledge_points(km, no_interactive=True, report=report)
            mock_click.prompt.assert_not_called()

    def test_R12_fidelity_warnings_visible_in_report(self, tmp_path):
        """Fidelity warnings are recorded in ImportReport.warnings."""
        drafts = {"kp-1": _make_draft("kp-1")}
        fidelity = {"kp-1": ["数字丢失: 256", "术语丢失: Redis"]}
        report = ImportReport(dry_run=True)

        review_drafts(drafts, fidelity, no_interactive=True, report=report)
        assert any("256" in w for w in report.warnings)
        assert any("Redis" in w for w in report.warnings)


# ===========================================================================
# Data Quality: Fidelity check edge cases
# ===========================================================================


class TestDataQualityFidelity:
    """Fidelity check covers various data quality scenarios."""

    def test_fidelity_ignores_trivial_numbers(self):
        """Single-digit numbers (1, 2, 3) are not flagged as missing."""
        source = "Step 1: do X. Step 2: do Y."
        draft = "Do X then do Y."
        warnings = verify_content_fidelity(source, draft)
        # "1" and "2" are < 2 chars and < 10, should not be flagged
        assert not any("数字丢失" in w for w in warnings)

    def test_fidelity_catches_port_numbers(self):
        """Port numbers like 6379, 3306 are flagged when missing."""
        source = "Connect to Redis on port 6379 and MySQL on 3306."
        draft = "Connect to Redis and MySQL."
        warnings = verify_content_fidelity(source, draft)
        assert any("6379" in w or "3306" in w for w in warnings)

    def test_fidelity_allows_partial_code_drop(self):
        """Dropping < 30% of code fragments does not trigger warning."""
        source = "Run `cmd1`, `cmd2`, `cmd3`, `cmd4`."
        draft = "Run `cmd1`, `cmd2`, `cmd3`."  # 1/4 = 25% drop, below threshold
        warnings = verify_content_fidelity(source, draft)
        assert not any("代码片段丢失" in w for w in warnings)

    def test_fidelity_chinese_text_no_false_positives(self):
        """Chinese text without CamelCase terms does not trigger term warnings."""
        source = "Redis 连接池耗尽导致服务超时，需要调整配置。"
        draft = "Redis 连接池配置调整。"
        warnings = verify_content_fidelity(source, draft)
        # "Redis" is a proper noun — should NOT be flagged since it appears in both
        assert not any("术语丢失" in w and "Redis" in w for w in warnings)

    def test_fidelity_empty_source(self):
        """Empty source section produces no warnings."""
        warnings = verify_content_fidelity("", "Some draft content")
        assert warnings == []


# ===========================================================================
# Data Quality: Draft normalization
# ===========================================================================


class TestDataQualityNormalization:
    """DraftNormalizer handles all entry types correctly."""

    def test_normalizer_preserves_valid_draft(self):
        """Valid draft passes through normalization unchanged (modulo formatting)."""
        draft = _make_draft("test-001", type_="pitfall", category="database")
        norm = DraftNormalizer()
        result, warnings = norm.normalize(draft, kb_type="pitfall")
        post = fm.loads(result)
        assert post.metadata["type"] == "pitfall"
        assert post.metadata["category"] == "database"

    def test_normalizer_fixes_invalid_category(self):
        """Invalid category is corrected to a valid one."""
        draft = _make_draft("test", type_="pitfall", category="invalid_cat")
        norm = DraftNormalizer()
        result, warnings = norm.normalize(draft, kb_type="pitfall")
        post = fm.loads(result)
        # Category should be replaced with a valid one
        assert post.metadata["category"] != "invalid_cat"


# ===========================================================================
# Data Quality: Interactive review helpers
# ===========================================================================


class TestDataQualityReviewHelpers:
    """Interactive review helper functions work correctly."""

    def test_extract_title_from_frontmatter(self):
        draft = _make_draft("test", title="My Great Title")
        assert _extract_title(draft) == "My Great Title"

    def test_extract_title_missing(self):
        assert _extract_title("no frontmatter here") == "(untitled)"

    def test_extract_type_from_frontmatter(self):
        draft = _make_draft("test", type_="guideline")
        assert _extract_type(draft) == "guideline"

    def test_extract_type_missing(self):
        assert _extract_type("no frontmatter") == "unknown"


# ===========================================================================
# Routing: Classifier complexity-based routing
# ===========================================================================


class TestRoutingClassifier:
    """Classifier-based routing logic."""

    def test_needs_dag_only_for_complex_incident(self):
        """needs_dag is True only for incident + complex_branching."""
        assert _classification(DocumentType.incident, DiagnosticComplexity.complex_branching).needs_dag is True
        assert _classification(DocumentType.incident, DiagnosticComplexity.simple).needs_dag is False
        assert _classification(DocumentType.runbook, DiagnosticComplexity.complex_branching).needs_dag is False
        assert _classification(DocumentType.guideline).needs_dag is False

    def test_legacy_multi_incident_maps_to_incident(self):
        """Legacy 'multi_incident' LLM output maps to incident."""
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"multi_incident","reason":"legacy"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify("text")
        assert result.doc_type == DocumentType.incident

    def test_non_kb_skips_pipeline(self, tmp_path):
        """non_kb classification → skip, no pipeline execution."""
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            mock_cls.return_value.classify.return_value = _classification(DocumentType.non_kb)
            report = pipeline.run("meeting notes")
        assert any("non-kb" in w for w in report.warnings)

    @pytest.mark.parametrize("doc_type", [
        DocumentType.runbook,
        DocumentType.guideline,
        DocumentType.mixed,
    ])
    def test_non_incident_never_routes_to_dag(self, doc_type, tmp_path):
        """Runbook/guideline/mixed never route to DAG regardless of complexity."""
        pipeline = _make_pipeline(tmp_path)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag:
            mock_cls.return_value.classify.return_value = _classification(
                doc_type, DiagnosticComplexity.complex_branching,
            )
            pipeline.run("x" * 200)
        mock_dag.assert_not_called()


# ===========================================================================
# Routing: CLI flag orthogonality
# ===========================================================================


class TestRoutingCliFlags:
    """--type and --dag are orthogonal."""

    def test_type_without_dag_uses_classic(self, tmp_path):
        """--type pitfall without --dag → Classic pipeline."""
        pipeline = _make_pipeline(tmp_path, force_type="pitfall", use_dag=False)
        with patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls, \
             patch.object(pipeline, "_run_dag_pipeline") as mock_dag:
            mock_cls.return_value.classify.return_value = _classification(DocumentType.incident)
            pipeline.run("x" * 200)
        mock_dag.assert_not_called()

    def test_dag_without_type_routes_to_dag(self, tmp_path):
        """--dag without --type → DAG pipeline, Classifier skipped."""
        pipeline = _make_pipeline(tmp_path, use_dag=True)
        with patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag, \
             patch.object(pipeline, "_run_complementary_extraction"), \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            pipeline.run("x" * 200)
        mock_dag.assert_called_once()
        mock_cls.assert_not_called()

    def test_dag_with_type_routes_to_dag(self, tmp_path):
        """--dag --type pitfall → DAG pipeline (--dag takes priority)."""
        pipeline = _make_pipeline(tmp_path, use_dag=True, force_type="pitfall")
        with patch.object(pipeline, "_run_dag_pipeline", return_value=ImportReport(dry_run=True)) as mock_dag, \
             patch.object(pipeline, "_run_complementary_extraction"), \
             patch("holmes.kb.agent.pipeline.DocumentClassifier") as mock_cls:
            pipeline.run("x" * 200)
        mock_dag.assert_called_once()
        mock_cls.assert_not_called()


# ===========================================================================
# Complementary Extraction
# ===========================================================================


class TestComplementaryExtraction:
    """M8: After DAG, Classic Reader scans uncovered portions."""

    def test_complementary_skipped_when_no_dag_json(self, tmp_path):
        """No .dag.json → complementary extraction does nothing."""
        pipeline = _make_pipeline(tmp_path)
        report = ImportReport(dry_run=True)
        ctx = {"source_hash": "nope123"}
        # Should not raise
        pipeline._run_complementary_extraction("text", report, None, ctx)
        # No complementary traces
        assert not any("Complementary" in t for t in report.phase_traces)

    def test_complementary_skipped_when_low_uncovered(self, tmp_path):
        """<10% uncovered → complementary skipped."""
        # Create a .dag.json that covers almost all lines
        state_dir = tmp_path / "_import-state"
        state_dir.mkdir()
        source = "\n".join(f"line {i}" for i in range(100))
        nodes = [{"line_range": [1, 95]}]  # covers 95% of lines
        dag_path = state_dir / "abc123.dag.json"
        dag_path.write_text(json.dumps({"nodes": nodes}))

        pipeline = _make_pipeline(tmp_path)
        report = ImportReport(dry_run=True)
        ctx = {"source_hash": "abc123"}
        pipeline._run_complementary_extraction(source, report, None, ctx)

        assert any("skipped" in t and "< 10%" in t for t in report.phase_traces)

    def test_complementary_filters_pitfall_process(self, tmp_path):
        """Complementary extraction filters out pitfall/process types."""
        state_dir = tmp_path / "_import-state"
        state_dir.mkdir()
        source = "\n".join(f"line {i}" for i in range(100))
        nodes = [{"line_range": [1, 30]}]  # only covers 30%
        dag_path = state_dir / "abc123.dag.json"
        dag_path.write_text(json.dumps({"nodes": nodes}))

        pipeline = _make_pipeline(tmp_path)
        report = ImportReport(dry_run=True)
        ctx = {"source_hash": "abc123", "source_text": source}

        # Mock Reader returning pitfall + guideline KPs
        km_with_mixed = _make_km([
            KnowledgePoint(id="kp-1", description="A pitfall", section_start=0,
                           section_end=50, type_hint="pitfall"),
            KnowledgePoint(id="kp-2", description="A guideline", section_start=50,
                           section_end=100, type_hint="guideline"),
        ])

        with patch("holmes.kb.agent.phases.reader.ReaderAgent.run", return_value=km_with_mixed):
            pipeline._run_complementary_extraction(source, report, None, ctx)

        # After filtering, only guideline remains — Reader was called
        assert any("Complementary" in t for t in report.phase_traces)


# ===========================================================================
# Pipeline integration: write path
# ===========================================================================


class TestPipelineWritePath:
    """_write_pending_entries writes directly without LLM loop."""

    def test_write_pending_creates_entries(self, tmp_path):
        """Direct write path creates entries via write_kb_entry tool."""
        (tmp_path / "contributions" / "pending").mkdir(parents=True)
        pipeline = _make_pipeline(tmp_path, dry_run=False)
        report = ImportReport(dry_run=False)
        ctx = {
            "kb_root": tmp_path,
            "dry_run": False,
            "source_hash": "test123",
            "source_file": "",
            "force_type": "",
            "force": False,
        }
        drafts = {"kp-1": _make_draft("kp-1", title="Test Entry")}

        with patch("holmes.kb.agent.runner.ImportAgentRunner"):
            pipeline._write_pending_entries(drafts, ctx, report)

        assert len(report.created) == 1
        assert report.created[0].startswith("pending-")

    def test_write_pending_dry_run_no_files(self, tmp_path):
        """Dry run creates no files."""
        pipeline = _make_pipeline(tmp_path, dry_run=True)
        report = ImportReport(dry_run=True)
        ctx = {
            "kb_root": tmp_path,
            "dry_run": True,
            "source_hash": "test123",
            "source_file": "",
            "force_type": "",
            "force": False,
        }
        drafts = {"kp-1": _make_draft("kp-1")}
        pipeline._write_pending_entries(drafts, ctx, report)

        assert len(report.created) == 0
        pending_files = list(tmp_path.rglob("pending-*.md"))
        assert len(pending_files) == 0


# ===========================================================================
# Document-level scenario tests (mock LLM, full pipeline flow)
# ===========================================================================


class TestScenarioSimplePitfall:
    """Scenario: simple pitfall → Classic pipeline, ~1 KP."""

    def test_simple_pitfall_classified_as_simple_incident(self):
        """Simple pitfall should be classified as incident/simple."""
        # This tests the prompt design intent — mock LLM returns expected result
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"incident","complexity":"simple","reason":"single fix"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify(_SIMPLE_PITFALL_ZH)
        assert result.doc_type == DocumentType.incident
        assert result.complexity == DiagnosticComplexity.simple
        assert result.needs_dag is False


class TestScenarioGuideline:
    """Scenario: guideline document → Classic, multiple KPs."""

    def test_guideline_classified_correctly(self):
        """Guideline doc → DocumentType.guideline."""
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"guideline","complexity":"simple","reason":"best practices"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify(_GUIDELINE_EN)
        assert result.doc_type == DocumentType.guideline


class TestScenarioMixedDocument:
    """Scenario: mixed document → Classic, diverse KP types."""

    def test_mixed_doc_document_map_has_all_sections(self):
        """Document map captures all section headings."""
        dm = build_document_map(_MIXED_DOC_ZH)
        assert "故障概述" in dm
        assert "根因分析" in dm
        assert "迁移前检查清单" in dm
        assert "PostgreSQL" in dm

    def test_mixed_doc_classified_as_mixed_or_incident(self):
        """Mixed doc → mixed or incident type."""
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"mixed","complexity":"simple","reason":"multi-type"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify(_MIXED_DOC_ZH)
        assert result.doc_type == DocumentType.mixed


class TestScenarioComplexDiagnostic:
    """Scenario: complex diagnostic → DAG pipeline."""

    def test_complex_diagnostic_has_branching_structure(self):
        """Document map shows multi-level branching structure."""
        dm = build_document_map(_COMPLEX_DIAGNOSTIC)
        assert "SSH/SNMP" in dm or "连通性" in dm
        assert "SFP" in dm or "光模块" in dm

    def test_complex_classified_as_complex_incident(self):
        """Complex diagnostic → incident/complex_branching."""
        provider = MagicMock()
        provider.complete.return_value = (
            True, [],
            [{"role": "assistant", "content": '{"doc_type":"incident","complexity":"complex","reason":"multi-branch diagnostic"}'}],
            {},
        )
        cls = DocumentClassifier(provider=provider, model="test")
        result = cls.classify(_COMPLEX_DIAGNOSTIC)
        assert result.needs_dag is True


class TestScenarioDecision:
    """Scenario: ADR decision document → Classic, 1 KP."""

    def test_decision_document_map(self):
        """Decision doc has Context/Decision/Rationale headings."""
        dm = build_document_map(_DECISION_EN)
        assert "Context" in dm
        assert "Decision" in dm
        assert "Rationale" in dm
