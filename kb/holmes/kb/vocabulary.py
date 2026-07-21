"""Vocabulary and kb-config.yml loading for applies_to (spec 043 D6).

The vocabulary is the open-world value set for the fixed applies_to keys
(product_line / test_stage). It self-accumulates: import injects it into the
Summarizer prompt, doctor lints out-of-vocabulary values, and kb_browse
exposes it in the guide field so agents can filter.

Interface (canonical — merge conflicts resolve in favor of this module):

    load_kb_config(kb_root) -> dict
        Raw parsed kb-config.yml ({} when missing/unparseable).

    load_vocabulary(kb_root) -> dict[str, list[str]]
        {"product_line": [...], "test_stage": [...]}.
        Source precedence:
          1. kb-config.yml `vocabulary:` section
          2. aggregated from existing entries' applies_to
          3. {} when neither exists
"""

from __future__ import annotations

from pathlib import Path

import yaml

from holmes.kb.schema import _APPLIES_TO_LIST_KEYS


def load_kb_config(kb_root: Path) -> dict:
    """Load kb-config.yml as a dict; return {} when missing or unparseable."""
    config_path = kb_root / "kb-config.yml"
    if not config_path.exists():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_vocabulary(kb_root: Path) -> dict[str, list[str]]:
    """Load the applies_to value vocabulary.

    Prefers the kb-config.yml `vocabulary:` section; falls back to
    aggregating values from existing entries' applies_to frontmatter.
    Returns {} when neither source yields anything.
    """
    vocab_cfg = load_kb_config(kb_root).get("vocabulary")
    if isinstance(vocab_cfg, dict):
        vocab: dict[str, list[str]] = {}
        for key in sorted(_APPLIES_TO_LIST_KEYS):
            values = vocab_cfg.get(key)
            if isinstance(values, list):
                vocab[key] = sorted({str(v) for v in values if isinstance(v, str) and v})
        if vocab:
            return vocab

    # Aggregate from existing entries.
    from holmes.kb.store import list_entries

    aggregated: dict[str, set[str]] = {}
    for entry in list_entries(kb_root, kb_status=None):
        applies_to = entry.applies_to
        if not isinstance(applies_to, dict):
            continue
        for key in _APPLIES_TO_LIST_KEYS:
            values = applies_to.get(key)
            if isinstance(values, list):
                aggregated.setdefault(key, set()).update(
                    v for v in values if isinstance(v, str) and v
                )
    return {key: sorted(values) for key, values in sorted(aggregated.items())}
