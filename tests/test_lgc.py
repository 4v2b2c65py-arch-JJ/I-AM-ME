"""LGC-1: Lineage & Graph Control tests."""

from soe_ddci import (
    Capability,
    JoinRequest,
    LineageGraph,
    LineageNode,
    NodeStatus,
    Operation,
)


def test_lineage_graph_add_root():
    g = LineageGraph()
    n = g.add_root("root-hash", formation_hash="f1", author="system")
    assert n.state_hash == "root-hash"
    assert n.parent_hash is None
    assert len(g.heads()) == 1


def test_propose_creates_child_and_moves_head():
    g = LineageGraph()
    root = g.add_root("r")
    child = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    assert child is not None
    assert child.parent_hash == root.state_hash
    assert len(g.heads()) == 1
    assert g.heads()[0].state_hash == child.state_hash


def test_propose_unknown_parent_returns_none():
    g = LineageGraph()
    assert g.propose("missing", {"v": 1}, author="a", capability_id="c1") is None


def test_detect_fork_single_child_is_not_fork():
    g = LineageGraph()
    root = g.add_root("r")
    g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    fork = g.detect_fork(root.state_hash)
    assert fork.is_fork is False
    assert len(fork.children) == 1


def test_detect_fork_two_children_is_fork():
    g = LineageGraph()
    root = g.add_root("r")
    g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    g.propose(root.state_hash, {"v": 2}, author="b", capability_id="c2")
    fork = g.detect_fork(root.state_hash)
    assert fork.is_fork is True
    assert len(fork.children) == 2


def test_lineage_chain_walks_to_root():
    g = LineageGraph()
    r = g.add_root("r")
    c1 = g.propose(r.state_hash, {"v": 1}, author="a", capability_id="c1")
    c2 = g.propose(c1.state_hash, {"v": 2}, author="a", capability_id="c1")
    chain = g.lineage(c2.state_hash)
    assert [n.state_hash for n in chain] == ["r", c1.state_hash, c2.state_hash]


def test_is_ancestor():
    g = LineageGraph()
    r = g.add_root("r")
    c1 = g.propose(r.state_hash, {"v": 1}, author="a", capability_id="c1")
    c2 = g.propose(c1.state_hash, {"v": 2}, author="a", capability_id="c1")
    assert g.is_ancestor(r.state_hash, c2.state_hash) is True
    assert g.is_ancestor(c2.state_hash, r.state_hash) is False


def test_verify_lineage_valid():
    g = LineageGraph()
    r = g.add_root("r")
    c = g.propose(r.state_hash, {"v": 1}, author="a", capability_id="c1")
    assert g.verify_lineage(c.state_hash) is True
    assert g.verify_lineage(r.state_hash) is True


def test_join_unknown_parent_denied():
    g = LineageGraph()
    root = g.add_root("r")
    cap = Capability("c1", "s", Operation.WRITE, "t")
    req = JoinRequest(parents=["missing"], merge_operation="merge", capability=cap)
    result = g.join(req)
    assert result.decision == "denied"


def test_join_single_parent_commits():
    g = LineageGraph()
    root = g.add_root("r")
    c = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    cap = Capability("c1", "s", Operation.WRITE, "t")
    req = JoinRequest(parents=[c.state_hash], merge_operation="merge", capability=cap)
    result = g.join(req)
    assert result.decision == "committed"
    assert result.merged_state_hash is not None


def test_join_conflict_without_resolution():
    g = LineageGraph()
    root = g.add_root("r")
    a = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    b = g.propose(root.state_hash, {"v": 2}, author="b", capability_id="c2")
    cap = Capability("c1", "s", Operation.WRITE, "t")
    req = JoinRequest(parents=[a.state_hash, b.state_hash], merge_operation="merge", capability=cap)
    result = g.join(req)
    assert result.decision == "conflict"


def test_join_with_resolution_commits():
    g = LineageGraph()
    root = g.add_root("r")
    a = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    b = g.propose(root.state_hash, {"v": 2}, author="b", capability_id="c2")
    cap = Capability("c1", "s", Operation.WRITE, "t")
    req = JoinRequest(
        parents=[a.state_hash, b.state_hash],
        merge_operation="merge",
        capability=cap,
        conflict_resolution={"v": 99},
    )
    result = g.join(req)
    assert result.decision == "committed"
    assert result.merged_state_hash is not None
    assert len(result.contributing_parents) == 2


def test_join_records_contributing_parents():
    g = LineageGraph()
    root = g.add_root("r")
    a = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    b = g.propose(root.state_hash, {"v": 2}, author="b", capability_id="c2")
    cap = Capability("c1", "s", Operation.WRITE, "t")
    req = JoinRequest(
        parents=[a.state_hash, b.state_hash],
        merge_operation="merge",
        capability=cap,
        conflict_resolution={"v": 5},
    )
    result = g.join(req)
    assert set(result.contributing_parents) == {a.state_hash, b.state_hash}


def test_node_status_default_active():
    g = LineageGraph()
    n = g.add_root("r")
    assert n.status is NodeStatus.ACTIVE


def test_lineage_node_to_dict():
    n = LineageNode(
        state_hash="h",
        parent_hash="p",
        formation_hash="f",
        author="a",
        operation_hash="o",
        capability_id="c",
    )
    d = n.to_dict()
    assert d["state_hash"] == "h"
    assert d["parent_hash"] == "p"
    assert d["status"] == "active"


def test_fork_result_to_dict():
    g = LineageGraph()
    root = g.add_root("r")
    a = g.propose(root.state_hash, {"v": 1}, author="a", capability_id="c1")
    b = g.propose(root.state_hash, {"v": 2}, author="b", capability_id="c2")
    fork = g.detect_fork(root.state_hash)
    d = fork.to_dict()
    assert d["is_fork"] is True
    assert len(d["children"]) == 2