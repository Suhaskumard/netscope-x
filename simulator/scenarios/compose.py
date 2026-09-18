"""Generates a real, deployable docker-compose.yml for a scenario (spec Phase 18).

Follows the same convention every service in simulator/docker/docker-compose.yml already uses
(an off-the-shelf image with a mounted script, no bespoke Dockerfile) -- one service per node, all
running the same generic_node/app.py, each told its outgoing dependencies via an env var built
from the scenario's edges. This is what makes a generated scenario genuinely deployable, not just
a declared graph on paper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from simulator.scenarios.topologies import ScenarioEdge

GENERIC_NODE_APP = (Path(__file__).resolve().parent / "generic_node" / "app.py").resolve()


def generate_compose(scenario_id: str, roles: Dict[str, Any], edges: List[ScenarioEdge]) -> Dict[str, Any]:
    """Builds a docker-compose.yml-shaped dict (dumped to YAML by the caller). Absolute host
    paths are used for the app.py mount -- this generated compose file is only meant to be run
    on the machine that generated it, same as every other artifact under experiments_data/."""
    network_name = f"netscope-scenario-{scenario_id}"
    upstreams: Dict[str, List[str]] = {node: [] for node in roles}
    for edge in edges:
        upstreams[edge.source].append(edge.target)

    services: Dict[str, Any] = {}
    for node, role in roles.items():
        role_value = role.value if hasattr(role, "value") else str(role)
        services[node] = {
            "image": "python:3.12-alpine",
            "working_dir": "/app",
            "volumes": [f"{GENERIC_NODE_APP.as_posix()}:/app/app.py:ro"],
            "environment": {
                "NODE_ROLE": role_value,
                "UPSTREAM_HOSTS": ",".join(upstreams[node]),
            },
            "command": "python app.py",
            "networks": [network_name],
        }

    return {
        "services": services,
        "networks": {network_name: {"name": network_name}},
    }
