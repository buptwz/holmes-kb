"""Knowledge base search — BM25 ranked search with optional LLM query expansion.

Provides:
- BM25Backend: IDF-weighted, length-normalized search with Chinese bigram tokenization.
- LinearScanBackend: Legacy full-text scan (kept for compatibility).
- LLM query expansion: cross-language synonym expansion using existing chat model.

The default backend is BM25Backend (lazy index build on first search).
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import frontmatter

from holmes.kb.store import EVIDENCE_SIDECAR_DIR, _should_skip


@dataclass
class SearchResult:
    """A single search result from the knowledge base."""

    entry_id: str
    title: str
    kb_type: str
    category: Optional[str]
    maturity: str
    tags: list[str]
    snippet: str
    score: float
    file_path: str
    brief: str = ""
    last_evidence_date: Optional[str] = None


class SearchBackend(ABC):
    """Abstract base class for KB search backends.

    Implementations must be thread-safe and stateless (or lazily initialised).
    """

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search the knowledge base for entries matching query.

        Args:
            query: Search terms (keywords or short phrase).
            limit: Maximum number of results to return.

        Returns:
            List of SearchResult ordered by descending relevance score.
        """


def _build_evidence_date_index(kb_root: Path) -> dict:
    """Scan all evidence sidecar directories once and return {entry_id: max_date}."""
    evidence_root = kb_root / EVIDENCE_SIDECAR_DIR
    if not evidence_root.is_dir():
        return {}
    index: dict[str, str] = {}
    for entry_dir in evidence_root.iterdir():
        if not entry_dir.is_dir():
            continue
        entry_id = entry_dir.name
        dates: list[str] = []
        for json_file in entry_dir.glob("*.json"):
            try:
                record = json.loads(json_file.read_text(encoding="utf-8"))
                if isinstance(record, dict) and record.get("date"):
                    dates.append(str(record["date"]))
            except Exception:  # noqa: BLE001
                pass
        if dates:
            index[entry_id] = max(dates)
    return index


# ---------------------------------------------------------------------------
# Tokenizer (shared by BM25 and snippet extraction)
# ---------------------------------------------------------------------------

# English token: alphanumeric words, preserving hyphens/dots/underscores
_EN_TOKEN_RE = re.compile(r"[a-z0-9][-a-z0-9_.]*[a-z0-9]|[a-z0-9]+")

# Unicode ranges for CJK characters
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+"
)


def tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text for BM25.

    English: split on whitespace/punctuation, lowercase, preserve hyphens.
    Chinese: character bigrams (no jieba dependency).

    Returns:
        List of lowercase tokens.
    """
    text_lower = text.lower()
    tokens: list[str] = []

    # Extract English tokens.
    tokens.extend(_EN_TOKEN_RE.findall(text_lower))

    # Extract Chinese bigrams.
    for cjk_run in _CJK_RE.findall(text_lower):
        if len(cjk_run) == 1:
            tokens.append(cjk_run)
        else:
            for i in range(len(cjk_run) - 1):
                tokens.append(cjk_run[i : i + 2])

    return tokens


# ---------------------------------------------------------------------------
# BM25 index document
# ---------------------------------------------------------------------------

@dataclass
class _IndexedDoc:
    """A single indexed document (KB entry) for BM25 scoring."""

    entry_id: str
    title: str
    kb_type: str
    category: Optional[str]
    maturity: str
    tags: list[str]
    body: str
    file_path: str
    brief: str = ""
    tf: Counter = field(default_factory=Counter)
    dl: int = 0  # document length (total tokens)
    last_evidence_date: Optional[str] = None
    kb_status: str = "active"
    parent_id: Optional[str] = None


# ---------------------------------------------------------------------------
# BM25Backend
# ---------------------------------------------------------------------------


class BM25Backend(SearchBackend):
    """BM25 ranked search, zero external dependencies.

    Lazy-builds an in-memory index on first search. The index lives for the
    lifetime of this object (suitable for long-running MCP server processes).

    Call invalidate() to force a rebuild on next search (e.g. after import).
    """

    K1 = 1.2   # term frequency saturation
    B = 0.75   # document length normalization

    TITLE_BOOST = 3  # title token tf multiplier

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root
        self._docs: dict[str, _IndexedDoc] = {}
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0
        self._built = False
        self._evidence_date_index: dict[str, str] = {}

    def invalidate(self) -> None:
        """Mark the index as stale; next search will rebuild."""
        self._built = False
        self._docs.clear()
        self._idf.clear()
        self._evidence_date_index.clear()

    def search(
        self,
        query: str,
        limit: int = 5,
        active_only: bool = True,
        exclude_sub_entries: bool = True,
        kb_type: Optional[str] = None,
    ) -> list[SearchResult]:
        """BM25 ranked search over all KB entries.

        Args:
            query: Space-separated keywords or natural language phrase.
            limit: Maximum results.
            active_only: Filter to kb_status active/pending.
            exclude_sub_entries: Exclude process sub-entries with parent_id.
            kb_type: Filter to a specific entry type (e.g. "pitfall").

        Returns:
            Up to limit SearchResult objects ordered by BM25 score (descending).
        """
        if not self._built:
            self._build_index()

        terms = tokenize(query)
        if not terms:
            return []

        if not self._evidence_date_index:
            self._evidence_date_index = _build_evidence_date_index(self._kb_root)
        results: list[SearchResult] = []

        for entry_id, doc in self._docs.items():
            # Filters.
            if active_only and doc.kb_status not in ("active", "pending"):
                continue
            if exclude_sub_entries and doc.kb_type == "process" and doc.parent_id:
                continue
            if kb_type and doc.kb_type != kb_type:
                continue

            # BM25 score.
            score = 0.0
            for t in terms:
                idf = self._idf.get(t, 0.0)
                tf = doc.tf.get(t, 0)
                if tf == 0:
                    continue
                numerator = tf * (self.K1 + 1)
                denominator = tf + self.K1 * (
                    1 - self.B + self.B * doc.dl / self._avg_dl
                )
                score += idf * numerator / denominator

            if score <= 0:
                continue

            led = self._evidence_date_index.get(entry_id) or doc.last_evidence_date
            snippet = _extract_snippet(doc.body, [t for t in terms])
            results.append(
                SearchResult(
                    entry_id=entry_id,
                    title=doc.title,
                    kb_type=doc.kb_type,
                    category=doc.category,
                    maturity=doc.maturity,
                    tags=doc.tags,
                    snippet=snippet,
                    score=score,
                    file_path=doc.file_path,
                    brief=doc.brief,
                    last_evidence_date=led,
                )
            )

        # Sort: primary by BM25 score, secondary by evidence freshness.
        results.sort(
            key=lambda r: (r.score, r.last_evidence_date or ""),
            reverse=True,
        )
        return results[:limit]

    def _build_index(self) -> None:
        """Scan all KB .md files and build the BM25 index."""
        self._docs.clear()
        self._idf.clear()

        search_roots = [
            self._kb_root / t
            for t in ("pitfall", "model", "guideline", "process", "decision")
        ]
        pending_dir = self._kb_root / "contributions" / "pending"
        if pending_dir.is_dir():
            search_roots.append(pending_dir)
        new_pending = self._kb_root / "_pending"
        if new_pending.is_dir():
            for sub in new_pending.iterdir():
                if sub.is_dir():
                    search_roots.append(sub)

        # Document frequency per term.
        df: Counter = Counter()

        for type_dir in search_roots:
            if not type_dir.is_dir():
                continue
            for md_file in sorted(type_dir.rglob("*.md")):
                if md_file.name.startswith("_"):
                    continue
                if _should_skip(md_file, self._kb_root):
                    continue
                try:
                    raw = md_file.read_text(encoding="utf-8")
                    post = frontmatter.loads(raw)
                    meta = post.metadata

                    entry_id = str(meta.get("id", md_file.stem))

                    # Tokenize title/tags separately for boosting.
                    title_text = str(meta.get("title", ""))
                    tags_text = " ".join(str(t) for t in meta.get("tags", []))
                    body_text = post.content or ""

                    title_tags_tokens = tokenize(title_text + " " + tags_text)
                    body_tokens = tokenize(body_text)
                    all_tokens = title_tags_tokens + body_tokens
                    tf = Counter(all_tokens)
                    # Boost title/tags tokens so title matches rank higher.
                    for tok in title_tags_tokens:
                        tf[tok] += self.TITLE_BOOST - 1  # already counted once
                    tokens = all_tokens

                    doc = _IndexedDoc(
                        entry_id=entry_id,
                        title=str(meta.get("title", md_file.stem)),
                        kb_type=str(meta.get("type", "")),
                        category=meta.get("category"),
                        maturity=str(meta.get("maturity", "draft")),
                        tags=list(meta.get("tags", [])),
                        body=post.content or "",
                        file_path=str(md_file),
                        brief=str(meta.get("brief", "")),
                        tf=tf,
                        dl=len(tokens),
                        kb_status=str(meta.get("kb_status", "active")),
                        parent_id=meta.get("parent_id"),
                    )
                    self._docs[entry_id] = doc

                    # Update document frequencies (unique terms per doc).
                    for term in set(tokens):
                        df[term] += 1

                except Exception:  # noqa: BLE001
                    pass

        # Compute IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        n = len(self._docs)
        for term, freq in df.items():
            self._idf[term] = math.log((n - freq + 0.5) / (freq + 0.5) + 1)

        # Average document length.
        total_dl = sum(doc.dl for doc in self._docs.values())
        self._avg_dl = total_dl / max(n, 1)

        self._built = True


# ---------------------------------------------------------------------------
# LinearScanBackend (legacy, kept for compatibility)
# ---------------------------------------------------------------------------


class LinearScanBackend(SearchBackend):
    """Full-text linear scan over all .md files in the KB.

    Suitable for KBs up to ~1000 entries. No index required.
    """

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root

    def search(
        self,
        query: str,
        limit: int = 5,
        active_only: bool = True,
        exclude_sub_entries: bool = True,
        kb_type: Optional[str] = None,
    ) -> list[SearchResult]:
        """Scan all KB entries for query terms and return ranked results."""
        terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return []

        results: list[SearchResult] = []
        date_index = _build_evidence_date_index(self._kb_root)
        search_roots = [
            self._kb_root / t
            for t in ("pitfall", "model", "guideline", "process", "decision")
        ]
        pending_dir = self._kb_root / "contributions" / "pending"
        if pending_dir.is_dir():
            search_roots.append(pending_dir)
        new_pending = self._kb_root / "_pending"
        if new_pending.is_dir():
            for sub in new_pending.iterdir():
                if sub.is_dir():
                    search_roots.append(sub)

        for type_dir in search_roots:
            if not type_dir.is_dir():
                continue
            for md_file in sorted(type_dir.rglob("*.md")):
                if md_file.name.startswith("_"):
                    continue
                if _should_skip(md_file, self._kb_root):
                    continue
                try:
                    raw = md_file.read_text(encoding="utf-8")
                    post = frontmatter.loads(raw)
                    meta = post.metadata
                    if active_only:
                        entry_kb_status = str(meta.get("kb_status", "active"))
                        if entry_kb_status not in ("active", "pending"):
                            continue
                    if exclude_sub_entries:
                        if str(meta.get("type", "")) == "process" and meta.get("parent_id"):
                            continue
                    if kb_type and str(meta.get("type", "")) != kb_type:
                        continue
                    haystack = (
                        raw.lower()
                        + " "
                        + str(meta.get("title", "")).lower()
                        + " "
                        + " ".join(str(t) for t in meta.get("tags", [])).lower()
                    )
                    hits = sum(1 for term in terms if term in haystack)
                    if hits == 0:
                        continue

                    score = hits / len(terms)
                    snippet = _extract_snippet(post.content, terms)
                    entry_id_str = str(meta.get("id", md_file.stem))
                    led = date_index.get(entry_id_str)
                    results.append(
                        SearchResult(
                            entry_id=entry_id_str,
                            title=str(meta.get("title", md_file.stem)),
                            kb_type=str(meta.get("type", "")),
                            category=meta.get("category"),
                            maturity=str(meta.get("maturity", "draft")),
                            tags=list(meta.get("tags", [])),
                            snippet=snippet,
                            score=score,
                            file_path=str(md_file),
                            brief=str(meta.get("brief", "")),
                            last_evidence_date=led,
                        )
                    )
                except Exception:  # noqa: BLE001
                    pass

        results.sort(key=lambda r: (r.last_evidence_date or "", r.score), reverse=True)
        return results[:limit]


def _extract_snippet(body: str, terms: list[str], context: int = 100) -> str:
    """Extract a short snippet from body text around the first matched term."""
    body_lower = body.lower()
    for term in terms:
        idx = body_lower.find(term)
        if idx >= 0:
            start = max(0, idx - context // 2)
            end = min(len(body), idx + len(term) + context // 2)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(body) else ""
            return prefix + body[start:end].strip() + suffix
    return body[:context].strip() + ("..." if len(body) > context else "")


# ---------------------------------------------------------------------------
# LLM query expansion
# ---------------------------------------------------------------------------

_EXPAND_SYSTEM = (
    "You are a search query expander for a technical troubleshooting knowledge base. "
    "Given the user's search query, output 5-8 additional search terms: "
    "synonyms, translations (Chinese↔English), related technical terms, "
    "and common error messages. Output ONLY the terms, space-separated, no explanation."
)


def expand_query(query: str, provider: Any) -> str:
    """Expand a search query with LLM-generated synonyms and translations.

    Uses the existing chat LLM provider (no embedding model needed).
    Falls back to the original query on any error.

    Args:
        query: Original user search query.
        provider: LLMProvider instance with simple_complete().

    Returns:
        Expanded query string (original + LLM additions).
    """
    try:
        expansion = provider.simple_complete(
            messages=[{"role": "user", "content": query}],
            system=_EXPAND_SYSTEM,
            max_tokens=100,
        )
        if expansion and expansion.strip():
            return f"{query} {expansion.strip()}"
    except Exception:  # noqa: BLE001
        pass
    return query


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

# Module-level singleton for MCP server (long-lived process).
_bm25_cache: dict[str, BM25Backend] = {}


def get_bm25_backend(kb_root: Path) -> BM25Backend:
    """Get or create a cached BM25Backend for the given kb_root."""
    key = str(kb_root)
    if key not in _bm25_cache:
        _bm25_cache[key] = BM25Backend(kb_root)
    return _bm25_cache[key]


def search(
    kb_root: Path,
    query: str,
    limit: int = 5,
    backend: Optional[SearchBackend] = None,
    active_only: bool = True,
    exclude_sub_entries: bool = True,
    kb_type: Optional[str] = None,
) -> list[SearchResult]:
    """Module-level convenience function for KB search.

    Uses BM25Backend by default. Pass a custom backend for testing or
    to use LinearScanBackend.

    Args:
        kb_root: Root directory of the knowledge base.
        query: Search query string.
        limit: Maximum results to return.
        backend: Optional SearchBackend override.
        active_only: When True (default) only include kb_status "active" entries.
        exclude_sub_entries: When True (default) exclude process sub-entries.
        kb_type: Filter to a specific entry type (e.g. "pitfall").

    Returns:
        List of SearchResult objects.
    """
    if backend is None:
        backend = get_bm25_backend(kb_root)
    if isinstance(backend, (BM25Backend, LinearScanBackend)):
        return backend.search(
            query,
            limit=limit,
            active_only=active_only,
            exclude_sub_entries=exclude_sub_entries,
            kb_type=kb_type,
        )
    return backend.search(query, limit=limit)
