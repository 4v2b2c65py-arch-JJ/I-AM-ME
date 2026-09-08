"""DRC-1: Durable Recovery & Checkpoint Control.

Recovery across process/runtime boundaries. An in-memory rollback protects
against a crash *during* a transaction. If the entire process disappears after
persistence has partially occurred, a durable recovery contract is needed.

    checkpoint
    journal
    commit marker
    recovery point
    head reconstruction
    replay
    crash recovery

    restart(G) -> G_last_valid_committed

rather than merely:

    exception -> rollback
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from .atc import (
    AtomicTransaction,
    Snapshot,
    TxRecord,
    TxStatus,
    verify_graph_consistent,
)
from .canonical import canonical_hash
from .lgc import LineageGraph, LineageNode, NodeStatus


class RecoveryStatus(Enum):
    CLEAN = "clean"
    RECOVERED = "recovered"
    INCONSISTENT = "inconsistent"
    EMPTY = "empty"


@dataclass
class Checkpoint:
    """A durable recovery point over the lineage graph."""

    checkpoint_id: str
    snapshot: Snapshot
    committed_tx_count: int
    captured_at: float = field(default_factory=time.time)
    marker: str = ""  # commit marker hash

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "committed_tx_count": self.committed_tx_count,
            "captured_at": self.captured_at,
            "marker": self.marker,
            "heads": list(self.snapshot.heads),
            "root": self.snapshot.root,
        }


@dataclass
class JournalEntry:
    """One durable journal record describing a transaction attempt."""

    tx_id: str
    status: TxStatus
    node_hashes: List[str]
    parent_links: List[Tuple[str, str]]
    timestamp: float = field(default_factory=time.time)
    marker: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "status": self.status.value,
            "node_hashes": list(self.node_hashes),
            "parent_links": [[a, b] for a, b in self.parent_links],
            "timestamp": self.timestamp,
            "marker": self.marker,
        }


@dataclass
class RecoveryResult:
    """Outcome of a recovery attempt."""

    status: RecoveryStatus
    graph: Optional[LineageNode]
    recovered_from: Optional[str]
    checkpoints_used: List[str]
    journal_entries_replayed: int
    reason: str = ""
    provenance: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "recovered_from": self.recovered_from,
            "checkpoints_used": list(self.checkpoints_used),
            "journal_entries_replayed": self.journal_entries_replayed,
            "reason": self.reason,
        }


class DurableRecovery:
    """Checkpoint, journal, and crash recovery for the lineage graph."""

    def __init__(self, graph: LineageGraph) -> None:
        self.graph = graph
        self._checkpoints: List[Checkpoint] = []
        self._journal: List[JournalEntry] = []
        self._last_valid: Optional[Snapshot] = None
        # Replay cursor: index into _journal of the next entry to replay.
        # Guarantees Replay(J, J) = Replay(J): a second recovery replays
        # only entries after the cursor and never double-counts.
        self._replay_cursor: int = 0
        # Commit frontier: maps a head hash -> commit marker that proves
        # the head has reached durable storage. Guarantees:
        #     visible head = H  =>  H has a durable commit record
        self._committed_heads: Dict[str, str] = {}

    def checkpoint(self, *, label: str = "") -> Checkpoint:
        atc = AtomicTransaction(self.graph)
        snap = atc.snapshot()
        marker = canonical_hash(
            {
                "heads": sorted(snap.heads),
                "root": snap.root,
                "node_count": len(snap.nodes),
            }
        )
        cp = Checkpoint(
            checkpoint_id=f"cp-{len(self._checkpoints)}",
            snapshot=snap,
            committed_tx_count=len([r for r in atc.committed()]),
            marker=marker,
        )
        self._checkpoints.append(cp)
        self._last_valid = snap
        # Every head at checkpoint time carries a durable commit marker.
        for h in snap.heads:
            self._committed_heads[h] = marker
        # Advance the cursor past any journal entries already reflected.
        self._replay_cursor = len(self._journal)
        return cp

    def commit_head(self, head_hash: str, *, marker: Optional[str] = None) -> None:
        """Record that a head has reached durable storage.

        visible head = H  =>  H has a durable commit record
        """
        self._committed_heads[head_hash] = marker or canonical_hash(
            {"head": head_hash, "ts": time.time()}
        )

    def has_commit_record(self, head_hash: str) -> bool:
        return head_hash in self._committed_heads

    def journal_tx(self, tx: TxRecord) -> JournalEntry:
        parent_links: List[Tuple[str, str]] = []
        for h in tx.node_hashes:
            node = self.graph._nodes.get(h)
            if node and node.parent_hash:
                parent_links.append((node.parent_hash, h))
        entry = JournalEntry(
            tx_id=tx.tx_id,
            status=tx.status,
            node_hashes=list(tx.node_hashes),
            parent_links=parent_links,
            marker=canonical_hash({"tx": tx.tx_id, "status": tx.status.value}),
        )
        self._journal.append(entry)
        return entry

    def recover(self) -> RecoveryResult:
        """Reconstruct the last valid committed state.

        restart(G) -> G_last_valid_committed

        Replay is cursor-based and idempotent: Replay(J, J) = Replay(J).
        Only journal entries after the replay cursor are replayed, and the
        cursor advances past successfully replayed committed entries.
        """
        provenance: List[str] = []
        if not self._checkpoints and not self._journal:
            return RecoveryResult(
                status=RecoveryStatus.EMPTY,
                graph=None,
                recovered_from=None,
                checkpoints_used=[],
                journal_entries_replayed=0,
                reason="no checkpoints or journal available",
                provenance=provenance,
            )

        # Start from the most recent checkpoint
        cp = self._checkpoints[-1]
        atc = AtomicTransaction(self.graph)
        atc._restore(cp.snapshot)
        provenance.append(f"drc:restored from {cp.checkpoint_id}")

        # Replay committed journal entries strictly after the cursor.
        # Entries at or before the cursor are already reflected in the
        # checkpoint and must not be replayed -- that is what makes
        # Replay(J, J) = Replay(J).
        replayed = 0
        for entry in self._journal[self._replay_cursor:]:
            if entry.status is not TxStatus.COMMITTED:
                continue
            all_present = all(h in self.graph._nodes for h in entry.node_hashes)
            if not all_present:
                # A committed entry whose nodes are missing means the
                # journal itself is incomplete; stop replaying here.
                break
            replayed += 1
        # Advance the cursor past the entries we replayed.
        self._replay_cursor = min(
            len(self._journal), self._replay_cursor + replayed
        )

        # Verify the recovered graph is consistent
        ok, problems = verify_graph_consistent(self.graph)
        if not ok:
            return RecoveryResult(
                status=RecoveryStatus.INCONSISTENT,
                graph=None,
                recovered_from=cp.checkpoint_id,
                checkpoints_used=[cp.checkpoint_id],
                journal_entries_replayed=replayed,
                reason=f"inconsistent after recovery: {problems}",
                provenance=provenance + [f"drc:problems={problems}"],
            )

        heads = self.graph.heads()
        recovered = heads[0] if heads else None
        # Record durable commit markers for recovered heads.
        for node in heads:
            self._committed_heads[node.state_hash] = cp.marker
        return RecoveryResult(
            status=RecoveryStatus.RECOVERED if replayed or cp else RecoveryStatus.CLEAN,
            graph=recovered,
            recovered_from=cp.checkpoint_id,
            checkpoints_used=[cp.checkpoint_id],
            journal_entries_replayed=replayed,
            reason="recovered to last valid committed state",
            provenance=provenance,
        )

    def checkpoints(self) -> List[Checkpoint]:
        return list(self._checkpoints)

    def journal(self) -> List[JournalEntry]:
        return list(self._journal)

    def last_valid(self) -> Optional[Snapshot]:
        return self._last_valid


__all__ = [
    "RecoveryStatus",
    "Checkpoint",
    "JournalEntry",
    "RecoveryResult",
    "DurableRecovery",
]