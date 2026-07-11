"""Evaluation metrics — auto-extracted baselines from source documents.

Design principle: metrics must correlate with actual quality.
If the metric is high, the output MUST be good. No false positives.

Two categories of metrics:

A. Auto-extracted (no human maintenance):
   - command_recall:   auto-extract ALL commands from source code blocks,
                       check each appears verbatim in output.
   - number_recall:    auto-extract ALL significant numbers from source,
                       check each appears in output.
   - content_coverage: split source into semantic chunks (sentences with
                       technical content), measure what fraction has a
                       corresponding match in the output.

B. Human-specified (ground truth YAML):
   - type_correct:     classification accuracy (0/1)
   - section_valid:    required sections exist AND are non-empty (≥50 chars)
   - branch_count:     number of ### subsections under Resolution matches
                       expected branch count
   - tag_coverage:     expected behavior tags appear in output
   - brief_quality:    brief exists, 10-150 chars, contains technical term
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import frontmatter


# ---------------------------------------------------------------------------
# Auto-extraction from source documents
# ---------------------------------------------------------------------------


def extract_code_blocks(text: str) -> list[str]:
    """Extract all fenced code block contents from markdown.

    Returns each code block as a single string (multi-line preserved).
    Strips the language tag and leading $ prompts.
    """
    blocks: list[str] = []
    pattern = re.compile(r"```(?:\w*)\s*\n(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        block = m.group(1).strip()
        if block:
            blocks.append(block)
    return blocks


def extract_commands_from_source(source_text: str) -> list[str]:
    """Extract individual commands from source document code blocks.

    Each non-empty, non-comment line in a code block = one command.
    Multi-line commands (ending with \\) are joined.
    """
    blocks = extract_code_blocks(source_text)
    commands: list[str] = []

    for block in blocks:
        lines = block.splitlines()
        current: list[str] = []
        for line in lines:
            stripped = line.strip()

            # Skip empty lines, pure comments, and output-like lines
            if not stripped:
                if current:
                    commands.append(" ".join(current))
                    current = []
                continue
            if stripped.startswith("#") and not stripped.startswith("#!"):
                continue

            # Strip leading $ prompt
            if stripped.startswith("$ "):
                stripped = stripped[2:]

            # Handle line continuation
            if stripped.endswith("\\"):
                current.append(stripped[:-1].strip())
                continue

            current.append(stripped)
            commands.append(" ".join(current))
            current = []

        if current:
            commands.append(" ".join(current))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for cmd in commands:
        normalized = " ".join(cmd.split())
        if normalized not in seen and len(normalized) >= 5:
            seen.add(normalized)
            unique.append(normalized)

    return unique


def extract_significant_numbers(text: str) -> set[str]:
    """Extract numbers that carry technical meaning.

    Filters out noise: step numbers (1-9), list indices, etc.
    Keeps: version numbers, thresholds, percentages, port numbers,
    memory sizes, durations, etc.
    """
    # Find all number-like tokens
    raw = re.findall(r"(?<!\w)(\d+\.?\d*)(?!\w)", text)

    significant: set[str] = set()
    for n in raw:
        # Skip single-digit numbers (usually step/list numbers)
        try:
            val = float(n)
        except ValueError:
            continue

        # Keep if: >= 2 digits, or is a decimal, or >= 10
        if len(n) >= 2 or "." in n or val >= 10:
            significant.add(n)

    return significant


def extract_technical_sentences(text: str) -> list[str]:
    """Extract sentences that contain technical content.

    A sentence is "technical" if it contains at least one of:
    - backtick-wrapped code
    - a number with unit context
    - a known technical pattern (command, path, error message)

    Returns normalized sentences (whitespace-collapsed).
    """
    # Split into lines, skip headings and empty lines
    lines = text.splitlines()
    sentences: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("```"):
            continue

        # Check if line has technical content
        has_code = "`" in stripped
        has_number = bool(re.search(r"\d{2,}", stripped))
        has_technical = bool(re.search(
            r"[A-Z]{2,}|[a-z]+_[a-z]+|/[a-z]|0x[0-9a-f]|::\w",
            stripped,
        ))

        if has_code or has_number or has_technical:
            normalized = " ".join(stripped.split())
            if len(normalized) >= 15:  # skip trivial fragments
                sentences.append(normalized)

    return sentences


# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------


@dataclass
class EvalScore:
    """Complete evaluation result for one document."""

    source: str

    # --- Auto-extracted metrics ---
    cmd_total: int = 0            # total commands in source
    cmd_found: int = 0            # commands found in output
    cmd_missing: list[str] = field(default_factory=list)

    num_total: int = 0            # significant numbers in source
    num_found: int = 0            # numbers found in output
    num_missing: list[str] = field(default_factory=list)

    content_total: int = 0        # technical sentences in source
    content_found: int = 0        # sentences with match in output
    content_missing: list[str] = field(default_factory=list)

    # --- Human-specified metrics ---
    type_correct: bool = False
    actual_type: str = ""
    expected_type: str = ""

    section_results: dict[str, bool] = field(default_factory=dict)
    # True = section exists AND has ≥50 chars content

    branch_expected: int = 0
    branch_actual: int = 0

    tags_expected: list[str] = field(default_factory=list)
    tags_found: list[str] = field(default_factory=list)
    tags_missing: list[str] = field(default_factory=list)

    brief_ok: bool = False
    brief_value: str = ""

    @property
    def command_recall(self) -> float:
        return self.cmd_found / self.cmd_total if self.cmd_total else 1.0

    @property
    def number_recall(self) -> float:
        return self.num_found / self.num_total if self.num_total else 1.0

    @property
    def content_coverage(self) -> float:
        return self.content_found / self.content_total if self.content_total else 1.0

    @property
    def section_score(self) -> float:
        if not self.section_results:
            return 1.0
        return sum(self.section_results.values()) / len(self.section_results)

    @property
    def branch_score(self) -> float:
        if self.branch_expected == 0:
            return 1.0
        return min(self.branch_actual / self.branch_expected, 1.0)

    @property
    def tag_score(self) -> float:
        if not self.tags_expected:
            return 1.0
        return len(self.tags_found) / len(self.tags_expected)

    @property
    def aggregate(self) -> float:
        """Weighted aggregate (0-100)."""
        weights = {
            "command_recall": 30,     # most critical for NPI
            "number_recall": 15,      # thresholds, versions
            "content_coverage": 15,   # overall info retention
            "type_correct": 10,       # classification
            "section_score": 10,      # structure
            "branch_score": 10,       # multi-path diagnosis
            "tag_score": 5,           # behavior annotation
            "brief_ok": 5,            # discoverability
        }
        values = {
            "command_recall": self.command_recall,
            "number_recall": self.number_recall,
            "content_coverage": self.content_coverage,
            "type_correct": 1.0 if self.type_correct else 0.0,
            "section_score": self.section_score,
            "branch_score": self.branch_score,
            "tag_score": self.tag_score,
            "brief_ok": 1.0 if self.brief_ok else 0.0,
        }
        total_w = sum(weights.values())
        score = sum(values[k] * weights[k] for k in weights)
        return round(score / total_w * 100, 1)

    def summary_line(self) -> str:
        return (
            f"Cmd={self.command_recall*100:.0f}%({self.cmd_found}/{self.cmd_total}) "
            f"Num={self.number_recall*100:.0f}%({self.num_found}/{self.num_total}) "
            f"Content={self.content_coverage*100:.0f}%({self.content_found}/{self.content_total}) "
            f"Type={'Y' if self.type_correct else 'N'} "
            f"Sect={self.section_score*100:.0f}% "
            f"Branch={self.branch_actual}/{self.branch_expected} "
            f"Tags={self.tag_score*100:.0f}% "
            f"Brief={'Y' if self.brief_ok else 'N'} "
            f"=> {self.aggregate}"
        )


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


def evaluate(
    source_text: str,
    draft: str,
    expected_type: str = "",
    expected_sections: list[str] | None = None,
    expected_branch_count: int = 0,
    expected_tags: list[str] | None = None,
    source_name: str = "",
) -> EvalScore:
    """Evaluate a generated draft against its source document.

    Auto-extracted metrics need only source_text and draft.
    Human-specified metrics use the optional parameters.
    """
    score = EvalScore(source=source_name)

    # Parse draft
    try:
        post = frontmatter.loads(draft)
        meta = post.metadata or {}
        body = post.content or ""
    except Exception:
        meta = {}
        body = draft

    body_normalized = " ".join(body.split())
    body_lower = body.lower()

    # ===== Auto-extracted metrics =====

    # 1. Command recall — full extraction from source code blocks
    source_commands = extract_commands_from_source(source_text)
    score.cmd_total = len(source_commands)
    draft_normalized = " ".join(draft.split())
    for cmd in source_commands:
        cmd_norm = " ".join(cmd.split())
        if cmd_norm in draft_normalized:
            score.cmd_found += 1
        else:
            # Try relaxed match: core command (first 40 chars) present
            core = cmd_norm[:40]
            if len(core) >= 10 and core in draft_normalized:
                score.cmd_found += 1
            else:
                score.cmd_missing.append(
                    cmd[:80] + ("..." if len(cmd) > 80 else "")
                )

    # 2. Number recall — all significant numbers from source
    source_numbers = extract_significant_numbers(source_text)
    draft_numbers = extract_significant_numbers(draft)
    score.num_total = len(source_numbers)
    for n in source_numbers:
        if n in draft_numbers:
            score.num_found += 1
        else:
            score.num_missing.append(n)

    # 3. Content coverage — technical sentences from source
    source_sentences = extract_technical_sentences(source_text)
    score.content_total = len(source_sentences)
    for sent in source_sentences:
        # Check if the core information appears in output
        # Use overlapping keywords (≥3 significant words match)
        words = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", sent.lower()))
        if len(words) < 3:
            score.content_found += 1  # trivial sentence, skip
            continue

        draft_words = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", body_lower))
        overlap = words & draft_words
        coverage = len(overlap) / len(words)

        if coverage >= 0.5:  # at least 50% keyword overlap
            score.content_found += 1
        else:
            score.content_missing.append(
                sent[:60] + ("..." if len(sent) > 60 else "")
            )

    # ===== Human-specified metrics =====

    # 4. Type correct
    score.expected_type = expected_type
    score.actual_type = meta.get("type", "")
    score.type_correct = score.actual_type == expected_type if expected_type else True

    # 5. Section validation — exists AND non-empty (≥50 chars)
    if expected_sections:
        for section in expected_sections:
            section_lower = section.lower()
            # Find section in body
            found = False
            for line in body.splitlines():
                if line.strip().startswith("## ") and section_lower in line.lower():
                    # Found heading — check content length
                    idx = body.find(line)
                    rest = body[idx + len(line):]
                    # Content = text until next ## heading
                    next_heading = re.search(r"\n## ", rest)
                    if next_heading:
                        content = rest[:next_heading.start()]
                    else:
                        content = rest
                    found = len(content.strip()) >= 50
                    break
            score.section_results[section] = found

    # 6. Branch count — count ### subsections under ## Resolution
    score.branch_expected = expected_branch_count
    resolution_match = re.search(
        r"## Resolution\b(.*?)(?=\n## |\Z)", body, re.DOTALL | re.IGNORECASE,
    )
    if resolution_match:
        resolution_body = resolution_match.group(1)
        h3_headings = re.findall(r"^### .+", resolution_body, re.MULTILINE)
        score.branch_actual = len(h3_headings)
    else:
        score.branch_actual = 0

    # 7. Behavior tags
    score.tags_expected = expected_tags or []
    for tag in score.tags_expected:
        if tag in body:
            score.tags_found.append(tag)
        else:
            score.tags_missing.append(tag)

    # 8. Brief quality
    brief = str(meta.get("brief", ""))
    score.brief_value = brief
    # Brief must: exist, 10-150 chars, contain at least one technical term
    has_technical = bool(re.search(
        r"[A-Z]{2,}|[\u4e00-\u9fff]{2,}|\d{2,}", brief,
    ))
    score.brief_ok = bool(brief) and 10 <= len(brief) <= 150 and has_technical

    return score


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_report(scores: list[EvalScore]) -> str:
    """Format evaluation results as a readable report."""
    lines = [
        "",
        "=" * 90,
        "  EVALUATION REPORT",
        "=" * 90,
        "",
        f"{'Document':<38} {'Cmd':>8} {'Num':>8} {'Content':>8} "
        f"{'Type':>5} {'Sect':>5} {'Branch':>7} {'Tags':>5} {'Brief':>5} {'Score':>6}",
        "-" * 90,
    ]

    for s in scores:
        lines.append(
            f"{s.source:<38} "
            f"{s.cmd_found}/{s.cmd_total:>5} "
            f"{s.num_found}/{s.num_total:>5} "
            f"{s.content_found}/{s.content_total:>5} "
            f"{'Y' if s.type_correct else 'N':>5} "
            f"{s.section_score*100:4.0f}% "
            f"{s.branch_actual}/{s.branch_expected:>4} "
            f"{s.tag_score*100:4.0f}% "
            f"{'Y' if s.brief_ok else 'N':>5} "
            f"{s.aggregate:>5.1f}"
        )

    if scores:
        avg = sum(s.aggregate for s in scores) / len(scores)
        lines.append("-" * 90)
        lines.append(f"{'AVERAGE':<38} {' '*55} {avg:>5.1f}")

    # Missing details
    for s in scores:
        missing_parts = []
        if s.cmd_missing:
            missing_parts.append(
                f"  Commands ({len(s.cmd_missing)} missing):\n"
                + "\n".join(f"    - {c}" for c in s.cmd_missing[:5])
            )
        if s.num_missing:
            missing_parts.append(
                f"  Numbers ({len(s.num_missing)} missing): {', '.join(sorted(s.num_missing)[:10])}"
            )
        if s.content_missing:
            missing_parts.append(
                f"  Content ({len(s.content_missing)} unmatched):\n"
                + "\n".join(f"    - {c}" for c in s.content_missing[:5])
            )
        if s.tags_missing:
            missing_parts.append(f"  Tags missing: {', '.join(s.tags_missing)}")
        bad_sections = [k for k, v in s.section_results.items() if not v]
        if bad_sections:
            missing_parts.append(f"  Sections empty/missing: {', '.join(bad_sections)}")

        if missing_parts:
            lines.append(f"\n{s.source} (score={s.aggregate}):")
            lines.extend(missing_parts)

    return "\n".join(lines)
