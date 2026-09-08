"""SOE-DDCI engine: orchestrates entity, data bank, relations, history,
context reconstruction, and decision-making into one operational core.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .context import ContextEngine, ContextSnapshot
from .decision import Decision, DecisionEngine
from .data_bank import DataBank, DataDomain
from .entity import Entity, EntityConfig
from .formation import FormationResult, FormationStage
from .history import EventLog, EventType
from .relations import RelationGraph, RelationType
from .rcs import RemainClusterSelector, RemainResult, ClusterItem
from .states import State


class SOEDDCIEngine:
    """Single Objective Entity + Dynamic Data Context Integration."""

    def __init__(
        self,
        config: Optional[EntityConfig] = None,
        *,
        session_id: str = "session-0",
    ) -> None:
        self.entity = Entity(config or EntityConfig())
        self.session_id = session_id
        self.entity.metadata["session_id"] = session_id

        self.context_engine = ContextEngine(
            self.entity.data_bank, self.entity.event_log, self.entity.relation_graph
        )
        self.decision_engine = DecisionEngine(
            self.entity.relation_graph, objective=self.entity.objective
        )
        self.remain_selector = RemainClusterSelector()
        self.formation_stage = FormationStage()

    # ------------------------------------------------------------------
    # Primary operation: input -> state -> decision -> output
    # ------------------------------------------------------------------
    def process(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Run one full cycle: observe -> decide -> transition -> output."""
        # 1. OBSERVATION - route through ACTIVE if needed
        if self.entity.state is State.CREATED:
            self.entity.transition_to(State.ACTIVE, action="activate")
        self.entity.transition_to(
            State.OBSERVED, action="observe", result=f"received input keys={list(input_data)}"
        )
        self.entity.remember(
            DataDomain.EVENT,
            {"input": input_data, "session_id": self.session_id},
        )

        # 2. STATE MATCH + MEMORY RETRIEVAL
        context = self.context_engine.reconstruct(
            self.session_id,
            current_state=State.ACTIVE,
            objective=self.entity.objective,
        )

        # 3. RELATION MAP + OBJECTIVE EVALUATION
        decision = self.decision_engine.decide(
            self.entity.state, input_data, context
        )

        # 4. TRANSITION
        ok = self.entity.transition_to(
            decision.to_state,
            action=decision.action,
            result=decision.result,
        )

        # 5. OUTPUT
        output: Dict[str, Any] = {
            "entity_id": self.entity.entity_id,
            "session_id": self.session_id,
            "input": input_data,
            "state_before": decision.from_state.value,
            "state_after": decision.to_state.value,
            "transition_ok": ok,
            "action": decision.action,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "context_retrieval_relevance": context.retrieval_relevance,
            "profile": self.entity.profile(),
            "data_bank_summary": self.entity.data_bank.summary(),
        }
        return output

    # ------------------------------------------------------------------
    # Cross-session continuity
    # ------------------------------------------------------------------
    def new_session(self, session_id: str) -> "SOEDDCIEngine":
        """Start a new session, reconstructing context from the data bank."""
        self.session_id = session_id
        self.entity.metadata["session_id"] = session_id
        # Reconstruct and log the handoff
        snapshot = self.context_engine.reconstruct(
            session_id,
            current_state=self.entity.state,
            objective=self.entity.objective,
        )
        self.entity.event_log.append(
            EventType.CONTEXT_RECONSTRUCTED,
            session_id=session_id,
            action="new_session",
            result=f"reconstructed context with {len(snapshot.relevant_records)} records",
            payload={"snapshot": snapshot.to_dict()},
        )
        return self

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    @property
    def state(self) -> State:
        return self.entity.state

    @property
    def data_bank(self) -> DataBank:
        return self.entity.data_bank

    @property
    def event_log(self) -> EventLog:
        return self.entity.event_log

    @property
    def relation_graph(self) -> RelationGraph:
        return self.entity.relation_graph

    def relate(self, other_engine: "SOEDDCIEngine", **kw) -> Relation:
        return self.entity.relate_to(other_engine.entity, **kw)

    # ------------------------------------------------------------------
    # RCS-0: Remain Cluster Selector (zero-reasoning terminal reduction)
    # ------------------------------------------------------------------
    def produce_remain(
        self,
        memory_cluster: Sequence[Any],
        unique_sequence: str,
        *,
        prefix: str = "C",
    ) -> Tuple[Optional[ClusterItem], RemainResult]:
        """Reduce a clustered memory to its terminal remain.

        C -> U -> X -> Ø -> R
        No inference, ranking, or prediction. The encoded sequence itself
        determines explicit selection; the output is what remains.
        """
        survivor, result = self.remain_selector.produce(
            memory_cluster, unique_sequence, prefix=prefix
        )
        # Persist the reduction as an event for cross-session continuity
        self.entity.event_log.append(
            EventType.TRANSFORMED,
            session_id=self.session_id,
            action="rcs0_select",
            result=(
                f"cluster[{result.cluster_size}] -> remain[{result.matched_count}] "
                f"survivor={survivor.id if survivor else None}"
            ),
            payload=result.to_dict(),
        )
        return survivor, result

    # ------------------------------------------------------------------
    # F4: Formation stage (terminal crystallization of the remain)
    # ------------------------------------------------------------------
    def produce_formation(
        self,
        memory_cluster: Sequence[Any],
        unique_sequence: str,
        *,
        prefix: str = "C",
    ) -> Tuple[Optional[ClusterItem], RemainResult, FormationResult]:
        """Run RCS-0 selection then F4 formation in one call.

        RCS-0 -> UTT -> F4 -> terminal formation

        Preserves the invariant:
            assert result.reasoning_steps == 0
            assert result.direct_index is not None
            assert result.remains == [cluster[result.direct_index - 1]]
        """
        cluster = self.remain_selector.cluster(memory_cluster, prefix=prefix)
        remain_result = self.remain_selector.select(cluster, unique_sequence)
        formation = self.formation_stage.form(remain_result, cluster=cluster)

        self.entity.event_log.append(
            EventType.TRANSFORMED,
            session_id=self.session_id,
            action="f4_form",
            result=(
                f"remain[{remain_result.matched_count}] -> "
                f"formation[{formation.formation_id}]"
            ),
            payload={
                "remain": remain_result.to_dict(),
                "formation": formation.to_dict(),
            },
        )
        return remain_result.survivor, remain_result, formation

    def snapshot(self) -> ContextSnapshot:
        return self.context_engine.reconstruct(
            self.session_id,
            current_state=self.entity.state,
            objective=self.entity.objective,
        )

    def __repr__(self) -> str:
        return (
            f"SOEDDCIEngine(entity={self.entity!r}, session={self.session_id})"
        )