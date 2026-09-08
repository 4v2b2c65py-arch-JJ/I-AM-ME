"""ATC-1: Atomic Transaction Control.

Graph consistency under failure. A proposal must either complete fully or
leave no trace -- never a node with a missing parent link, advanced head, or
incomplete provenance.

    proposal
       ↓
    authorize
       ↓
    create node
       ↓
    authenticate
       ↓
    link parent(s)
       ↓
    advance head

A crash mid-flight must roll back to the prior consistent snapshot.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import canonical_hash
from .lgc import LineageGraph, LineageNode, NodeStatus


class TxStatus(Enum):
    PENDING = "pending"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class Snapshot:
    """An immutable point-in-time view of the lineage graph."""

    nodes: Dict[str, LineageNode]
    children: Dict[str, List[str]]
    heads: Set[str]
    root: Optional[str]
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {h: n.to_dict() for h, n in self.nodes.items()},
            "children": {k: list(v) for k, v in self.children.items()},
            "heads": list(self.heads),
            "root": self.root,
            "captured_at": self.captured_at,
        }


@dataclass
class TxRecord:
    """A recorded transaction attempt."""

    tx_id: str
    status: TxStatus
    snapshot_before: Snapshot
    snapshot_after: Optional[Snapshot]
    node_hashes: List[str]
    reason: str = ""
    provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "status": self.status.value,
            "node_hashes": list(self.node_hashes),
            "reason": self.reason,
            "provenance": list(self.provenance),
        }


class AtomicTransaction:
    """Executes a graph mutation atomically with snapshot/rollback."""

    def __init__(self, graph: LineageGraph) -> None:
        self.graph = graph
        self._history: List[TxRecord] = []

    def snapshot(self) -> Snapshot:
        return Snapshot(
            nodes={h: copy.deepcopy(n) for h, n in self.graph._nodes.items()},
            children={k: list(v) for k, v in self.graph._children.items()},
            heads=set(self.graph._heads),
            root=self.graph._root,
        )

    def _restore(self, snap: Snapshot) -> None:
        self.graph._nodes = {h: copy.deepcopy(n) for h, n in snap.nodes.items()}
        self.graph._children = {k: list(v) for k, v in snap.children.items()}
        self.graph._heads = set(snap.heads)
        self.graph._root = snap.root

    def run(self, mutate, *, tx_id: str = "", reason_on_fail: str = "") -> Tuple[TxStatus, List[str], str]:
        before = self.snapshot()
        created: List[str] = []
        provenance: List[str] = [f"atc:tx={tx_id or 'auto'}"]
        try:
            created = mutate(self.graph, created, provenance)
            after = self.snapshot()
            rec = TxRecord(
                tx_id=tx_id or f"tx-{len(self._history)}",
                status=TxStatus.COMMITTED,
                snapshot_before=before,
                snapshot_after=after,
                node_hashes=list(created),
                provenance=provenance,
            )
            self._history.append(rec)
            return TxStatus.COMMITTED, created, "committed"
        except Exception as exc:  # noqa: BLE001
            self._restore(before)
            rec = TxRecord(
                tx_id=tx_id or f"tx-{len(self._history)}",
                status=TxStatus.ROLLED_BACK,
                snapshot_before=before,
                snapshot_after=None,
                node_hashes=list(created),
                reason=reason_on_fail or str(exc),
                provenance=provenance + [f"atc:rolled_back {exc}"],
            )
            self._history.append(rec)
            return TxStatus.ROLLED_BACK, [], str(exc)

    def history(self) -> List[TxRecord]:
        return list(self._history)

    def committed(self) -> List[TxRecord]:
        return [r for r in self._history if r.status is TxStatus.COMMITTED]

    def rolled_back(self) -> List[TxRecord]:
        return [r for r in self._history if r.status is TxStatus.ROLLED_BACK]


def verify_graph_consistent(graph: LineageGraph) -> Tuple[bool, List[str]]:
    """Check every node's parent link resolves and heads are well-formed."""
    problems: List[str] = []
    for h, node in graph._nodes.items():
        if node.parent_hash is not None:
            if node.parent_hash not in graph._nodes:
                problems.append(f"node {h[:12]}... has missing parent {node.parent_hash[:12]}...")
    for h in graph._heads:
        if h not in graph._nodes:
            problems.append(f"head {h[:12]}... not in nodes")
    return (len(problems) == 0), problems


__all__ = [
    "TxStatus",
    "Snapshot",
    "TxRecord",
    "AtomicTransaction",
    "verify_graph_consistent",
]