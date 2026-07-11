"""Pipeline regression evaluation — 3-layer quantitative quality metrics.

Run:
    # Layer 1 only (import quality, ~7 min)
    HOLMES_LLM_TESTS=1 pytest tests/test_eval_regression.py -v -s -k "import"

    # Layer 1 + 2 (import + retrieval, ~8 min)
    HOLMES_LLM_TESTS=1 pytest tests/test_eval_regression.py -v -s -k "not consistency"

    # All layers including consistency (~25 min)
    HOLMES_LLM_TESTS=1 EVAL_CONSISTENCY_RUNS=3 pytest tests/test_eval_regression.py -v -s

    # Full report (always passes, prints summary table)
    HOLMES_LLM_TESTS=1 pytest tests/test_eval_regression.py -v -s -k "full_report"

Layer 1 — Import Quality (per-document):
    Scores how well the pipeline extracts content from source documents.
    8 dimensions: type, category, commands, numbers, branches, tags, sections, brief.

Layer 2 — Retrieval Quality (per-query):
    Scores whether an agent can find the right entry given a problem description.
    Simulates kb_browse keyword matching.

Layer 3 — Consistency (multi-run):
    Scores how stable pipeline output is across repeated runs.
    Reports mean and std_dev for each metric.

Ground truth is defined in: tests/fixtures/eval/ground_truth.yaml
New documents: add source file + ground truth entry → done.
"""

from __future__ import annotations

import math
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter
import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent
_FIXTURES_DIR = _TESTS_DIR / "fixtures"
_EVAL_DIR = _FIXTURES_DIR / "eval"
_GT_PATH = _EVAL_DIR / "ground_truth.yaml"

# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------


@dataclass
class DocGroundTruth:
    """Expected outputs for a single test document."""

    source: str  # relative to fixtures/
    type: str
    category: str
    language: str
    commands: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    behavior_tags: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    key_terms: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return Path(self.source).name


@dataclass
class QueryGroundTruth:
    """Expected retrieval result for a problem description."""

    question: str
    match_type: str
    match_keywords: list[str] = field(default_factory=list)


def _load_ground_truth() -> tuple[list[DocGroundTruth], list[QueryGroundTruth]]:
    """Load ground truth from YAML file."""
    if not _GT_PATH.exists():
        pytest.skip(f"Ground truth not found: {_GT_PATH}")

    raw = yaml.safe_load(_GT_PATH.read_text(encoding="utf-8"))

    docs = []
    for d in raw.get("documents", []):
        docs.append(DocGroundTruth(
            source=d["source"],
            type=d["type"],
            category=d.get("category", ""),
            language=d.get("language", "en"),
            commands=d.get("commands", []),
            numbers=[str(n) for n in d.get("numbers", [])],
            branches=d.get("branches", []),
            behavior_tags=d.get("behavior_tags", []),
            sections=d.get("sections", []),
            key_terms=d.get("key_terms", []),
        ))

    queries = []
    for q in raw.get("queries", []):
        queries.append(QueryGroundTruth(
            question=q["question"],
            match_type=q["match_type"],
            match_keywords=q.get("match_keywords", []),
        ))

    return docs, queries


# ---------------------------------------------------------------------------
# Layer 1: Import Quality — Evaluation
# ---------------------------------------------------------------------------


@dataclass
class ImportEvalResult:
    """Evaluation result for a single document import."""

    source: str
    type_correct: float = 0.0
    category_correct: float = 0.0
    command_recall: float = 0.0
    number_recall: float = 0.0
    branch_recall: float = 0.0
    tag_coverage: float = 0.0
    section_complete: float = 0.0
    brief_quality: float = 0.0
    term_recall: float = 0.0
    # Debug details
    missing_commands: list[str] = field(default_factory=list)
    missing_numbers: list[str] = field(default_factory=list)
    missing_branches: list[str] = field(default_factory=list)
    missing_tags: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)
    missing_terms: list[str] = field(default_factory=list)
    actual_type: str = ""

    # Dimension weights for aggregate score
    _WEIGHTS = {
        "type_correct": 15,
        "command_recall": 25,
        "number_recall": 10,
        "branch_recall": 15,
        "tag_coverage": 10,
        "section_complete": 10,
        "brief_quality": 5,
        "category_correct": 5,
        "term_recall": 5,
    }

    @property
    def aggregate(self) -> float:
        """Weighted aggregate score (0-100)."""
        total_w = sum(self._WEIGHTS.values())
        score = sum(getattr(self, k) * w for k, w in self._WEIGHTS.items())
        return round(score / total_w * 100, 1)

    @property
    def metrics_dict(self) -> dict[str, float]:
        """All metric values as a dict."""
        return {k: getattr(self, k) for k in self._WEIGHTS}


def evaluate_import(gt: DocGroundTruth, draft: str) -> ImportEvalResult:
    """Score a generated draft against ground truth."""
    result = ImportEvalResult(source=gt.source)

    # Parse frontmatter
    try:
        post = frontmatter.loads(draft)
        meta = post.metadata or {}
        body = post.content or ""
    except Exception:
        meta = {}
        body = draft

    body_lower = body.lower()
    all_text = draft  # includes frontmatter for number matching

    # 1. Type
    result.actual_type = meta.get("type", "")
    result.type_correct = 1.0 if result.actual_type == gt.type else 0.0

    # 2. Category
    actual_cat = str(meta.get("category", "")).lower()
    result.category_correct = 1.0 if gt.category.lower() in actual_cat else 0.0

    # 3. Command recall
    if gt.commands:
        found = 0
        for cmd in gt.commands:
            if cmd.lower() in body_lower:
                found += 1
            else:
                result.missing_commands.append(cmd)
        result.command_recall = found / len(gt.commands)
    else:
        result.command_recall = 1.0

    # 4. Number recall
    if gt.numbers:
        draft_numbers = set(re.findall(r"(?<!\w)(\d+\.?\d*)(?!\w)", all_text))
        found = 0
        for num in gt.numbers:
            if num in draft_numbers:
                found += 1
            else:
                result.missing_numbers.append(num)
        result.number_recall = found / len(gt.numbers)
    else:
        result.number_recall = 1.0

    # 5. Branch recall
    if gt.branches:
        found = 0
        for kw in gt.branches:
            if kw.lower() in body_lower:
                found += 1
            else:
                result.missing_branches.append(kw)
        result.branch_recall = found / len(gt.branches)
    else:
        result.branch_recall = 1.0

    # 6. Behavior tag coverage
    if gt.behavior_tags:
        found = 0
        for tag in gt.behavior_tags:
            if tag in body:
                found += 1
            else:
                result.missing_tags.append(tag)
        result.tag_coverage = found / len(gt.behavior_tags)
    else:
        result.tag_coverage = 1.0

    # 7. Section completeness
    if gt.sections:
        headings = [
            line.strip().lstrip("#").strip().lower()
            for line in body.splitlines()
            if line.strip().startswith("## ")
        ]
        found = 0
        for section in gt.sections:
            if any(section.lower() in h for h in headings):
                found += 1
            else:
                result.missing_sections.append(section)
        result.section_complete = found / len(gt.sections)
    else:
        result.section_complete = 1.0

    # 8. Brief quality
    brief = meta.get("brief", "")
    if brief and 10 <= len(brief) <= 150:
        result.brief_quality = 1.0
    elif brief and len(brief) > 150:
        result.brief_quality = 0.5
    else:
        result.brief_quality = 0.0

    # 9. Key term recall
    if gt.key_terms:
        found = 0
        for term in gt.key_terms:
            if term.lower() in body_lower or term.lower() in str(meta).lower():
                found += 1
            else:
                result.missing_terms.append(term)
        result.term_recall = found / len(gt.key_terms)
    else:
        result.term_recall = 1.0

    return result


# ---------------------------------------------------------------------------
# Layer 2: Retrieval Quality — Evaluation
# ---------------------------------------------------------------------------


@dataclass
class RetrievalEvalResult:
    """Evaluation result for a single retrieval query."""

    question: str
    found: bool = False           # matched entry exists
    type_match: bool = False      # matched entry has expected type
    keyword_recall: float = 0.0   # fraction of keywords found in title+brief
    rank: int = -1                # position in browse results (1-based, -1 = not found)
    matched_title: str = ""
    missing_keywords: list[str] = field(default_factory=list)


def evaluate_retrieval(
    query: QueryGroundTruth,
    entries: list[dict[str, Any]],
) -> RetrievalEvalResult:
    """Score a retrieval query against browse results.

    Args:
        query: The ground truth query.
        entries: List of browse result dicts with id, type, title, brief.
    """
    result = RetrievalEvalResult(question=query.question)

    # Find best matching entry: type match + most keyword overlap
    best_rank = -1
    best_kw_score = 0.0
    best_title = ""
    best_type_match = False

    for i, entry in enumerate(entries):
        title = entry.get("title", "").lower()
        brief = entry.get("brief", "").lower()
        entry_type = entry.get("type", "")
        searchable = f"{title} {brief}"

        type_ok = entry_type == query.match_type

        # Count keyword hits
        if query.match_keywords:
            hits = sum(1 for kw in query.match_keywords if kw.lower() in searchable)
            kw_score = hits / len(query.match_keywords)
        else:
            kw_score = 1.0 if type_ok else 0.0

        # Best = type match + highest keyword score
        score = (1 if type_ok else 0) * 100 + kw_score * 10
        if score > best_kw_score or best_rank == -1:
            if kw_score > 0 or type_ok:
                best_kw_score = score
                best_rank = i + 1
                best_title = entry.get("title", "")
                best_type_match = type_ok

    if best_rank > 0:
        result.found = True
        result.rank = best_rank
        result.matched_title = best_title
        result.type_match = best_type_match

        # Recompute keyword recall for the best match
        entry = entries[best_rank - 1]
        searchable = f"{entry.get('title', '')} {entry.get('brief', '')}".lower()
        if query.match_keywords:
            found = 0
            for kw in query.match_keywords:
                if kw.lower() in searchable:
                    found += 1
                else:
                    result.missing_keywords.append(kw)
            result.keyword_recall = found / len(query.match_keywords)
        else:
            result.keyword_recall = 1.0

    return result


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def run_pipeline_for_eval(
    source_path: Path,
    kb_root: Path,
    holmes_config: Any,
    provider: Any,
) -> str:
    """Run import pipeline and return the generated draft content."""
    from holmes.kb.agent.pipeline import ImportPipeline

    source_text = source_path.read_text(encoding="utf-8")
    pipeline = ImportPipeline(
        kb_root=kb_root,
        cfg=holmes_config,
        no_interactive=True,
        dry_run=False,
        force=True,
        _provider=provider,
    )
    report = pipeline.run(source_text, file_path=source_path)

    if report.errors:
        pytest.fail(f"Pipeline errors for {source_path.name}: {report.errors}")

    pending_dir = kb_root / "contributions" / "pending"
    if not pending_dir.exists():
        pytest.fail(f"No pending directory for {source_path.name}")

    entries = sorted(pending_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not entries:
        pytest.fail(f"No entry created for {source_path.name}")

    return entries[-1].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_import_report(results: list[ImportEvalResult]) -> str:
    """Format Layer 1 results as a markdown table."""
    lines = [
        "",
        "=" * 80,
        "  LAYER 1: Import Quality",
        "=" * 80,
        "",
        "| Document | Type | Cat | Cmd | Num | Branch | Tags | Sect | Brief | Term | **Score** |",
        "|----------|------|-----|-----|-----|--------|------|------|-------|------|-----------|",
    ]
    for r in results:
        lines.append(
            f"| {r.source:35s} "
            f"| {_pct(r.type_correct)} "
            f"| {_pct(r.category_correct)} "
            f"| {_pct(r.command_recall)} "
            f"| {_pct(r.number_recall)} "
            f"| {_pct(r.branch_recall)} "
            f"| {_pct(r.tag_coverage)} "
            f"| {_pct(r.section_complete)} "
            f"| {_pct(r.brief_quality)} "
            f"| {_pct(r.term_recall)} "
            f"| **{r.aggregate}** |"
        )

    if results:
        n = len(results)
        avg_score = sum(r.aggregate for r in results) / n
        lines.append(
            f"| {'**AVERAGE**':35s} "
            + "| " * 9
            + f"     | **{avg_score:.1f}** |"
        )

    # Missing details
    for r in results:
        missing = []
        if r.missing_commands:
            missing.append(f"Commands: {', '.join(r.missing_commands)}")
        if r.missing_numbers:
            missing.append(f"Numbers: {', '.join(r.missing_numbers)}")
        if r.missing_branches:
            missing.append(f"Branches: {', '.join(r.missing_branches)}")
        if r.missing_tags:
            missing.append(f"Tags: {', '.join(r.missing_tags)}")
        if r.missing_sections:
            missing.append(f"Sections: {', '.join(r.missing_sections)}")
        if r.missing_terms:
            missing.append(f"Terms: {', '.join(r.missing_terms)}")
        if r.actual_type != r.source:  # always show actual type for context
            pass
        if missing:
            lines.append(f"\n  {r.source} (actual_type={r.actual_type}):")
            for m in missing:
                lines.append(f"    - {m}")

    return "\n".join(lines)


def format_retrieval_report(results: list[RetrievalEvalResult]) -> str:
    """Format Layer 2 results."""
    lines = [
        "",
        "=" * 80,
        "  LAYER 2: Retrieval Quality",
        "=" * 80,
        "",
        "| Query | Found | Type | KW Recall | Rank | Matched Entry |",
        "|-------|-------|------|-----------|------|---------------|",
    ]
    for r in results:
        lines.append(
            f"| {r.question[:40]:40s} "
            f"| {'Y' if r.found else 'N':5s} "
            f"| {'Y' if r.type_match else 'N':4s} "
            f"| {_pct(r.keyword_recall)} "
            f"| {r.rank if r.rank > 0 else '-':4} "
            f"| {r.matched_title[:30]} |"
        )
        if r.missing_keywords:
            lines.append(f"    missing kw: {', '.join(r.missing_keywords)}")

    if results:
        found_rate = sum(1 for r in results if r.found) / len(results)
        type_rate = sum(1 for r in results if r.type_match) / len(results)
        avg_kw = sum(r.keyword_recall for r in results) / len(results)
        lines.append(f"\n  Found: {found_rate*100:.0f}%  |  "
                      f"Type match: {type_rate*100:.0f}%  |  "
                      f"Avg KW recall: {avg_kw*100:.0f}%")

    return "\n".join(lines)


def format_consistency_report(
    all_runs: dict[str, list[ImportEvalResult]],
) -> str:
    """Format Layer 3 results: mean ± std for each metric."""
    lines = [
        "",
        "=" * 80,
        "  LAYER 3: Consistency (multi-run)",
        "=" * 80,
        "",
        "| Document | Metric | Mean | Std | Min | Max |",
        "|----------|--------|------|-----|-----|-----|",
    ]

    metric_names = list(ImportEvalResult._WEIGHTS.keys())

    for source, runs in all_runs.items():
        for metric in metric_names:
            values = [getattr(r, metric) for r in runs]
            if len(values) < 2:
                std = 0.0
            else:
                std = statistics.stdev(values)
            mean = statistics.mean(values)
            lines.append(
                f"| {source:35s} "
                f"| {metric:18s} "
                f"| {mean*100:5.1f}% "
                f"| {std*100:5.1f}% "
                f"| {min(values)*100:5.1f}% "
                f"| {max(values)*100:5.1f}% |"
            )
        # Aggregate score
        agg_values = [r.aggregate for r in runs]
        agg_std = statistics.stdev(agg_values) if len(agg_values) >= 2 else 0.0
        lines.append(
            f"| {source:35s} "
            f"| {'**aggregate**':18s} "
            f"| {statistics.mean(agg_values):5.1f}  "
            f"| {agg_std:5.1f}  "
            f"| {min(agg_values):5.1f}  "
            f"| {max(agg_values):5.1f}  |"
        )
        lines.append("|" + "-" * 78 + "|")

    return "\n".join(lines)


def _pct(v: float) -> str:
    return f"{v*100:3.0f}%"


# ---------------------------------------------------------------------------
# Minimum thresholds
# ---------------------------------------------------------------------------

IMPORT_THRESHOLDS = {
    "type_correct": 1.0,
    "command_recall": 0.70,
    "number_recall": 0.60,
    "branch_recall": 0.80,
    "tag_coverage": 0.60,
    "section_complete": 1.0,
    "brief_quality": 0.5,
    "aggregate_min": 75.0,
}

RETRIEVAL_THRESHOLDS = {
    "found_rate": 0.80,
    "type_match_rate": 0.80,
    "keyword_recall_avg": 0.60,
}

CONSISTENCY_THRESHOLDS = {
    "max_aggregate_std": 15.0,  # aggregate score std < 15 points
}


# ---------------------------------------------------------------------------
# Layer 1 tests: Import Quality
# ---------------------------------------------------------------------------


def _load_docs() -> list[DocGroundTruth]:
    docs, _ = _load_ground_truth()
    return docs


def _load_queries() -> list[QueryGroundTruth]:
    _, queries = _load_ground_truth()
    return queries


# Parametrize at module load
_DOCS = _load_docs() if _GT_PATH.exists() else []
_QUERIES = _load_queries() if _GT_PATH.exists() else []


@pytest.mark.llm
class TestLayer1ImportQuality:
    """Layer 1 — evaluate import pipeline extraction quality."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, holmes_config, real_provider):
        self.kb_root = tmp_path
        self.config = holmes_config
        self.provider = real_provider

    @pytest.mark.parametrize("gt", _DOCS, ids=[d.name for d in _DOCS])
    def test_import_document(self, gt: DocGroundTruth):
        source_path = _FIXTURES_DIR / gt.source
        assert source_path.exists(), f"Missing: {source_path}"

        kb = self.kb_root / gt.name.replace(".md", "")
        kb.mkdir(parents=True, exist_ok=True)

        draft = run_pipeline_for_eval(source_path, kb, self.config, self.provider)
        result = evaluate_import(gt, draft)

        _print_import_result(result)

        # Threshold assertions
        assert result.type_correct >= IMPORT_THRESHOLDS["type_correct"], \
            f"Type: expected={gt.type}, actual={result.actual_type}"
        assert result.command_recall >= IMPORT_THRESHOLDS["command_recall"], \
            f"Command recall {result.command_recall*100:.0f}%: missing {result.missing_commands}"
        assert result.number_recall >= IMPORT_THRESHOLDS["number_recall"], \
            f"Number recall {result.number_recall*100:.0f}%: missing {result.missing_numbers}"
        assert result.section_complete >= IMPORT_THRESHOLDS["section_complete"], \
            f"Missing sections: {result.missing_sections}"
        assert result.aggregate >= IMPORT_THRESHOLDS["aggregate_min"], \
            f"Aggregate {result.aggregate} < {IMPORT_THRESHOLDS['aggregate_min']}"


# ---------------------------------------------------------------------------
# Layer 2 tests: Retrieval Quality
# ---------------------------------------------------------------------------


@pytest.mark.llm
class TestLayer2RetrievalQuality:
    """Layer 2 — evaluate whether queries find the right entries.

    Requires Layer 1 entries to exist. Imports all docs first, then queries.
    """

    @pytest.fixture(autouse=True)
    def _setup_kb(self, tmp_path, holmes_config, real_provider):
        """Import all ground truth docs into a shared temp KB."""
        self.kb_root = tmp_path / "retrieval_kb"
        self.kb_root.mkdir()
        self.config = holmes_config
        self.provider = real_provider

        # Import all docs
        for gt in _DOCS:
            source_path = _FIXTURES_DIR / gt.source
            if source_path.exists():
                run_pipeline_for_eval(
                    source_path, self.kb_root, self.config, self.provider,
                )

        # Collect all generated entries for browse simulation
        self.entries: list[dict[str, Any]] = []
        pending_dir = self.kb_root / "contributions" / "pending"
        if pending_dir.exists():
            for p in sorted(pending_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(p))
                    self.entries.append({
                        "id": post.metadata.get("id", p.stem),
                        "type": post.metadata.get("type", ""),
                        "title": post.metadata.get("title", ""),
                        "brief": post.metadata.get("brief", ""),
                    })
                except Exception:
                    pass

    @pytest.mark.parametrize(
        "query", _QUERIES,
        ids=[q.question[:30] for q in _QUERIES],
    )
    def test_retrieval_query(self, query: QueryGroundTruth):
        result = evaluate_retrieval(query, self.entries)

        print(f"\n  Query: {query.question}")
        print(f"  Found: {result.found} | Type: {result.type_match} "
              f"| KW: {result.keyword_recall*100:.0f}% | Rank: {result.rank}")
        if result.matched_title:
            print(f"  Match: {result.matched_title}")
        if result.missing_keywords:
            print(f"  Missing KW: {result.missing_keywords}")

        assert result.found, f"No matching entry found for: {query.question}"
        assert result.type_match, \
            f"Type mismatch: expected {query.match_type}, got entry '{result.matched_title}'"


# ---------------------------------------------------------------------------
# Layer 3 tests: Consistency
# ---------------------------------------------------------------------------


@pytest.mark.llm
class TestLayer3Consistency:
    """Layer 3 — run each document N times, measure metric stability."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, holmes_config, real_provider):
        self.kb_root = tmp_path
        self.config = holmes_config
        self.provider = real_provider
        self.n_runs = int(os.environ.get("EVAL_CONSISTENCY_RUNS", "3"))

    def test_consistency(self):
        all_runs: dict[str, list[ImportEvalResult]] = {}

        for gt in _DOCS:
            source_path = _FIXTURES_DIR / gt.source
            if not source_path.exists():
                continue

            runs: list[ImportEvalResult] = []
            for i in range(self.n_runs):
                kb = self.kb_root / f"{gt.name}-run{i}"
                kb.mkdir(parents=True, exist_ok=True)

                draft = run_pipeline_for_eval(
                    source_path, kb, self.config, self.provider,
                )
                result = evaluate_import(gt, draft)
                runs.append(result)
                print(f"  {gt.name} run {i+1}/{self.n_runs}: {result.aggregate}")

            all_runs[gt.name] = runs

        # Print report
        report = format_consistency_report(all_runs)
        print(report)

        # Assert stability
        for source, runs in all_runs.items():
            agg_values = [r.aggregate for r in runs]
            if len(agg_values) >= 2:
                std = statistics.stdev(agg_values)
                assert std <= CONSISTENCY_THRESHOLDS["max_aggregate_std"], \
                    f"{source}: aggregate std={std:.1f} > {CONSISTENCY_THRESHOLDS['max_aggregate_std']}"


# ---------------------------------------------------------------------------
# Full report test (always passes — for humans)
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_full_report(tmp_path, holmes_config, real_provider):
    """Run all layers and print a combined report.

    This test always passes — it's the human-readable summary.
    Use individual layer tests for threshold enforcement.
    """
    # --- Layer 1: Import ---
    import_results: list[ImportEvalResult] = []
    for gt in _DOCS:
        source_path = _FIXTURES_DIR / gt.source
        if not source_path.exists():
            continue
        kb = tmp_path / gt.name.replace(".md", "")
        kb.mkdir(parents=True, exist_ok=True)
        draft = run_pipeline_for_eval(source_path, kb, holmes_config, real_provider)
        import_results.append(evaluate_import(gt, draft))

    print(format_import_report(import_results))

    # --- Layer 2: Retrieval ---
    # Collect entries from Layer 1
    entries: list[dict[str, Any]] = []
    for gt in _DOCS:
        kb = tmp_path / gt.name.replace(".md", "")
        pending_dir = kb / "contributions" / "pending"
        if pending_dir.exists():
            for p in sorted(pending_dir.glob("*.md")):
                try:
                    post = frontmatter.load(str(p))
                    entries.append({
                        "id": post.metadata.get("id", p.stem),
                        "type": post.metadata.get("type", ""),
                        "title": post.metadata.get("title", ""),
                        "brief": post.metadata.get("brief", ""),
                    })
                except Exception:
                    pass

    retrieval_results = [evaluate_retrieval(q, entries) for q in _QUERIES]
    print(format_retrieval_report(retrieval_results))

    # Save combined report
    report_path = tmp_path / "eval_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(format_import_report(import_results))
        f.write("\n\n")
        f.write(format_retrieval_report(retrieval_results))
    print(f"\nReport saved: {report_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_import_result(r: ImportEvalResult) -> None:
    print(f"\n{'='*60}")
    print(f"  {r.source}")
    print(f"  Score: {r.aggregate}/100  (type={r.actual_type})")
    print(f"  Type={_pct(r.type_correct)}  Cat={_pct(r.category_correct)}  "
          f"Cmd={_pct(r.command_recall)}  Num={_pct(r.number_recall)}")
    print(f"  Branch={_pct(r.branch_recall)}  Tags={_pct(r.tag_coverage)}  "
          f"Sect={_pct(r.section_complete)}  Brief={_pct(r.brief_quality)}  "
          f"Terms={_pct(r.term_recall)}")
    if r.missing_commands:
        print(f"  Missing cmds: {r.missing_commands}")
    if r.missing_numbers:
        print(f"  Missing nums: {r.missing_numbers}")
    if r.missing_tags:
        print(f"  Missing tags: {r.missing_tags}")
    if r.missing_sections:
        print(f"  Missing sect: {r.missing_sections}")
    if r.missing_terms:
        print(f"  Missing terms: {r.missing_terms}")
    print(f"{'='*60}")
