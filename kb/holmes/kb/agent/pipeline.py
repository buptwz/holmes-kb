"""ImportPipeline — Classifier → Summarizer → Review → Generator → Write (042).

One document = one KB entry. Three LLM calls:
  1. Classifier (1 call): document type + multi-topic detection
  2. Summarizer (1 call): whole-document structured extraction
  3. Generator (1 call): format confirmed summary into KB entry

This replaces the old ThreePhaseImportPipeline (Reader→Extractor→Dedup→Verifier).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import frontmatter as _fm

from holmes.config import HolmesConfig
from holmes.kb.agent.fidelity import verify_summary_fidelity_042
from holmes.kb.agent.interactive_review import review_draft, review_summary
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.observability import get_langfuse, observe
from holmes.kb.agent.outline import extract_document_outline
from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentClassifier, DocumentType
from holmes.kb.agent.phases.generator import GeneratorAgent
from holmes.kb.agent.phases.summarizer import SummarizerAgent
from holmes.kb.agent.pipeline_utils import (
    build_fallback_outline,
    check_structure,
    detect_language_heuristic,
    fallback_extract,
    fix_yaml_values,
    infer_type_from_summary,
    strip_llm_wrapper,
)
from holmes.kb.agent.provider import create_provider
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport
from holmes.kb.store import compute_source_hash
from holmes.kb.progress import NullReporter, ProgressReporter

# Backward-compatible aliases for code that imports these from pipeline
_infer_type_from_summary = infer_type_from_summary
_detect_language_heuristic = detect_language_heuristic
_fallback_extract = fallback_extract


# ---------------------------------------------------------------------------
# Source-file helpers
# ---------------------------------------------------------------------------


def _compute_source_file(file_path: Optional[Path]) -> str:
    """Return the source path relative to cwd when possible, else absolute.

    Previously this stored only the basename — two documents with the same
    filename in different directories were falsely treated as "the same
    document, updated" (spec 043, post-eval). Returns '' if None.
    """
    if file_path is None:
        return ""
    try:
        return str(file_path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(file_path.resolve())


def _is_pending_entry(entry: Any) -> bool:
    """Return True if entry lives in a pending directory."""
    fp = str(entry.file_path).replace("\\", "/")
    return "/_pending/" in fp or "/contributions/pending/" in fp


def _inject_applies_to(draft: str, applies_to: dict[str, Any]) -> str:
    """Mechanically write applies_to into the draft's YAML frontmatter (T039).

    Belt-and-suspenders: the Generator prompt asks the LLM to copy it, but
    frontmatter is too structural to leave to LLM compliance. Returns the
    draft unchanged when it cannot be parsed.
    """
    try:
        post = _fm.loads(draft)
        if not post.metadata:
            return draft
        post.metadata["applies_to"] = applies_to
        return _fm.dumps(post)
    except Exception:  # noqa: BLE001
        return draft


def _prompt_cancel_old_pending(
    old_pending: list,
    no_interactive: bool,
    kb_root: Path,
) -> None:
    """Offer to delete old pending entries on re-import."""
    import click

    print(f"检测到同文档的旧 pending 条目（共 {len(old_pending)} 个，未审核）：")
    for entry in old_pending:
        date_hint = entry.created_at[:10] if entry.created_at else "未知"
        print(f"  - {entry.id} (pending, 导入于 {date_hint})")

    if no_interactive:
        print("  → 非交互模式，自动并存（跳过清理）")
        return

    if click.confirm("是否取消旧 pending，用本次新 import 替换？", default=True):
        for entry in old_pending:
            Path(entry.file_path).unlink(missing_ok=True)
            print(f"  已取消: {entry.id}")
    else:
        print("  → 新旧 pending 并存，reviewer 在 approve 时自行选择")


# Kept for backward compatibility — old test code imports this name.
ThreePhaseImportPipeline = None  # Will be set at module level after class definition.


class ImportPipeline:
    """One-doc-one-entry import pipeline.

    Args:
        kb_root: Root directory of the knowledge base.
        cfg: HolmesConfig with provider, model, api_key, api_base_url.
        no_interactive: When True, suppress all confirmation gates.
        verbose: When True, collect per-field decision traces.
        dry_run: When True, all write tools become no-ops.
        force_type: Override KB entry type.
        force: Bypass document-level dedup pre-check.
    """

    def __init__(
        self,
        kb_root: Path,
        cfg: HolmesConfig,
        no_interactive: bool = False,
        verbose: bool = False,
        dry_run: bool = False,
        _provider: Optional[LLMProvider] = None,
        force_type: Optional[str] = None,
        force: bool = False,
        progress_fn: Optional[Any] = None,
        reporter: Optional[ProgressReporter] = None,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.no_interactive = no_interactive
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_type = force_type
        self.force = force
        if reporter is not None:
            self.reporter: ProgressReporter = reporter
        elif progress_fn is not None:
            self.reporter = ProgressReporter(progress_fn)
        else:
            self.reporter = NullReporter()
        self._provider: LLMProvider = _provider if _provider is not None else create_provider(cfg)

    @observe(name="import_pipeline")
    def run(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport:
        """Run the full pipeline for a single source document.

        Args:
            source_text: Full source document text.
            file_path: Optional source file path (for dedup / logging).

        Returns:
            ImportReport summarising all actions taken.
        """
        get_langfuse().update_current_span(
            metadata={
                "source_file": str(file_path) if file_path else "(stdin)",
                "source_chars": len(source_text),
                "model": self.cfg.model,
                "dry_run": self.dry_run,
            },
        )
        report = ImportReport(dry_run=self.dry_run)
        source_hash = compute_source_hash(source_text)
        source_file = _compute_source_file(file_path)

        # ------------------------------------------------------------------
        # Step 0: Dedup / update detection
        # ------------------------------------------------------------------
        if not self.force:
            skip = self._check_dedup(source_hash, source_file, report)
            if skip:
                return report

        # Shared pipeline context
        ctx: dict[str, Any] = {
            "kb_root": self.kb_root,
            "dry_run": self.dry_run,
            "source_text": source_text,
            "source_hash": source_hash,
            "source_file": source_file,
            "no_interactive": self.no_interactive,
            "force_type": self.force_type or "",
            "force": self.force,
            "provider": self._provider,
            "model": self.cfg.model,
            "report": report,
        }

        # ------------------------------------------------------------------
        # Phase 1: Classifier
        # ------------------------------------------------------------------
        self.reporter.start("文档分类中...")
        classifier = DocumentClassifier(
            provider=self._provider, model=self.cfg.model, reporter=self.reporter,
        )
        classification = classifier.classify(source_text)
        self.reporter.done(f"分类完成: {classification.doc_type.value} → {classification.suggested_type}")
        branch_info = f", branches={classification.branch_count}" if classification.branch_count else ""
        report.phase_traces.append(
            f"Classifier: {classification.doc_type.value} → {classification.suggested_type}"
            f"{branch_info} — {classification.reason}"
        )

        if classification.doc_type == DocumentType.non_kb:
            if self.force:
                report.warnings.append(f"non-kb document (--force bypassed): {classification.reason}")
            else:
                report.warnings.append(f"non-kb document: {classification.reason} — skipped")
                return report

        # Determine KB type
        suggested_type = self.force_type or classification.suggested_type
        language = classification.language
        has_complex_branching = classification.has_complex_branching

        # Heuristic language fallback: if classifier says "en" but the source
        # text has substantial Chinese characters, override to "zh".
        if language == "en":
            language = _detect_language_heuristic(source_text, language)

        # ------------------------------------------------------------------
        # Multi-topic split
        # ------------------------------------------------------------------
        if classification.is_multi_topic and classification.topic_boundaries:
            return self._run_multi_topic(
                source_text, file_path, classification, ctx, report,
            )

        # ------------------------------------------------------------------
        # Dry-run: stop after classification
        # ------------------------------------------------------------------
        if self.dry_run:
            report.suggestions.append(
                f'Would create: "{classification.suggested_type}" entry'
                f' from {source_file or "(stdin)"}'
            )
            return report

        # ------------------------------------------------------------------
        # Phase 2: Summarizer
        # ------------------------------------------------------------------
        self.reporter.start("Phase 2: Summarizer — 提取文档摘要...")
        summarizer = SummarizerAgent(
            provider=self._provider, model=self.cfg.model, reporter=self.reporter,
            read_chunk_chars=getattr(self.cfg, "read_chunk_chars", 0),
            direct_mode_char_limit=getattr(self.cfg, "direct_mode_char_limit", 0),
        )
        summary = summarizer.run(source_text, ctx, suggested_type=suggested_type)
        summary_from_llm = summary is not None
        if summary is None:
            self.reporter.warn("Summarizer LLM 失败，使用正则兜底提取...")
            summary = _fallback_extract(source_text)
            report.warnings.append("Summarizer LLM failed — using regex fallback")
        report.phase_traces.append(
            f"Summarizer: {len(summary.get('key_facts', []))} facts, "
            f"{len(summary.get('commands', []))} commands"
        )

        # ------------------------------------------------------------------
        # T033: read-coverage hard invariant — every outline section must have
        # been read via read_document_range. Uncovered sections trigger a
        # forced supplement; sections still unread afterwards are recorded
        # explicitly in the report (never silently dropped).
        # ------------------------------------------------------------------
        if summary_from_llm:
            still_unread = summarizer.ensure_coverage(summary, source_text, ctx)
            if summarizer.last_exhausted:
                report.phase_traces.append(
                    "Summarizer: iteration cap reached "
                    f"({len(summarizer.last_read_ranges)} read ranges)"
                )
            if still_unread:
                report.warnings.append(
                    f"未覆盖 sections（补读后仍未读取）: {', '.join(still_unread[:5])}"
                )
                report.phase_traces.append(
                    f"Coverage: {len(still_unread)} section(s) unread after supplement"
                )

        # ------------------------------------------------------------------
        # Phase 2.5: Infer type from summary content (overrides Classifier)
        # ------------------------------------------------------------------
        # Root-cause gating (spec 043 post-eval): the keyword heuristics in
        # infer_type_from_summary are weaker than the Classifier's holistic
        # judgment — e.g. an oscilloscope *guideline* was flipped to
        # "decision" just because the LLM-written outline had a section
        # literally named "Decision". So the override only applies when:
        #   a) the Classifier result is a failure fallback (reason indicates
        #      parse failure / exception / max retries), or
        #   b) the content carries a STRONG pitfall signal (>=2 symptoms or
        #      >=2 resolution branches) — the volume-based signal this
        #      override exists for in the NPI domain.
        # A confident non-fallback Classifier type is never flipped to
        # decision/model/guideline/process by keyword matching.
        classifier_failed = (
            "classification failed" in classification.reason
            or classification.reason.startswith("exception:")
            or classification.reason == "max retries"
        )
        if not self.force_type:
            inferred = _infer_type_from_summary(summary)
            strong_pitfall_signal = inferred == "pitfall" and (
                len(summary.get("symptoms") or []) >= 2
                or len(summary.get("resolution_branches") or []) >= 2
            )
            if inferred != suggested_type and (classifier_failed or strong_pitfall_signal):
                self.reporter.info(
                    f"Type inference: {suggested_type} → {inferred} "
                    f"(based on summary content)"
                )
                report.phase_traces.append(
                    f"Type override: {suggested_type} → {inferred}"
                )
                suggested_type = inferred

        # Dual-signal trigger: Summarizer branches override Classifier
        n_branches = len(summary.get("resolution_branches", []))
        if n_branches >= 3 and not has_complex_branching:
            has_complex_branching = True
            self.reporter.info(
                f"Complex branching: Summarizer 检测到 {n_branches} 条分支 "
                f"(Classifier branch_count={classification.branch_count})"
            )
            report.phase_traces.append(
                f"Dual-signal: Summarizer branches={n_branches} triggered complex branching"
            )

        # Backfill decision_tree when complex branching is triggered but
        # Summarizer didn't generate one (e.g. dual-signal override).
        if has_complex_branching and not summary.get("decision_tree"):
            branches = summary.get("resolution_branches", [])
            if branches:
                tree_lines = [summary.get("brief", "问题")]
                labels = "ABCDEFGHIJ"
                for i, b in enumerate(branches):
                    label = labels[i] if i < len(labels) else str(i)
                    connector = "└─" if i == len(branches) - 1 else "├─"
                    when = b.get("when", "")
                    bl = b.get("label", "")
                    tree_lines.append(f"{connector} {when} ─→ [{label}] {bl}")
                summary["decision_tree"] = "\n".join(tree_lines)
                self.reporter.info(
                    f"Decision tree: 自动生成 ({len(branches)} branches)"
                )

        # Ensure outline exists — fallback built from actual summary content
        if not summary.get("outline"):
            summary["outline"] = self._build_fallback_outline(
                summary, suggested_type,
            )
            self.reporter.info(
                f"Outline: Summarizer 未生成目录，从摘要内容构建 {suggested_type} 目录 "
                f"({len(summary['outline'])} sections)"
            )

        # ------------------------------------------------------------------
        # Phase 2.5: User review
        # ------------------------------------------------------------------
        source_name = file_path.name if file_path else ""
        if not review_summary(summary, self.no_interactive, report, source_name):
            report.phase_traces.append("Generator: cancelled by user")
            return report

        # ------------------------------------------------------------------
        # Phase 3: Generator + validation feedback loop
        # ------------------------------------------------------------------
        self.reporter.start("Phase 3: Generator — 生成知识条目...")
        generator = GeneratorAgent(
            provider=self._provider, model=self.cfg.model, reporter=self.reporter,
        )
        draft = generator.run(
            summary, ctx, suggested_type=suggested_type,
            language=language, has_complex_branching=has_complex_branching,
        )
        if not draft:
            # LLM variance can produce an empty draft even after in-loop nudges;
            # give it one completely fresh run before declaring failure.
            self.reporter.warn("Generator: 空 draft，丢弃并全新生成一次...")
            draft = generator.run(
                summary, ctx, suggested_type=suggested_type,
                language=language, has_complex_branching=has_complex_branching,
            )
        if not draft:
            report.errors.append("Generator returned empty draft")
            return report

        # ------------------------------------------------------------------
        # Feedback loop: format → structure → fidelity (max 2 retries)
        # ------------------------------------------------------------------
        fidelity_warnings: list[str] = []
        for attempt in range(3):  # initial + up to 2 retries
            # Step 1: Format validation (YAML parseable, code fences cleaned)
            format_errors: list[str] = []
            # Retry attempts validate into a throwaway report so user-facing
            # report isn't polluted — but the feedback MUST be read from that
            # same report, otherwise the LLM gets empty feedback on retries.
            attempt_report = report if attempt == 0 else ImportReport()
            validated = self._validate_and_normalize(
                draft, suggested_type, attempt_report,
            )
            if not validated:
                format_errors = [e for e in attempt_report.errors if "YAML" in e or "frontmatter" in e]
                if not format_errors:
                    format_errors = ["YAML frontmatter is missing or unparseable"]

            # Step 2: Structure validation (required sections present)
            structure_errors: list[str] = []
            if validated:
                structure_errors = self._check_structure(
                    validated, suggested_type, has_complex_branching,
                )
                # Required frontmatter fields belong INSIDE the feedback loop:
                # previously they were only enforced at write time (schema gate
                # in write_kb_entry), where a missing `category` killed the
                # draft with no chance of retry.
                try:
                    _post = _fm.loads(validated)
                    _missing = [
                        f for f in ("type", "title", "category", "tags")
                        if not _post.metadata.get(f)
                    ]
                    structure_errors.extend(
                        f"Missing required frontmatter field: {f}" for f in _missing
                    )
                except Exception:  # noqa: BLE001
                    pass

            # Step 3: Fidelity check (commands, branches, symptoms, numbers)
            # Returns (errors, warnings):
            #   errors = MUST retry (branch missing, commands >30% lost, all symptoms gone)
            #   warnings = tolerable (partial loss, numbers missing)
            fidelity_errors: list[str] = []
            fidelity_warnings: list[str] = []
            if validated and not structure_errors:
                fidelity_errors, fidelity_warnings = verify_summary_fidelity_042(
                    summary, validated, entry_type=suggested_type,
                )

            # Collect issues that trigger retry
            all_issues = format_errors + structure_errors + fidelity_errors
            # Warnings also trigger retry on first attempt (try to get a clean draft)
            if attempt == 0 and fidelity_warnings:
                all_issues.extend(fidelity_warnings)

            # Accept if no structural/fidelity errors.
            # Attempt 0: require zero issues (try for a clean draft).
            # Attempt ≥1: tolerate warnings (already retried once for them).
            if validated and not format_errors and not structure_errors and not fidelity_errors:
                if not fidelity_warnings or attempt > 0:
                    draft = validated
                    break

            # Last attempt: accept if no structural/fidelity errors
            # (tolerate fidelity warnings — partial info loss is better than no entry)
            if attempt == 2 and validated and not format_errors and not structure_errors and not fidelity_errors:
                draft = validated
                break

            # Retry with feedback (not on last attempt)
            if attempt < 2:
                feedback = "; ".join(all_issues[:5])  # cap at 5 to avoid noise
                self.reporter.start(f"反哺重试 ({attempt + 1}/2): {feedback[:120]}")
                raw_draft = draft  # keep raw for feedback context
                retry_draft = generator.run_with_feedback(
                    summary, ctx, raw_draft, feedback,
                    suggested_type=suggested_type, language=language,
                    has_complex_branching=has_complex_branching,
                )
                if retry_draft:
                    draft = retry_draft
                    # Clear format errors from report so retry gets clean check
                    report.errors = [e for e in report.errors
                                     if "YAML" not in e and "frontmatter" not in e]
                else:
                    # Retry returned empty — use whatever we had
                    if validated:
                        draft = validated
                    break
            else:
                # Last attempt: use best available
                if validated:
                    draft = validated

        if not draft or draft == "":
            report.errors.append("Generator: all attempts produced invalid output")
            return report

        all_fidelity_issues = fidelity_errors + fidelity_warnings
        report.phase_traces.append(
            f"Generator: draft generated ({len(draft)} chars)"
            + (f", {len(all_fidelity_issues)} fidelity issue(s)" if all_fidelity_issues else "")
        )

        # ------------------------------------------------------------------
        # Image references: NPI docs carry waveform/scope screenshots the text
        # pipeline cannot ingest. If the draft dropped image refs, note it
        # explicitly so the agent can point the human at the source images.
        # ------------------------------------------------------------------
        import re as _re_img
        _src_images = _re_img.findall(r"!\[[^\]]*\]\([^)]+\)", source_text)
        if _src_images:
            _draft_images = _re_img.findall(r"!\[[^\]]*\]\([^)]+\)", draft)
            if len(_draft_images) < len(_src_images):
                _src_note = f"：{source_file}" if source_file else ""
                draft = draft.rstrip() + (
                    f"\n\n> 📷 原文档含 {len(_src_images)} 张配图（波形/截图等），"
                    f"本条未包含，请查阅源文件{_src_note}。\n"
                )
                report.warnings.append(
                    f"Images: {len(_src_images)} image(s) in source not carried into entry — noted in entry"
                )

        # ------------------------------------------------------------------
        # T039: mechanically ensure applies_to lands in the frontmatter
        # ------------------------------------------------------------------
        if isinstance(summary.get("applies_to"), dict) and summary["applies_to"]:
            draft = _inject_applies_to(draft, summary["applies_to"])

        # ------------------------------------------------------------------
        # Phase 3.6: User review draft
        # ------------------------------------------------------------------
        if not review_draft(draft, all_fidelity_issues, self.no_interactive, report):
            report.phase_traces.append("Writer: cancelled by user")
            return report

        # ------------------------------------------------------------------
        # Phase 4: Write to _pending/
        # ------------------------------------------------------------------
        self.reporter.start("写入待审条目...")
        self._write_pending(draft, ctx, report)
        self.reporter.done(f"写入完成 — {len(report.created)} 个条目已创建")

        # Rebuild index so new entries are immediately discoverable
        if not self.dry_run and report.created:
            from holmes.kb.store import rebuild_index_files
            rebuild_index_files(self.kb_root)

        # Git commit
        if not self.dry_run and report.created:
            self._git_commit(f"holmes import: {source_hash[:8]}")

        return report

    # ------------------------------------------------------------------
    # Multi-topic handling
    # ------------------------------------------------------------------

    def _run_multi_topic(
        self,
        source_text: str,
        file_path: Optional[Path],
        classification: ClassificationResult,
        ctx: dict[str, Any],
        report: ImportReport,
    ) -> ImportReport:
        """Split multi-topic document and run pipeline on each segment."""
        # T032: topic_boundaries are full-document offsets (the Classifier
        # sees the full outline for truncated docs). As a safety net, snap
        # each boundary to a nearby heading offset (topics start at section
        # boundaries) and drop out-of-range/duplicate values with a warning
        # instead of slicing mid-section.
        boundaries = self._sanitize_topic_boundaries(
            classification.topic_boundaries, source_text, report,
        )
        segments: list[str] = []
        prev = 0
        for b in boundaries:
            if 0 < b < len(source_text):
                seg = source_text[prev:b].strip()
                if seg:
                    segments.append(seg)
                prev = b
        final = source_text[prev:].strip()
        if final:
            segments.append(final)

        if len(segments) <= 1:
            # False positive — treat as single document
            segments = [source_text]

        self.reporter.info(f"多主题文档: 切分为 {len(segments)} 段")
        report.phase_traces.append(f"Multi-topic: {len(segments)} segments")

        for i, segment in enumerate(segments):
            self.reporter.start(f"段落 {i + 1}/{len(segments)}...")
            sub_pipeline = ImportPipeline(
                kb_root=self.kb_root,
                cfg=self.cfg,
                no_interactive=self.no_interactive,
                verbose=self.verbose,
                dry_run=self.dry_run,
                _provider=self._provider,
                force_type=self.force_type,
                force=True,  # Skip dedup for segments
                reporter=self.reporter,
            )
            sub_report = sub_pipeline.run(segment, file_path)

            # Merge results
            report.created.extend(sub_report.created)
            report.skipped.extend(sub_report.skipped)
            report.warnings.extend(sub_report.warnings)
            report.errors.extend(sub_report.errors)
            report.phase_traces.extend(
                f"[seg {i + 1}] {t}" for t in sub_report.phase_traces
            )

        return report

    # Maximum distance a topic boundary may be snapped to a heading offset.
    _BOUNDARY_SNAP_CHARS = 300

    def _sanitize_topic_boundaries(
        self,
        raw_boundaries: list[int],
        source_text: str,
        report: ImportReport,
    ) -> list[int]:
        """Validate/snap multi-topic boundaries (T032).

        Boundaries are full-document offsets. Out-of-range values are dropped
        with a report warning; in-range values within _BOUNDARY_SNAP_CHARS of
        a heading offset are snapped to it so segments start at section
        boundaries instead of mid-section.
        """
        total = len(source_text)
        heading_offsets = [h["offset"] for h in extract_document_outline(source_text)]
        clean: list[int] = []
        for b in sorted(set(int(x) for x in raw_boundaries)):
            if not 0 < b < total:
                report.warnings.append(
                    f"Multi-topic: 边界偏移 {b} 超出文档范围 (0–{total})，已丢弃"
                )
                continue
            if heading_offsets:
                nearest = min(heading_offsets, key=lambda o: abs(o - b))
                if 0 < abs(nearest - b) <= self._BOUNDARY_SNAP_CHARS:
                    self.reporter.info(
                        f"Multi-topic: 边界 {b} 吸附到最近标题偏移 {nearest}"
                    )
                    b = nearest
            if b not in clean:
                clean.append(b)
        return sorted(clean)

    # ------------------------------------------------------------------
    # Dedup check
    # ------------------------------------------------------------------
    def _check_dedup(
        self,
        source_hash: str,
        source_file: str,
        report: ImportReport,
    ) -> bool:
        """Check for duplicate/update. Returns True if should skip."""
        from holmes.kb.store import find_entries_by_source_hash, find_entries_by_source_file

        # Hash match → exact duplicate
        hash_matches = find_entries_by_source_hash(self.kb_root, source_hash)
        if hash_matches:
            for m in hash_matches:
                report.skipped.append(m.id)
            report.warnings.append(
                f"已存在完全相同的文档，跳过导入（{len(hash_matches)} 个匹配条目）"
            )
            return True

        # Source-file match + different hash → document update
        if source_file:
            file_matches = find_entries_by_source_file(self.kb_root, source_file)
            if file_matches:
                oldest = min(
                    (m.created_at for m in file_matches if m.created_at),
                    default="",
                )
                date_hint = oldest[:10] if oldest else "未知"
                self.reporter.info(f"文档有更新（上次导入：{date_hint}），继续导入新版本…")
                old_pending = [m for m in file_matches if _is_pending_entry(m)]
                if old_pending and not self.dry_run:
                    _prompt_cancel_old_pending(
                        old_pending, self.no_interactive, self.kb_root,
                    )

        return False

    # ------------------------------------------------------------------
    # Delegates to pipeline_utils (kept as staticmethods for test compat)
    # ------------------------------------------------------------------

    _strip_llm_wrapper = staticmethod(strip_llm_wrapper)

    _fix_yaml_values = staticmethod(fix_yaml_values)

    # ------------------------------------------------------------------
    # Validate + normalize draft
    # ------------------------------------------------------------------

    def _validate_and_normalize(
        self,
        draft: str,
        suggested_type: str,
        report: ImportReport,
    ) -> str:
        """Validate YAML frontmatter and run normalizer. Returns draft or empty."""
        # Strip preamble text and code fences that LLMs commonly prepend.
        draft = self._strip_llm_wrapper(draft)


        # Validate YAML parseable
        try:
            post = _fm.loads(draft)
            if not post.metadata:
                report.errors.append("Generator draft has no YAML frontmatter")
                return ""
        except Exception as exc:
            # Try to fix common YAML issues: unquoted values containing colons
            draft = self._fix_yaml_values(draft)
            try:
                post = _fm.loads(draft)
                if not post.metadata:
                    report.errors.append("Generator draft has no YAML frontmatter")
                    return ""
            except Exception as exc2:
                report.errors.append(f"Generator draft YAML error: {exc2}")
                return ""

        # Clean stray code fences from body (LLM sometimes inserts ``` after ---)
        body = post.content or ""
        if body.lstrip().startswith("```"):
            lines = body.splitlines()
            # Remove leading ``` line (and optional trailing ```)
            start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), -1)
            if start != -1:
                lines.pop(start)
                # Also remove trailing ``` if it matches
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                post.content = "\n".join(lines)
                draft = _fm.dumps(post)

        # Backfill type from suggested_type if missing
        if not post.metadata.get("type") and suggested_type:
            post.metadata["type"] = suggested_type
            draft = _fm.dumps(post)

        # Normalizer
        normalizer = DraftNormalizer()
        kb_type = post.metadata.get("type", suggested_type) or ""
        draft, norm_warnings = normalizer.normalize(draft, kb_type=kb_type)
        for w in norm_warnings:
            report.warnings.append(w)

        # Apply force_type
        if self.force_type:
            try:
                post = _fm.loads(draft)
                post.metadata["type"] = self.force_type
                draft = _fm.dumps(post)
            except Exception:  # noqa: BLE001
                pass

        return draft

    _build_fallback_outline = staticmethod(build_fallback_outline)

    # ------------------------------------------------------------------
    # Structure validation
    # ------------------------------------------------------------------

    _check_structure = staticmethod(check_structure)

    # ------------------------------------------------------------------
    # Write to _pending/
    # ------------------------------------------------------------------

    def _write_pending(
        self,
        draft: str,
        ctx: dict[str, Any],
        report: ImportReport,
    ) -> None:
        """Write a single draft to _pending/."""
        from holmes.kb.agent.tools import write_kb_entry

        source_hash = ctx.get("source_hash", "")
        result = write_kb_entry(ctx, {
            "content": draft,
            "source_hash": source_hash,
            "confidence": 1.0,
        })

        pending_id = result.get("pending_id")
        if pending_id:
            if result.get("duplicate"):
                report.skipped.append(f"(duplicate: {pending_id})")
            else:
                try:
                    post = _fm.loads(draft)
                    title = str(post.metadata.get("title", pending_id))
                except Exception:
                    title = pending_id
                report.created.append(title)
                self.reporter.done(f"→ {pending_id}")
        elif result.get("error"):
            report.errors.append(result["error"])
        elif ctx.get("dry_run"):
            report.suggestions.append(result.get("action", "would create"))

        report.phase_traces.append(
            f"Writer: {len(report.created)} created, {len(report.skipped)} skipped"
        )

    # ------------------------------------------------------------------
    # Git commit
    # ------------------------------------------------------------------

    def _git_commit(self, message: str) -> None:
        """Best-effort git commit after write.

        Stages ONLY the pipeline's own output area (contributions/: pending
        files, evidence, log). Never ``git add -A`` — an import must not
        sweep the user's unrelated uncommitted changes into its commit.
        """
        try:
            import subprocess
            subprocess.run(
                ["git", "add", "--", "contributions"],
                cwd=str(self.kb_root),
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                ["git", "commit", "-m", message, "--allow-empty"],
                cwd=str(self.kb_root),
                capture_output=True,
                timeout=30,
            )
        except Exception:  # noqa: BLE001
            pass


# Backward compatibility alias
ThreePhaseImportPipeline = ImportPipeline
