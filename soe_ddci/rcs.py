"""RCS-0: Remain Cluster Selector, Zero-Reasoning.

A terminal subsystem where clustered historical information is reduced by
an encoded selector until only a uniquely identifiable remainder survives.

    C -> U -> X -> Ø -> R

    C = clustered memory
    U = unique encoded sequence
    X = explicit selection
    Ø = no inferential / reasoning stage
    R = terminal remain

    R = Remain( X( U( C ) ) )

The system does NOT optimize, speculate, rank, or reason across alternatives.
The encoded sequence itself determines the selection. The output is not the
chosen path -- it is what remains after selection.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class ClusterItem:
    """A single item inside a memory cluster."""

    id: str
    payload: Any
    encoding: str = ""  # derived stable encoding used for matching


@dataclass
class RemainResult:
    """The terminal output of an RCS-0 selection."""

    cluster_size: int
    sequence: str
    matched_count: int
    remains: List[ClusterItem]
    survivor: Optional[ClusterItem]
    eliminated: List[ClusterItem]
    zero_reasoning: bool = True
    # UTT invariants: direct_index is *where* identity resolved;
    # remains is *what* survives. They are distinct artifacts.
    direct_index: Optional[int] = None
    reasoning_steps: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_size": self.cluster_size,
            "sequence": self.sequence,
            "matched_count": self.matched_count,
            "remains": [r.id for r in self.remains],
            "survivor": self.survivor.id if self.survivor else None,
            "eliminated": [e.id for e in self.eliminated],
            "zero_reasoning": self.zero_reasoning,
            "direct_index": self.direct_index,
            "reasoning_steps": self.reasoning_steps,
        }


class RemainClusterSelector:
    """Deterministic, zero-reasoning reduction of a memory cluster."""

    def __init__(
        self,
        *,
        encoding_fn: Optional[Callable[[Any], str]] = None,
        match_fn: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.encoding_fn = encoding_fn or self._default_encode
        self.match_fn = match_fn or self._exact_match

    # ------------------------------------------------------------------
    @staticmethod
    def _default_encode(payload: Any) -> str:
        """Stable deterministic encoding of a payload."""
        raw = repr(payload).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _exact_match(a: str, b: str) -> bool:
        return a == b

    # ------------------------------------------------------------------
    def encode(self, item: ClusterItem) -> ClusterItem:
        item.encoding = self.encoding_fn(item.payload)
        return item

    def cluster(self, items: Sequence[Any], *, prefix: str = "C") -> List[ClusterItem]:
        """Build a cluster of encoded memory items."""
        cluster: List[ClusterItem] = []
        for i, payload in enumerate(items):
            cluster.append(ClusterItem(id=f"{prefix}-{i:04d}", payload=payload))
        return [self.encode(it) for it in cluster]

    # ------------------------------------------------------------------
    def select(
        self,
        cluster: Sequence[ClusterItem],
        unique_sequence: str,
    ) -> RemainResult:
        """Explicit selection: keep only items whose encoding matches the sequence.

        No inference. No ranking. No prediction. The sequence determines
        the selection, and the terminal remain is the last surviving item.
        """
        cluster = list(cluster)
        matched = [
            item for item in cluster
            if self.match_fn(item.encoding, unique_sequence)
        ]
        eliminated = [item for item in cluster if item not in matched]

        survivor = matched[-1] if matched else None

        # direct_index = where identity resolved (1-based position in cluster)
        direct_index: Optional[int] = None
        if survivor is not None:
            for idx, item in enumerate(cluster, start=1):
                if item is survivor:
                    direct_index = idx
                    break

        return RemainResult(
            cluster_size=len(cluster),
            sequence=unique_sequence,
            matched_count=len(matched),
            remains=list(matched),
            survivor=survivor,
            eliminated=eliminated,
            zero_reasoning=True,
            direct_index=direct_index,
            reasoning_steps=0,
        )

    # ------------------------------------------------------------------
    def utt_match(
        self,
        g: Any,
        q: Any,
        r: Any,
    ) -> RemainResult:
        """UTT = G -> Q -> R  with the sustain chain B2 -> B1 -> B3.

        The third occurrence is NOT inferred -- it is reached by the exact
        identity condition. SHA(B2) == SHA(B1) == SHA(B3) is the equality
        test; when the ordered match resolves to the third element,
        Direct(G, Q, R) = 3, and the terminal state is 0,0 -> R_remain.

        `direct_index` records *where* identity resolved; `remains` records
        *what* survives. They are distinct artifacts.
        """
        b2 = self.encode(ClusterItem(id="B2", payload=g))
        b1 = self.encode(ClusterItem(id="B1", payload=q))
        b3 = self.encode(ClusterItem(id="B3", payload=r))

        identity_holds = (
            self.match_fn(b2.encoding, b1.encoding)
            and self.match_fn(b1.encoding, b3.encoding)
        )

        cluster = [b2, b1, b3]
        survivor = b3 if identity_holds else None

        return RemainResult(
            cluster_size=3,
            sequence=b3.encoding,
            matched_count=3 if identity_holds else 0,
            remains=[b3] if identity_holds else [],
            survivor=survivor,
            eliminated=[] if identity_holds else cluster,
            zero_reasoning=True,
            direct_index=3 if identity_holds else None,
            reasoning_steps=0,
        )

    # ------------------------------------------------------------------
    def produce(
        self,
        memory_cluster: Sequence[Any],
        unique_sequence: str,
        *,
        prefix: str = "C",
    ) -> Tuple[Optional[ClusterItem], RemainResult]:
        """Convenience: cluster raw payloads, then select the terminal remain."""
        cluster = self.cluster(memory_cluster, prefix=prefix)
        result = self.select(cluster, unique_sequence)
        return result.survivor, result


__all__ = [
    "ClusterItem",
    "RemainResult",
    "RemainClusterSelector",
]