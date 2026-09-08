"""LGC-1: Lineage & Graph Control.

Concurrency boundary built on top of RWA-1's parent_state primitive.

    RWA-1
       |
authorized proposal
       |
       v
    LGC-1
       |
  ┌────┼────┐
  ▼    ▼    ▼
 HEAD  FORK JOIN
  │     │    │
  ▼     ▼    ▼
 S₁   S₂/S₃ merge

Every state has a cryptographic lineage reference. A write cannot erase
its parent. Multiple children of one parent constitute a detectable fork.
Conflicting descendants are detectable without inference.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import canonical_hash
from .rwa import Capability, Operation, WriteRequest, WriteResult


class NodeStatus(Enum):
    ACTIVE = "active"
    CONFLICT = "conflict"
    MERGED = "merged"
    ARCHIVED = "archived"


@dataclass
class LineageNode:
    """A node in the verifiable state graph."""

    state_hash: str
    parent_hash: Optional[str]
    formation_hash: str
    author: str
    operation_hash: str
    capability_id: str
    status: NodeStatus = NodeStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    provenance: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_hash": self.state_hash,
            "parent_hash": self.parent_hash,
            "formation_hash": self.formation_hash,
            "author": self.author,
            "operation_hash": self.operation_hash,
            "capability_id": self.capability_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "provenance": list(self.provenance),
        }


@dataclass
class ForkResult:
    """Outcome of a fork detection."""

    parent_hash: str
    children: List[LineageNode]
    is_fork: bool
    conflict_fields: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_hash": self.parent_hash,
            "children": [c.state_hash for c in self.children],
            "is_fork": self.is_fork,
            "conflict_fields": list(self.conflict_fields),
        }


@dataclass
class JoinRequest:
    """Explicit join of two or more lineage branches."""

    parents: List[str]
    merge_operation: str
    capability: Capability
    conflict_resolution: Dict[str, Any] = field(default_factory=dict)
    nonce: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parents": list(self.parents),
            "merge_operation": self.merge_operation,
            "capability_id": self.capability.capability_id,
            "conflict_resolution": dict(self.conflict_resolution),
        }


@dataclass
class JoinResult:
    """Outcome of a join attempt."""

    decision: str  # "committed" | "conflict" | "denied"
    merged_state_hash: Optional[str]
    contributing_parents: List[str]
    conflict_fields: List[str]
    reason: str = ""
    provenance: List[str] = field(default_factory=list)

    @property
    def committed(self) -> bool:
        return self.decision == "committed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "merged_state_hash": self.merged_state_hash,
            "contributing_parents": list(self.contributing_parents),
            "conflict_fields": list(self.conflict_fields),
            "reason": self.reason,
            "provenance": list(self.provenance),
        }


__all__ = [
    "NodeStatus",
    "LineageNode",
    "ForkResult",
    "JoinRequest",
    "JoinResult",
    "LineageGraph",
]


class LineageGraph:
    """Verifiable state graph with fork detection and explicit joins."""

    def __init__(self) -> None:
        self._nodes: Dict[str, LineageNode] = {}
        self._children: Dict[str, List[str]] = {}
        self._heads: Set[str] = set()
        self._root: Optional[str] = None

    def add_root(self, state_hash: str, formation_hash: str = "", author: str = "system") -> LineageNode:
        node = LineageNode(
            state_hash=state_hash,
            parent_hash=None,
            formation_hash=formation_hash,
            author=author,
            operation_hash=canonical_hash({"op": "root", "state": state_hash}),
            capability_id="root",
            provenance=["lgc:root"],
        )
        self._nodes[state_hash] = node
        self._heads.add(state_hash)
        self._root = state_hash
        return node

    def propose(self, parent_hash: str, mutation: Dict[str, Any], *, author: str, capability_id: str, formation_hash: str = "") -> Optional[LineageNode]:
        if parent_hash not in self._nodes:
            return None
        new_hash = canonical_hash(mutation)
        if new_hash in self._nodes:
            return self._nodes[new_hash]
        node = LineageNode(
            state_hash=new_hash,
            parent_hash=parent_hash,
            formation_hash=formation_hash,
            author=author,
            operation_hash=canonical_hash({"op": "propose", "parent": parent_hash, "mutation": mutation}),
            capability_id=capability_id,
            provenance=[f"lgc:parent={parent_hash[:12]}..."],
        )
        self._nodes[new_hash] = node
        self._children.setdefault(parent_hash, []).append(new_hash)
        self._heads.discard(parent_hash)
        self._heads.add(new_hash)
        return node

    def children_of(self, parent_hash: str) -> List[LineageNode]:
        return [self._nodes[h] for h in self._children.get(parent_hash, []) if h in self._nodes]

    def detect_fork(self, parent_hash: str) -> ForkResult:
        kids = self.children_of(parent_hash)
        conflict_fields: List[str] = []
        is_fork = len(kids) > 1
        if is_fork:
            seen: Dict[str, Set[str]] = {}
            for k in kids:
                for f in k.provenance:
                    seen.setdefault(f, set()).add(k.state_hash)
            conflict_fields = sorted({f for f, owners in seen.items() if len(owners) > 1})
        return ForkResult(
            parent_hash=parent_hash,
            children=kids,
            is_fork=is_fork,
            conflict_fields=conflict_fields,
        )

    def join(self, request: JoinRequest) -> JoinResult:
        parents = list(request.parents)
        provenance = [f"lgc:join parents={len(parents)}"]
        for ph in parents:
            if ph not in self._nodes:
                return JoinResult(
                    decision="denied",
                    merged_state_hash=None,
                    contributing_parents=[],
                    conflict_fields=[],
                    reason="unknown parent in join",
                    provenance=provenance,
                )
        nodes = [self._nodes[ph] for ph in parents]
        # Detect conflicting descendants without inference
        conflict_fields: List[str] = []
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                if a.state_hash == b.state_hash:
                    continue
                fork_a = self.detect_fork(a.parent_hash) if a.parent_hash else ForkResult("", [], False, [])
                fork_b = self.detect_fork(b.parent_hash) if b.parent_hash else ForkResult("", [], False, [])
                conflict_fields.extend(fork_a.conflict_fields)
                conflict_fields.extend(fork_b.conflict_fields)
        conflict_fields = sorted(set(conflict_fields))
        if conflict_fields and not request.conflict_resolution:
            return JoinResult(
                decision="conflict",
                merged_state_hash=None,
                contributing_parents=[n.state_hash for n in nodes],
                conflict_fields=conflict_fields,
                reason="conflicting descendants; explicit resolution required",
                provenance=provenance,
            )
        merged = dict(request.conflict_resolution)
        for ph in parents:
            merged.setdefault(f"parent:{ph[:12]}...", self._nodes[ph].state_hash)
        merged_hash = canonical_hash(merged)
        node = LineageNode(
            state_hash=merged_hash,
            parent_hash=None,
            formation_hash="",
            author=request.capability.subject,
            operation_hash=canonical_hash({"op": "join", "parents": parents, "resolution": merged}),
            capability_id=request.capability.capability_id,
            status=NodeStatus.MERGED,
            provenance=provenance + [f"lgc:merged={merged_hash[:12]}..."],
        )
        self._nodes[merged_hash] = node
        for ph in parents:
            self._heads.discard(ph)
        self._heads.add(merged_hash)
        return JoinResult(
            decision="committed",
            merged_state_hash=merged_hash,
            contributing_parents=[n.state_hash for n in nodes],
            conflict_fields=conflict_fields,
            reason="joined with explicit resolution",
            provenance=provenance + [f"lgc:merged={merged_hash[:12]}..."],
        )

    def heads(self) -> List[LineageNode]:
        return [self._nodes[h] for h in self._heads if h in self._nodes]

    def get(self, state_hash: str) -> Optional[LineageNode]:
        return self._nodes.get(state_hash)

    def lineage(self, state_hash: str) -> List[LineageNode]:
        chain: List[LineageNode] = []
        cur = state_hash
        seen: Set[str] = set()
        while cur and cur in self._nodes and cur not in seen:
            seen.add(cur)
            node = self._nodes[cur]
            chain.append(node)
            cur = node.parent_hash
        chain.reverse()
        return chain

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        cur = descendant
        seen: Set[str] = set()
        while cur and cur in self._nodes and cur not in seen:
            seen.add(cur)
            if cur == ancestor:
                return True
            cur = self._nodes[cur].parent_hash
        return False

    def verify_lineage(self, state_hash: str) -> bool:
        node = self._nodes.get(state_hash)
        if node is None:
            return False
        if node.parent_hash is None:
            return True
        parent = self._nodes.get(node.parent_hash)
        return parent is not None


