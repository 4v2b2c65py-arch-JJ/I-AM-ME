"""Decision engine: transition the entity toward its objective.

E_{t+1} = T(E_t, I_t, M_t, R_t)

Where:
  E = entity state
  I = new input
  M = retrieved memory
  R = relationship graph
  T = transformation mechanism
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .context import ContextSnapshot
from .relations import RelationGraph
from .states import State, VALID_TRANSITIONS, available_from, is_terminal


@dataclass
class Decision:
    """The outcome of one decision step."""

    from_state: State
    to_state: State
    action: str
    result: str
    confidence: float
    rationale: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)


class DecisionEngine:
    """Selects the next state transition based on objective + context."""

    def __init__(
        self,
        relation_graph: Optional[RelationGraph] = None,
        *,
        objective: Optional[Dict[str, object]] = None,
        transition_guard: Optional[Callable[[State, State, object], bool]] = None,
    ) -> None:
        self.relation_graph = relation_graph or RelationGraph()
        self.objective = objective or {}
        self.transition_guard = transition_guard

    # ------------------------------------------------------------------
    def decide(
        self,
        current: State,
        input_data: Dict[str, object],
        context: Optional[ContextSnapshot] = None,
    ) -> Decision:
        candidates = available_from(current)

        # Score each candidate by how well it serves the objective.
        scored: List[Tuple[float, State, str]] = []
        for cand in candidates:
            score, rationale = self._score(cand, current, input_data, context)
            scored.append((score, cand, rationale))

        if not scored:
            return Decision(
                from_state=current,
                to_state=current,
                action="noop",
                result="no_available_transition",
                confidence=0.0,
                rationale="terminal state",
            )

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_state, best_rationale = scored[0]

        # If the best candidate is INVALID and we have alternatives, prefer
        # a non-INVALID state unless the objective explicitly demands it.
        if best_state is State.INVALID and len(scored) > 1:
            second = scored[1]
            if second[0] > 0.0:
                best_score, best_state, best_rationale = second

        action = self._action_for(current, best_state)
        result = f"transitioned {current.value} -> {best_state.value}"
        confidence = min(1.0, max(0.0, best_score))

        return Decision(
            from_state=current,
            to_state=best_state,
            action=action,
            result=result,
            confidence=confidence,
            rationale=best_rationale,
            metadata={
                "candidates": [
                    {"state": s.value, "score": round(sc, 4), "why": why}
                    for sc, s, why in scored
                ],
                "objective": self.objective,
            },
        )

    # ------------------------------------------------------------------
    def _score(
        self,
        candidate: State,
        current: State,
        input_data: Dict[str, object],
        context: Optional[ContextSnapshot],
    ) -> Tuple[float, str]:
        """Compute objective-aligned score for a candidate state."""
        obj_type = str(self.objective.get("type", "single"))
        target = self.objective.get("target", "")
        priority = float(self.objective.get("priority", 1.0))

        base = 0.0
        why = ""

        # Base preference by objective type
        if obj_type == "single" and target:
            if candidate.value.lower() == str(target).lower():
                base = 1.0 * priority
                why = f"directly matches objective target '{target}'"
            elif candidate is State.STORED:
                base = 0.8 * priority
                why = "stores progress toward objective"
            elif candidate is State.ACTIVE:
                base = 0.6 * priority
                why = "keeps entity processing toward objective"
            else:
                base = 0.3 * priority
                why = "weak objective alignment"
        else:
            base = 0.5
            why = "no specific objective target"

        # Contextual adjustments
        if context is not None:
            if candidate is State.ACTIVE and context.retrieval_relevance > 0.5:
                base += 0.1
                why += "; strong retrieval context"
            if candidate is State.OBSERVED and input_data:
                base += 0.1
                why += "; input available to observe"
            if candidate is State.INVALID:
                base -= 0.5
                why = "avoid invalid unless forced"
            if candidate is State.ARCHIVED:
                base -= 0.3
                why = "archival halts progress"

        # Relation-graph influence
        if self.relation_graph.relation_count() > 0 and candidate is State.RELATED:
            base += 0.1
            why += "; relations exist to leverage"

        return max(0.0, min(1.0, base)), why

    def _action_for(self, from_state: State, to_state: State) -> str:
        mapping = {
            (State.NULL, State.CREATED): "initialize",
            (State.CREATED, State.ACTIVE): "activate",
            (State.CREATED, State.STORED): "persist",
            (State.ACTIVE, State.OBSERVED): "observe",
            (State.OBSERVED, State.ACTIVE): "process",
            (State.OBSERVED, State.STORED): "commit",
            (State.ACTIVE, State.RELATED): "link",
            (State.STORED, State.RETRIEVED): "recall",
            (State.RETRIEVED, State.TRANSFORMED): "transform",
            (State.RELATED, State.TRANSFORMED): "integrate",
            (State.TRANSFORMED, State.ACTIVE): "resume",
            (State.TRANSFORMED, State.ARCHIVED): "archive",
            (State.TRANSFORMED, State.INVALID): "quarantine",
            (State.ACTIVE, State.ARCHIVED): "finalize",
            (State.STORED, State.ARCHIVED): "finalize",
        }
        return mapping.get((from_state, to_state), "transition")

    def score_state(self, state: State, context: Optional[ContextSnapshot] = None) -> float:
        """Public scoring helper for diagnostics."""
        sc, _ = self._score(state, State.ACTIVE, {}, context)
        return sc