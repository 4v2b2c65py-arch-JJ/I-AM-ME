"""BRN-1: Branch Seed Memory Attention Layer.

Future identities belonging to the same branch seed are managed by an
attention layer over the lineage graph rather than by copying private keys
between devices.

    I_root
       |
    +--+--+--+
    |  |  |  |
   K_A K_B K_C ...

The root identity maintains a signed device registry. Each device holds its
own non-exportable hardware key. The attention layer decides which branch
seed a candidate identity belongs to, and which device keys are authorized
for that seed.

    attention(seed, candidate) -> branch
    authorize(branch, device_key) -> bool
    register(branch, device_key, attestation) -> registry entry
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import canonical_hash
from .lgc import LineageGraph, LineageNode


class AttentionStatus(Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


@dataclass
class DeviceAttestation:
    """A signed claim that a device key belongs to a branch seed."""

    device_id: str
    public_key_ref: str
    branch_seed: str
    attestation: str
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return self.expires_at != 0.0 and time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "public_key_ref": self.public_key_ref,
            "branch_seed": self.branch_seed,
            "attestation": self.attestation,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


@dataclass
class AttentionResult:
    """Outcome of an attention query over the branch seed."""

    status: AttentionStatus
    branch_seed: str
    candidate: str
    matched_devices: List[DeviceAttestation]
    reason: str = ""
    provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "branch_seed": self.branch_seed,
            "candidate": self.candidate,
            "matched_devices": [d.to_dict() for d in self.matched_devices],
            "reason": self.reason,
        }


class BranchSeedMemory:
    """Attention layer over a lineage graph for same-seed identities."""

    def __init__(self, graph: LineageGraph) -> None:
        self.graph = graph
        self._registry: Dict[str, List[DeviceAttestation]] = {}
        self._seeds: Set[str] = set()

    def register_seed(self, seed_hash: str) -> None:
        self._seeds.add(seed_hash)
        self._registry.setdefault(seed_hash, [])

    def register(self, attestation: DeviceAttestation) -> DeviceAttestation:
        self._registry.setdefault(attestation.branch_seed, []).append(attestation)
        return attestation

    def attention(self, candidate: str, *, branch_seed: Optional[str] = None) -> AttentionResult:
        provenance = [f"brn:candidate={candidate[:12]}..."]
        seeds = [branch_seed] if branch_seed else list(self._seeds)
        if not seeds:
            return AttentionResult(
                status=AttentionStatus.UNMATCHED,
                branch_seed="",
                candidate=candidate,
                matched_devices=[],
                reason="no registered branch seeds",
                provenance=provenance,
            )
        matches: List[DeviceAttestation] = []
        ambiguous = False
        for seed in seeds:
            for att in self._registry.get(seed, []):
                if att.public_key_ref == candidate or att.device_id == candidate:
                    matches.append(att)
                    if att.branch_seed != branch_seed and branch_seed is not None:
                        ambiguous = True
        if ambiguous:
            return AttentionResult(
                status=AttentionStatus.AMBIGUOUS,
                branch_seed=branch_seed or "",
                candidate=candidate,
                matched_devices=matches,
                reason="candidate matches multiple branch seeds",
                provenance=provenance,
            )
        if not matches:
            return AttentionResult(
                status=AttentionStatus.UNMATCHED,
                branch_seed=branch_seed or "",
                candidate=candidate,
                matched_devices=[],
                reason="no device attestation matches candidate",
                provenance=provenance,
            )
        return AttentionResult(
            status=AttentionStatus.MATCHED,
            branch_seed=matches[0].branch_seed,
            candidate=candidate,
            matched_devices=matches,
            reason="candidate matches an authorized device on this seed",
            provenance=provenance + [f"brn:seed={matches[0].branch_seed[:12]}..."],
        )

    def authorize(self, branch_seed: str, device_key: str) -> bool:
        for att in self._registry.get(branch_seed, []):
            if att.public_key_ref == device_key and not att.is_expired():
                return True
        return False

    def devices_for_seed(self, branch_seed: str) -> List[DeviceAttestation]:
        return [a for a in self._registry.get(branch_seed, []) if not a.is_expired()]

    def seeds(self) -> List[str]:
        return list(self._seeds)

    def prune_expired(self) -> int:
        removed = 0
        for seed in list(self._registry):
            alive = []
            for att in self._registry[seed]:
                if att.is_expired():
                    removed += 1
                else:
                    alive.append(att)
            self._registry[seed] = alive
        return removed


__all__ = [
    "AttentionStatus",
    "DeviceAttestation",
    "AttentionResult",
    "BranchSeedMemory",
]
