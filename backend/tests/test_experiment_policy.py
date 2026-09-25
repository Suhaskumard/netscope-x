"""Phase 80: experiment policies (LinUCB / static / random) and the experiment-driven twin repair."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

import numpy as np
import pytest

from backend.app.models.topology import Edge, Node, TopologyGraph
from backend.dependency.experiment_policy import (
    FEATURE_NAMES,
    LinUCBPolicy,
    RandomPolicy,
    StaticPolicy,
    node_features,
    repair_twin,
)
from backend.dependency.experiment_recommendations import generate_experiment_recommendations

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _graph(names: List[str], pairs: List[Tuple[str, str]]) -> TopologyGraph:
    nodes = [
        Node(node_id=n, ip_addresses=[f"10.0.0.{i + 1}"], first_observed=NOW, last_observed=NOW)
        for i, n in enumerate(names)
    ]
    edges = [
        Edge(edge_id=f"{a}-{b}", source_node_id=a, target_node_id=b, confidence=0.8, evidence=["observed"],
             observation_count=3, first_observed=NOW, last_observed=NOW, protocols=["tcp"])
        for a, b in pairs
    ]
    return TopologyGraph(graph_id="g", generated_at=NOW, nodes=nodes, edges=edges)


PATH = _graph(list("abcde"), [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")])


def test_features_are_deterministic_and_reflect_structure() -> None:
    one, two = node_features(PATH), node_features(PATH)
    assert set(one) == set("abcde") and all(len(v) == len(FEATURE_NAMES) for v in one.values())
    assert all(np.array_equal(one[k], two[k]) for k in one)
    articulation = FEATURE_NAMES.index("is_articulation_point")
    assert one["c"][articulation] == 1.0 and one["a"][articulation] == 0.0
    stranded = FEATURE_NAMES.index("predicted_stranded_fraction")
    assert one["c"][stranded] > one["a"][stranded]
    repaired = FEATURE_NAMES.index("adjacent_to_repaired_node")
    assert node_features(PATH, frozenset({"a"}))["b"][repaired] == 1.0


def test_linucb_never_reselects_a_tested_node_and_stops_when_done() -> None:
    policy = LinUCBPolicy()
    tested = set()
    for _ in range(5):
        node = policy.select(PATH, tested)
        assert node is not None and node not in tested
        policy.update(node, 0.5)
        tested.add(node)
    assert policy.select(PATH, tested) is None


def test_linucb_learns_to_prefer_high_reward_nodes() -> None:
    """Reward 1 for articulation points, 0 for leaves: after training, pure exploitation picks an
    articulation point first, whereas an untrained policy falls back to the lowest id (a leaf)."""
    trainer = LinUCBPolicy(alpha=1.0)
    for _ in range(6):
        tested: set = set()
        for _ in range(5):
            node = trainer.select(PATH, tested)
            trainer.update(node, 1.0 if node in {"b", "c", "d"} else 0.0)
            tested.add(node)
    exploit = LinUCBPolicy.from_state(trainer.state(), alpha=0.0)
    assert exploit.select(PATH, set()) in {"b", "c", "d"}
    assert LinUCBPolicy(alpha=0.0).select(PATH, set()) == "a"


def test_state_round_trip() -> None:
    a = LinUCBPolicy()
    a.select(PATH, set())
    a.update("a", 0.7)
    b = LinUCBPolicy.from_state(a.state())
    assert np.array_equal(a.A, b.A) and np.array_equal(a.b, b.b)
    assert a.select(PATH, {"a"}) == b.select(PATH, {"a"})


def test_static_policy_follows_phase_67_order_and_can_run_out() -> None:
    star = _graph(list("hxyz"), [("h", "x"), ("h", "y"), ("h", "z")])
    recommended = [r.node_id for r in generate_experiment_recommendations(star)]
    policy = StaticPolicy(star)
    order, tested = [], set()
    while (node := policy.select(star, tested)) is not None:
        order.append(node)
        tested.add(node)
    assert order == recommended and len(order) < len(star.nodes)  # leaves are never recommended
    assert policy.select(star, set(), frozenset({"h"})) == recommended[0]  # never revised after repairs


def test_random_policy_is_seeded_and_never_repeats() -> None:
    def run(seed: int):
        policy, tested = RandomPolicy(seed), set()
        while (node := policy.select(PATH, tested)) is not None:
            tested.add(node)
            yield node

    assert list(run(1)) == list(run(1)) and sorted(run(1)) == list("abcde")
    assert list(run(1)) != list(run(2))


def test_repair_bridges_a_false_stranding() -> None:
    twin = _graph(list("abc"), [("a", "b"), ("b", "c")])  # the a-c edge was never observed
    edges_before = list(twin.edges)
    result = repair_twin(twin, "b", ["a", "c"])  # reality: a and c stayed connected without b
    assert result.bridges == [("a", "c")] and result.missing_stranding_count == 0
    bridge = result.graph.edges[-1]
    assert bridge.edge_id.startswith("experiment-bridge:") and "unidentified" in bridge.evidence[0]
    assert bridge.confidence == 0.5 and len(result.graph.edges) == 3
    assert twin.edges == edges_before  # input never modified


def test_repair_is_a_no_op_when_the_twin_already_agrees() -> None:
    twin = _graph(list("abc"), [("a", "b"), ("b", "c")])
    result = repair_twin(twin, "b", ["a"])  # reality: c really is stranded
    assert result.bridges == [] and result.graph is twin and result.missing_stranding_count == 0


def test_repair_reports_stranding_it_cannot_fix() -> None:
    twin = _graph(list("abc"), [("a", "b"), ("b", "c"), ("a", "c")])  # a spurious a-c edge
    result = repair_twin(twin, "b", ["a"])  # reality: c stranded, twin thinks a-c connected
    assert result.bridges == [] and result.missing_stranding_count == 1


def test_repair_rejects_unknown_nodes_and_uses_nearest_nodes_for_multi_node_components() -> None:
    twin = _graph(list("abcde"), [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")])
    with pytest.raises(ValueError):
        repair_twin(twin, "zzz", [])
    result = repair_twin(twin, "c", ["a", "b", "d", "e"])  # reality: {a,b} and {d,e} still connected
    assert len(result.bridges) == 1
    a, b = result.bridges[0]
    assert {a, b} in ({"b", "d"},)  # the bridge joins the failed node's own former neighbours
