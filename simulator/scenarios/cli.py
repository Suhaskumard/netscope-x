"""Scenario generation and (for a deployed scenario) ground-truth capture (spec Phase 18).

Generate every archetype's declaration + deployable compose file:
    python -m simulator.scenarios.cli generate-all --root experiments_data

Once a specific generated scenario has actually been brought up
(docker compose -f experiments_data/scenarios/<id>/docker-compose.yml up -d), capture its real
ground truth (container IPs) the same way simulator/ground_truth/cli.py does for the fixed lab:
    python -m simulator.scenarios.cli capture-ground-truth --scenario-id star-4 --root experiments_data
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from backend.app.models import ServiceRole
from experiments.artifacts.io import read_json, write_json
from experiments.artifacts.paths import scenario_compose_path, scenario_declaration_path, scenario_topology_path
from simulator.ground_truth.cli import docker_ip_lookup
from simulator.scenarios.compose import generate_compose
from simulator.scenarios.generate import build_declaration, build_topology_graph
from simulator.scenarios.models import ScenarioArchetype, ScenarioDeclaration, ScenarioSpec
from simulator.scenarios.topologies import (
    ScenarioEdge,
    dynamic_service_network,
    multi_path,
    multi_tier,
    redundant,
    simple_chain,
    star,
)

Generator = Tuple[str, ScenarioArchetype, Dict[str, object], Dict[str, ServiceRole], List[ScenarioEdge]]


def _representative_scenarios() -> List[Generator]:
    chain_roles, chain_edges = simple_chain(4)
    star_roles, star_edges = star(4)
    tier_roles, tier_edges = multi_tier([1, 2, 2, 1])
    redundant_roles, redundant_edges = redundant(4)
    multipath_roles, multipath_edges = multi_path(3)
    dynamic_roles, dynamic_edges = dynamic_service_network(seed=42, n=6)

    return [
        ("simple-chain-4", ScenarioArchetype.SIMPLE_CHAIN, {"n": 4}, chain_roles, chain_edges),
        ("star-4", ScenarioArchetype.STAR, {"n": 4}, star_roles, star_edges),
        ("multi-tier-1-2-2-1", ScenarioArchetype.MULTI_TIER, {"tier_sizes": [1, 2, 2, 1]}, tier_roles, tier_edges),
        ("redundant-4", ScenarioArchetype.REDUNDANT, {"n": 4}, redundant_roles, redundant_edges),
        ("multi-path-3", ScenarioArchetype.MULTI_PATH, {"k": 3}, multipath_roles, multipath_edges),
        (
            "dynamic-6-seed42",
            ScenarioArchetype.DYNAMIC_SERVICE_NETWORK,
            {"seed": 42, "n": 6},
            dynamic_roles,
            dynamic_edges,
        ),
    ]


def generate_all(root: Path) -> None:
    for scenario_id, archetype, params, roles, edges in _representative_scenarios():
        declaration = build_declaration(roles, edges)
        write_json(scenario_declaration_path(root, scenario_id), declaration)

        compose = generate_compose(scenario_id, roles, edges)
        compose_path = scenario_compose_path(root, scenario_id)
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")

        spec = ScenarioSpec(
            scenario_id=scenario_id,
            archetype=archetype,
            parameters=params,
            node_count=len(roles),
            edge_count=len(edges),
        )
        print(
            f"{scenario_id:<20} archetype={archetype.value:<24} "
            f"nodes={spec.node_count:<3} edges={spec.edge_count:<3} -> {compose_path}"
        )


def capture_ground_truth(root: Path, scenario_id: str) -> None:
    declaration = read_json(scenario_declaration_path(root, scenario_id), ScenarioDeclaration)
    roles = declaration.roles
    edges = [ScenarioEdge(e.source, e.target, e.protocols) for e in declaration.edges]

    graph = build_topology_graph(roles, edges, docker_ip_lookup, graph_id=scenario_id)
    write_json(scenario_topology_path(root, scenario_id), graph)
    print(f"Captured ground truth for deployed scenario {scenario_id!r}: {len(graph.nodes)} nodes")
    for edge in graph.edges:
        print(f"  {edge.source_node_id} -> {edge.target_node_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and inspect NETSCOPE-X network scenarios.")
    parser.add_argument("action", choices=["generate-all", "capture-ground-truth"])
    parser.add_argument("--scenario-id")
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    args = parser.parse_args()

    if args.action == "generate-all":
        generate_all(args.root)
    elif args.action == "capture-ground-truth":
        if not args.scenario_id:
            parser.error("--scenario-id is required for capture-ground-truth")
        capture_ground_truth(args.root, args.scenario_id)


if __name__ == "__main__":
    main()
