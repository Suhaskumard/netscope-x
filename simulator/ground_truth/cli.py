"""Real ground-truth generation against the live lab (spec Phase 16).

Run (with the lab already up -- see simulator/docker/docker-compose.yml):
    python -m simulator.ground_truth.cli --capture-id lab-run-1 --root experiments_data
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml

from experiments.artifacts.io import write_ground_truth
from experiments.artifacts.paths import ground_truth_dir, ground_truth_topology_path
from simulator.ground_truth.generate import (
    build_expected_paths,
    build_roles,
    build_topology_graph,
    check_services_match_compose,
)

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker" / "docker-compose.yml"


def load_compose_service_names() -> set[str]:
    with COMPOSE_PATH.open("r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)
    return set(compose["services"].keys())


def docker_ip_lookup(service: str) -> str:
    """Finds the running container for a compose service via its compose
    label (not a guessed container-name convention, which is fragile across
    different invocation directories) and returns its real assigned IP."""
    ps = subprocess.run(
        ["docker", "ps", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    container_ids = ps.stdout.split()
    if not container_ids:
        raise RuntimeError(f"no running container found for compose service {service!r} -- is the lab up?")

    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
            container_ids[0],
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    ips = inspect.stdout.split()
    if not ips:
        raise RuntimeError(f"no IP address found for compose service {service!r} (container {container_ids[0]})")
    return ips[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ground truth from the live lab.")
    parser.add_argument("--capture-id", default="lab-ground-truth")
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    args = parser.parse_args()

    check_services_match_compose(load_compose_service_names())

    graph = build_topology_graph(docker_ip_lookup)
    roles = build_roles()
    paths = build_expected_paths(graph)

    gt_dir = ground_truth_dir(args.root, args.capture_id)
    topology_digest = write_ground_truth(ground_truth_topology_path(args.root, args.capture_id), graph)
    roles_digest = write_ground_truth(gt_dir / "roles.json", roles)
    paths_digest = write_ground_truth(gt_dir / "paths.json", paths)

    print(f"Ground truth written to {gt_dir}")
    print(f"  nodes: {len(graph.nodes)}  edges: {len(graph.edges)}")
    print(f"  topology.json sha256: {topology_digest}")
    print(f"  roles.json    sha256: {roles_digest}")
    print(f"  paths.json    sha256: {paths_digest}")
    for key, path in paths.paths.items():
        print(f"  expected path {key}: {' -> '.join(path) if path else '(no path found)'}")


if __name__ == "__main__":
    main()
