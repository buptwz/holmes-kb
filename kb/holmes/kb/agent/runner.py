"""Import agent runner — backward-compatible entry point for KB import pipeline.

ImportAgentRunner delegates to ImportPipeline (042 three-phase architecture).
Kept for backward compatibility with CLI and tests that instantiate the runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from holmes.config import HolmesConfig
from holmes.kb.agent.provider import create_provider
from holmes.kb.agent.provider.base import LLMProvider
from holmes.kb.agent.report import ImportReport


class ImportAgentRunner:
    """Backward-compatible wrapper that delegates to ImportPipeline.

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
        use_dag: bool = False,
        reporter: Optional[Any] = None,
    ) -> None:
        self.kb_root = kb_root
        self.cfg = cfg
        self.no_interactive = no_interactive
        self.verbose = verbose
        self.dry_run = dry_run
        self.force_type = force_type
        self.force = force
        self.use_dag = use_dag
        self._reporter = reporter
        self._provider: Optional[LLMProvider] = None

    def run(self, source_text: str, file_path: Optional[Path] = None) -> ImportReport:
        """Run the import pipeline for a single source text.

        Delegates to ImportPipeline (042 three-phase architecture).

        Args:
            source_text: Raw text to import.
            file_path: Optional source file path (for logging).

        Returns:
            ImportReport summarising all actions taken.
        """
        from holmes.kb.agent.pipeline import ImportPipeline

        if self._provider is None:
            self._provider = create_provider(self.cfg)

        pipeline = ImportPipeline(
            kb_root=self.kb_root,
            cfg=self.cfg,
            no_interactive=self.no_interactive,
            verbose=self.verbose,
            dry_run=self.dry_run,
            _provider=self._provider,
            force_type=self.force_type,
            force=self.force,
            use_dag=self.use_dag,
            reporter=self._reporter,
        )
        return pipeline.run(source_text, file_path)
