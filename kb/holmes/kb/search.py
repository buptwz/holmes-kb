"""Knowledge base search — SearchBackend abstraction with linear scan implementation.

The SearchBackend interface is designed for extensibility. The current
LinearScanBackend reads all .md files and matches keywords in O(n) time,
which is sufficient for knowledge bases up to ~1000 entries at <200ms.

Future index-backed backends can be added by implementing SearchBackend.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
    """Scan all evidence sidecar directories once and return {entry_id: max_date}.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        Dict mapping entry_id to the most recent evidence date string (ISO8601),
        or empty dict if the sidecar directory does not exist.
    """
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
    ) -> list[SearchResult]:
        """Scan all KB entries for query terms and return ranked results.

        Args:
            query: Space-separated keywords.
            limit: Maximum results.
            active_only: When True (default) only include entries with kb_status "active"
                (or legacy entries with no kb_status field).  Pass False to include all.
            exclude_sub_entries: When True (default) filter out process entries that have
                a parent_id set.  Pass False to include sub-entries in results.

        Returns:
            Up to limit SearchResult objects ordered by score (descending).
        """
        terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return []

        results: list[SearchResult] = []
        date_index = _build_evidence_date_index(self._kb_root)
        search_roots = [
            self._kb_root / t
            for t in ("pitfall", "model", "guideline", "process", "decision")
        ]
        # Include pending entries so agents can find recently imported knowledge.
        pending_dir = self._kb_root / "contributions" / "pending"
        if pending_dir.is_dir():
            search_roots.append(pending_dir)

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
                    # M1: kb_status filter — legacy entries without the field default to "active".
                    if active_only:
                        entry_kb_status = str(meta.get("kb_status", "active"))
                        if entry_kb_status != "active":
                            continue
                    # M1: exclude process sub-entries (type=process AND parent_id set).
                    if exclude_sub_entries:
                        if str(meta.get("type", "")) == "process" and meta.get("parent_id"):
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
                            last_evidence_date=led,
                        )
                    )
                except Exception:  # noqa: BLE001
                    pass

        # P0-3: primary sort by evidence freshness (DESC), secondary by keyword score (DESC).
        # Entries with no evidence sort as "" which is lexicographically before all ISO dates.
        results.sort(key=lambda r: (r.last_evidence_date or "", r.score), reverse=True)
        return results[:limit]


def _extract_snippet(body: str, terms: list[str], context: int = 100) -> str:
    """Extract a short snippet from body text around the first matched term.

    Args:
        body: Markdown body text.
        terms: Lowercase search terms.
        context: Characters of context around the hit.

    Returns:
        Short snippet string with leading/trailing ellipsis as needed.
    """
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


def search(
    kb_root: Path,
    query: str,
    limit: int = 5,
    backend: Optional[SearchBackend] = None,
    active_only: bool = True,
    exclude_sub_entries: bool = True,
) -> list[SearchResult]:
    """Module-level convenience function for KB search.

    Uses LinearScanBackend by default. Pass a custom backend for testing or
    future index-backed implementations.

    Args:
        kb_root: Root directory of the knowledge base.
        query: Search query string.
        limit: Maximum results to return.
        backend: Optional SearchBackend override.
        active_only: When True (default) only include kb_status "active" entries.
        exclude_sub_entries: When True (default) exclude process sub-entries.

    Returns:
        List of SearchResult objects.
    """
    if backend is None:
        backend = LinearScanBackend(kb_root)
    if isinstance(backend, LinearScanBackend):
        return backend.search(
            query,
            limit=limit,
            active_only=active_only,
            exclude_sub_entries=exclude_sub_entries,
        )
    return backend.search(query, limit=limit)
