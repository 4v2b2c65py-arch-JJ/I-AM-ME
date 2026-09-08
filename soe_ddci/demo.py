"""Demonstration of the SOE-DDCI architecture.

Run: python3 -m soe_ddci.demo
"""

from soe_ddci import (
    AtomicTransaction,
    Authenticator,
    DurableRecovery,
    EntityConfig,
    JoinRequest,
    LineageGraph,
    Operation,
    ReadWriteGate,
    RemainClusterSelector,
    SOEDDCIEngine,
    State,
    WriteRequest,
    canonical_bytes,
    formation_canonical,
    make_capability,
    round_trip_stable,
    verify_graph_consistent,
    verify_formation,
)


def _process_section(engine, inputs):
    for i, data in enumerate(inputs, start=1):
        out = engine.process(data)
        print(f"\n[session-1] step {i}")
        print(f"  state      : {out['state_before']} -> {out['state_after']}")
        print(f"  action     : {out['action']}")
        print(f"  confidence : {out['confidence']:.4f}")


def main():
    cfg = EntityConfig(
        objective_type="single",
        objective_target="ARCHIVED",
        objective_priority=1.0,
        initial_state=State.CREATED,
    )
    engine = SOEDDCIEngine(cfg, session_id="session-1")

    print("=" * 60)
    print("SOE-DDCI DEMO")
    print("=" * 60)

    _process_section(engine, [
        {"text": "initial observation", "source": "user"},
        {"text": "related fact A", "source": "knowledge"},
        {"text": "related fact B", "source": "knowledge"},
        {"text": "contradiction detected", "source": "validator"},
    ])

    print("\n" + "-" * 60)
    print("CROSS-SESSION CONTINUITY")
    engine.new_session("session-2")
    out = engine.process({"text": "resume after pause", "source": "user"})
    print(f"\n[session-2] state: {out['state_before']} -> {out['state_after']}")
    print(f"  history depth: {len(engine.event_log)} events")
    print(f"  sessions seen : {engine.event_log.sessions()}")

    print("\n" + "-" * 60)
    print("RCS-0 + UTT + F4")
    cluster = ["alpha", "beta", "gamma", "delta"]
    seq = RemainClusterSelector()._default_encode("gamma")
    survivor, remain_result, formation = engine.produce_formation(cluster, seq)
    print(f"  cluster          : {cluster}")
    print(f"  direct_index     : {remain_result.direct_index}   (address)")
    print(f"  reasoning_steps  : {remain_result.reasoning_steps}   (zero, not inferred)")
    print(f"  remains          : {[x.payload for x in remain_result.remains]}   (artifact)")
    print(f"  formation_id     : {formation.formation_id}")
    print(f"  terminal         : {formation.terminal}")

    print("\n" + "-" * 60)
    print("REPLAY DETERMINISM")
    e2 = SOEDDCIEngine(session_id="r2")
    _, _, f2 = e2.produce_formation(cluster, seq)
    print(f"  instance id differs : {formation.formation_id != f2.formation_id}")
    print(f"  content id matches  : {formation.formation_encoding == f2.formation_encoding}")

    print("\n" + "-" * 60)
    print("CANONICALIZATION & TAMPER RESISTANCE")
    print(f"  verify_formation   : {verify_formation(remain_result, formation)}")
    from soe_ddci import FormationResult
    tampered = FormationResult(
        formation_id=formation.formation_id,
        source_remain=formation.source_remain,
        formation_encoding="0" * 64,
        terminal=True,
        reasoning_steps=0,
        direct_index=formation.direct_index,
        provenance=list(formation.provenance),
    )
    print(f"  verify (tampered)  : {verify_formation(remain_result, tampered)}  (rejected)")
    print(f"  canonical id       : {formation_canonical(formation)}")
    print(f"  round-trip stable  : {round_trip_stable(formation)}")

    print("\n" + "-" * 60)
    print("SECRET-BACKED AUTHENTICITY")
    auth = Authenticator(b"top-secret-key")
    tag = auth.sign(formation)
    print(f"  verify (authentic): {auth.verify(formation, tag)}")
    attacker = Authenticator(b"attacker-key")
    print(f"  verify (attacker) : {attacker.verify(formation, tag)}  (rejected)")

    print("\n" + "-" * 60)
    print("RWA-1: READ/WRITE AUTHORITY")
    gate = ReadWriteGate()
    parent0 = gate.current_hash("target-1")
    cap0 = make_capability(
        "subject-1", Operation.WRITE, "target-1",
        parent_state=parent0, authenticator=gate.authenticator,
    )
    r0 = gate.write(WriteRequest(cap0, "target-1", {"v": 2}, parent_state=parent0))
    print(f"  write #1 (authorized) : {r0.decision.value} -> {r0.new_state_hash[:16]}...")
    cap1 = make_capability(
        "subject-1", Operation.WRITE, "target-1",
        parent_state=parent0, authenticator=gate.authenticator,
    )
    r1 = gate.write(WriteRequest(cap1, "target-1", {"v": 3}, parent_state=parent0))
    print(f"  write #2 (stale parent): {r1.decision.value}  ({r1.reason})")
    cap_r = make_capability("subject-1", Operation.READ, "target-1")
    snap = gate.read(cap_r, {"v": 2})
    print(f"  read snapshot state_hash: {snap.state_hash[:16]}...")
    print(f"  committed writes: {len(gate.committed_writes())}")
    print(f"  denied writes   : {len(gate.denied_writes())}")
    print(f"  total history   : {len(gate.history())}")

    print("\n" + "-" * 60)
    print("LGC-1: LINEAGE & GRAPH CONTROL")
    print("-" * 60)
    print("Verifiable state graph with fork detection and explicit joins.")
    g = LineageGraph()
    root = g.add_root("root-state")
    a = g.propose(root.state_hash, {"v": 1}, author="writer-A", capability_id="cap-A")
    b = g.propose(root.state_hash, {"v": 2}, author="writer-B", capability_id="cap-B")
    fork = g.detect_fork(root.state_hash)
    print(f"  fork detected     : {fork.is_fork}")
    print(f"  children          : {len(fork.children)}")
    cap = make_capability("writer-A", Operation.WRITE, "target-1")
    join_req = JoinRequest(
        parents=[a.state_hash, b.state_hash],
        merge_operation="merge",
        capability=cap,
        conflict_resolution={"v": 99},
    )
    jr = g.join(join_req)
    print(f"  join decision     : {jr.decision}")
    print(f"  contributing      : {len(jr.contributing_parents)}")
    print(f"  merged hash       : {jr.merged_state_hash[:16]}...")

    print("\n" + "-" * 60)
    print("ATC-1: ATOMIC TRANSACTION CONTROL")
    print("-" * 60)
    print("Graph consistency under failure: full commit or clean rollback.")
    g2 = LineageGraph()
    g2.add_root("root")
    atc = AtomicTransaction(g2)

    def ok_mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        n = graph.propose(parent, {"v": 1}, author="a", capability_id="c1")
        created.append(n.state_hash)
        provenance.append("atc:proposed")
        return created

    def crash_mutate(graph, created, provenance):
        parent = list(graph._nodes)[0]
        graph.propose(parent, {"v": 2}, author="b", capability_id="c2")
        raise RuntimeError("simulated crash mid-flight")

    s1, c1, _ = atc.run(ok_mutate, tx_id="commit-1")
    print(f"  tx commit-1      : {s1.value}  ({len(c1)} node(s))")
    s2, c2, reason = atc.run(crash_mutate, tx_id="crash-1")
    print(f"  tx crash-1        : {s2.value}  ({reason})")
    ok, problems = verify_graph_consistent(g2)
    print(f"  graph consistent : {ok}  ({len(problems)} problems)")
    print(f"  committed tx     : {len(atc.committed())}")
    print(f"  rolled back tx    : {len(atc.rolled_back())}")

    print("\n" + "-" * 60)
    print("DRC-1: DURABLE RECOVERY & CHECKPOINT CONTROL")
    print("-" * 60)
    print("Crash recovery across process/runtime boundaries.")
    print("restart(G) -> G_last_valid_committed")
    g3 = LineageGraph()
    g3.add_root("root")
    drc = DurableRecovery(g3)
    drc.checkpoint()
    # Simulate a committed transaction then a crash
    parent = list(g3._nodes)[0]
    g3.propose(parent, {"v": 1}, author="a", capability_id="c1")
    drc.checkpoint()
    result = drc.recover()
    print(f"  recovery status   : {result.status.value}")
    print(f"  recovered from    : {result.recovered_from}")
    print(f"  checkpoints used  : {len(result.checkpoints_used)}")
    print(f"  journal replayed  : {result.journal_entries_replayed}")
    print(f"  last valid root   : {drc.last_valid().root if drc.last_valid() else None}")

    print("\n" + "=" * 60)
    print(f"Final state: {engine.state.value}")
    print(f"Total events: {len(engine.event_log)}")
    print("=" * 60)


if __name__ == "__main__":
    main()