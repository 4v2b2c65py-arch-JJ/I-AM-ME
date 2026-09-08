"""Context reconstruction engine.

Reconstructs the relevant context for a new session by retrieving
relevant records from the persistent data bank and the event log.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .data_bank import DataBank, DataRecord, DataDomain
from .history import EventLog, Event
from .relations import RelationGraph
from .states import State


@dataclass
class ContextSnapshot:
    """A reconstructed context for a session."""

    session_id: str
    entity_id: str
    current_state: State
    recent_events: List[Event]
    relevant_records: List[DataRecord]
    active_relations: List[object]
    objective: Dict[str, object]
    confidence: float
    retrieval_relevance: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "session_id": self.session_id,
            "entity_id": self.entity_id,
            "current_state": self.current_state.value,
            "recent_events": [e.to_dict() for e in self.recent_events],
            "relevant_records": [r.to_dict() for r in self.relevant_records],
            "objective": self.objective,
            "confidence": self.confidence,
            "retrieval_relevance": self.retrieval_relevance,
        }


class ContextEngine:
    """Reconstructs context for a new session from persistent stores."""

    def __init__(
        self,
        data_bank: DataBank,
        event_log: EventLog,
        relation_graph: RelationGraph,
    ) -> None:
        self.data_bank = data_bank
        self.event_log = event_log
        self.relation_graph = relation_graph

    def reconstruct(
        self,
        session_id: str,
        *,
        current_state: State = State.ACTIVE,
        objective: Optional[Dict[str, object]] = None,
        recency_weight: float = 0.6,
        keyword: Optional[str] = None,
    ) -> ContextSnapshot:
        recent_events = self.event_log.recent(20)

        # Retrieve relevant records: recent + keyword match
        relevant = self._retrieve(keyword=keyword)

        # Active relations: outgoing + incoming for the entity
        active_relations = self.relation_graph.all_relations()

        # Confidence derived from data integrity
        confidence = self._estimate_confidence(relevant)

        # Retrieval relevance: how much of the bank was surfaced
        total = len(self.data_bank)
        relevance = (len(relevant) / total) if total > 0 else 1.0

        return ContextSnapshot(
            session_id=session_id,
            entity_id=self.event_log.entity_id,
            current_state=current_state,
            recent_events=recent_events,
            relevant_records=relevant,
            active_relations=active_relations,
            objective=objective or {},
            confidence=confidence,
            retrieval_relevance=relevance,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _retrieve(self, keyword: Optional[str] = None) -> List[DataRecord]:
        """Selective history retrieval: recency + keyword filtering."""
        all_records = self.data_bank.recent(50)
        if keyword is None:
            return all_records
        kw = keyword.lower()
        scored: List[Tuple[float, DataRecord]] = []
        for rec in all_records:
            hay = " ".join(
                str(v) for v in rec.payload.values()
            ).lower()
            score = 1.0 if kw in hay else 0.0
            scored.append((score, rec))
        return [r for s, r in scored if s > 0]

    def _estimate_confidence(self, records: List[DataRecord]) -> float:
        if not records:
            return 0.5
        avg = sum(r.confidence for r in records) / len(records)
        # recency bonus: newer records raise confidence
        now = max((r.timestamp for r in records), default=0.0)
        recency = sum(1 for r in records if now - r.timestamp < 86400) / len(records)
        return round(min(1.0, 0.5 * avg + 0.5 * recency), 4)

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)