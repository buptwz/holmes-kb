"""Import report and curator finding data models with formatting.

ImportReport accumulates results from a single ``holmes import`` run and
renders them as a structured summary (FR-020) or verbose trace (FR-021).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from holmes.kb.agent.knowledge_map import KnowledgeMap


@dataclass
class CuratorFinding:
    """A single incremental skill curation finding (FR-014).

    Attributes:
        finding_type: One of "merge_candidate", "oversized", "update_candidate".
        skill_names: Names of affected skills.
        reason: Human-readable explanation.
        confidence: Confidence of the finding (0.0–1.0); relevant for
                    merge_candidate findings that use LLM confirmation.
    """

    finding_type: str
    skill_names: list[str]
    reason: str
    confidence: float = 1.0

    def __str__(self) -> str:
        names = " + ".join(self.skill_names)
        return f"{self.finding_type}: {names} — {self.reason}"


@dataclass
class DecisionTrace:
    """Per-knowledge-point verbose trace for --verbose output (FR-021).

    Attributes:
        title: KB entry title.
        confidence: LLM classification confidence.
        field_sources: Mapping of field name → source text fragment.
        unsupported_fields: Fields cleared by verifier.
        skill_decision: Skill recommendation and outcome.
        curator_findings: Curation findings for this entry's category.
    """

    title: str
    confidence: float = 0.0
    field_sources: dict[str, str] = field(default_factory=dict)
    unsupported_fields: list[str] = field(default_factory=list)
    skill_decision: str = ""
    curator_findings: list[CuratorFinding] = field(default_factory=list)


@dataclass
class ImportReport:
    """Aggregated result of a single ``holmes import`` invocation.

    Attributes:
        created: Titles of entries created.
        updated: Entry IDs that were merge-updated.
        skipped: Entry IDs/hashes that were skipped (exact duplicate).
        skills_generated: Skill names created by the agent.
        skills_linked: Skill names linked to entries (pre-existing).
        suggestions: Human-readable suggestions (skill candidates, curator
                     findings) that require user action.
        warnings: Low-confidence or missing-field warnings.
        errors: Per-item failures (LLM errors, validation failures, etc.).
        auto_decisions: Decisions made automatically in --no-interactive mode.
        dry_run: Whether this was a dry-run (no files written).
        traces: Per-knowledge-point decision traces for --verbose output.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    skills_generated: list[str] = field(default_factory=list)
    skills_linked: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    auto_decisions: list[str] = field(default_factory=list)
    dry_run: bool = False
    traces: list[DecisionTrace] = field(default_factory=list)
    knowledge_map: Optional["KnowledgeMap"] = None
    phase_traces: list[str] = field(default_factory=list)
    coverage_pct: float = 0.0

    def add_trace(self, trace: DecisionTrace) -> None:
        """Append a per-knowledge-point trace."""
        self.traces.append(trace)

    def format_summary(self) -> str:
        """Render the one-line structured summary (FR-020).

        Format:
            ✓ N created, N updated, N skipped | skill: N generated, N merged | N suggestion(s)

        Returns:
            Formatted summary string.
        """
        prefix = "[DRY RUN] " if self.dry_run else ""
        parts = [
            f"{len(self.created)} created",
            f"{len(self.updated)} updated",
            f"{len(self.skipped)} skipped",
        ]
        skill_parts = [
            f"{len(self.skills_generated)} generated",
            f"{len(self.skills_linked)} linked",
        ]
        line = f"{prefix}✓ {', '.join(parts)} | skill: {', '.join(skill_parts)}"

        suggestion_count = len(self.suggestions)
        if suggestion_count:
            first = self.suggestions[0][:60] + ("…" if len(self.suggestions[0]) > 60 else "")
            line += f" | {suggestion_count} suggestion(s): {first}"

        error_count = len(self.errors)
        if error_count:
            first_err = self.errors[0][:60]
            line += f" | ⚠ {error_count} error(s): {first_err}"

        return line

    def format_verbose(self) -> str:
        """Render the full verbose decision trace (FR-021).

        Includes KnowledgeMap summary when available (T029, 可观测性原则).

        Returns:
            Multi-line string with per-entry blocks covering confidence,
            source fragments, unsupported fields, skill decision, and
            curator findings.
        """
        lines: list[str] = []

        # T029: Surface KnowledgeMap stats in verbose output.
        if self.knowledge_map is not None:
            km = self.knowledge_map
            lines.append("  [Reader phase]")
            lines.append(f"    knowledge points: {len(km.knowledge_points)}")
            lines.append(f"    coverage: {km.coverage_pct:.1f}%")
            lines.append(f"    reading passes: {km.reading_passes}")
            if km.diminishing_returns:
                lines.append("    stopped: diminishing returns")
            if self.phase_traces:
                for trace in self.phase_traces:
                    lines.append(f"    {trace}")

        for trace in self.traces:
            lines.append(f"  [{trace.title}] confidence: {trace.confidence:.2f}")
            for fname, fragment in trace.field_sources.items():
                short = fragment[:80].replace("\n", " ")
                lines.append(f"    {fname}  ← \"{short}\"")
            for fname in trace.unsupported_fields:
                lines.append(f"    {fname}  ← [CLEARED — no source support]")
            if trace.skill_decision:
                lines.append(f"    skill  ← {trace.skill_decision}")
            for finding in trace.curator_findings:
                lines.append(f"    curator: {finding}")

        if self.auto_decisions:
            lines.append("")
            lines.append("  Auto-decisions (--no-interactive):")
            for decision in self.auto_decisions:
                lines.append(f"    • {decision}")

        if self.warnings:
            lines.append("")
            lines.append("  Warnings:")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")

        return "\n".join(lines)

    def format_dry_run_plan(self) -> str:
        """Render the dry-run execution plan (US6 / E-4, FR-019).

        Returns:
            Multi-line string listing all planned actions.
        """
        lines = ["[DRY RUN] Planned actions:"]
        for s in self.suggestions:
            lines.append(f"  {s}")

        # E-4 fix (018): show KP count from Reader pass.
        if self.warnings and any("non-kb" in w for w in self.warnings):
            for w in self.warnings:
                if "non-kb" in w:
                    lines.append(f"  Would reject: non-kb document — {w}")
                    break
        elif self.knowledge_map is not None:
            kps = self.knowledge_map.knowledge_points
            if kps:
                for kp in kps:
                    category = kp.category_hint or "unknown"
                    lines.append(
                        f'  Would create (est.): "{kp.description}" ({kp.type_hint}/{category})'
                    )
            else:
                lines.append("  Would process: (~0 knowledge point(s) estimated)")
        else:
            lines.append("  Would process: (Reader phase not run)")

        lines.append("")
        lines.append("[DRY RUN] No files written.")
        return "\n".join(lines)
