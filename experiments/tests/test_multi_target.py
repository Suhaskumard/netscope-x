"""Phase 73 multi-target failure/counterfactual sweep unit tests (pure, no Docker).

Target selection is checked on the real declared topologies; the sweep
itself is checked by running the REAL matrix cell (real PathForge and
counterfactual execution, real scoring). See
`docs/architecture/experimental_matrix.md`'s "Phase 73" section for real
numbers from a full run.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import pytest

import experiments.matrix_runner as matrix_runner
from backend.app.models.metric import MetricContext
from backend.dependency.criticality import NodeCriticality
from experiments.matrix_runner import TOPOLOGY_LEVELS, _pick_failure_targets, format_target_report, run_matrix_cell
from experiments.synthetic_traffic import assign_ips, build_ground_truth_graph


def _targets(level: str, k: int = 3):
    roles, edges = TOPOLOGY_LEVELS[level]()
    graph = build_ground_truth_graph(roles, edges, assign_ips(list(roles)), graph_id="gt")
    return [t.node_id for t in _pick_failure_targets(graph, k)]


def test_star_yields_hub_and_one_leaf_not_interchangeable_leaves() -> None:
    targets = _targets("medium")
    assert targets[0] == "hub"
    assert len(targets) == 2 and targets[1].startswith("leaf-")


def test_chain_yields_middle_then_one_end() -> None:
    assert _targets("small") == ["node-2", "node-1"]


def test_targets_are_criticality_ordered_distinct_and_deterministic() -> None:
    roles, edges = TOPOLOGY_LEVELS["dynamic"]()
    graph = build_ground_truth_graph(roles, edges, assign_ips(list(roles)), graph_id="gt")
    first = _pick_failure_targets(graph, 3)
    assert len(first) == 3
    assert len({t.node_id for t in first}) == 3
    keys = [(t.path_dependency_impact, t.betweenness_centrality, t.degree_centrality) for t in first]
    assert keys == sorted(keys, reverse=True)
    assert [t.node_id for t in _pick_failure_targets(graph, 3)] == [t.node_id for t in first]


def test_k_caps_the_target_count() -> None:
    assert len(_targets("dynamic", k=1)) == 1


def test_cell_scores_every_target_and_headline_is_the_mean(tmp_path: Path) -> None:
    cell = run_matrix_cell(tmp_path / "artifacts", "dynamic", 1.0, seed=1, packets_per_edge=8)
    for context_name, context in (("pathforge", MetricContext.PATHFORGE), ("counterfactual", MetricContext.COUNTERFACTUAL)):
        raw = cell.raw_evaluations[context_name]
        f1s = [t["affected_node_f1"] for t in raw["targets"]]
        assert len(f1s) == raw["aggregate"]["target_count"] == 3
        assert [t["criticality_rank"] for t in raw["targets"]] == [1, 2, 3]
        assert raw["aggregate"]["f1"]["mean"] == pytest.approx(statistics.fmean(f1s))
        headline = next(m for m in cell.metrics if m.context == context)
        assert headline.f1 == pytest.approx(statistics.fmean(f1s))
        mean = statistics.fmean(f1s)
        expected_shift = max(abs(mean - (sum(f1s) - f) / (len(f1s) - 1)) for f in f1s)
        assert raw["aggregate"]["max_leave_one_out_f1_shift"] == pytest.approx(expected_shift)
    assert set(cell.raw_evaluations["resilience_indicators"]) == {
        t["target"] for t in cell.raw_evaluations["pathforge"]["targets"]
    }
    assert cell.experiment.configuration["failure_target_count"] == 3


def test_unobserved_target_is_skipped_and_reported_never_substituted(tmp_path: Path, monkeypatch) -> None:
    real_pick = matrix_runner._pick_failure_targets

    def with_ghost(graph, k):
        ghost = NodeCriticality(
            node_id="ghost", degree_centrality=1.0, betweenness_centrality=1.0,
            is_articulation_point=True, path_dependency_impact=99, mean_incident_edge_confidence=None,
        )
        return [ghost] + real_pick(graph, k)

    monkeypatch.setattr(matrix_runner, "_pick_failure_targets", with_ghost)
    cell = run_matrix_cell(tmp_path / "artifacts", "medium", 1.0, seed=1, packets_per_edge=8)
    raw = cell.raw_evaluations["pathforge"]
    assert raw["aggregate"]["skipped_targets"] == ["ghost"]
    assert "ghost" not in {t["target"] for t in raw["targets"]}
    assert raw["aggregate"]["target_count"] == 2


def test_target_report_has_a_row_per_target_plus_aggregate_and_skips_ablations(tmp_path: Path) -> None:
    cell = run_matrix_cell(tmp_path / "artifacts", "medium", 1.0, seed=1, packets_per_edge=8)
    ablated = run_matrix_cell(tmp_path / "artifacts", "medium", 1.0, seed=1, packets_per_edge=8, ablation="without_temporal")
    report = format_target_report([cell, ablated])
    rows = report.splitlines()[2:]
    targets = cell.raw_evaluations["pathforge"]["targets"]
    assert len(rows) == len(targets) + 1
    assert [r.split(" | ")[2] for r in rows[:-1]] == [t["target"] for t in targets]
    assert "**aggregate** (n=2" in rows[-1] and "LOO shift" in rows[-1]


def test_failed_node_itself_counts_as_affected_so_a_leaf_is_not_zero_by_construction(tmp_path: Path) -> None:
    # A star leaf strands nobody; PathForge lists only the leaf itself as the primary
    # impact. Before Phase 73 the actual outcome left the failed node out, scoring 0.0.
    cell = run_matrix_cell(tmp_path / "artifacts", "medium", 1.0, seed=1, packets_per_edge=8)
    leaf = next(t for t in cell.raw_evaluations["pathforge"]["targets"] if t["target"].startswith("leaf-"))
    assert leaf["actual_stranded_count"] == 0
    assert leaf["affected_node_f1"] == 1.0
