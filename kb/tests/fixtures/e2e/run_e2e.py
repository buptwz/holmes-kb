#!/usr/bin/env python3
"""E2E validation script — run each fixture through the full 042 pipeline.

Usage:
    python tests/fixtures/e2e/run_e2e.py [filename]

If filename is given, only that file is processed. Otherwise all .md files in
the e2e fixtures dir are processed.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent
ALL_FIXTURES = sorted(f for f in FIXTURE_DIR.glob("*.md") if not f.name.startswith("output_"))

from holmes.config import load_config
from holmes.kb.agent.provider.openai_provider import OpenAIProvider
from holmes.kb.agent.phases.classifier import DocumentClassifier
from holmes.kb.agent.phases.summarizer import SummarizerAgent
from holmes.kb.agent.phases.generator import GeneratorAgent
from holmes.kb.agent.normalizer import DraftNormalizer
from holmes.kb.agent.fidelity import verify_summary_fidelity_042
from holmes.kb.progress import NullReporter

import frontmatter as _fm


def run_one(filepath: Path, cfg, provider) -> dict:
    """Run the full pipeline on one file, return result dict."""
    reporter = NullReporter()
    source = filepath.read_text(encoding="utf-8")
    result = {
        "file": filepath.name,
        "source_chars": len(source),
        "phases": {},
        "errors": [],
        "warnings": [],
    }

    # Phase 1: Classifier
    try:
        classifier = DocumentClassifier(provider=provider, model=cfg.model, reporter=reporter)
        classification = classifier.classify(source)
        result["phases"]["classifier"] = {
            "doc_type": classification.doc_type.value,
            "suggested_type": classification.suggested_type,
            "language": classification.language,
            "is_multi_topic": classification.is_multi_topic,
            "reason": classification.reason,
        }
    except Exception as e:
        result["errors"].append(f"Classifier: {e}")
        traceback.print_exc()
        return result

    suggested_type = classification.suggested_type
    language = classification.language

    # Heuristic language fallback (same as pipeline)
    from holmes.kb.agent.pipeline import _detect_language_heuristic
    if language == "en":
        language = _detect_language_heuristic(source, language)

    # Phase 2: Summarizer
    ctx = {"source_text": source}
    try:
        class DebugReporter:
            def start(self, msg: str) -> None: print(f"    [S] {msg}")
            def done(self, msg: str) -> None: print(f"    [S] DONE: {msg}")
            def info(self, msg: str) -> None: print(f"    [S] {msg}")
            def warn(self, msg: str) -> None: print(f"    [S] WARN: {msg}")
        summarizer = SummarizerAgent(provider=provider, model=cfg.model, reporter=DebugReporter())
        summary = summarizer.run(source, ctx, suggested_type=suggested_type)
        if summary is None:
            result["errors"].append("Summarizer returned None")
            return result
        result["phases"]["summarizer"] = {
            "brief": summary.get("brief", ""),
            "key_facts_count": len(summary.get("key_facts", [])),
            "commands_count": len(summary.get("commands", [])),
            "symptoms_count": len(summary.get("symptoms", [])),
            "branches_count": len(summary.get("resolution_branches", [])),
            "key_facts": summary.get("key_facts", []),
            "commands": summary.get("commands", []),
        }
    except Exception as e:
        result["errors"].append(f"Summarizer: {e}")
        traceback.print_exc()
        return result

    # Phase 3: Generator
    try:
        generator = GeneratorAgent(provider=provider, model=cfg.model, reporter=reporter)
        draft = generator.run(summary, ctx, suggested_type=suggested_type, language=language)
        if not draft:
            result["errors"].append("Generator returned empty draft")
            return result
        result["phases"]["generator_raw"] = draft[:200]  # raw before strip
        result["phases"]["generator"] = {
            "draft_chars": len(draft),
            "draft_preview": draft[:500],
        }
    except Exception as e:
        result["errors"].append(f"Generator: {e}")
        traceback.print_exc()
        return result

    # Validate YAML frontmatter (use pipeline's strip logic)
    from holmes.kb.agent.pipeline import ImportPipeline
    draft = ImportPipeline._strip_llm_wrapper(draft)

    # Fix unquoted YAML values with colons
    draft = ImportPipeline._fix_yaml_values(draft)

    post = None
    try:
        post = _fm.loads(draft)
        if not post.metadata:
            result["errors"].append("No YAML frontmatter in generated draft")
        else:
            result["phases"]["frontmatter"] = dict(post.metadata)
    except Exception as e:
        result["errors"].append(f"YAML parse error: {e}")

    # Clean stray code fences from body (LLM sometimes wraps body in ```)
    if post and post.content:
        body = post.content
        if body.lstrip().startswith("```"):
            lines = body.splitlines()
            start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), -1)
            if start != -1:
                lines.pop(start)
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                post.content = "\n".join(lines)
                draft = _fm.dumps(post)

    # Normalize
    if post and post.metadata:
        normalizer = DraftNormalizer()
        kb_type = post.metadata.get("type", suggested_type) or ""
        draft, norm_warnings = normalizer.normalize(draft, kb_type=kb_type)
        result["warnings"].extend(norm_warnings)

    # Fidelity check
    fidelity_warnings = verify_summary_fidelity_042(summary, draft)
    if fidelity_warnings:
        result["warnings"].extend([f"FIDELITY: {w}" for w in fidelity_warnings])

    # Section structure check
    body = ""
    try:
        post2 = _fm.loads(draft)
        body = post2.content
    except Exception:
        body = draft

    sections = [line.strip() for line in body.splitlines() if line.strip().startswith("## ")]
    result["phases"]["sections"] = sections

    # Full draft for review
    result["full_draft"] = draft

    return result


def main():
    cfg = load_config()
    provider = OpenAIProvider(cfg)

    # Determine which files to process
    if len(sys.argv) > 1:
        targets = [FIXTURE_DIR / sys.argv[1]]
    else:
        targets = ALL_FIXTURES

    results = []
    for fp in targets:
        if not fp.exists():
            print(f"SKIP: {fp} not found")
            continue
        print(f"\n{'='*70}")
        print(f"  Processing: {fp.name}")
        print(f"{'='*70}")
        r = run_one(fp, cfg, provider)
        results.append(r)

        # Print summary
        if r["errors"]:
            print(f"  ERRORS: {r['errors']}")
            raw = r["phases"].get("generator_raw", "")
            if raw:
                print(f"  RAW DRAFT (first 300 chars): {raw[:300]}")
        cls = r["phases"].get("classifier", {})
        print(f"  Classifier: type={cls.get('suggested_type')} lang={cls.get('language')} multi={cls.get('is_multi_topic')}")

        summ = r["phases"].get("summarizer", {})
        print(f"  Summarizer: {summ.get('key_facts_count', '?')} facts, {summ.get('commands_count', '?')} cmds, {summ.get('symptoms_count', '?')} symptoms, {summ.get('branches_count', '?')} branches")

        gen = r["phases"].get("generator", {})
        print(f"  Generator: {gen.get('draft_chars', 0)} chars")

        fm = r["phases"].get("frontmatter", {})
        if fm:
            print(f"  Frontmatter: type={fm.get('type')} category={fm.get('category')} title={fm.get('title')}")

        secs = r["phases"].get("sections", [])
        print(f"  Sections: {secs}")

        if r["warnings"]:
            for w in r["warnings"]:
                print(f"  WARNING: {w}")

        if not r["errors"]:
            print(f"  -> OK")
        else:
            print(f"  -> FAILED")

    # Summary table
    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for r in results if not r["errors"])
    failed = sum(1 for r in results if r["errors"])
    print(f"  {passed} passed, {failed} failed out of {len(results)} documents")
    for r in results:
        status = "OK" if not r["errors"] else f"FAIL: {r['errors'][0]}"
        print(f"    {r['file']:40s} {status}")

    # Write full results for detailed review
    out_path = FIXTURE_DIR / "e2e_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        # Remove full_draft from JSON (too large), keep in separate files
        for r in results:
            draft = r.pop("full_draft", "")
            draft_path = FIXTURE_DIR / f"output_{r['file']}"
            draft_path.write_text(draft, encoding="utf-8")
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  Results: {out_path}")
    print(f"  Drafts:  {FIXTURE_DIR}/output_*.md")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
