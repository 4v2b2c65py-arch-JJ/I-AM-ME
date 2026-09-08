"""SOE-DDCI: Single Objective Entity + Dynamic Data Context Integration.

A compact schema representing all available states, relationships,
mechanisms, artificial data-bank records, and cross-session chat-history
continuity under a single-objective entity model.
"""

from .states import State, StateTransition, VALID_TRANSITIONS, available_from, is_terminal
from .entity import Entity, EntityConfig
from .data_bank import DataBank, DataDomain
from .relations import Relation, RelationGraph, RelationType
from .history import EventLog, Event, EventType
from .context import ContextEngine
from .decision import DecisionEngine
from .authenticity import Authenticator, verify_formation_authentic
from .canonical import (
    canonical_bytes,
    canonical_hash,
    cluster_canonical,
    formation_canonical,
    round_trip_stable,
    verify_formation,
    verify_provenance,
)
from .formation import FormationStage, FormationResult
from .rcs import RemainClusterSelector, RemainResult, ClusterItem
from .drc import (
    Checkpoint,
    DurableRecovery,
    JournalEntry,
    RecoveryResult,
    RecoveryStatus,
)
from .atc import (
    AtomicTransaction,
    Snapshot,
    TxRecord,
    TxStatus,
    verify_graph_consistent,
)
from .lgc import (
    ForkResult,
    JoinRequest,
    JoinResult,
    LineageGraph,
    LineageNode,
    NodeStatus,
)
from .rwa import (
    Capability,
    Decision,
    Operation,
    ReadSnapshot,
    ReadWriteGate,
    WriteRequest,
    WriteResult,
    make_capability,
)
from .engine import SOEDDCIEngine

__all__ = [
    "State",
    "StateTransition",
    "VALID_TRANSITIONS",
    "available_from",
    "is_terminal",
    "Entity",
    "EntityConfig",
    "DataBank",
    "DataDomain",
    "Relation",
    "RelationGraph",
    "RelationType",
    "EventLog",
    "Event",
    "EventType",
    "ContextEngine",
    "DecisionEngine",
    "FormationStage",
    "FormationResult",
    "Authenticator",
    "verify_formation_authentic",
    "canonical_bytes",
    "canonical_hash",
    "cluster_canonical",
    "formation_canonical",
    "round_trip_stable",
    "verify_formation",
    "verify_provenance",
    "Capability",
    "Decision",
    "Operation",
    "ReadSnapshot",
    "ReadWriteGate",
    "WriteRequest",
    "WriteResult",
    "make_capability",
    "ForkResult",
    "JoinRequest",
    "JoinResult",
    "LineageGraph",
    "LineageNode",
    "NodeStatus",
    "AtomicTransaction",
    "Snapshot",
    "TxRecord",
    "TxStatus",
    "verify_graph_consistent",
    "Checkpoint",
    "DurableRecovery",
    "JournalEntry",
    "RecoveryResult",
    "RecoveryStatus",
    "SOEDDCIEngine",
]
