"""Canonicalization and tamper resistance for SOE-DDCI artifacts.

Deterministic systems usually discover that ambiguity sneaks into
serialization. This module closes those leaks:

    - canonical bytes: order-stable, deterministic serialization
    - tamper detection: verify a formation encoding against its remain
    - round-trip stability: canonical form survives serialize/deserialize
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional, Sequence

from .formation import FormationResult
from .rcs import ClusterItem, RemainResult


def _stable_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, no NaN."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(obj: Any) -> bytes:
    """Produce canonical byte serialization for any SOE-DDCI artifact."""
    if is_dataclass(obj):
        payload = asdict(obj)
    elif isinstance(obj, (dict, list, tuple)):
        payload = obj
    else:
        payload = _stable_json(obj)
    return _stable_json(payload).encode("utf-8")


def canonical_hash(obj: Any) -> str:
    """Content-derived canonical hash: stable across equivalent artifacts."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def verify_formation(
    remain_result: RemainResult,
    formation: FormationResult,
) -> bool:
    """Tamper detection: does the formation encoding match its remain?

    f(R) = H("formation::" + H(R)). If the formation was derived from a
    different remain -- or was tampered after the fact -- this returns False.
    """
    survivor = getattr(remain_result, "survivor", None)
    if survivor is None:
        return False
    expected_encoding = getattr(formation, "formation_encoding", None)
    if expected_encoding is None:
        return False
    expected = hashlib.sha256(
        f"formation::{survivor.encoding}".encode("utf-8")
    ).hexdigest()
    return expected == expected_encoding


def verify_provenance(formation: FormationResult, expected: Sequence[str]) -> bool:
    """Check the provenance chain matches the expected trace."""
    actual = getattr(formation, "provenance", None)
    if actual is None:
        return False
    return list(actual) == list(expected)


def round_trip_stable(obj: Any) -> bool:
    """Serialize -> parse -> re-serialize must be byte-identical."""
    once = canonical_bytes(obj)
    reparsed = json.loads(once.decode("utf-8"))
    twice = canonical_bytes(reparsed)
    return once == twice


def cluster_canonical(cluster: Sequence[ClusterItem]) -> str:
    """Canonical encoding of a cluster: order-stable over items."""
    items = [
        {"id": it.id, "payload": it.payload, "encoding": it.encoding}
        for it in cluster
    ]
    return canonical_hash(items)


def formation_canonical(formation: FormationResult) -> str:
    """Canonical identity of a formation (content-derived, excludes UUID)."""
    payload = {
        "source_remain": formation.source_remain.id,
        "formation_encoding": formation.formation_encoding,
        "terminal": formation.terminal,
        "reasoning_steps": formation.reasoning_steps,
        "direct_index": formation.direct_index,
        "provenance": list(formation.provenance),
    }
    return canonical_hash(payload)


__all__ = [
    "canonical_bytes",
    "canonical_hash",
    "verify_formation",
    "verify_provenance",
    "round_trip_stable",
    "cluster_canonical",
    "formation_canonical",
]