"""RWA-1: Read/Write Authority.

Capability-based access boundary between the canonical/authenticity system
and persistence. Nobody writes directly to authoritative state.

    SOE-DDCI
        |
   RCS-0 -> UTT -> F4
        |
   Canonical Form
        |
   Integrity / HMAC
        |
        v
   RWA-1
   ├───────────────┐
   ▼               ▼
   READ           WRITE
   │               │
   ▼               ▼
   Snapshot     Capability
   │               │
   │            Parent hash
   │               │
   │            Transition
   │               │
   └───────┬───────┘
           v
      AUTHENTIC STATE
"""

from __future__ import annotations

import copy
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .canonical import canonical_bytes, canonical_hash


class Operation(Enum):
    READ = "read"
    WRITE = "write"


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class Capability:
    """Capability-based access token."""

    capability_id: str
    subject: str
    operation: Operation
    target: str
    scope: str = "*"
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    nonce: str = ""
    parent_state: str = ""
    authenticator: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.expires_at != 0.0 and time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "subject": self.subject,
            "operation": self.operation.value,
            "target": self.target,
            "scope": self.scope,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "parent_state": self.parent_state,
        }


class ReadWriteGate:
    """Enforces capability-authorized reads and writes.

    Nobody writes directly to authoritative state. Every write names its
    parent state; a stale parent cannot overwrite newer state.
    """

    def __init__(self, authenticator: Optional["Authenticator"] = None) -> None:
        # local import to avoid a cycle at module load
        from .authenticity import Authenticator
        self.authenticator = authenticator or Authenticator(b"rwa-default-key")
        self._state: Dict[str, str] = {}
        self._history: List[WriteResult] = []

    # ------------------------------------------------------------------
    # State hashing
    # ------------------------------------------------------------------
    @staticmethod
    def state_hash(payload: Dict[str, Any]) -> str:
        return canonical_hash(payload)

    def current_hash(self, target: str) -> str:
        return self._state.get(target, canonical_hash({}))

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------
    def read(self, capability: Capability, payload: Dict[str, Any]) -> ReadSnapshot:
        """Produce an immutable authenticated snapshot.

        READ(S) -> Snapshot(S), not a mutable reference to S.
        """
        target = capability.target
        state_hash = self.state_hash(payload)
        provenance = [
            f"rwa:read target={target}",
            f"rwa:capability={capability.capability_id}",
            f"rwa:state_hash={state_hash}",
        ]
        return ReadSnapshot(
            target=target,
            state_hash=state_hash,
            payload=copy.deepcopy(payload),
            capability_id=capability.capability_id,
            issued_at=capability.issued_at,
            provenance=provenance,
        )

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------
    def write(self, request: WriteRequest) -> WriteResult:
        """Capability-authorized transition with optimistic concurrency.

        Checks, in order:
          1. capability valid (not expired, operation == WRITE, target matches)
          2. target valid
          3. scope valid
          4. current state authentic
          5. expected parent hash matches
          6. transition permitted
          7. authorization valid
        """
        target = request.target
        cap = request.capability
        prev = self.current_hash(target)
        provenance: List[str] = [
            f"rwa:write target={target}",
            f"rwa:capability={cap.capability_id}",
            f"rwa:parent_state={request.parent_state}",
            f"rwa:previous_state={prev}",
        ]

        # 1. capability valid
        if cap.operation is not Operation.WRITE:
            return self._deny(target, prev, cap, "capability operation is not WRITE", provenance)
        if cap.is_expired():
            return self._deny(target, prev, cap, "capability expired", provenance)
        if cap.target != target and cap.target != "*":
            return self._deny(target, prev, cap, "capability target mismatch", provenance)

        # 2. target valid
        if not target:
            return self._deny(target, prev, cap, "empty target", provenance)

        # 3. scope valid
        if cap.scope not in ("*", target) and cap.scope != target:
            return self._deny(target, prev, cap, "scope not authorized", provenance)

        # 4. current state authentic
        if not self._state_authentic(target):
            return self._deny(target, prev, cap, "current state not authentic", provenance)

        # 5. expected parent hash matches (optimistic concurrency)
        if request.parent_state != prev:
            result = WriteResult(
                decision=Decision.DENY,
                target=target,
                new_state_hash=None,
                previous_state_hash=prev,
                capability_id=cap.capability_id,
                reason="stale parent state: write rejected",
                provenance=provenance + ["rwa:stale_parent_detected"],
            )
            self._history.append(result)
            return result

        # 6. transition permitted
        if not self._transition_permitted(request):
            return self._deny(target, prev, cap, "transition not permitted", provenance)

        # 7. authorization valid
        if not self._authorize(request):
            return self._deny(target, prev, cap, "authorization invalid", provenance)

        # COMMIT
        new_hash = self.state_hash(request.mutation)
        self._state[target] = new_hash
        result = WriteResult(
            decision=Decision.ALLOW,
            target=target,
            new_state_hash=new_hash,
            previous_state_hash=prev,
            capability_id=cap.capability_id,
            reason="committed",
            provenance=provenance + [f"rwa:new_state={new_hash}"],
        )
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Hooks (override in subclasses for custom policy)
    # ------------------------------------------------------------------
    def _state_authentic(self, target: str) -> bool:
        return True

    def _transition_permitted(self, request: WriteRequest) -> bool:
        return True

    def _authorize(self, request: WriteRequest) -> bool:
        return self.authenticator.verify_canonical(
            request.parent_state, request.capability.authenticator
        )

    def _deny(
        self,
        target: str,
        prev: str,
        cap: Capability,
        reason: str,
        provenance: List[str],
    ) -> WriteResult:
        result = WriteResult(
            decision=Decision.DENY,
            target=target,
            new_state_hash=None,
            previous_state_hash=prev,
            capability_id=cap.capability_id,
            reason=reason,
            provenance=provenance,
        )
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def history(self) -> List[WriteResult]:
        return list(self._history)

    def denied_writes(self) -> List[WriteResult]:
        return [r for r in self._history if r.decision is Decision.DENY]

    def committed_writes(self) -> List[WriteResult]:
        return [r for r in self._history if r.decision is Decision.ALLOW]


def make_capability(
    subject: str,
    operation: Operation,
    target: str,
    *,
    parent_state: str = "",
    authenticator: Optional["Authenticator"] = None,
    scope: str = "*",
    expires_at: float = 0.0,
) -> Capability:
    """Convenience constructor that binds an HMAC tag to the parent state."""
    from .authenticity import Authenticator
    auth = authenticator or Authenticator(b"rwa-default-key")
    tag = auth.sign_canonical(parent_state) if parent_state else ""
    return Capability(
        capability_id=str(uuid.uuid4()),
        subject=subject,
        operation=operation,
        target=target,
        scope=scope,
        expires_at=expires_at,
        nonce=str(uuid.uuid4())[:8],
        parent_state=parent_state,
        authenticator=tag,
    )


__all__ = [
    "Operation",
    "Decision",
    "Capability",
    "ReadSnapshot",
    "WriteRequest",
    "WriteResult",
    "ReadWriteGate",
    "make_capability",
]


@dataclass
class ReadSnapshot:
    """Immutable, authenticated view of state returned by READ."""

    target: str
    state_hash: str
    payload: Dict[str, Any]
    capability_id: str
    issued_at: float
    provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "state_hash": self.state_hash,
            "payload": self.payload,
            "capability_id": self.capability_id,
            "issued_at": self.issued_at,
            "provenance": list(self.provenance),
        }


@dataclass
class WriteRequest:
    """A proposed mutation carrying its parent-state expectation."""

    capability: Capability
    target: str
    mutation: Dict[str, Any]
    parent_state: str
    nonce: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability.capability_id,
            "target": self.target,
            "mutation": self.mutation,
            "parent_state": self.parent_state,
            "nonce": self.nonce,
        }


@dataclass
class WriteResult:
    """Outcome of a write attempt."""

    decision: Decision
    target: str
    new_state_hash: Optional[str]
    previous_state_hash: str
    capability_id: str
    reason: str = ""
    provenance: List[str] = field(default_factory=list)

    @property
    def committed(self) -> bool:
        return self.decision is Decision.ALLOW

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "target": self.target,
            "new_state_hash": self.new_state_hash,
            "previous_state_hash": self.previous_state_hash,
            "capability_id": self.capability_id,
            "reason": self.reason,
            "provenance": list(self.provenance),
        }