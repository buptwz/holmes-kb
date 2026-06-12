"""Import agent runner — provider-agnostic tool-use loop for KB import pipeline.

ImportAgentRunner orchestrates the full holmes import pipeline:
  1. Compute source_hash and check for exact duplicate (idempotency).
  2. Run LLM tool-use agent loop to classify, verify, and write entry.
  3. After write, evaluate skill generation and run incremental curation.
  4. Commit to git as pipeline-level rollback.

All file writes delegate to tool functions in agent/tools.py which use
atomic_write() from kb/atomic.py.

The LLM connection is created by create_provider(cfg) and abstracted behind
LLMProvider so that both Anthropic SDK and OpenAI-compatible SDK are supported.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

import click

from holmes.config import HolmesConfig
from holmes.kb.agent.provider import create_provider
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import CuratorFinding, DecisionTrace, ImportReport
from holmes.kb.agent.tools import TOOL_DEFINITIONS, TOOL_HANDLERS
from holmes.kb.importer import compute_source_hash

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_GATE_THRESHOLD = 0.7
MAX_TOOL_ITERATIONS = 20

_IMPORT_SYSTEM_PROMPT = """\
You are an autonomous KB import agent for a technical knowledge base.

Your task: Analyze the provided source text and import it as one or more
structured KB entries. For each knowledge point:

1. Determine the KB type (pitfall/model/guideline/process/decision) and
   category (for pitfall: network/system/application/database/kubernetes/messaging/cache/monitoring).
2. Use check_source_hash to detect exact duplicates (skip if found).
3. Use verify_content to self-verify the draft against the source before writing.
4. Use write_kb_entry (new entry) to persist. Always create a new entry — never
   merge with or update existing entries.
5. Use evaluate_skill to assess skill generation value.
6. Use create_skill_for_entry if skill is recommended.
7. Use report_item to log suggestions, warnings, and decisions.

IMPORTANT RULES:
- Only include field content that has direct source text support.
  If a field lacks source support, leave it empty in the frontmatter/body.
- For pitfall entries, always include: ## Symptoms, ## Root Cause, ## Resolution
- All commands in ## Resolution must appear verbatim in the source text.
- Emit report_item(type="warning") for every field cleared by verify_content.
- When confidence < {threshold}, emit report_item(type="auto_decision") if
  no_interactive=true; otherwise the caller will prompt the user.
- The source_hash is provided in the system context — use it in write_kb_entry.
- Write ALL field content (title, root_cause, resolution steps, etc.) in the same
  language as the source document. Do not translate or switch languages.
""".replace("{threshold}", str(CONFIDENCE_GATE_THRESHOLD))


# ---------------------------------------------------------------------------
# ImportAgentRunner
# ---------------------------------------------------------------------------


class ImportAgentRunner:
    """Orchestrates the full import pipeline via a provider-agnostic tool-use loop.

    Attributes:
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
        force_type: Optional[str] = None,
        force: bool = False,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.no_interactive = no_interactive
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_type = force_type
        # T009 (020): force bypasses document-level dedup pre-check in pipeline.
        self.force = force
        self._provider: LLMProvider = create_provider(cfg)
        # Set by run() so gate methods can log auto-decisions to the active report.
        self._current_report: Optional[ImportReport] = None
        # Accumulated per-entry trace for --verbose output (N-2).
        self._pending_trace: Optional[DecisionTrace] = None
        # C-2: Track created entry content keyed by pending_id for skill fallback.
        self._created_entry_contents: dict[str, str] = {}
        # US3 (023): Track entry_ids updated via update_kb_entry for skill evaluation.
        self._updated_entry_ids: set[str] = set()
        # E-12: Track entry_ids for which skill creation was already attempted
        # (either confirmed or declined) so _finalize_skill_generation skips them.
        self._skill_evaluated_entries: set[str] = set()
        # Lazily initialised — use self.skill_executor property.
        self._skill_executor: Optional["SkillExecutor"] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport:
        """Run the import agent pipeline for a single source text.

        Delegates to ThreePhaseImportPipeline (three-phase architecture).
        Signature is preserved for backward compatibility.

        Args:
            source_text: Raw text to import.
            file_path: Optional source file path (for logging).

        Returns:
            ImportReport summarising all actions taken.
        """
        from holmes.kb.agent.pipeline import ThreePhaseImportPipeline

        pipeline = ThreePhaseImportPipeline(
            kb_root=self.kb_root,
            cfg=self.cfg,
            no_interactive=self.no_interactive,
            verbose=self.verbose,
            dry_run=self.dry_run,
            _provider=self._provider,  # reuse runner's already-created provider
            force_type=self.force_type,
            force=self.force,
        )
        return pipeline.run(source_text, file_path)

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    def _dispatch_tool(
        self,
        name: str,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a tool call by name and return the result dict.

        N-1: Classification and dedup gates are wired here, before the handler
        executes, so the user can intervene at the two most critical decision points.
        """
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}

        # Gate: classification confidence before write_kb_entry.
        if name == "write_kb_entry" and not self.dry_run:
            confidence = float(tool_input.get("confidence", 1.0))
            kb_type = self._extract_type_from_content(tool_input.get("content", ""))
            confirmed_type = self._gate_classification(kb_type, confidence)
            if confirmed_type and confirmed_type != kb_type:
                tool_input = dict(tool_input)
                tool_input["content"] = self._patch_content_type(
                    tool_input.get("content", ""), confirmed_type
                )

        # Gate: dedup decision before update_kb_entry.
        if name == "update_kb_entry" and not self.dry_run:
            entry_id = tool_input.get("entry_id", "unknown")
            if self.no_interactive:
                # C-4: Record auto-merge decision in audit log.
                if self._current_report:
                    self._current_report.auto_decisions.append(
                        f"Merged into {entry_id}: auto-merged without user confirmation"
                    )
            else:
                decision = self._gate_dedup(entry_id, entry_id)
                if decision == "new":
                    return {
                        "success": False,
                        "action": "skipped: user chose to create new entry instead",
                        "user_choice": "new",
                    }

        # E-12 fix (018): interactive gate for LLM-called create_skill_for_entry.
        # Mark entry as evaluated BEFORE the gate so _finalize_skill_generation
        # won't re-evaluate regardless of whether the user confirms or declines.
        if name == "create_skill_for_entry":
            _eval_entry_id = tool_input.get("entry_id", "")
            if _eval_entry_id:
                self._skill_evaluated_entries.add(_eval_entry_id)

        if name == "create_skill_for_entry" and not self.no_interactive:
            skill_name = tool_input.get("name", "")
            confirmed = self._gate_skill_create(skill_name)
            if not confirmed:
                return {"created": False, "linked": False, "action": "skipped (user declined)", "skill_dir": None}

        # Upgrade skill instructions via skill-creator before the actual tool call.
        # The LLM passes its own draft instructions; we replace them with skill-creator output.
        if name == "create_skill_for_entry" and not tool_input.get("link_only"):
            tool_input = self._enrich_skill_tool_input(tool_input, ctx)

        try:
            result = handler(ctx, tool_input)
        except Exception as exc:  # noqa: BLE001
            result = {"error": str(exc)}
        self._maybe_post_process(name, tool_input, result, ctx)
        return result

    def _maybe_post_process(
        self,
        name: str,
        tool_input: dict[str, Any],
        result: dict[str, Any],
        ctx: dict[str, Any],
    ) -> None:
        """Hook post-processing: update report lists from tool results.

        Also handles US2 verifier integration and N-2 verbose trace population.
        """
        import frontmatter as fm

        report: ImportReport = ctx["report"]

        # ------------------------------------------------------------------
        # N-2: Build per-entry DecisionTrace for --verbose output.
        # verify_content → accumulate; write_kb_entry → finalise; evaluate_skill → annotate.
        # ------------------------------------------------------------------
        if self.verbose:
            if name == "verify_content":
                if self._pending_trace is None:
                    self._pending_trace = DecisionTrace(title="(pending)")
                conf = float(result.get("confidence", 1.0))
                self._pending_trace.confidence = conf
                for item in result.get("unsupported_fields", []):
                    field = item.get("field", "unknown") if isinstance(item, dict) else str(item)
                    # D-7: last-write-wins — remove from field_sources if now CLEARED
                    self._pending_trace.field_sources.pop(field, None)
                    if field not in self._pending_trace.unsupported_fields:
                        self._pending_trace.unsupported_fields.append(field)
                for field in result.get("verified_fields", []):
                    # D-7: last-write-wins — remove from unsupported_fields if now verified
                    if field in self._pending_trace.unsupported_fields:
                        self._pending_trace.unsupported_fields.remove(field)
                    self._pending_trace.field_sources[field] = "(verified)"

            elif name == "write_kb_entry" and result.get("pending_id") and not self.dry_run:
                if self._pending_trace is None:
                    self._pending_trace = DecisionTrace(title="(unknown)")
                title = tool_input.get("title", result.get("pending_id", "unknown"))
                self._pending_trace.title = str(title)
                confidence = float(tool_input.get("confidence", 0.0))
                if confidence > 0:
                    self._pending_trace.confidence = confidence
                content = tool_input.get("content", "")
                try:
                    post = fm.loads(content)
                    for field in ("type", "category"):
                        val = post.metadata.get(field, "")
                        if val and field not in self._pending_trace.field_sources:
                            self._pending_trace.field_sources[field] = str(val)
                except Exception:  # noqa: BLE001
                    pass
                report.add_trace(self._pending_trace)
                self._pending_trace = None

            elif name == "update_kb_entry" and result.get("success") and not self.dry_run:
                # C-1b: Add trace for update/merge path.
                trace = self._pending_trace or DecisionTrace(
                    title=f"update:{tool_input.get('entry_id', '?')}"
                )
                trace.title = f"update:{tool_input.get('entry_id', '?')}"
                patch = tool_input.get("patch", {})
                for field, val in patch.items():
                    if isinstance(val, str) and val:
                        trace.field_sources[field] = val[:80]
                report.add_trace(trace)
                self._pending_trace = None

            elif name == "evaluate_skill" and self._pending_trace is not None:
                rec = result.get("recommendation", "SKIP")
                skill_name = result.get("skill_name", "")
                self._pending_trace.skill_decision = (
                    f"{rec}: {skill_name}" if skill_name else rec
                )

        # ------------------------------------------------------------------
        # Standard report list updates
        # ------------------------------------------------------------------
        if name == "write_kb_entry":
            if not self.dry_run and result.get("pending_id"):
                if result.get("duplicate"):
                    # D-5: duplicate skip — count as skipped, do NOT add to created or
                    # _created_entry_contents (entry already exists; content may be empty).
                    report.skipped.append(str(result["pending_id"]))
                else:
                    title = tool_input.get("title", result.get("pending_id", "unknown"))
                    report.created.append(str(title))
                    # C-2: Remember content for deterministic skill-generation fallback.
                    pending_id = str(result["pending_id"])
                    self._created_entry_contents[pending_id] = tool_input.get("content", "")
            elif self.dry_run:
                title = tool_input.get("title", "(unknown)")
                suggestion = f"Would create: {title}"
                # W6-F1: Guard against duplicate dry-run suggestions (LLM may call tool twice).
                if suggestion not in report.suggestions:
                    report.suggestions.append(suggestion)
        elif name == "update_kb_entry" and result.get("success") and not self.dry_run:
            entry_id = str(tool_input.get("entry_id", "unknown"))
            report.updated.append(entry_id)
            self._updated_entry_ids.add(entry_id)  # US3 (023): track for skill evaluation
        elif name == "check_source_hash" and result.get("match"):
            report.skipped.append(str(result.get("entry_id", tool_input.get("hash", ""))))
        elif name == "create_skill_for_entry":
            skill_name = tool_input.get("name", "")
            if result.get("created") and not self.dry_run:
                report.skills_generated.append(skill_name)
            elif result.get("linked") and not result.get("created") and not self.dry_run:
                report.skills_linked.append(skill_name)
            elif self.dry_run:
                report.suggestions.append(f"Would create skill: {skill_name}")
        elif name == "verify_content":
            # US2: log warnings for unsupported fields so they appear in report.
            for item in result.get("unsupported_fields", []):
                field_name = item.get("field", "unknown") if isinstance(item, dict) else str(item)
                reason = item.get("reason", "no source support") if isinstance(item, dict) else "no source support"
                report.warnings.append(f"{field_name}: cleared ({reason})")
            # Low-confidence draft gets maturity=draft (handled by agent in system prompt).

    # ------------------------------------------------------------------
    # Skill execution — delegate to SkillExecutor
    # ------------------------------------------------------------------

    @property
    def skill_executor(self) -> "SkillExecutor":
        """Lazily-initialised SkillExecutor bound to this runner's provider."""
        if self._skill_executor is None:
            from holmes.kb.skill.executor import SkillExecutor
            extra_roots: list[Path] = []
            meta_root = getattr(self.cfg, "meta_skills_root", "") or ""
            if meta_root:
                extra_roots.append(Path(meta_root))
            self._skill_executor = SkillExecutor(
                provider=self._provider,
                kb_root=self.kb_root,
                extra_roots=extra_roots,
            )
        return self._skill_executor

    def _enrich_skill_tool_input(
        self,
        tool_input: dict[str, Any],
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace LLM-drafted skill instructions with skill-creator output.

        Called by _dispatch_tool when the LLM issues a create_skill_for_entry
        tool call. Recovers entry context (title, symptoms, root_cause,
        resolution) from the pending entry, then invokes skill-creator to
        produce high-quality agent instructions.

        Returns a shallow copy of tool_input with enriched description and
        instructions fields if skill-creator succeeds; the original tool_input
        is returned unchanged on any error.
        """
        entry_id = tool_input.get("entry_id", "")
        # Try to read entry content from memory cache or filesystem.
        content = self._created_entry_contents.get(entry_id, "")
        if not content:
            content = self._read_entry_content(entry_id)
        if not content:
            return tool_input  # can't enrich without entry content

        try:
            import frontmatter as _fm
            post = _fm.loads(content)
            title = str(post.metadata.get("title", "")) or tool_input.get("name", "")
        except Exception:  # noqa: BLE001
            title = tool_input.get("name", "")

        resolution_text = self._extract_resolution_section(content)
        if not resolution_text:
            return tool_input

        symptoms_text = self._extract_section(content, ("## Symptoms", "## 症状", "## 现象", "## 故障现象"))
        root_cause_text = self._extract_section(content, ("## Root Cause", "## 根因", "## 原因分析", "## 根本原因"))

        gen_description, gen_instructions = self.skill_executor.create_from_kb_entry(
            title=title,
            resolution_text=resolution_text,
            symptoms_text=symptoms_text,
            root_cause_text=root_cause_text,
        )

        if not gen_instructions:
            return tool_input

        enriched = dict(tool_input)
        enriched["instructions"] = gen_instructions
        if gen_description:
            enriched["description"] = gen_description
        return enriched

    def _generate_skill_instructions(
        self,
        title: str,
        resolution_text: str,
        symptoms_text: str = "",
        root_cause_text: str = "",
    ) -> tuple[str, str]:
        """Generate SKILL.md (description, body) by delegating to SkillExecutor.

        SkillExecutor executes the skill-creator skill to produce agent-quality
        SKILL.md content. Falls back to resolution_text if skill-creator is
        unavailable.
        """
        return self.skill_executor.create_from_kb_entry(
            title=title,
            resolution_text=resolution_text,
            symptoms_text=symptoms_text,
            root_cause_text=root_cause_text,
        )

    def _run_skill_and_curation(
        self,
        entry_id: str,
        resolution_text: str,
        category: Optional[str],
        report: ImportReport,
        description: Optional[str] = None,
        symptoms_text: str = "",
        root_cause_text: str = "",
    ) -> None:
        """Evaluate skill generation and run incremental curation (US5).

        Called by the agent loop after a successful write_kb_entry.  This
        mirrors what the agent would do via tools, but as a direct library
        call for tighter control over gating and report population.

        Args:
            entry_id: KB entry ID just written (may be a pending_id).
            resolution_text: The ## Resolution section body.
            category: Entry category for curation scope.
            report: ImportReport to update in-place.
            description: Entry title for SkillAdvisor._find_similar_skill.
            symptoms_text: ## Symptoms section (passed to skill generation).
            root_cause_text: ## Root Cause section (passed to skill generation).
        """
        from holmes.kb.agent.curator import SkillCurator
        from holmes.kb.agent.skill_advisor import Recommendation, SkillAdvisor
        from holmes.kb.skill.usage import mark_agent_created

        advisor = SkillAdvisor()
        advice = advisor.advise(entry_id, resolution_text, self.kb_root, description=description)

        if advice.recommendation == Recommendation.RECOMMENDED:
            confirmed = self._gate_skill_create(advice.suggested_name)
            if confirmed and not self.dry_run:
                from holmes.kb.agent.tools import create_skill_for_entry
                # Delegate to SkillExecutor which runs skill-creator.
                gen_description, gen_instructions = self.skill_executor.create_from_kb_entry(
                    title=description or advice.suggested_name,
                    resolution_text=resolution_text,
                    symptoms_text=symptoms_text,
                    root_cause_text=root_cause_text,
                )
                ctx: dict = {
                    "kb_root": self.kb_root,
                    "dry_run": False,
                    "report": report,
                }
                result = create_skill_for_entry(ctx, {
                    "name": advice.suggested_name,
                    "entry_id": entry_id,
                    "description": gen_description,
                    "instructions": gen_instructions,
                })
                if result.get("created"):
                    report.skills_generated.append(advice.suggested_name)
                elif result.get("linked"):
                    report.skills_linked.append(advice.suggested_name)
            elif self.dry_run:
                report.suggestions.append(
                    f"Would create skill: {advice.suggested_name} ({advice.reason})"
                )
        elif advice.recommendation == Recommendation.LINK and not self.dry_run:
            from holmes.kb.agent.tools import create_skill_for_entry
            ctx = {"kb_root": self.kb_root, "dry_run": False, "report": report}
            result = create_skill_for_entry(ctx, {
                "name": advice.existing_skill or advice.suggested_name,
                "entry_id": entry_id,
                "link_only": True,
            })
            if result.get("linked"):
                report.skills_linked.append(advice.existing_skill or advice.suggested_name)

        # Incremental curation pass.
        curator = SkillCurator()
        findings = curator.curate(self.kb_root, category=category)
        for finding in findings:
            report.suggestions.append(str(finding))

    # ------------------------------------------------------------------
    # C-2: Deterministic skill-generation fallback
    # ------------------------------------------------------------------

    def _read_entry_content(self, entry_id: str) -> str:
        """Read the full content of a KB entry by ID from the filesystem.

        Returns:
            Full Markdown content string, or "" if the entry is not found.
        """
        from holmes.kb.store import list_entries
        for entry in list_entries(self.kb_root):
            if entry.id.upper() == entry_id.upper():
                try:
                    return Path(entry.file_path).read_text(encoding="utf-8")
                except OSError:
                    return ""
        return ""

    def _extract_resolution_section(self, content: str) -> str:
        """Extract the actionable steps section from entry content.

        Looks for ## Resolution / ## Steps (English) or common Chinese equivalents.
        """
        headers = (
            "## Resolution",
            "## Steps",
            # C-2a: Chinese resolution/steps headers
            "## 解决方案",
            "## 解决步骤",
            "## 解决",
            "## 恢复步骤",
            "## 恢复",
            "## 诊断步骤",
            "## 操作步骤",
            "## 修复步骤",
            "## 修复",
            "## 处理步骤",
            "## 处理方案",
        )
        for header in headers:
            m = re.search(
                rf"{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL
            )
            if m:
                return m.group(1).strip()
        return ""

    def _extract_section(self, content: str, headers: tuple[str, ...]) -> str:
        """Generic section extractor for arbitrary header aliases."""
        for header in headers:
            m = re.search(
                rf"{re.escape(header)}\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL
            )
            if m:
                return m.group(1).strip()
        return ""

    def _finalize_skill_generation(self, report: ImportReport) -> None:
        """Deterministic skill-generation fallback after the tool-use loop.

        Called after every run(). If the LLM did not call evaluate_skill /
        create_skill_for_entry (e.g., gpt-4o exits after write_kb_entry),
        this method evaluates and creates skills for all newly created entries,
        and also evaluates skill generation for updated entries.

        Skipped if:
        - No entries were created or updated.
        - Skill evaluation was already signalled by suggestions.
        """
        # E-1 fix (018): removed early-return on existing skills_generated/linked.
        # Per-entry duplicate detection is handled by SkillAdvisor._find_existing_skill().

        _SYMPTOMS_HEADERS = ("## Symptoms", "## 症状", "## 现象", "## 故障现象")
        _ROOT_CAUSE_HEADERS = ("## Root Cause", "## 根因", "## 原因分析", "## 根本原因")

        for pending_id, content in self._created_entry_contents.items():
            # E-12 fix: skip entries where the LLM already called create_skill_for_entry
            # (whether the user confirmed or declined) to avoid double-prompting or
            # bypassing user's explicit rejection.
            if pending_id in self._skill_evaluated_entries:
                continue
            resolution_text = self._extract_resolution_section(content)
            if not resolution_text:
                continue
            try:
                import frontmatter as _fm
                post = _fm.loads(content)
                category: Optional[str] = str(post.metadata.get("category", "")) or None
                # E-11 fix: pass entry title as description for _find_similar_skill check.
                title: Optional[str] = str(post.metadata.get("title", "")) or None
            except Exception:  # noqa: BLE001
                category = None
                title = None
            symptoms_text = self._extract_section(content, _SYMPTOMS_HEADERS)
            root_cause_text = self._extract_section(content, _ROOT_CAUSE_HEADERS)
            self._run_skill_and_curation(
                pending_id, resolution_text, category, report,
                description=title,
                symptoms_text=symptoms_text,
                root_cause_text=root_cause_text,
            )

        # US3 (023): Also evaluate skill for updated entries.
        for entry_id in self._updated_entry_ids:
            if entry_id in self._skill_evaluated_entries:
                continue
            content = self._read_entry_content(entry_id)
            if not content:
                continue
            resolution_text = self._extract_resolution_section(content)
            if not resolution_text:
                continue
            try:
                import frontmatter as _fm
                post = _fm.loads(content)
                category = str(post.metadata.get("category", "")) or None
                title = str(post.metadata.get("title", "")) or None
            except Exception:  # noqa: BLE001
                category = None
                title = None
            self._run_skill_and_curation(entry_id, resolution_text, category, report, description=title)

    # ------------------------------------------------------------------
    # Confirmation gates (US4)
    # ------------------------------------------------------------------

    def _gate_classification(self, kb_type: str, confidence: float) -> str:
        """Return the confirmed type. Prompts user if confidence < threshold."""
        if confidence >= CONFIDENCE_GATE_THRESHOLD or self.no_interactive:
            if self.no_interactive and confidence < CONFIDENCE_GATE_THRESHOLD:
                if self._current_report:
                    self._current_report.auto_decisions.append(
                        f"classification: used LLM best guess "
                        f"(confidence {confidence:.2f}, threshold {CONFIDENCE_GATE_THRESHOLD})"
                    )
            return kb_type

        answer = click.prompt(
            f"I think this is {kb_type} (confidence {confidence:.0%}). "
            "Correct? [Y/n/other type]",
            default="y",
        )
        if answer.lower() in ("y", "yes", ""):
            return kb_type
        return answer.strip() or kb_type

    # ------------------------------------------------------------------
    # Helpers for gate N-1
    # ------------------------------------------------------------------

    def _extract_type_from_content(self, content: str) -> str:
        """Extract the KB entry type from frontmatter content string."""
        try:
            import frontmatter as fm
            post = fm.loads(content)
            return str(post.metadata.get("type", ""))
        except Exception:  # noqa: BLE001
            return ""

    def _patch_content_type(self, content: str, new_type: str) -> str:
        """Replace the 'type' field in frontmatter content."""
        try:
            import frontmatter as fm
            post = fm.loads(content)
            post.metadata["type"] = new_type
            return fm.dumps(post)
        except Exception:  # noqa: BLE001
            return content

    def _gate_dedup(self, existing_id: str, title: str) -> str:
        """Return 'update' or 'new'. Prompts user if interactive."""
        if self.no_interactive:
            return "new"
        answer = click.prompt(
            f"Similar entry found: {existing_id} \"{title}\". "
            "Update it or create new? [u=update/n=new]",
            default="n",
        )
        return "update" if answer.lower().startswith("u") else "new"

    def _gate_skill_create(self, name: str) -> bool:
        """Return True if skill should be created. Prompts user if interactive."""
        if self.no_interactive:
            return True  # C-2: auto-confirm RECOMMENDED skills in no-interactive mode
        answer = click.prompt(
            f"Recommend creating skill: {name}. Confirm? [Y/n]",
            default="y",
        )
        return answer.lower() in ("y", "yes", "")

    # ------------------------------------------------------------------
    # Git commit
    # ------------------------------------------------------------------

    def _git_commit(self, message: str) -> bool:
        """Stage all changes in kb_root and commit. Non-fatal on failure."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=self.kb_root,
                capture_output=True,
                check=False,
            )
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.kb_root,
                capture_output=True,
                check=False,
            )
            return result.returncode == 0
        except Exception:  # noqa: BLE001
            return False
