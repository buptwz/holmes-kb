"""DAG schema dataclasses for Agent 1 extraction output.

Defines the internal data model for a troubleshooting DAG extracted from
a pitfall document.  All entities are plain dataclasses with no external
dependencies, so they can be freely imported by any module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NodeType(str, Enum):
    """Semantic type of a DAG node — drives behavior tags in KB entries.

    5 types (original 'action' split into remote_action + physical_action):
      - human_observation: must be done by human on-site (eyes/ears/hands)
      - api_call: remote command/API to retrieve information (read-only)
      - remote_action: remote command/API to change system state
      - physical_action: physical manipulation of hardware
      - decision: choose branch based on prior results
    """

    human_observation = "human_observation"
    api_call = "api_call"
    remote_action = "remote_action"
    physical_action = "physical_action"
    decision = "decision"


class Complexity(str, Enum):
    """Node complexity — determines whether an independent KB entry is created."""

    simple = "simple"    # 1-2 steps, inline in parent entry Resolution
    process = "process"  # complex steps, generates an independent process entry


# ---------------------------------------------------------------------------
# Core graph entities
# ---------------------------------------------------------------------------


@dataclass
class DAGEdge:
    """Directed edge from a parent node to a target node.

    Attributes:
        condition: Trigger condition text (e.g., "红色闪烁").
        target: Target node ID (e.g., "N3").
        is_back_edge: True for cycle-breaking markers.  Back-edges are excluded
                      from cycle detection and structural routing.
    """

    condition: str
    target: str
    is_back_edge: bool = False


@dataclass
class DAGNode:
    """Single node in the troubleshooting tree.

    Attributes:
        id: Node identifier (e.g., "N1", "N7").
        description: One-sentence description.
        node_type: Semantic type hint (human_observation/api_call/remote_action/physical_action/decision).
        complexity: simple (inline) or process (independent KB entry).
        section_heading: Source document heading for Agent 2 to locate content.
        line_range: Source document line range [start, end] for Agent 2 to locate content.
        is_end: True for terminal END nodes (no outgoing edges allowed).
        children: Outgoing edges (empty for END nodes).
    """

    id: str
    description: str
    node_type: NodeType
    complexity: Complexity
    section_heading: Optional[str] = None
    line_range: Optional[tuple[int, int]] = None
    is_end: bool = False
    children: list[DAGEdge] = field(default_factory=list)


@dataclass
class DAGGraph:
    """Complete troubleshooting DAG extracted from one source document.

    Attributes:
        nodes: All nodes in the graph.
        title: Human-readable title (e.g., "硬件初始化失败").
        source_file: Relative path of the source document (for display).
        generated: ISO date string (YYYY-MM-DD).
    """

    nodes: list[DAGNode]
    title: str
    source_file: str
    generated: str

    def node_by_id(self, node_id: str) -> Optional[DAGNode]:
        """Return the node with the given ID, or None."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def root_nodes(self) -> list[DAGNode]:
        """Return nodes that have no incoming edges (roots of the tree)."""
        referenced: set[str] = set()
        for n in self.nodes:
            for edge in n.children:
                if not edge.is_back_edge:
                    referenced.add(edge.target)
        return [n for n in self.nodes if n.id not in referenced]


# ---------------------------------------------------------------------------
# Crash recovery snapshot
# ---------------------------------------------------------------------------


@dataclass
class Agent1Session:
    """Crash recovery snapshot written every 20 LLM turns.

    Attributes:
        source_hash: 16-char SHA-256 prefix of the source document.
        turn_count: Number of LLM turns completed at snapshot time.
        messages: Complete message history in provider wire format.
        source_file: Optional relative path for display in --resume selection.
    """

    source_hash: str
    turn_count: int
    messages: list[Any]
    source_file: str = ""
