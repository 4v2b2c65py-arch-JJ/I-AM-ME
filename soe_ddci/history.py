"""Cross-session history mechanism.

SESSION != MEMORY
CHAT    != DATABASE
CONTEXT != PERMANENT STORAGE

An event log captures every meaningful occurrence so that a later session
can reconstruct context by retrieving relevant records.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(Enum):
    CREATED = "created"
    ACTIVATED = "activated"
    OBSERVED = "observed"
    RELATED = "related"
    STORED = "stored"
    RETRIEVED = "retrieved"
    TRANSFORMED = "transformed"
    ARCHIVED = "archived"
    INVALIDATED = "invalidated"
    RELATION_ADDED = "relation_added"
    MEMORY_WRITTEN = "memory_written"
    CONTEXT_RECONSTRUCTED = "context_reconstructed"
    DECISION_MADE = "decision_made"


@dataclass
class Event:
    """A single recorded event in the entity's history."""

    event_id: str
    session_id: str
    timestamp: float
    type: EventType
    entity_id: str
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    action: str = ""
    result: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "type": self.type.value,
            "entity_id": self.entity_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "action": self.action,
            "result": self.result,
            "payload": self.payload,
            "confidence": self.confidence,
        }


class EventLog:
    """Append-only log of all events across sessions."""

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self._events: List[Event] = []

    def append(
        self,
        type: EventType,
        session_id: str,
        *,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        action: str = "",
        result: str = "",
        payload: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
    ) -> Event:
        ev = Event(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            timestamp=time.time(),
            type=type,
            entity_id=self.entity_id,
            from_state=from_state,
            to_state=to_state,
            action=action,
            result=result,
            payload=payload or {},
            confidence=confidence,
        )
        self._events.append(ev)
        return ev

    def all(self) -> List[Event]:
        return list(self._events)

    def since_session(self, session_id: str) -> List[Event]:
        return [e for e in self._events if e.session_id == session_id]

    def since(self, timestamp: float) -> List[Event]:
        return [e for e in self._events if e.timestamp >= timestamp]

    def of_type(self, type: EventType) -> List[Event]:
        return [e for e in self._events if e.type == type]

    def transitions(self) -> List[Event]:
        return [e for e in self._events if e.from_state and e.to_state]

    def __len__(self) -> int:
        return len(self._events)

    def recent(self, n: int = 10) -> List[Event]:
        return self._events[-n:]

    def sessions(self) -> List[str]:
        seen: List[str] = []
        for e in self._events:
            if e.session_id not in seen:
                seen.append(e.session_id)
        return seen

    def history_depth(self) -> int:
        return len(self._events)