"""F4: Formation stage, terminal.

The next layer after RCS-0 / UTT:

    RCS-0
      ↓
    UTT
      ↓
    F4
      ↓
    terminal formation

Architectural rule preserved:

    Identity establishes the address.
    The address establishes the remain.
    Nothing in between is allowed to infer.

F4 does NOT reason about the remain. It deterministically crystallizes the
terminal remain into a formation record. Every input property is preserved
and every output property is derived from an input -- nothing is guessed.

Invariant carried forward:

    assert result.reasoning_steps == 0
    assert result.direct_index is not None
    assert result.remains == [cluster[result.direct_index - 1]]
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .rcs import ClusterItem, RemainResult


@dataclass
class FormationResult:
    """The terminal output of an F4 formation step."""

    formation_id: str
    source_remain: ClusterItem
    formation_encoding: str
    terminal: bool = True
    reasoning_steps: int = 0
    direct_index: Optional[int] = None
    provenance: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formation_id": self.formation_id,
            "source_remain": self.source_remain.id,
            "formation_encoding": self.formation_encoding,
            "terminal": self.terminal,
            "reasoning_steps": self.reasoning_steps,
            "direct_index": self.direct_index,
            "provenance": list(self.provenance),
        }


class FormationStage:
    """Deterministic, zero-reasoning crystallization of a terminal remain."""

    def __init__(
        self,
        *,
        encoding_fn: Optional[callable] = None,
    ) -> None:
        self.encoding_fn = encoding_fn or self._default_form_encode

    # ------------------------------------------------------------------
    @staticmethod
    def _default_form_encode(remain: ClusterItem) -> str:
        """Derive a formation encoding from the remain's own encoding.

        Pure function of the input. No inference, no ranking, no prediction.
        """
        raw = f"formation::{remain.encoding}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ------------------------------------------------------------------
    def form(
        self,
        remain_result: RemainResult,
        *,
        cluster: Optional[Sequence[ClusterItem]] = None,
    ) -> FormationResult:
        """Crystallize the terminal remain into a formation record.

        Preserves the architectural invariant:

            assert result.reasoning_steps == 0
            assert result.direct_index is not None
            assert result.remains == [cluster[result.direct_index - 1]]
        """
        if remain_result.survivor is None:
            raise ValueError("cannot form from a remain result with no survivor")

        survivor = remain_result.survivor
        formation_encoding = self.encoding_fn(survivor)

        provenance: List[str] = [
            f"rcs0:cluster_size={remain_result.cluster_size}",
            f"rcs0:matched_count={remain_result.matched_count}",
            f"rcs0:direct_index={remain_result.direct_index}",
            f"rcs0:reasoning_steps={remain_result.reasoning_steps}",
        ]

        # Verify the invariant when a cluster is supplied.
        if cluster is not None and remain_result.direct_index is not None:
            idx = remain_result.direct_index - 1
            assert 0 <= idx < len(cluster), (
                f"direct_index {remain_result.direct_index} out of range"
            )
            assert remain_result.remains == [cluster[idx]], (
                "remains must equal [cluster[direct_index - 1]]"
            )

        return FormationResult(
            formation_id=str(uuid.uuid4()),
            source_remain=survivor,
            formation_encoding=formation_encoding,
            terminal=True,
            reasoning_steps=0,
            direct_index=remain_result.direct_index,
            provenance=provenance,
            metadata={
                "cluster_size": remain_result.cluster_size,
                "sequence": remain_result.sequence,
            },
        )

    def form_chain(
        self,
        cluster: Sequence[ClusterItem],
        unique_sequence: str,
    ) -> Tuple[RemainResult, FormationResult]:
        """Convenience: select the remain, then form it, verifying the invariant."""
        # local import to avoid a cycle at module load
        from .rcs import RemainClusterSelector

        selector = RemainClusterSelector()
        result = selector.select(cluster, unique_sequence)
        formation = self.form(result, cluster=cluster)
        return result, formation


__all__ = [
    "FormationResult",
    "FormationStage",
]