"""Investigation report demo / check (Phase 100).

    python -m scripts.run_report_check [--level small] [--node busiest]

Seeds a real capture, builds the cited report for every dependency (deterministic template, no key needed) and prints one
report with its citation table. If ANTHROPIC_API_KEY (and the `anthropic` package) is available it also asks the real model
to draft each report and counts how many drafts pass the code-side verification vs fall back to the template; otherwise that
half prints NOT RUN and no real-model result is claimed.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from collections import Counter
from pathlib import Path

from backend.app.core.config import get_settings
from backend.dependency.causal_candidates import generate_causal_candidates
from backend.dependency.strength import estimate_dependency_strength
from backend.nettrace.topology.discovery import discover_nodes
from backend.nettrace.topology.edges import discover_edges
from backend.nettrace.topology.graph import build_topology_graph
from backend.nlq.llm import AnthropicClient, LLMUnavailableError
from backend.nlq.report import generate_report
from scripts.seed_attribution_demo import seed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", default="small")
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp()) / "art"
    os.environ["NETSCOPE_ARTIFACT_ROOT"] = str(root)
    get_settings.cache_clear()
    st = get_settings()
    cid = seed(root, args.level)["capture_id"]
    graph = build_topology_graph(root, cid, graph_id=cid)
    deps = estimate_dependency_strength(root, cid)
    edges = discover_edges(root, cid, discover_nodes(root, cid))
    cands = generate_causal_candidates(deps, strength_threshold=st.causal_candidate_strength_threshold)
    busiest = max(graph.nodes, key=lambda n: sum(n.node_id in (e.source_node_id, e.target_node_id) for e in graph.edges)).node_id

    def build(i, llm):
        d = deps[i]
        cand = next((c for c in cands if c.dependency_id == d.dependency_id), None)
        return generate_report(graph, d, edges[i].confidence, cand, busiest, st, llm, cands)

    first = build(0, None)
    print(first["markdown"], "\n\nCITATIONS")
    for c in first["citations"]:
        print(f"  [{c['fact_id']}] {c['source']} = {c['value']!r}")
    print(f"\n{len(deps)} dependencies; template reports built for all: {all(build(i, None)['source'] == 'template' for i in range(len(deps)))}")
    try:
        llm = AnthropicClient()
    except LLMUnavailableError as exc:
        print(f"REAL-LLM HALF NOT RUN: {exc}. No result is claimed for a real model.")
        return 0
    tally = Counter(build(i, llm)["source"] for i in range(len(deps)))
    print(f"real model drafts: {dict(tally)} (llm = passed verification, template = fell back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
