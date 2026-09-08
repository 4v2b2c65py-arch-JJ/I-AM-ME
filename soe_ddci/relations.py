"""Relationship mechanism.

Every relationship becomes a directed, weighted graph edge between entities.
"""

from __future__ import annotations

import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class RelationType(Enum):
    CAUSAL = "causal"
    ASSOCIATIVE = "associative"
    HIERARCHICAL = "hierarchical"
    CONTRADICTORY = "contradictory"
    SUPPORTIVE = "supportive"
    DEPENDENT = "dependent"


@dataclass
class Relation:
    """A single graph edge in the relationship graph."""

    relation_id: str
    source: str
    target: str
    type: RelationType
    weight: float = 0.5        # strength of the edge
    confidence: float = 1.0    # how certain we are of the relation
    created_at: float = field(default_factory=time.time)
    last_verified: float = field(default_factory=time.time)
    metadata: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (-1.0 <= self.weight <= 1.0):
            raise ValueError("weight must be in [-1.0, 1.0]")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")

    def verify(self) -> None:
        self.last_verified = time.time()

    def to_dict(self) -> Dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "weight": self.weight,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_verified": self.last_verified,
        }


class RelationGraph:
    """Directed weighted graph of entity relationships."""

    def __init__(self) -> None:
        self._edges: Dict[str, Relation] = {}
        self._adj: Dict[str, Set[str]] = {}     # source -> {targets}
        self._rev: Dict[str, Set[str]] = {}     # target -> {sources}

    def add(self, relation: Relation) -> None:
        self._edges[relation.relation_id] = relation
        self._adj.setdefault(relation.source, set()).add(relation.target)
        self._rev.setdefault(relation.target, set()).add(relation.source)

    def connect(
        self,
        source: str,
        target: str,
        type: RelationType = RelationType.ASSOCIATIVE,
        weight: float = 0.5,
        confidence: float = 1.0,
        relation_id: Optional[str] = None,
    ) -> Relation:
        rel = Relation(
            relation_id=relation_id or str(uuid.uuid4()),
            source=source,
            target=target,
            type=type,
            weight=weight,
            confidence=confidence,
        )
        self.add(rel)
        return rel

    def get(self, relation_id: str) -> Optional[Relation]:
        return self._edges.get(relation_id)

    def outgoing(self, entity: str) -> List[Relation]:
        return [
            self._edges[e]
            for e in self._edges
            if self._edges[e].source == entity
        ]

    def incoming(self, entity: str) -> List[Relation]:
        return [
            self._edges[e]
            for e in self._edges
            if self._edges[e].target == entity
        ]

    def neighbors(self, entity: str) -> Set[str]:
        return self._adj.get(entity, set()) | self._rev.get(entity, set())

    def relation_count(self, entity: Optional[str] = None) -> int:
        if entity is None:
            return len(self._edges)
        return len(self.outgoing(entity)) + len(self.incoming(entity))

    def density(self, entities: Optional[Set[str]] = None) -> float:
        if entities is None:
            entities = set(self._adj) | set(self._rev)
        n = len(entities)
        if n <= 1:
            return 0.0
        max_edges = n * (n - 1)
        return len(self._edges) / max_edges if max_edges else 0.0

    def find_contradictions(self) -> List[Tuple[str, str]]:
        """Return pairs of entities linked by contradictory relations."""
        pairs: List[Tuple[str, str]] = []
        for rel in self._edges.values():
            if rel.type == RelationType.CONTRADICTORY:
                pairs.append((rel.source, rel.target))
        return pairs

    def all_relations(self) -> List[Relation]:
        return list(self._edges.values())