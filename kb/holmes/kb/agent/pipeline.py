"""ThreePhaseImportPipeline — Reader → Extractor → Dedup → Verifier orchestrator.

Orchestrates the import pipeline as designed in:
  specs/015-three-phase-import-agent/

Phase 1  (Reader):    ReaderAgent builds a KnowledgeMap of all knowledge points.
Phase 2  (Extractor): ExtractorAgent produces a draft KB entry per knowledge point.
Phase 2.5 (Dedup):   Intra-import draft dedup — compares drafts produced within
                      this single import run against each other to prevent
                      duplicate KB entries from the same document.
                      Duplicate drafts are skipped; the first occurrence is kept.
Phase 3  (Verifier):  LLM tool-use loop verifies remaining drafts and writes entries.

Knowledge validity is determined by the evidence timeline, not by import merging.
Import always creates new entries; evidence freshness decides which knowledge is current.

This class owns the shared pipeline context (ctx) and ensures that
ctx["source_text"] is always the full, untruncated original document.
"""

from __future__ import annotations

import difflib
import json
import re as _re_dedup
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from holmes.config import HolmesConfig
import frontmatter as _fm

from holmes.kb.agent.fidelity import verify_content_fidelity
from holmes.kb.agent.interactive_review import review_drafts, review_knowledge_points
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.phases.classifier import DocumentClassifier, DocumentType
from holmes.kb.agent.phases.extractor import ExtractorAgent
from holmes.kb.agent.phases.reader import COVERAGE_THRESHOLD, ReaderAgent
from holmes.kb.agent.provider import create_provider
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport
from holmes.kb.agent.tools import TOOL_DEFINITIONS, TOOL_HANDLERS
from holmes.kb.importer import compute_source_hash


MAX_EXTRACTION_ITERATIONS = 20  # tool-call iterations for extraction loop (safety cap)


# ---------------------------------------------------------------------------
# Intra-import dedup helpers (Phase 2.5)
# ---------------------------------------------------------------------------

def _text_similarity(a: str, b: str) -> float:
    """Return sequence-based similarity ratio between two strings (0.0–1.0)."""
    return difflib.SequenceMatcher(None, a[:500], b[:500]).ratio()


def _draft_dedup_key(draft_body: str, draft_metadata: dict) -> str:
    """Extract the dedup key from a draft: Root Cause for pitfall types, title otherwise."""
    m = _re_dedup.search(r"## Root Cause\s*\n(.*?)(?=\n##|\Z)", draft_body, _re_dedup.DOTALL)
    if m:
        return m.group(1).strip()[:500]
    return str(draft_metadata.get("title", ""))


# ---------------------------------------------------------------------------
# M2 Step 0 helpers
# ---------------------------------------------------------------------------

def _compute_source_file(kb_root: Path, file_path: Optional[Path]) -> str:
    """Return path relative to kb_root as a POSIX string, or '' if not applicable.

    Returns '' when file_path is None or lies outside kb_root (e.g. stdin / external paths).

    Args:
        kb_root: Root directory of the knowledge base.
        file_path: Absolute path to the source document (may be None).

    Returns:
        Relative POSIX path string (e.g. ``docs/hardware/gpu.md``) or empty string.
    """
    if file_path is None:
        return ""
    try:
        return file_path.relative_to(kb_root).as_posix()
    except ValueError:
        return ""


def _is_pending_entry(entry: Any) -> bool:
    """Return True if entry lives in a pending directory.

    Checks both the new-format ``_pending/<type>/<category>/`` hierarchy
    and the legacy ``contributions/pending/`` flat directory.
    """
    fp = str(entry.file_path).replace("\\", "/")
    return "/_pending/" in fp or "/contributions/pending/" in fp


def _prompt_cancel_old_pending(
    old_pending: list,
    no_interactive: bool,
    kb_root: Path,
) -> None:
    """Offer to delete old pending entries when re-importing an updated document.

    In interactive mode, prompts the user with [Y/n].  In non-interactive mode
    (batch import or --no-interactive), automatically keeps the old entries (n).
    Dry-run callers must not call this function (guard at call site).

    Args:
        old_pending: List of EntryMeta for pending entries from a previous import.
        no_interactive: When True, auto-answer n (keep old pending).
        kb_root: Root directory of the knowledge base.
    """
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
            # Delete by file path — works for both _pending/<type>/<category>/ (new)
            # and contributions/pending/ (legacy) without depending on directory layout.
            Path(entry.file_path).unlink(missing_ok=True)
            print(f"  已取消: {entry.id}")
    else:
        print("  → 新旧 pending 并存，reviewer 在 approve 时自行选择")


class ThreePhaseImportPipeline:
    """Orchestrates the three-phase import pipeline for a single source document.

    Each phase runs with an isolated LLM message context (forked agent pattern).
    The full untruncated source_text is always available in ctx["source_text"].

    Args:
        kb_root: Root directory of the knowledge base.
        cfg: HolmesConfig with provider, model, api_key, api_base_url.
        no_interactive: When True, suppress all confirmation gates.
        verbose: When True, collect per-field decision traces.
        dry_run: When True, all write tools become no-ops.
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
        use_dag: bool = False,
        progress_fn: Optional[Any] = None,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.no_interactive = no_interactive
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_type = force_type
        # T007 (020): force bypasses document-level dedup pre-check.
        self.force = force
        # 039: --dag flag forces DAG pipeline regardless of Classifier result.
        self.use_dag = use_dag
        # 039/M9: unified progress callback. Defaults to print().
        self._progress = progress_fn if progress_fn is not None else print
        # Allow caller to inject a pre-created provider (e.g. for testing / reuse).
        self._provider: LLMProvider = _provider if _provider is not None else create_provider(cfg)

    def run(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport:
        """Run the full three-phase pipeline for a single source document.

        Args:
            source_text: Full, untruncated source document text.
            file_path: Optional source file path (for logging / prompt context).

        Returns:
            ImportReport summarising all actions taken.
        """
        report = ImportReport(dry_run=self.dry_run)
        source_hash = compute_source_hash(source_text)

        # M2 Step 0: 去重与更新检测
        # --force bypasses all Step 0 checks so engineers can force a fresh import.
        source_file = _compute_source_file(self.kb_root, file_path)
        if not self.force:
            from holmes.kb.store import find_entries_by_source_hash, find_entries_by_source_file

            # Step 0a: hash match → exact duplicate, skip without starting pipeline.
            hash_matches = find_entries_by_source_hash(self.kb_root, source_hash)
            if hash_matches:
                for m in hash_matches:
                    report.skipped.append(m.id)
                n = len(hash_matches)
                report.warnings.append(
                    f"已存在完全相同的文档，跳过导入（{n} 个匹配{'条目' if n > 1 else '条目'}）"
                )
                return report

            # Step 0b: source_file match + different hash → document update.
            # Continue pipeline (new entries will be generated), but notify user
            # and offer to clean up any old pending entries from the previous import.
            if source_file:
                file_matches = find_entries_by_source_file(self.kb_root, source_file)
                if file_matches:
                    oldest = min(
                        (m.created_at for m in file_matches if m.created_at),
                        default="",
                    )
                    date_hint = oldest[:10] if oldest else "未知"
                    self._progress(f"文档有更新（上次导入：{date_hint}），继续导入新版本…")
                    old_pending = [m for m in file_matches if _is_pending_entry(m)]
                    if old_pending and not self.dry_run:
                        _prompt_cancel_old_pending(
                            old_pending, self.no_interactive, self.kb_root
                        )

        # Shared pipeline context — source_text is NEVER truncated here.
        ctx: dict[str, Any] = {
            "kb_root": self.kb_root,
            "dry_run": self.dry_run,
            "provider": self._provider,
            "model": self.cfg.model,
            "report": report,
            "source_hash": source_hash,
            # M2: propagate source_file so write_kb_entry can stamp it on new entries.
            "source_file": source_file,
            "no_interactive": self.no_interactive,
            # C-001: full original source available to all phases via ctx.
            "source_text": source_text,
            # E-2 fix: propagate force_type to write_kb_entry so Phase 3 LLM cannot override.
            "force_type": self.force_type or "",
            # T009 (020): propagate CLI --force so write_kb_entry bypasses entry-level dedup.
            "force": self.force,
        }

        # 039: --dag flag bypasses Classifier entirely → DAG pipeline.
        if getattr(self, 'use_dag', False):
            dag_report = self._run_dag_pipeline(source_text, file_path)
            self._run_complementary_extraction(source_text, dag_report, file_path, ctx)
            return dag_report

        # ------------------------------------------------------------------
        # Root D (018): DocumentClassifier — pre-Reader document type check.
        # ------------------------------------------------------------------
        classifier = DocumentClassifier(provider=self._provider, model=self.cfg.model)
        classification = classifier.classify(source_text)
        report.phase_traces.append(
            f"Classifier: {classification.doc_type.value}"
            f" / {classification.complexity.value}"
            f" — {classification.reason}"
        )
        if classification.doc_type == DocumentType.non_kb:
            if self.force:
                report.warnings.append(
                    f"non-kb document (--force bypassed): {classification.reason}"
                )
            else:
                report.warnings.append(
                    f"non-kb document: {classification.reason} — skipped"
                )
                return report
        # 039: Route incident + complex_branching to DAG pipeline.
        if classification.needs_dag:
            dag_report = self._run_dag_pipeline(source_text, file_path)
            self._run_complementary_extraction(source_text, dag_report, file_path, ctx)
            return dag_report

        if classification.granularity_hint:
            ctx["granularity_hint"] = classification.granularity_hint

        # 022 US3: log_fn wires per-pass Reader progress into report.phase_traces.
        def _reader_log(msg: str) -> None:
            report.phase_traces.append(msg)

        # E-4 fix (018): dry-run path — run Classifier + Reader only (no writes).
        if self.dry_run:
            reader = ReaderAgent(provider=self._provider, model=self.cfg.model)
            knowledge_map = reader.run(source_text, ctx, log_fn=_reader_log)
            report.knowledge_map = knowledge_map
            report.coverage_pct = knowledge_map.coverage_pct
            report.phase_traces.append(
                f"Reader: {len(knowledge_map.knowledge_points)} knowledge points identified, "
                f"{knowledge_map.coverage_pct:.0f}% coverage, "
                f"{knowledge_map.reading_passes} reading pass(es)"
                + (" [diminishing returns]" if knowledge_map.diminishing_returns else "")
            )
            if len(knowledge_map.knowledge_points) == 0:
                report.warnings.append(
                    "No knowledge points identified — document may be empty, "
                    "unrecognized format, or contain no actionable knowledge."
                )
            return report

        # ------------------------------------------------------------------
        # Phase 1: Reader — build KnowledgeMap
        # ------------------------------------------------------------------
        reader = ReaderAgent(provider=self._provider, model=self.cfg.model)
        knowledge_map = reader.run(source_text, ctx, log_fn=_reader_log)
        report.knowledge_map = knowledge_map
        report.coverage_pct = knowledge_map.coverage_pct
        report.phase_traces.append(
            f"Reader: {len(knowledge_map.knowledge_points)} knowledge points identified, "
            f"{knowledge_map.coverage_pct:.0f}% coverage, "
            f"{knowledge_map.reading_passes} reading pass(es)"
            + (" [diminishing returns]" if knowledge_map.diminishing_returns else "")
        )

        # D-4: Warn when Reader finds no knowledge points (silent exit guard).
        if len(knowledge_map.knowledge_points) == 0:
            report.warnings.append(
                "No knowledge points identified — document may be empty, "
                "unrecognized format, or contain no actionable knowledge."
            )

        # ------------------------------------------------------------------
        # 039: KP review gate — let user confirm/skip/cancel before extraction.
        # ------------------------------------------------------------------
        knowledge_map = review_knowledge_points(knowledge_map, self.no_interactive, report)
        if not knowledge_map.knowledge_points:
            return report

        # ------------------------------------------------------------------
        # Phase 2: Extraction — one ExtractorAgent per KnowledgePoint (T019)
        # Coverage gate (T020): only start extraction when Reader is confident.
        # ------------------------------------------------------------------
        kp_drafts: dict[str, str] = {}
        if knowledge_map.coverage_pct >= COVERAGE_THRESHOLD or knowledge_map.diminishing_returns:
            extractor = ExtractorAgent(provider=self._provider, model=self.cfg.model)
            _total_kps = len(knowledge_map.knowledge_points)

            def _extract_one(kp_idx_kp: tuple[int, Any]) -> tuple[str, str, list[str]]:
                """Extract a single KP (thread-safe — each KP has isolated messages)."""
                kp_idx, kp = kp_idx_kp
                _desc = str(kp.description or kp.id)[:60]
                self._progress(f"  [{kp_idx + 1}/{_total_kps}] Extracting: {_desc}...")
                draft = extractor.run(kp, knowledge_map, ctx)
                if not draft:
                    return kp.id, "", []
                repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)
                if not repaired:
                    return kp.id, "", [f"{kp.id}: draft format error — {warning}; skipping this knowledge point"]
                warnings: list[str] = []
                if warning:
                    warnings.append(f"{kp.id}: draft repaired — {warning}")
                normalizer = DraftNormalizer()
                kb_type_hint = kp.type_hint or ""
                repaired, norm_warnings = normalizer.normalize(repaired, kb_type=kb_type_hint)
                for w in norm_warnings:
                    warnings.append(f"{kp.id}: {w}")
                if self.force_type:
                    try:
                        _post = _fm.loads(repaired)
                        _post.metadata["type"] = self.force_type
                        repaired = _fm.dumps(_post)
                    except Exception:  # noqa: BLE001
                        pass
                if (kp.type_hint or "") == "pitfall" and _is_resolution_empty(repaired):
                    source_slice = source_text[kp.section_start:kp.section_end].strip()
                    if source_slice:
                        repaired = _inject_resolution(repaired, source_slice)
                        warnings.append(f"{kp.id}: resolution auto-recovered from source text")
                kp.extracted = True
                return kp.id, repaired, warnings

            # US-3: parallel extraction — each KP has independent LLM context (C-003).
            kp_items = list(enumerate(knowledge_map.knowledge_points))
            max_workers = min(3, len(kp_items))
            if max_workers <= 1:
                # Single KP — run directly.
                for item in kp_items:
                    kp_id, draft, warns = _extract_one(item)
                    for w in warns:
                        if "draft format error" in w:
                            report.errors.append(w)
                        else:
                            report.warnings.append(w)
                    if draft:
                        kp_drafts[kp_id] = draft
            else:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(_extract_one, item): item for item in kp_items}
                    for future in as_completed(futures):
                        kp_id, draft, warns = future.result()
                        for w in warns:
                            if "draft format error" in w:
                                report.errors.append(w)
                            else:
                                report.warnings.append(w)
                        if draft:
                            kp_drafts[kp_id] = draft

            report.phase_traces.append(
                f"Extractor: {len(kp_drafts)}/{len(knowledge_map.knowledge_points)} "
                f"knowledge points extracted"
                f" (parallel, workers={max_workers})" if max_workers > 1 else
                f"Extractor: {len(kp_drafts)}/{len(knowledge_map.knowledge_points)} "
                f"knowledge points extracted (serial)"
            )
        else:
            report.phase_traces.append(
                f"Extractor: skipped (coverage {knowledge_map.coverage_pct:.0f}% "
                f"< threshold {COVERAGE_THRESHOLD:.0f}%)"
            )

        # ------------------------------------------------------------------
        # Phase 2.5: Intra-import draft dedup
        # Compares drafts within this import run against each other.
        # No cross-KB reads or updates — import always creates new entries.
        # ------------------------------------------------------------------
        if kp_drafts:
            dedup_handled = self._run_intra_import_dedup(kp_drafts, report)
            for kp_id in dedup_handled:
                kp_drafts.pop(kp_id, None)
            if dedup_handled:
                report.phase_traces.append(
                    f"Dedup: {len(dedup_handled)} draft(s) skipped as intra-import duplicate(s)"
                )

        # ------------------------------------------------------------------
        # 039: Fidelity check + draft review gate
        # ------------------------------------------------------------------
        fidelity_results: dict[str, list[str]] = {}
        for kp_id, draft in kp_drafts.items():
            kp = next((k for k in knowledge_map.knowledge_points if k.id == kp_id), None)
            if kp:
                section = source_text[kp.section_start:kp.section_end]
                fidelity_results[kp_id] = verify_content_fidelity(section, draft)

        kp_drafts = review_drafts(kp_drafts, fidelity_results, self.no_interactive, report)

        if not kp_drafts:
            report.phase_traces.append("Writer: cancelled by user or no drafts remaining")
            return report

        # ------------------------------------------------------------------
        # 039: Direct write to _pending/ (replaces Phase 3 LLM loop)
        # ------------------------------------------------------------------
        self._write_pending_entries(kp_drafts, ctx, report)

        return report

    # ------------------------------------------------------------------
    # Internal: Intra-import draft dedup (Phase 2.5)
    # ------------------------------------------------------------------

    def _run_intra_import_dedup(
        self,
        kp_drafts: dict[str, Any],
        report: ImportReport,
    ) -> set[str]:
        """Deduplicate drafts within a single import run.

        Compares drafts against each other (not against existing KB entries).
        For each draft, extracts a dedup key (Root Cause for pitfall types,
        title for others) and compares it against all previously seen keys
        using difflib similarity. If similarity >= 0.8, the draft is a
        duplicate and is skipped; the first occurrence is kept.

        This preserves the "always create new" policy — no existing KB entries
        are read or modified. Dedup only prevents the same document from
        producing multiple near-identical entries in one import run.

        Returns:
            Set of KP IDs to skip (duplicates). Caller removes them from kp_drafts
            before the LLM writer loop.
        """
        seen: list[tuple[str, str]] = []  # (kp_id, dedup_key)
        duplicates: set[str] = set()

        for kp_id, draft in kp_drafts.items():
            try:
                post = _fm.loads(draft)
                body = post.content or ""
                metadata = post.metadata
            except Exception:  # noqa: BLE001
                continue

            key = _draft_dedup_key(body, metadata)
            if not key:
                continue

            matched_id: Optional[str] = None
            for seen_id, seen_key in seen:
                if _text_similarity(key, seen_key) >= 0.8:
                    matched_id = seen_id
                    break

            if matched_id is not None:
                duplicates.add(kp_id)
                report.skipped.append(
                    f"{kp_id} (intra-import duplicate of {matched_id})"
                )
                report.phase_traces.append(
                    f"Dedup: {kp_id} is a near-duplicate of {matched_id} "
                    f"within this import run — skipped"
                )
            else:
                seen.append((kp_id, key))

        return duplicates

    # ------------------------------------------------------------------
    # Internal: DAG pipeline framework (M3 stub — M4 fills in)
    # ------------------------------------------------------------------

    def _run_dag_pipeline(
        self,
        source_text: str,
        file_path: Optional[Path] = None,
    ) -> "ImportReport":
        """DAG-based import pipeline for pitfall document types.

        US-4: If a cached .dag.json exists for this source_hash, skips Agent 1
        entirely and jumps directly to Agent 2 (with checkpoint recovery).

        Args:
            source_text: Full, untruncated source document text.
            file_path: Optional source file path.

        Returns:
            ImportReport summarising all actions.
        """
        source_hash = compute_source_hash(source_text)
        state_dir = self.kb_root / "_import-state"
        dag_json_path = state_dir / f"{source_hash}.dag.json"

        # US-4: DAG cache reuse — skip Agent 1 if .dag.json already exists.
        if dag_json_path.exists() and not self.dry_run:
            self._progress("DAG cache hit — skipping Agent 1, jumping to Agent 2")
            from holmes.kb.agent.dag.harness2 import run_agent2

            report = run_agent2(
                source_text=source_text,
                file_path=file_path,
                kb_root=self.kb_root,
                cfg=self.cfg,
                provider=self._provider,
                source_hash=source_hash,
                dag_json_path=dag_json_path,
                no_interactive=self.no_interactive,
                dry_run=self.dry_run,
            )
            report.phase_traces.insert(0, "DAG cache hit — Agent 1 skipped")
            return report

        from holmes.kb.agent.dag import run_agent1

        return run_agent1(
            source_text=source_text,
            file_path=file_path,
            kb_root=self.kb_root,
            cfg=self.cfg,
            provider=self._provider,
            no_interactive=self.no_interactive,
            dry_run=self.dry_run,
        )

    # ------------------------------------------------------------------
    # Internal: Complementary Extraction (039/M8)
    # ------------------------------------------------------------------

    def _run_complementary_extraction(
        self,
        source_text: str,
        dag_report: ImportReport,
        file_path: Optional[Path],
        ctx: dict[str, Any],
    ) -> None:
        """After DAG completes, scan uncovered portions for non-pitfall knowledge.

        Reads the .dag.json to get covered line ranges, computes uncovered percentage.
        If >10% of the document is uncovered, runs Classic Reader on the remainder,
        filtering for non-pitfall/process types (since DAG already handles those).

        Modifies dag_report in-place to add complementary entries.
        """
        source_hash = ctx.get("source_hash", "")
        if not source_hash:
            source_hash = compute_source_hash(source_text)

        # Load DAG to get covered line ranges.
        state_dir = self.kb_root / "_import-state"
        dag_json_path = state_dir / f"{source_hash}.dag.json"
        if not dag_json_path.exists():
            return

        try:
            import json as _json
            dag_data = _json.loads(dag_json_path.read_text(encoding="utf-8"))
            nodes = dag_data.get("nodes", [])
        except Exception:  # noqa: BLE001
            return

        # Collect covered line ranges from DAG nodes.
        covered_lines: set[int] = set()
        for node in nodes:
            lr = node.get("line_range")
            if lr and len(lr) == 2:
                start, end = int(lr[0]), int(lr[1])
                covered_lines.update(range(start, end + 1))

        if not covered_lines:
            return

        # Convert to uncovered percentage.
        total_lines = source_text.count("\n") + 1
        uncovered_pct = 100.0 * (1.0 - len(covered_lines) / max(total_lines, 1))

        if uncovered_pct < 10:
            dag_report.phase_traces.append(
                f"Complementary: skipped (uncovered {uncovered_pct:.0f}% < 10%)"
            )
            return

        dag_report.phase_traces.append(
            f"Complementary: {uncovered_pct:.0f}% uncovered, running Classic Reader..."
        )

        # Build uncovered char ranges for Reader context.
        lines = source_text.split("\n")
        uncovered_sections: list[str] = []
        char_pos = 0
        for line_idx, line in enumerate(lines):
            if (line_idx + 1) not in covered_lines:
                uncovered_sections.append(line)
            char_pos += len(line) + 1

        uncovered_text = "\n".join(uncovered_sections)
        if len(uncovered_text.strip()) < 100:
            dag_report.phase_traces.append(
                "Complementary: uncovered text too short, skipping"
            )
            return

        # Run Classic Reader on uncovered text.
        def _log(msg: str) -> None:
            dag_report.phase_traces.append(f"Complementary-Reader: {msg}")

        reader = ReaderAgent(provider=self._provider, model=self.cfg.model)
        km = reader.run(uncovered_text, ctx, log_fn=_log)

        # Filter out pitfall/process (DAG already covers those).
        km.knowledge_points = [
            kp for kp in km.knowledge_points
            if kp.type_hint not in ("pitfall", "process")
        ]

        if not km.knowledge_points:
            dag_report.phase_traces.append(
                "Complementary: no non-pitfall knowledge points found"
            )
            return

        # Review gate.
        km = review_knowledge_points(km, self.no_interactive, dag_report)
        if not km.knowledge_points:
            return

        # Extract drafts.
        extractor = ExtractorAgent(provider=self._provider, model=self.cfg.model)
        kp_drafts: dict[str, str] = {}
        for kp in km.knowledge_points:
            draft = extractor.run(kp, km, ctx)
            if not draft:
                continue
            repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)
            if not repaired:
                dag_report.errors.append(f"{kp.id}: complementary draft error — {warning}")
                continue
            if warning:
                dag_report.warnings.append(f"{kp.id}: {warning}")
            normalizer = DraftNormalizer()
            repaired, norm_warnings = normalizer.normalize(repaired, kb_type=kp.type_hint or "")
            for w in norm_warnings:
                dag_report.warnings.append(f"{kp.id}: {w}")
            kp_drafts[kp.id] = repaired

        if not kp_drafts:
            return

        # Fidelity check + review.
        fidelity_results: dict[str, list[str]] = {}
        for kp_id, draft in kp_drafts.items():
            kp = next((k for k in km.knowledge_points if k.id == kp_id), None)
            if kp:
                section = uncovered_text[kp.section_start:kp.section_end]
                fidelity_results[kp_id] = verify_content_fidelity(section, draft)

        kp_drafts = review_drafts(kp_drafts, fidelity_results, self.no_interactive, dag_report)

        if kp_drafts:
            self._write_pending_entries(kp_drafts, ctx, dag_report)
            dag_report.phase_traces.append(
                f"Complementary: {len(kp_drafts)} non-pitfall entries extracted"
            )

    # ------------------------------------------------------------------
    # Internal: Direct write to _pending/ (039 — replaces Phase 3 LLM loop)
    # ------------------------------------------------------------------

    def _write_pending_entries(
        self,
        kp_drafts: dict[str, str],
        ctx: dict[str, Any],
        report: ImportReport,
    ) -> None:
        """Write verified drafts directly to _pending/ without an LLM loop.

        Each draft already has valid YAML frontmatter (repaired + normalized by
        Phase 2). This method stamps source_hash/source_file, applies force_type
        override, and calls write_pending() to persist.

        Skill generation runs as post-processing after all writes.
        """
        from holmes.kb.agent.tools import write_kb_entry

        source_hash = ctx.get("source_hash", "")

        for kp_id, draft in kp_drafts.items():
            result = write_kb_entry(ctx, {
                "content": draft,
                "source_hash": source_hash,
                "confidence": 1.0,
            })
            pending_id = result.get("pending_id")
            if pending_id:
                if result.get("duplicate"):
                    report.skipped.append(f"{kp_id} (duplicate: {pending_id})")
                else:
                    report.created.append(pending_id)
                    self._progress(f"  ✓ {kp_id} → {pending_id}")
            elif result.get("error"):
                report.errors.append(f"{kp_id}: {result['error']}")
            elif ctx.get("dry_run"):
                report.suggestions.append(f"{kp_id}: {result.get('action', 'would create')}")

        report.phase_traces.append(
            f"Writer: {len(report.created)} created, {len(report.skipped)} skipped (direct write)"
        )

        # Skill generation post-processing (same as before).
        try:
            from holmes.kb.agent.runner import ImportAgentRunner
            runner = ImportAgentRunner(
                kb_root=self.kb_root,
                cfg=self.cfg,
                no_interactive=self.no_interactive,
                verbose=self.verbose,
                dry_run=self.dry_run,
            )
            runner._current_report = report
            runner._provider = self._provider
            runner._finalize_skill_generation(report)
        except Exception as _skill_exc:
            report.warnings.append(
                f"Skill generation failed (entries still saved): "
                f"{type(_skill_exc).__name__}: {_skill_exc}"
            )

        # Git commit after all writes.
        if not self.dry_run and report.created:
            try:
                from holmes.kb.agent.runner import ImportAgentRunner
                runner = ImportAgentRunner(
                    kb_root=self.kb_root,
                    cfg=self.cfg,
                    no_interactive=self.no_interactive,
                    dry_run=self.dry_run,
                )
                runner._git_commit(f"holmes import: {ctx.get('source_hash', '')[:8]}")
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Internal: Extraction + Verification loop (legacy, kept for fallback)
    # ------------------------------------------------------------------

    def _run_extraction_loop(
        self,
        source_text: str,
        source_hash: str,
        file_path: Optional[Path],
        ctx: dict[str, Any],
        report: ImportReport,
    ) -> None:
        """Run Phase 3 verification + KB write via the LLM tool-use loop.

        When kp_drafts are available (from ExtractorAgent), they are passed to
        the LLM as pre-extracted drafts for verification (T023). The LLM then
        calls verify_content with ctx["source_text"] (full untruncated source)
        and write_kb_entry to persist the verified entries.

        For T024: skill generation runs after all KPs are extracted and verified.
        """
        from holmes.kb.agent.runner import (
            MAX_TOOL_ITERATIONS,
            _IMPORT_SYSTEM_PROMPT,
            ImportAgentRunner,
        )

        # Build user prompt WITHOUT any truncation (W1-F1 root fix).
        user_prompt = (
            f"source_hash: {source_hash}\n"
            f"file: {file_path or '(stdin)'}\n\n"
            f"SOURCE TEXT:\n{source_text}"
        )

        # T023: Include pre-extracted KP drafts when available so the LLM can
        # verify each draft against the full source and write to pending, rather
        # than re-extracting from scratch. ctx["source_text"] (full original)
        # is used by verify_content via the W1-F1 fallback.
        kp_drafts: dict[str, str] = ctx.get("kp_drafts", {})
        km = report.knowledge_map

        if kp_drafts:
            drafts_block = "\n\n".join(
                f"--- Draft for {kp_id} ---\n{draft}"
                for kp_id, draft in kp_drafts.items()
            )
            user_prompt += (
                f"\n\nThe Reader and Extractor phases have pre-produced the following "
                f"{len(kp_drafts)} draft KB entry(ies). "
                f"Source hash has already been checked — no duplicates found. "
                f"Do NOT call check_source_hash. "
                f"For each draft, in order:\n"
                f"1. Call verify_content with the draft to check field support against "
                f"the full source text (already in your context).\n"
                f"2. Call write_kb_entry with the verified content and source_hash={source_hash}.\n"
                f"3. Call evaluate_skill / create_skill_for_entry if appropriate.\n"
                f"Process ALL {len(kp_drafts)} draft(s) before finishing.\n\n"
                f"{drafts_block}"
            )
        elif km and km.knowledge_points:
            kp_summary = "\n".join(
                f"  - {kp.id}: {kp.description} (chars {kp.section_start}–{kp.section_end})"
                for kp in km.knowledge_points
            )
            user_prompt += (
                f"\n\nReader identified {len(km.knowledge_points)} knowledge point(s):\n"
                f"{kp_summary}"
            )

        messages: list[Any] = [{"role": "user", "content": user_prompt}]

        # Need a runner instance for _dispatch_tool and gate logic.
        runner = ImportAgentRunner(
            kb_root=self.kb_root,
            cfg=self.cfg,
            no_interactive=self.no_interactive,
            verbose=self.verbose,
            dry_run=self.dry_run,
        )
        runner._current_report = report
        runner._provider = self._provider  # share provider instance

        # Scale iteration limit to number of pre-extracted drafts (each takes ~4-6 tool calls).
        iteration_limit = max(MAX_TOOL_ITERATIONS, len(kp_drafts) * 6) if kp_drafts else MAX_TOOL_ITERATIONS

        for _ in range(iteration_limit):
            stop, tool_calls, messages, _ = self._provider.complete(
                messages=messages,
                system=_IMPORT_SYSTEM_PROMPT,
                model=self.cfg.model,
                max_tokens=4096,
                tools=TOOL_DEFINITIONS,
            )

            if stop or not tool_calls:
                break

            results: list[tuple[str, str]] = []
            for tc in tool_calls:
                result = runner._dispatch_tool(tc.name, tc.input, ctx)
                results.append((tc.id, json.dumps(result)))

            messages = self._provider.append_tool_results(messages, results)

        report.phase_traces.append(
            f"Verifier+Writer: {len(report.created)} created, {len(report.updated)} updated"
        )

        # T024: Skill generation runs after all KPs extracted and verified (C-2 fallback).
        # Skill generation is post-processing — KB entries are already written at this point.
        # Any exception here must NOT propagate or change the exit code.
        try:
            runner._finalize_skill_generation(report)
        except Exception as _skill_exc:
            report.warnings.append(
                f"Skill generation failed (entries still saved): "
                f"{type(_skill_exc).__name__}: {_skill_exc}"
            )

        # Git commit after all writes.
        if not self.dry_run:
            runner._git_commit(f"holmes import: {source_hash[:8]}")


# ---------------------------------------------------------------------------
# Module-level helpers for Root E verbatim fallback (018)
# ---------------------------------------------------------------------------

import re as _re

_RESOLUTION_EMPTY_RE = _re.compile(
    r"(?m)^## Resolution\s*\n(.*?)(?=^##|\Z)", _re.DOTALL
)


def _is_resolution_empty(draft: str) -> bool:
    """Return True if the draft's ## Resolution section is missing or empty."""
    try:
        post = _fm.loads(draft)
        body = post.content
    except Exception:  # noqa: BLE001
        body = draft
    m = _RESOLUTION_EMPTY_RE.search(body)
    if m is None:
        return True
    return not m.group(1).strip()


def _inject_resolution(draft: str, source_text: str) -> str:
    """Inject auto-recovered source text into the draft's ## Resolution section."""
    try:
        post = _fm.loads(draft)
        body = post.content
    except Exception:  # noqa: BLE001
        return draft

    recovery_marker = "[auto-recovered from source]"
    replacement_text = f"## Resolution\n\n{recovery_marker}\n\n{source_text}\n"

    if _RESOLUTION_EMPTY_RE.search(body):
        body = _RESOLUTION_EMPTY_RE.sub(replacement_text, body)
    else:
        body = body.rstrip() + f"\n\n{replacement_text}"

    post.content = body
    return _fm.dumps(post)
