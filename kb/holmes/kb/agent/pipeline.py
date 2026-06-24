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
from pathlib import Path
from typing import Any, Optional

from holmes.config import HolmesConfig
import frontmatter as _fm

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
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.no_interactive = no_interactive
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_type = force_type
        # T007 (020): force bypasses document-level dedup pre-check.
        self.force = force
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
                    print(f"文档有更新（上次导入：{date_hint}），继续导入新版本…")
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

        # M3: --type pitfall bypasses Classifier entirely → DAG pipeline.
        if self.force_type == "pitfall":
            return self._run_dag_pipeline(source_text, file_path)

        # ------------------------------------------------------------------
        # Root D (018): DocumentClassifier — pre-Reader document type check.
        # ------------------------------------------------------------------
        classifier = DocumentClassifier(provider=self._provider, model=self.cfg.model)
        classification = classifier.classify(source_text)
        report.phase_traces.append(
            f"Classifier: {classification.doc_type.value} — {classification.reason}"
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
        # M3: Route single_incident / multi_incident to DAG pipeline.
        if classification.doc_type in (
            DocumentType.single_incident,
            DocumentType.multi_incident,
        ):
            if classification.doc_type == DocumentType.multi_incident:
                print(
                    "⚠ 警告：文档包含多个独立事件，建议拆分为独立文档分别导入。"
                    "（当前流程不阻断，将生成多棵独立排查树）"
                )
            return self._run_dag_pipeline(source_text, file_path)

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
        # Phase 2: Extraction — one ExtractorAgent per KnowledgePoint (T019)
        # Coverage gate (T020): only start extraction when Reader is confident.
        # ------------------------------------------------------------------
        kp_drafts: dict[str, str] = {}
        if knowledge_map.coverage_pct >= COVERAGE_THRESHOLD or knowledge_map.diminishing_returns:
            extractor = ExtractorAgent(provider=self._provider, model=self.cfg.model)
            _total_kps = len(knowledge_map.knowledge_points)
            for _kp_idx, kp in enumerate(knowledge_map.knowledge_points):
                _desc = str(kp.description or kp.id)[:60]
                print(f"  [{_kp_idx + 1}/{_total_kps}] Extracting: {_desc}...", flush=True)
                draft = extractor.run(kp, knowledge_map, ctx)
                if not draft:
                    continue
                # T002 fix (020): repair YAML FIRST so normalizer always runs on valid YAML.
                # Previously normalization ran before repair, causing silent skip on malformed YAML.
                repaired, warning = ExtractorAgent._validate_and_repair_draft(draft)
                if not repaired:
                    report.errors.append(
                        f"{kp.id}: draft format error — {warning}; skipping this knowledge point"
                    )
                    continue
                if warning:
                    report.warnings.append(f"{kp.id}: draft repaired — {warning}")
                # Root A: deterministic normalization after YAML repair (020 order fix).
                normalizer = DraftNormalizer()
                kb_type_hint = kp.type_hint or ""
                repaired, norm_warnings = normalizer.normalize(repaired, kb_type=kb_type_hint)
                for w in norm_warnings:
                    report.warnings.append(f"{kp.id}: {w}")
                # E-2: Enforce user-specified type after normalization (deterministic override).
                if self.force_type:
                    try:
                        _post = _fm.loads(repaired)
                        _post.metadata["type"] = self.force_type
                        repaired = _fm.dumps(_post)
                    except Exception:  # noqa: BLE001
                        pass
                # Root E (018): verbatim resolution fallback for pitfall entries.
                if (kp.type_hint or "") == "pitfall" and _is_resolution_empty(repaired):
                    source_slice = source_text[kp.section_start:kp.section_end].strip()
                    if source_slice:
                        repaired = _inject_resolution(repaired, source_slice)
                        report.warnings.append(
                            f"{kp.id}: resolution auto-recovered from source text"
                        )
                kp.extracted = True
                kp_drafts[kp.id] = repaired
            report.phase_traces.append(
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

        # Store drafts for Phase 3 (Verifier integration, T023).
        ctx["kp_drafts"] = kp_drafts

        # ------------------------------------------------------------------
        # Phase 3: Verification + KB write
        # ------------------------------------------------------------------
        self._run_extraction_loop(source_text, source_hash, file_path, ctx, report)

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

        Calls Agent 1 (dag/harness1.py) to extract the troubleshooting DAG,
        then presents an interactive [1/2/3] menu for the user to review.

        Runtime parameters are accessible via self:
          - self.dry_run: bool
          - self.no_interactive: bool
          - self.force_type: Optional[str]
          - self.force: bool

        Args:
            source_text: Full, untruncated source document text.
            file_path: Optional source file path.

        Returns:
            ImportReport summarising all Agent 1 actions.
        """
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
    # Internal: Extraction + Verification loop
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
            stop, tool_calls, messages = self._provider.complete(
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
