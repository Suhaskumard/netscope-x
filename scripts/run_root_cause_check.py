"""Phase 101 check: rank root causes for a real seeded capture's most damaging node failure and print the ranking."""
from __future__ import annotations

import tempfile
from pathlib import Path

from backend.app.models.failure import FailureScenario, FailureType
from backend.nettrace.topology.graph import build_topology_graph
from backend.nlq.rootcause import rank_root_causes
from backend.simulation.failure_propagation_pipeline import run_failure_propagation_pipeline
from scripts.seed_attribution_demo import seed


def main() -> None:
    root = Path(tempfile.mkdtemp())
    cid = seed(root, "small")["capture_id"]
    g = build_topology_graph(root, cid, graph_id=cid)
    cut = lambda n: len(run_failure_propagation_pipeline(g, FailureScenario(scenario_id="s", failure_type=FailureType.NODE_FAILURE, target_node_id=n), []).newly_unreachable_node_ids)
    failed = max((n.node_id for n in g.nodes), key=lambda n: (cut(n), n))
    out = rank_root_causes(g, failed)
    print(f"failed={failed} impacted={out['impacted_node_ids']}")
    for r in out["ranking"][:10]:
        print(f"#{r['rank']} score={r['score']:.2f} [{r['scenario_id']}] {r['explanation']}")
    print(out["caveat"])


if __name__ == "__main__":
    main()
