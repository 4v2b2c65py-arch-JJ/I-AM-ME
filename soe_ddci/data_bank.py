"""Artificial Data Bank layer.

Splits history into independent memory domains instead of one giant blob.

D1 ENTITY DATA    - identity, attributes, current state
D2 EVENT DATA     - timestamp, action, result
D3 RELATION DATA  - entity -> entity, strength, direction
D4 HISTORY DATA   - session events, previous context, transformations
D5 KNOWLEDGE DATA - facts, confidence, source
D6 OBJECTIVE DATA - goal, constraints, success metric
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DataDomain(Enum):
    """The six independent memory domains."""

    ENTITY = "D1"
    EVENT = "D2"
    RELATION = "D3"
    HISTORY = "D4"
    KNOWLEDGE = "D5"
    OBJECTIVE = "D6"

    @property
    def label(self) -> str:
        return {
            DataDomain.ENTITY: "ENTITY DATA",
            DataDomain.EVENT: "EVENT DATA",
            DataDomain.RELATION: "RELATION DATA",
            DataDomain.HISTORY: "HISTORY DATA",
            DataDomain.KNOWLEDGE: "KNOWLEDGE DATA",
            DataDomain.OBJECTIVE: "OBJECTIVE DATA",
        }[self]


@dataclass
class DataRecord:
    """A single record stored in one domain of the data bank."""

    domain: DataDomain
    record_id: str
    timestamp: float
    payload: Dict[str, Any]
    # optional provenance / embedding metadata
    confidence: float = 1.0
    source: str = "local"
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "confidence": self.confidence,
            "source": self.source,
        }


class DataBank:
    """Persistent, domain-partitioned store for all entity data."""

    def __init__(self, bank_id: Optional[str] = None) -> None:
        self.bank_id: str = bank_id or str(uuid.uuid4())
        self._domains: Dict[DataDomain, List[DataRecord]] = {
            d: [] for d in DataDomain
        }
        self._index: Dict[str, DataRecord] = {}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def store(
        self,
        domain: DataDomain,
        payload: Dict[str, Any],
        *,
        confidence: float = 1.0,
        source: str = "local",
        embedding: Optional[List[float]] = None,
        record_id: Optional[str] = None,
    ) -> DataRecord:
        rec = DataRecord(
            domain=domain,
            record_id=record_id or str(uuid.uuid4()),
            timestamp=time.time(),
            payload=payload,
            confidence=confidence,
            source=source,
            embedding=embedding,
        )
        self._domains[domain].append(rec)
        self._index[rec.record_id] = rec
        return rec

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def query(
        self,
        domain: Optional[DataDomain] = None,
        *,
        limit: Optional[int] = None,
        since: Optional[float] = None,
    ) -> List[DataRecord]:
        if domain is not None:
            pool = list(self._domains[domain])
        else:
            pool = [r for recs in self._domains.values() for r in recs]
        if since is not None:
            pool = [r for r in pool if r.timestamp >= since]
        pool.sort(key=lambda r: r.timestamp)
        if limit is not None:
            pool = pool[-limit:]
        return pool

    def get(self, record_id: str) -> Optional[DataRecord]:
        return self._index.get(record_id)

    def recent(self, n: int = 10) -> List[DataRecord]:
        return self.query(limit=n)

    def all(self) -> List[DataRecord]:
        return self.query()

    # ------------------------------------------------------------------
    # Domain convenience accessors
    # ------------------------------------------------------------------
    @property
    def entity_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.ENTITY]

    @property
    def event_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.EVENT]

    @property
    def relation_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.RELATION]

    @property
    def history_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.HISTORY]

    @property
    def knowledge_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.KNOWLEDGE]

    @property
    def objective_data(self) -> List[DataRecord]:
        return self._domains[DataDomain.OBJECTIVE]

    def __len__(self) -> int:
        return sum(len(v) for v in self._domains.values())

    def summary(self) -> Dict[str, int]:
        return {d.value: len(v) for d, v in self._domains.items()}