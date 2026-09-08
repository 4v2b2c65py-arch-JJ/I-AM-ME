"""Tests for the SOE-DDCI implementation."""

import time

from soe_ddci import (
    AtomicTransaction,
    Authenticator,
    Capability,
    Checkpoint,
    ClusterItem,
    DataBank,
    DataDomain,
    Decision,
    DecisionEngine,
    DurableRecovery,
    Entity,
    EntityConfig,
    EventLog,
    EventType,
    ForkResult,
    FormationResult,
    FormationStage,
    JoinRequest,
    JoinResult,
    JournalEntry,
    LineageGraph,
    LineageNode,
    NodeStatus,
    Operation,
    ReadSnapshot,
    ReadWriteGate,
    RecoveryResult,
    RecoveryStatus,
    Relation,
    RelationGraph,
    RelationType,
    RemainClusterSelector,
    RemainResult,
    SOEDDCIEngine,
    Snapshot,
    State,
    StateTransition,
    TxRecord,
    TxStatus,
    VALID_TRANSITIONS,
    WriteRequest,
    WriteResult,
    available_from,
    canonical_bytes,
    canonical_hash,
    cluster_canonical,
    formation_canonical,
    is_terminal,
    make_capability,
    round_trip_stable,
    verify_formation,
    verify_formation_authentic,
    verify_graph_consistent,
    verify_provenance,
)

def test_engine_process_cycle():
    engine = SOEDDCIEngine(
        EntityConfig(objective_target="ARCHIVED"), session_id="s1"
    )
    out = engine.process({"text": "hello"})
    assert out["state_before"] == "OBSERVED"
    assert out["state_after"] in [s.value for s in available_from(State.OBSERVED)]
    assert out["confidence"] >= 0.0


def test_engine_cross_session():
    engine = SOEDDCIEngine(session_id="s1")
    engine.process({"text": "first"})
    engine.process({"text": "second"})
    depth_before = len(engine.event_log)
    engine.new_session("s2")
    assert len(engine.event_log) > depth_before
    assert "s2" in engine.event_log.sessions()


def test_engine_relation_link():
    a = SOEDDCIEngine(session_id="s1")
    b = SOEDDCIEngine(session_id="s2")
    a.relate(b, type=RelationType.SUPPORTIVE, weight=0.9)
    assert a.relation_graph.relation_count() == 1
    assert a.relation_graph.outgoing(a.entity.entity_id)[0].target == b.entity.entity_id


# ---------------------------------------------------------------------------
# RCS-0: Remain Cluster Selector (zero-reasoning)
# ---------------------------------------------------------------------------
def test_rcs_default_encode_is_stable():
    sel = RemainClusterSelector()
    a = sel._default_encode({"x": 1})
    b = sel._default_encode({"x": 1})
    c = sel._default_encode({"x": 2})
    assert a == b
    assert a != c


def test_rcs_cluster_builds_encoded_items():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b", "c"], prefix="M")
    assert len(cluster) == 3
    assert all(it.encoding for it in cluster)
    assert cluster[0].id == "M-0000"


def test_rcs_select_keeps_only_explicit_match():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["alpha", "beta", "gamma"], prefix="M")
    target_seq = cluster[1].encoding  # the 'beta' item
    result = sel.select(cluster, target_seq)
    assert result.cluster_size == 3
    assert result.matched_count == 1
    assert result.survivor is not None
    assert result.survivor.payload == "beta"
    assert result.zero_reasoning is True
    assert len(result.eliminated) == 2


def test_rcs_select_no_match_has_no_survivor():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, "deadbeef" * 8)
    assert result.matched_count == 0
    assert result.survivor is None
    assert len(result.eliminated) == 2


def test_rcs_select_last_remain_is_terminal():
    """When multiple items match, the LAST one is the terminal remain."""
    sel = RemainClusterSelector()
    # Two payloads that hash to the same encoding via custom match_fn
    sel.match_fn = lambda a, b: True  # everything matches
    cluster = sel.cluster(["a", "b", "c"], prefix="M")
    result = sel.select(cluster, "anything")
    assert result.matched_count == 3
    assert result.survivor.payload == "c"  # last item


def test_rcs_produce_convenience():
    sel = RemainClusterSelector()
    survivor, result = sel.produce(["x", "y", "z"], sel._default_encode("y"))
    assert survivor is not None
    assert survivor.payload == "y"
    assert result.cluster_size == 3


def test_engine_produce_remain():
    engine = SOEDDCIEngine(session_id="s1")
    cluster = ["alpha", "beta", "gamma"]
    seq = RemainClusterSelector()._default_encode("beta")
    survivor, result = engine.produce_remain(cluster, seq)
    assert survivor.payload == "beta"
    assert result.zero_reasoning is True
    # RCS-0 reduction is logged as a transformed event
    assert any(e.type is EventType.TRANSFORMED for e in engine.event_log.all())


def test_rcs_result_to_dict():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    d = result.to_dict()
    assert d["cluster_size"] == 2
    assert d["matched_count"] == 1
    assert d["survivor"] == "M-0000"
    assert d["zero_reasoning"] is True


# ---------------------------------------------------------------------------
# UTT = G -> Q -> R  (sustain chain B2 -> B1 -> B3)
# ---------------------------------------------------------------------------
def test_utt_identity_holds_when_all_equal():
    sel = RemainClusterSelector()
    result = sel.utt_match("same", "same", "same")
    assert result.matched_count == 3
    assert result.direct_index == 3
    assert result.reasoning_steps == 0
    assert result.survivor is not None
    assert result.survivor.id == "B3"
    assert result.zero_reasoning is True


def test_utt_identity_fails_on_mismatch():
    sel = RemainClusterSelector()
    result = sel.utt_match("a", "a", "b")  # B3 differs
    assert result.matched_count == 0
    assert result.direct_index is None
    assert result.survivor is None
    assert len(result.eliminated) == 3


def test_utt_direct_index_is_address_not_inference():
    """3 is an address/index produced by identity; remains is the artifact."""
    sel = RemainClusterSelector()
    result = sel.utt_match("x", "x", "x")
    # direct_index records *where* identity resolved
    assert result.direct_index == 3
    # remains records *what* survives -- distinct from the index
    assert len(result.remains) == 1
    assert result.remains[0].id == "B3"
    assert result.reasoning_steps == 0


def test_utt_invariant_assertions():
    """The invariant encoding from the spec."""
    sel = RemainClusterSelector()
    g = "value"
    q = "value"
    r = "value"
    b2 = sel.encode(ClusterItem(id="B2", payload=g))
    b1 = sel.encode(ClusterItem(id="B1", payload=q))
    b3 = sel.encode(ClusterItem(id="B3", payload=r))
    assert b2.encoding == b1.encoding
    assert b1.encoding == b3.encoding

    result = sel.utt_match(g, q, r)
    assert result.direct_index == 3
    assert result.reasoning_steps == 0
    assert result.survivor.payload == r


# ---------------------------------------------------------------------------
# F4: Formation stage (terminal crystallization of the remain)
# ---------------------------------------------------------------------------
def test_formation_default_encoding_is_deterministic():
    stage = FormationStage()
    item = ClusterItem(id="X", payload="p", encoding="abc")
    a = stage.encoding_fn(item)
    b = stage.encoding_fn(item)
    assert a == b
    assert a.startswith("sha256:") or len(a) == 64


def test_formation_produces_terminal_record():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b", "c"], prefix="M")
    result = sel.select(cluster, cluster[1].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    assert isinstance(formation, FormationResult)
    assert formation.terminal is True
    assert formation.reasoning_steps == 0
    assert formation.direct_index == 2
    assert formation.source_remain.payload == "b"


def test_formation_preserves_invariant():
    """assert remains == [cluster[direct_index - 1]]"""
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b", "c", "d"], prefix="M")
    result = sel.select(cluster, cluster[2].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    idx = result.direct_index - 1
    assert result.remains == [cluster[idx]]
    assert formation.source_remain is cluster[idx]


def test_formation_rejects_no_survivor():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, "deadbeef" * 8)
    stage = FormationStage()
    try:
        stage.form(result)
        assert False, "should have raised"
    except ValueError:
        pass


def test_formation_to_dict():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    d = formation.to_dict()
    assert d["terminal"] is True
    assert d["reasoning_steps"] == 0
    assert d["direct_index"] == 1
    assert "rcs0:" in d["provenance"][0]


def test_formation_chain_convenience():
    sel = RemainClusterSelector()
    stage = FormationStage()
    cluster = sel.cluster(["x", "y", "z"], prefix="M")
    result, formation = stage.form_chain(cluster, cluster[1].encoding)
    assert result.survivor.payload == "y"
    assert formation.source_remain.payload == "y"
    assert formation.terminal is True


def test_engine_produce_formation():
    engine = SOEDDCIEngine(session_id="s1")
    cluster = ["alpha", "beta", "gamma"]
    seq = RemainClusterSelector()._default_encode("beta")
    survivor, remain_result, formation = engine.produce_formation(cluster, seq)
    assert survivor.payload == "beta"
    assert formation.terminal is True
    assert formation.reasoning_steps == 0
    assert formation.direct_index == 2
    # F4 step is logged
    assert any(e.action == "f4_form" for e in engine.event_log.all())


# ---------------------------------------------------------------------------
# Replay determinism: the core verification of the deterministic chain
# ---------------------------------------------------------------------------
def _run_formation(cluster_payloads, target_payload):
    """Helper: build a fresh engine, run RCS-0 + F4, return the artifacts."""
    engine = SOEDDCIEngine(session_id="replay")
    seq = RemainClusterSelector()._default_encode(target_payload)
    survivor, remain_result, formation = engine.produce_formation(
        cluster_payloads, seq
    )
    return engine, survivor, remain_result, formation


def test_replay_same_inputs_same_content_derived_outputs():
    """Given identical cluster + sequence, content-derived fields must match."""
    cluster = ["alpha", "beta", "gamma", "delta"]
    _, _, r1, f1 = _run_formation(cluster, "gamma")
    _, _, r2, f2 = _run_formation(cluster, "gamma")

    # Content-derived identities must be identical across replays
    assert r1.survivor.encoding == r2.survivor.encoding
    assert r1.direct_index == r2.direct_index
    assert r1.reasoning_steps == r2.reasoning_steps
    assert r1.matched_count == r2.matched_count
    assert f1.formation_encoding == f2.formation_encoding
    assert f1.direct_index == f2.direct_index
    assert f1.provenance == f2.provenance
    assert f1.terminal == f2.terminal


def test_replay_formation_id_differs_but_encoding_matches():
    """Instance identity (UUID) vs deterministic content identity.

    same remain -> run #1 -> UUID-A, run #2 -> UUID-B
    both: formation_encoding = X
    """
    cluster = ["alpha", "beta", "gamma"]
    _, _, r1, f1 = _run_formation(cluster, "beta")
    _, _, r2, f2 = _run_formation(cluster, "beta")

    # Instance identity: fresh UUID each run
    assert f1.formation_id != f2.formation_id

    # Content-derived identity: identical and distinct from the remain encoding
    assert f1.formation_encoding == f2.formation_encoding
    assert f1.formation_encoding != r1.survivor.encoding
    assert len(f1.formation_encoding) == 64


def test_replay_provenance_chain_identical():
    """The full provenance chain must reconstruct identically."""
    cluster = ["a", "b", "c", "d", "e"]
    _, _, r1, f1 = _run_formation(cluster, "d")
    _, _, r2, f2 = _run_formation(cluster, "d")

    assert f1.provenance == f2.provenance
    # Provenance encodes the whole RCS-0 -> UTT -> F4 stack
    assert any("direct_index=4" in p for p in f1.provenance)
    assert any("reasoning_steps=0" in p for p in f1.provenance)
    assert any("cluster_size=5" in p for p in f1.provenance)


def test_replay_different_sequence_changes_remain():
    """A different selector sequence must change the remain (non-triviality)."""
    cluster = ["alpha", "beta", "gamma"]
    _, _, r1, _ = _run_formation(cluster, "beta")
    _, _, r2, _ = _run_formation(cluster, "gamma")

    assert r1.survivor.payload != r2.survivor.payload
    assert r1.direct_index != r2.direct_index


def test_replay_formation_encoding_pure_function_of_remain():
    """f(R) = H("formation::" + H(R)) must be reproducible from the remain alone."""
    sel = RemainClusterSelector()
    cluster = sel.cluster(["x", "y", "z"], prefix="M")
    result = sel.select(cluster, cluster[1].encoding)
    stage = FormationStage()
    f1 = stage.form(result)
    f2 = stage.form(result)  # same remain object

    assert f1.formation_id != f2.formation_id
    assert f1.formation_encoding == f2.formation_encoding

    # And it must equal the closed-form derivation
    import hashlib
    expected = hashlib.sha256(
        f"formation::{result.survivor.encoding}".encode("utf-8")
    ).hexdigest()
    assert f1.formation_encoding == expected


# ---------------------------------------------------------------------------
# Canonicalization and tamper resistance
# ---------------------------------------------------------------------------
def test_canonical_bytes_deterministic():
    a = canonical_bytes({"b": 2, "a": 1})
    b = canonical_bytes({"a": 1, "b": 2})
    assert a == b  # key order must not matter


def test_canonical_hash_stable():
    a = canonical_hash([1, 2, 3])
    b = canonical_hash([1, 2, 3])
    assert a == b
    assert len(a) == 64


def test_round_trip_stable_for_formation():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    assert round_trip_stable(formation) is True


def test_cluster_canonical_order_stable():
    """Canonical form is stable for identical ordered clusters."""
    sel = RemainClusterSelector()
    items_a = [
        ClusterItem(id="id-a", payload="x", encoding=sel._default_encode("x")),
        ClusterItem(id="id-b", payload="y", encoding=sel._default_encode("y")),
        ClusterItem(id="id-c", payload="z", encoding=sel._default_encode("z")),
    ]
    items_b = [
        ClusterItem(id="id-a", payload="x", encoding=sel._default_encode("x")),
        ClusterItem(id="id-b", payload="y", encoding=sel._default_encode("y")),
        ClusterItem(id="id-c", payload="z", encoding=sel._default_encode("z")),
    ]
    assert cluster_canonical(items_a) == cluster_canonical(items_b)


def test_cluster_canonical_is_order_sensitive():
    """A cluster is an ordered sequence: different order -> different hash."""
    sel = RemainClusterSelector()
    items_a = [
        ClusterItem(id="id-a", payload="x", encoding=sel._default_encode("x")),
        ClusterItem(id="id-b", payload="y", encoding=sel._default_encode("y")),
    ]
    items_b = [
        ClusterItem(id="id-b", payload="y", encoding=sel._default_encode("y")),
        ClusterItem(id="id-a", payload="x", encoding=sel._default_encode("x")),
    ]
    assert cluster_canonical(items_a) != cluster_canonical(items_b)


def test_formation_canonical_excludes_uuid():
    """formation_canonical must be content-derived, not instance-derived."""
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    stage = FormationStage()
    f1 = stage.form(result, cluster=cluster)
    f2 = stage.form(result, cluster=cluster)  # different UUID, same content
    assert f1.formation_id != f2.formation_id
    assert formation_canonical(f1) == formation_canonical(f2)


def test_verify_formation_passes_for_matching_remain():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b", "c"], prefix="M")
    result = sel.select(cluster, cluster[1].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    assert verify_formation(result, formation) is True


def test_verify_formation_detects_tampered_encoding():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b", "c"], prefix="M")
    result = sel.select(cluster, cluster[1].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    # Tamper: point the formation at a different remain encoding
    tampered = FormationResult(
        formation_id=formation.formation_id,
        source_remain=formation.source_remain,
        formation_encoding="0" * 64,
        terminal=True,
        reasoning_steps=0,
        direct_index=formation.direct_index,
        provenance=list(formation.provenance),
    )
    assert verify_formation(result, tampered) is False


def test_verify_formation_fails_without_survivor():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, "deadbeef" * 8)
    stage = FormationStage()
    try:
        stage.form(result)
        assert False
    except ValueError:
        pass
    # A remain with no survivor cannot verify any formation
    dummy = object()
    assert verify_formation(result, dummy) is False  # type: ignore[arg-type]


def test_verify_provenance():
    sel = RemainClusterSelector()
    cluster = sel.cluster(["a", "b"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    stage = FormationStage()
    formation = stage.form(result, cluster=cluster)
    expected = [
        f"rcs0:cluster_size={result.cluster_size}",
        f"rcs0:matched_count={result.matched_count}",
        f"rcs0:direct_index={result.direct_index}",
        f"rcs0:reasoning_steps={result.reasoning_steps}",
    ]
    assert verify_provenance(formation, expected) is True
    assert verify_provenance(formation, ["tampered"]) is False


def test_canonical_replay_uses_canonical_id():
    """Two formations with identical content share a canonical id."""
    sel = RemainClusterSelector()
    cluster = sel.cluster(["alpha", "beta"], prefix="M")
    result = sel.select(cluster, cluster[0].encoding)
    stage = FormationStage()
    f1 = stage.form(result, cluster=cluster)
    f2 = stage.form(result, cluster=cluster)
    assert formation_canonical(f1) == formation_canonical(f2)
    assert f1.formation_id != f2.formation_id


# ---------------------------------------------------------------------------
# Secret-backed authenticity (HMAC over canonical bytes)

# ---------------------------------------------------------------------------
# RWA-1: Read/Write Authority (capability-based access boundary)
# ---------------------------------------------------------------------------
def test_capability_is_expired_default_false():
    cap = make_capability("s", Operation.READ, "t")
    assert cap.is_expired() is False


def test_capability_expires_after_deadline():
    cap = make_capability("s", Operation.READ, "t", expires_at=1.0)
    assert cap.is_expired() is True


def test_read_produces_immutable_snapshot():
    gate = ReadWriteGate()
    cap = make_capability("s", Operation.READ, "target-1")
    snap = gate.read(cap, {"k": "v"})
    assert isinstance(snap, ReadSnapshot)
    assert snap.target == "target-1"
    assert snap.state_hash == canonical_hash({"k": "v"})


def test_write_requires_write_operation():
    gate = ReadWriteGate()
    cap = make_capability("s", Operation.READ, "t")
    req = WriteRequest(cap, "t", {"x": 1}, parent_state=gate.current_hash("t"))
    result = gate.write(req)
    assert result.decision is Decision.DENY
    assert "not WRITE" in result.reason


def test_write_committed_when_authorized():
    """First write to a target commits when parent matches current state."""
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.WRITE, "t", parent_state=parent, authenticator=gate.authenticator)
    req = WriteRequest(cap, "t", {"v": 2}, parent_state=parent)
    result = gate.write(req)
    assert result.decision is Decision.ALLOW
    assert result.new_state_hash == gate.state_hash({"v": 2})
    assert result.previous_state_hash == parent


def test_write_stale_parent_rejected():
    """Optimistic concurrency: stale parent cannot overwrite newer state."""
    gate = ReadWriteGate()
    parent0 = gate.current_hash("t")
    cap0 = make_capability("s", Operation.WRITE, "t", parent_state=parent0, authenticator=gate.authenticator)
    gate.write(WriteRequest(cap0, "t", {"v": 2}, parent_state=parent0))
    cap1 = make_capability("s", Operation.WRITE, "t", parent_state=parent0, authenticator=gate.authenticator)
    req = WriteRequest(cap1, "t", {"v": 3}, parent_state=parent0)
    result = gate.write(req)
    assert result.decision is Decision.DENY
    assert "stale" in result.reason.lower()
    assert gate.current_hash("t") == gate.state_hash({"v": 2})


def test_write_target_mismatch_denied():
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.WRITE, "other-target", parent_state=parent, authenticator=gate.authenticator)
    req = WriteRequest(cap, "t", {"v": 2}, parent_state=parent)
    result = gate.write(req)
    assert result.decision is Decision.DENY


def test_write_empty_target_denied():
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.WRITE, "", parent_state=parent, authenticator=gate.authenticator)
    req = WriteRequest(cap, "", {"v": 1}, parent_state=parent)
    result = gate.write(req)
    assert result.decision is Decision.DENY


def test_write_records_history_including_denied():
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.READ, "t")
    gate.write(WriteRequest(cap, "t", {"v": 2}, parent_state=parent))
    assert len(gate.history()) == 1
    assert len(gate.denied_writes()) == 1
    assert len(gate.committed_writes()) == 0


def test_read_snapshot_is_immutable_copy():
    """READ(S) -> Snapshot(S), not a mutable reference to S."""
    gate = ReadWriteGate()
    cap = make_capability("s", Operation.READ, "t")
    original = {"shared": [1, 2, 3]}
    snap = gate.read(cap, original)
    snap.payload["shared"].append(99)
    assert original["shared"] == [1, 2, 3]


def test_rwa_invariant_no_direct_mutation():
    """The gate owns authoritative state; callers cannot mutate it directly."""
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.WRITE, "t", parent_state=parent, authenticator=gate.authenticator)
    gate.write(WriteRequest(cap, "t", {"v": 2}, parent_state=parent))
    assert gate.current_hash("t") == gate.state_hash({"v": 2})


def test_rwa_uses_canonical_form_before_authorization():
    """Canonical representation precedes authorization."""
    gate = ReadWriteGate()
    parent = gate.current_hash("t")
    cap = make_capability("s", Operation.WRITE, "t", parent_state=parent, authenticator=gate.authenticator)
    req = WriteRequest(cap, "t", {"v": 2}, parent_state=parent)
    result = gate.write(req)
    assert result.previous_state_hash == parent
print("appended")


# ---------------------------------------------------------------------------
# ATC-1: Atomic Transaction Control (graph consistency under failure)
# ---------------------------------------------------------------------------
def test_atomic_transaction_committed_keeps_state():
    g = LineageGraph()
    g.add_root("r")
    atc = AtomicTransaction(g)

    def mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        n = graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append(n.state_hash)
        provenance.append("atc:proposed")
        return created

    status, created, _ = atc.run(mutate, tx_id="t1")
    assert status is TxStatus.COMMITTED
    assert len(created) == 1
    assert len(g._nodes) == 2


def test_atomic_transaction_rollback_on_exception():
    g = LineageGraph()
    g.add_root("r")
    before_count = len(g._nodes)
    atc = AtomicTransaction(g)

    def mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append("dummy")
        raise RuntimeError("simulated crash")

    status, created, reason = atc.run(mutate, tx_id="t2")
    assert status is TxStatus.ROLLED_BACK
    assert len(g._nodes) == before_count
    assert "crash" in reason.lower()


def test_atomic_transaction_history_records_both_outcomes():
    g = LineageGraph()
    g.add_root("r")
    atc = AtomicTransaction(g)

    def ok(graph, created, provenance):
        parent = list(graph._nodes)[0]
        n = graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append(n.state_hash)
        return created

    def bad(graph, created, provenance):
        raise ValueError("nope")

    atc.run(ok, tx_id="ok")
    atc.run(bad, tx_id="bad")
    assert len(atc.committed()) == 1
    assert len(atc.rolled_back()) == 1


def test_verify_graph_consistent_clean_graph():
    g = LineageGraph()
    g.add_root("r")
    ok, problems = verify_graph_consistent(g)
    assert ok is True
    assert problems == []


def test_verify_graph_consistent_after_proposal():
    g = LineageGraph()
    root = g.add_root("r")
    g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    ok, _ = verify_graph_consistent(g)
    assert ok is True


def test_verify_graph_consistent_detects_missing_parent():
    g = LineageGraph()
    g.add_root("r")
    # Inject a node with a dangling parent link
    from soe_ddci.lgc import LineageNode
    g._nodes["dangling"] = LineageNode(
        state_hash="dangling",
        parent_hash="does-not-exist",
        formation_hash="",
        author="x",
        operation_hash="o",
        capability_id="c",
    )
    ok, problems = verify_graph_consistent(g)
    assert ok is False
    assert len(problems) >= 1


def test_snapshot_is_immutable_copy():
    g = LineageGraph()
    g.add_root("r")
    atc = AtomicTransaction(g)
    snap = atc.snapshot()
    # Mutating the graph must not affect the snapshot
    g.add_root("r2")
    assert snap.root == "r"


def test_tx_record_to_dict():
    g = LineageGraph()
    g.add_root("r")
    atc = AtomicTransaction(g)

    def mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        n = graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append(n.state_hash)
        return created

    atc.run(mutate, tx_id="t1")
    rec = atc.history()[0]
    d = rec.to_dict()
    assert d["tx_id"] == "t1"
    assert d["status"] == "committed"
    assert len(d["node_hashes"]) == 1


def test_tx_status_values():
    assert TxStatus.PENDING.value == "pending"
    assert TxStatus.COMMITTED.value == "committed"
    assert TxStatus.ROLLED_BACK.value == "rolled_back"
    assert TxStatus.FAILED.value == "failed"


# ---------------------------------------------------------------------------
# DRC-1: Durable Recovery & Checkpoint Control
# ---------------------------------------------------------------------------
def test_drc_checkpoint_records_snapshot():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    cp = drc.checkpoint()
    assert cp.checkpoint_id == "cp-0"
    assert cp.snapshot.root == "r"
    assert len(drc.checkpoints()) == 1


def test_drc_journal_records_transaction():
    g = LineageGraph()
    g.add_root("r")
    atc = AtomicTransaction(g)
    drc = DurableRecovery(g)

    def mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        n = graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append(n.state_hash)
        return created

    tx_rec = atc.run(mutate, tx_id="t1")
    # atc.run returns (status, created, reason); build a TxRecord manually
    rec = TxRecord(
        tx_id="t1",
        status=tx_rec[0],
        snapshot_before=drc.snapshot() if hasattr(drc, "snapshot") else None,
        snapshot_after=None,
        node_hashes=tx_rec[1],
    )
    drc.journal_tx(rec)
    assert len(drc.journal()) == 1
    assert drc.journal()[0].tx_id == "t1"


def test_drc_recover_empty_returns_empty():
    g = LineageGraph()
    drc = DurableRecovery(g)
    result = drc.recover()
    assert result.status is RecoveryStatus.EMPTY


def test_drc_recover_after_checkpoint():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()
    result = drc.recover()
    assert result.status in (RecoveryStatus.CLEAN, RecoveryStatus.RECOVERED)
    assert result.recovered_from == "cp-0"


def test_drc_recovery_result_to_dict():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()
    result = drc.recover()
    d = result.to_dict()
    assert "status" in d
    assert "checkpoints_used" in d


def test_checkpoint_to_dict():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    cp = drc.checkpoint()
    d = cp.to_dict()
    assert d["checkpoint_id"] == "cp-0"
    assert d["root"] == "r"
    assert "marker" in d


def test_journal_entry_to_dict():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    entry = JournalEntry(
        tx_id="t1",
        status=TxStatus.COMMITTED,
        node_hashes=["h1"],
        parent_links=[("r", "h1")],
    )
    d = entry.to_dict()
    assert d["tx_id"] == "t1"
    assert d["status"] == "committed"
    assert d["parent_links"] == [["r", "h1"]]


def test_recovery_status_values():
    assert RecoveryStatus.CLEAN.value == "clean"
    assert RecoveryStatus.RECOVERED.value == "recovered"
    assert RecoveryStatus.INCONSISTENT.value == "inconsistent"
    assert RecoveryStatus.EMPTY.value == "empty"


def test_drc_last_valid_after_checkpoint():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    assert drc.last_valid() is None
    drc.checkpoint()
    assert drc.last_valid() is not None
    assert drc.last_valid().root == "r"


# ---------------------------------------------------------------------------
# DRC-1 durability semantics: replay idempotency + commit-before-visibility
# ---------------------------------------------------------------------------
def test_replay_is_idempotent():
    """Replay(J, J) = Replay(J): a second recovery replays nothing new and
    leaves the graph identical to the first recovery."""
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()
    parent = list(g._nodes)[0]
    n = g.propose(parent, {"v": 1}, author="a", capability_id="c1")
    drc.journal_tx(
        TxRecord(
            tx_id="t1",
            status=TxStatus.COMMITTED,
            snapshot_before=None,
            snapshot_after=None,
            node_hashes=[n.state_hash],
        )
    )
    first = drc.recover()
    heads_after_first = {h.state_hash for h in g.heads()}
    second = drc.recover()
    heads_after_second = {h.state_hash for h in g.heads()}
    # The second recovery replays no new entries (cursor already advanced)
    assert second.journal_entries_replayed == 0
    # And the graph state is identical
    assert heads_after_first == heads_after_second
def test_replay_cursor_advances_after_recovery():
    """The replay cursor equals the journal length after a clean recovery.

    A checkpoint advances the cursor past every journal entry it already
    reflects, so a subsequent recovery replays nothing and the cursor is
    stable at len(journal). That is the idempotent endpoint.
    """
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()  # cursor = 0, journal empty
    # Journal a committed transaction whose node is already in the graph
    parent = list(g._nodes)[0]
    n = g.propose(parent, {"v": 1}, author="a", capability_id="c1")
    drc.journal_tx(
        TxRecord(
            tx_id="t1",
            status=TxStatus.COMMITTED,
            snapshot_before=None,
            snapshot_after=None,
            node_hashes=[n.state_hash],
        )
    )
    # Checkpoint again: the node is now in the snapshot, so the cursor
    # advances past the journal entry.
    drc.checkpoint()
    assert drc._replay_cursor == len(drc.journal())
    before = drc._replay_cursor
    drc.recover()
    # Recovery replays nothing new; cursor is unchanged
    assert drc._replay_cursor == before
def test_commit_head_records_durable_marker():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.commit_head("head-1", marker="m1")
    assert drc.has_commit_record("head-1") is True
    assert drc.has_commit_record("head-2") is False


def test_checkpoint_records_durable_commit_for_heads():
    """visible head = H  =>  H has a durable commit record."""
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()
    for h in g.heads():
        assert drc.has_commit_record(h.state_hash) is True


def test_commit_before_visibility_invariant():
    """Every visible head carries a durable commit marker after checkpoint."""
    g = LineageGraph()
    root = g.add_root("r")
    g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    drc = DurableRecovery(g)
    drc.checkpoint()
    visible = {h.state_hash for h in g.heads()}
    durable = set(drc._committed_heads.keys())
    assert visible.issubset(durable)


def test_recover_with_no_journal_after_checkpoint_is_clean():
    g = LineageGraph()
    g.add_root("r")
    drc = DurableRecovery(g)
    drc.checkpoint()
    result = drc.recover()
    assert result.status in (RecoveryStatus.CLEAN, RecoveryStatus.RECOVERED)
    assert result.journal_entries_replayed == 0
