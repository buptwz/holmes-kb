"""ImportPipeline — Classifier → Summarizer → Review → Generator → Write (042).

One document = one KB entry. Three LLM calls:
  1. Classifier (1 call): document type + multi-topic detection
  2. Summarizer (1 call): whole-document structured extraction
  3. Generator (1 call): format confirmed summary into KB entry

This replaces the old ThreePhaseImportPipeline (Reader→Extractor→Dedup→Verifier).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import frontmatter as _fm

from holmes.config import HolmesConfig
from holmes.kb.agent.fidelity import verify_summary_fidelity_042
from holmes.kb.agent.interactive_review import review_draft, review_summary
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.phases.classifier import ClassificationResult, DocumentClassifier, DocumentType
from holmes.kb.agent.phases.generator import GeneratorAgent
from holmes.kb.agent.phases.summarizer import SummarizerAgent
from holmes.kb.agent.provider import create_provider
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport
from holmes.kb.importer import compute_source_hash
from holmes.kb.progress import NullReporter, ProgressReporter


# ---------------------------------------------------------------------------
# Language detection fallback
# ---------------------------------------------------------------------------


def _detect_language_heuristic(text: str, default: str = "en") -> str:
    """Detect language from text using CJK character ratio.

    If the text contains a significant proportion of Chinese characters
    (relative to alphabetic characters), return "zh". Otherwise return default.
    """
    sample = text[:3000]  # sample first 3000 chars
    cjk = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
    alpha = sum(1 for c in sample if c.isascii() and c.isalpha())
    # If CJK chars are at least 10% of (CJK + alpha), treat as Chinese
    total = cjk + alpha
    if total > 0 and cjk / total >= 0.10:
        return "zh"
    return default


# ---------------------------------------------------------------------------
# Source-file helpers
# ---------------------------------------------------------------------------


def _compute_source_file(file_path: Optional[Path]) -> str:
    """Return basename of file_path, or '' if None."""
    if file_path is None:
        return ""
    return file_path.name


def _is_pending_entry(entry: Any) -> bool:
    """Return True if entry lives in a pending directory."""
    fp = str(entry.file_path).replace("\\", "/")
    return "/_pending/" in fp or "/contributions/pending/" in fp


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
        use_dag: bool = False,  # ignored in 042 — no DAG routing
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

    def run(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport:
        """Run the full pipeline for a single source document.

        Args:
            source_text: Full source document text.
            file_path: Optional source file path (for dedup / logging).

        Returns:
            ImportReport summarising all actions taken.
        """
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
        report.phase_traces.append(
            f"Classifier: {classification.doc_type.value} → {classification.suggested_type}"
            f" — {classification.reason}"
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
        )
        summary = summarizer.run(source_text, ctx, suggested_type=suggested_type)
        if summary is None:
            report.errors.append("Summarizer failed — no summary extracted")
            return report
        report.phase_traces.append(
            f"Summarizer: {len(summary.get('key_facts', []))} facts, "
            f"{len(summary.get('commands', []))} commands"
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
        draft = generator.run(summary, ctx, suggested_type=suggested_type, language=language)
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
            validated = self._validate_and_normalize(
                draft, suggested_type, report if attempt == 0 else ImportReport(),
            )
            if not validated:
                # Collect the format error from report for feedback
                format_errors = [e for e in report.errors if "YAML" in e or "frontmatter" in e]
                if attempt == 0 and not format_errors:
                    format_errors = ["YAML frontmatter is missing or unparseable"]

            # Step 2: Structure validation (required sections present)
            structure_errors: list[str] = []
            if validated:
                structure_errors = self._check_structure(validated, suggested_type)

            # Step 3: Fidelity check (key_facts and commands preserved)
            fidelity_warnings = []
            if validated and not structure_errors:
                fidelity_warnings = verify_summary_fidelity_042(summary, validated)

            # Collect all issues
            all_issues = format_errors + structure_errors
            if fidelity_warnings:
                all_issues.extend(fidelity_warnings)

            # If no issues, accept
            if validated and not all_issues:
                draft = validated
                break

            # If validated but only minor issues on last attempt, accept
            if validated and not format_errors and not structure_errors:
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

        report.phase_traces.append(
            f"Generator: draft generated ({len(draft)} chars)"
            + (f", {len(fidelity_warnings)} fidelity warning(s)" if fidelity_warnings else "")
        )

        # ------------------------------------------------------------------
        # Phase 3.6: User review draft
        # ------------------------------------------------------------------
        if not review_draft(draft, fidelity_warnings, self.no_interactive, report):
            report.phase_traces.append("Writer: cancelled by user")
            return report

        # ------------------------------------------------------------------
        # Phase 4: Write to _pending/
        # ------------------------------------------------------------------
        self.reporter.start("写入待审条目...")
        self._write_pending(draft, ctx, report)
        self.reporter.done(f"写入完成 — {len(report.created)} 个条目已创建")

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
        boundaries = sorted(classification.topic_boundaries)
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
    # Strip LLM wrapper
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_llm_wrapper(draft: str) -> str:
        """Remove preamble text, code fences, and trailing noise from LLM output.

        LLMs commonly output patterns like:
          - "Here's the entry:\n```markdown\n---\n..."
          - "```\n---\n...\n```"
          - Some preamble text\n---\nfrontmatter\n---\nbody
        This method extracts the actual YAML-frontmatter markdown.
        """
        import re

        stripped = draft.strip()

        # Strategy 0: Handle "---\n\n```yaml\n---\n..." pattern
        # LLM sometimes outputs an empty frontmatter block followed by code-fenced real content
        fence_after_empty_fm = re.search(
            r"^---\s*\n\s*```(?:markdown|md|yaml)?\s*\n(---\n.+)",
            stripped, re.DOTALL,
        )
        if fence_after_empty_fm:
            inner = fence_after_empty_fm.group(1)
            if inner.rstrip().endswith("```"):
                inner = inner.rstrip()[:-3].rstrip()
            stripped = inner

        # Strategy 1: If it starts with ```, strip outer code fence
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Remove opening fence line
            lines = lines[1:]
            # Remove closing fence if present
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        # Strategy 2: If there's preamble before ---, find the first ---
        if not stripped.startswith("---"):
            # Look for ``` code fence containing ---
            fence_match = re.search(r"```(?:markdown|md|yaml)?\s*\n(---\n.+)", stripped, re.DOTALL)
            if fence_match:
                inner = fence_match.group(1)
                # Remove trailing ``` if present
                if inner.rstrip().endswith("```"):
                    inner = inner.rstrip()[:-3].rstrip()
                stripped = inner
            else:
                # Just find the first ---
                idx = stripped.find("\n---\n")
                if idx != -1:
                    stripped = stripped[idx + 1:]  # skip the \n before ---

        # Strategy 3: Remove trailing ``` if still present
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()

        # Strategy 4: Fix missing closing --- in frontmatter.
        # If the draft starts with --- but has no second --- before body content,
        # find the first markdown heading (##) and insert --- before it.
        if stripped.startswith("---"):
            lines = stripped.splitlines()
            has_closing = False
            for i, line in enumerate(lines[1:], 1):
                if line.strip() == "---":
                    has_closing = True
                    break
                if line.startswith("## "):
                    # Found body heading before closing --- → insert one
                    lines.insert(i, "---")
                    stripped = "\n".join(lines)
                    break
            # Also handle blank line after opening --- (yaml needs content right after)

        return stripped

    @staticmethod
    def _fix_yaml_values(draft: str) -> str:
        """Fix unquoted YAML values that contain colons.

        LLMs often produce: `title: Granite NPI: Per-Slot Config`
        YAML requires quoting when the value contains `: `.
        This method wraps such values in double quotes.
        """
        import re

        lines = draft.splitlines()
        in_frontmatter = False
        result = []
        for line in lines:
            if line.strip() == "---":
                in_frontmatter = not in_frontmatter
                result.append(line)
                continue
            if in_frontmatter:
                # Match `key: value` where value is not already quoted and not
                # a YAML collection (list/dict)
                m = re.match(r"^(\w[\w-]*:\s+)(.+)$", line)
                if m:
                    key_part, value = m.group(1), m.group(2)
                    # Skip if already quoted, or is a YAML list/bool/number
                    if (
                        not value.startswith('"')
                        and not value.startswith("'")
                        and not value.startswith("[")
                        and not value.startswith("{")
                        and ": " in value
                    ):
                        # Escape existing double quotes in value, then wrap
                        value = value.replace("\\", "\\\\").replace('"', '\\"')
                        line = f'{key_part}"{value}"'
            result.append(line)
        return "\n".join(result)

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

    # ------------------------------------------------------------------
    # Structure validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_structure(draft: str, suggested_type: str) -> list[str]:
        """Check that the draft has the required sections for its KB type.

        Returns a list of error strings (empty = pass).
        """
        # Required sections per type (lowercase for matching)
        _REQUIRED: dict[str, list[str]] = {
            "pitfall": ["symptoms", "root cause", "resolution"],
            "model": ["overview", "key concepts", "usage"],
            "guideline": ["context", "guideline", "rationale"],
            "process": ["purpose", "steps", "outcome"],
            "decision": ["context", "decision", "rationale"],
        }

        required = _REQUIRED.get(suggested_type, [])
        if not required:
            return []

        # Extract ## headings from body
        try:
            post = _fm.loads(draft)
            body = post.content or ""
        except Exception:
            body = draft

        headings = [
            line.strip().lstrip("#").strip().lower()
            for line in body.splitlines()
            if line.strip().startswith("## ")
        ]

        errors = []
        for section in required:
            if not any(section in h for h in headings):
                errors.append(
                    f"Missing required section '## {section.title()}' for type={suggested_type}"
                )

        # Check for empty required sections
        for section in required:
            for h in headings:
                if section in h:
                    # Find content between this heading and the next
                    idx = body.lower().find(f"## {h}")
                    if idx == -1:
                        continue
                    rest = body[idx:]
                    lines = rest.splitlines()[1:]  # skip heading line
                    content = []
                    for line in lines:
                        if line.strip().startswith("## "):
                            break
                        content.append(line)
                    text = "\n".join(content).strip()
                    if not text:
                        errors.append(
                            f"Section '## {section.title()}' is empty for type={suggested_type}"
                        )
                    break

        return errors

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
        """Best-effort git commit after write."""
        try:
            import subprocess
            subprocess.run(
                ["git", "add", "-A"],
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
