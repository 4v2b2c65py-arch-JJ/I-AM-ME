"""Single Objective Entity core.

The central implementation: one entity, one objective, many states,
many data records, many relationships, selective history retrieval.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .data_bank import DataBank, DataDomain
from .history import EventLog, EventType
from .relations import RelationGraph, Relation, RelationType
from .states import State


@dataclass
class EntityConfig:
    """Configuration for a new entity."""

    entity_id: Optional[str] = None
    objective_type: str = "single"
    objective_target: str = ""
    objective_priority: float = 1.0
    initial_state: State = State.CREATED
    constraints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_objective(self) -> Dict[str, Any]:
        return {
            "type": self.objective_type,
            "target": self.objective_target,
            "priority": self.objective_priority,
        }


class Entity:
    """A Single Objective Entity (SOE)."""

    def __init__(self, config: Optional[EntityConfig] = None) -> None:
        cfg = config or EntityConfig()
        self.entity_id: str = cfg.entity_id or str(uuid.uuid4())
        self.objective: Dict[str, Any] = cfg.to_objective()
        self.constraints: List[str] = list(cfg.constraints)
        self.metadata: Dict[str, Any] = dict(cfg.metadata)

        self.state: State = cfg.initial_state
        self.data_bank = DataBank(bank_id=self.entity_id)
        self.event_log = EventLog(self.entity_id)
        self.relation_graph = RelationGraph()

        # Seed initial entity data record
        self.data_bank.store(
            DataDomain.ENTITY,
            {
                "identity": self.entity_id,
                "attributes": {},
                "current_state": self.state.value,
            },
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def transition_to(self, new_state: State, *, action: str = "", result: str = "") -> bool:
        """Attempt a state transition. Returns True on success."""
        from .states import VALID_TRANSITIONS
        if (self.state, new_state) not in VALID_TRANSITIONS:
            return False
        old = self.state
        self.state = new_state
        self.event_log.append(
            EventType.TRANSFORMED if new_state is State.TRANSFORMED
            else EventType.CREATED if new_state is State.CREATED
            else EventType.ARCHIVED if new_state is State.ARCHIVED
            else EventType.INVALIDATED if new_state is State.INVALID
            else EventType.ACTIVATED if new_state is State.ACTIVE
            else EventType.STORED if new_state is State.STORED
            else EventType.RETRIEVED if new_state is State.RETRIEVED
            else EventType.OBSERVED if new_state is State.OBSERVED
            else EventType.RELATION_ADDED if new_state is State.RELATED
            else EventType.CONTEXT_RECONSTRUCTED,
            session_id=self.metadata.get("session_id", "bootstrap"),
            from_state=old.value,
            to_state=new_state.value,
            action=action or f"transition_to_{new_state.value.lower()}",
            result=result or f"{old.value} -> {new_state.value}",
        )
        # Keep entity domain current
        self.data_bank.store(
            DataDomain.ENTITY,
            {"identity": self.entity_id, "current_state": self.state.value},
        )
        return True

    # ------------------------------------------------------------------
    # Memory / data bank
    # ------------------------------------------------------------------
    def remember(self, domain: DataDomain, payload: Dict[str, Any], **kw) -> object:
        rec = self.data_bank.store(domain, payload, **kw)
        self.event_log.append(
            EventType.MEMORY_WRITTEN,
            session_id=self.metadata.get("session_id", "bootstrap"),
            action=f"store_{domain.value}",
            result=f"record {rec.record_id}",
            payload={"record_id": rec.record_id, "domain": domain.value},
        )
        return rec

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------
    def relate_to(
        self,
        other: "Entity",
        type: RelationType = RelationType.ASSOCIATIVE,
        weight: float = 0.5,
        confidence: float = 1.0,
    ) -> Relation:
        rel = self.relation_graph.connect(
            self.entity_id, other.entity_id, type, weight, confidence
        )
        self.event_log.append(
            EventType.RELATION_ADDED,
            session_id=self.metadata.get("session_id", "bootstrap"),
            action="relate",
            result=f"{self.entity_id} -> {other.entity_id}",
            payload={"relation_id": rel.relation_id, "type": type.value},
        )
        return rel

    # ------------------------------------------------------------------
    # Vector profile
    # ------------------------------------------------------------------
    def vector(self) -> List[float]:
        """ENTITY VECTOR: measurable dimensions of the entity."""
        return [
            float(hash(self.entity_id) % 1000) / 1000.0,  # identity (stable proxy)
            float(self.state.value.__hash__() % 100) / 100.0,  # state
            float(self.objective.get("priority", 1.0)),  # objective priority
            self._confidence(),  # confidence
            self._relevance(),  # relevance
            self.relation_graph.density(),  # relation density
            min(1.0, len(self.event_log) / 100.0),  # history depth
            self._data_integrity(),  # data integrity
        ]

    def profile(self) -> Dict[str, float]:
        v = self.vector()
        names = [
            "identity",
            "state",
            "objective_priority",
            "state_confidence",
            "retrieval_relevance",
            "relation_density",
            "history_depth",
            "data_integrity",
        ]
        return {n: round(val, 4) for n, val in zip(names, v)}

    def _confidence(self) -> float:
        recs = self.data_bank.recent(20)
        if not recs:
            return 0.5
        return round(sum(r.confidence for r in recs) / len(recs), 4)

    def _relevance(self) -> float:
        total = len(self.data_bank)
        return round((len(self.data_bank.recent(10)) / total) if total else 1.0, 4)

    def _data_integrity(self) -> float:
        if not self.data_bank:
            return 1.0
        bad = sum(1 for r in self.data_bank.all() if r.confidence < 0.5)
        return round(1.0 - bad / len(self.data_bank), 4)

    def __repr__(self) -> str:
        return (
            f"Entity(id={self.entity_id}, state={self.state.value}, "
            f"objective={self.objective.get('target')})"
        )