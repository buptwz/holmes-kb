"""KB read tools for the Holmes Agent.

Three tools implementing progressive disclosure:
1. kb_read_overview   — reads KB README.md (50-line summary)
2. kb_read_category_index — reads a category _index.md
3. kb_read_entry      — reads a full entry by ID
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from holmes.agent.tools.base import BaseTool, ToolResult
from holmes.kb.store import get_entry, list_entries
from holmes.logging_config import get_logger


logger = get_logger("tools.kb_read")


class KbReadOverviewTool(BaseTool):
    """Read the KB overview README — entry point for knowledge discovery."""

    name = "kb_read_overview"
    description = (
        "Read the knowledge base overview README. Use this first to understand what "
        "knowledge is available before narrowing down to specific categories or entries. "
        "Returns the README.md content and a summary of available categories."
    )
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    requires_confirmation = False

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root

    async def execute(self, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        readme = self._kb_root / "README.md"
        index_json = self._kb_root / "index.json"
        parts: list[str] = []

        if readme.exists():
            parts.append(readme.read_text(encoding="utf-8"))
        else:
            parts.append("# Knowledge Base\n\n(No README.md found)")

        if index_json.exists():
            import json

            data = json.loads(index_json.read_text(encoding="utf-8"))
            total = data.get("total_entries", 0)
            cats = data.get("categories", {})
            summary_lines = [f"\n## Index Summary\n\nTotal entries: {total}\n"]
            for cat, info in cats.items():
                count = info.get("count", 0)
                summary_lines.append(f"- **{cat}**: {count} entries")
            parts.append("\n".join(summary_lines))

        return ToolResult("\n\n".join(parts))


class KbReadCategoryIndexTool(BaseTool):
    """Read a KB category index to see all entries in that category."""

    name = "kb_read_category_index"
    description = (
        "Read the index of a specific knowledge category. Returns a table of all entries "
        "in that category with ID, title, maturity, and tags. "
        "Use this after kb_read_overview to browse a specific category."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Knowledge category to browse. One of: pitfall, model, guideline, "
                    "process, decision. For pitfall subcategories use 'pitfall/network', "
                    "'pitfall/system', 'pitfall/application', 'pitfall/database'."
                ),
            }
        },
        "required": ["category"],
    }
    requires_confirmation = False

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root

    async def execute(self, category: str, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        # Support both "pitfall" and "pitfall/network" notation
        parts = category.strip("/").split("/", 1)
        kb_type = parts[0]
        subcat = parts[1] if len(parts) > 1 else None

        index_path = self._kb_root / kb_type / "_index.md"
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")
            if subcat:
                # Filter by subcategory — read full index then filter
                entries = list_entries(self._kb_root, kb_type)  # type: ignore[arg-type]
                filtered = [e for e in entries if e.category == subcat]
                if not filtered:
                    return ToolResult(f"No entries found in {category}.")
                rows = "\n".join(
                    f"| {e.id} | {e.title} | {e.maturity} | {', '.join(e.tags)} |"
                    for e in filtered
                )
                header = f"# {category} Entries\n\n| ID | Title | Maturity | Tags |\n|----|-------|----------|------|\n"
                return ToolResult(header + rows)
            return ToolResult(content)

        return ToolResult(f"Category '{category}' not found in knowledge base.")


class KbReadEntryTool(BaseTool):
    """Read the full content of a specific KB entry by ID."""

    name = "kb_read_entry"
    description = (
        "Read the complete content of a knowledge entry by its ID. "
        "Use this after identifying the relevant entry ID from kb_read_category_index. "
        "Returns the full Markdown content including all sections."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "entry_id": {
                "type": "string",
                "description": "The knowledge entry ID (e.g. 'PT-DB-001', 'MD-SVC-003').",
            }
        },
        "required": ["entry_id"],
    }
    requires_confirmation = False

    def __init__(self, kb_root: Path) -> None:
        self._kb_root = kb_root

    async def execute(self, entry_id: str, **kwargs: Any) -> ToolResult:  # noqa: ARG002
        entry = get_entry(self._kb_root, entry_id)
        if entry is None:
            return ToolResult(f"Entry '{entry_id}' not found in knowledge base.", is_error=True)
        content = entry.to_frontmatter_str()
        return ToolResult(content)


def create_kb_read_tools(kb_root: Path) -> list[BaseTool]:
    """Create all three KB read tools bound to a specific KB root.

    Args:
        kb_root: Root directory of the knowledge base.

    Returns:
        List of instantiated KB read tools.
    """
    return [
        KbReadOverviewTool(kb_root),
        KbReadCategoryIndexTool(kb_root),
        KbReadEntryTool(kb_root),
    ]
