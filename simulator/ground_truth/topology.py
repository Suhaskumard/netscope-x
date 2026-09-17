"""Declarative ground-truth description of the lab's intended architecture
(spec Phase 16).

This is knowledge only the ground-truth generator is allowed to have (spec
§4, restated in docs/research/problem_definition.md §2/§6) -- it must never
be imported by any future inference code (Phase 21+, which lives entirely
under backend/ and nettrace/, not simulator/). Cross-checked against
simulator/docker/docker-compose.yml's actual service list at generation
time by generate.py's `check_services_match_compose`, so an added/removed
lab service causes a loud mismatch, not silent staleness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from backend.app.models import ServiceRole

# external-service correctly maps to UNKNOWN: it is a stand-in for a
# third-party dependency, not one of the defined internal roles.
SERVICE_ROLES: Dict[str, ServiceRole] = {
    "client": ServiceRole.CLIENT,
    "gateway": ServiceRole.GATEWAY,
    "load-balancer": ServiceRole.LOAD_BALANCER,
    "load-balancer-2": ServiceRole.LOAD_BALANCER,
    "api-1": ServiceRole.API,
    "api-2": ServiceRole.API,
    "redis": ServiceRole.CACHE,
    "database": ServiceRole.DATABASE,
    "worker": ServiceRole.WORKER,
    "dns": ServiceRole.DNS,
    "external-service": ServiceRole.UNKNOWN,
}


@dataclass(frozen=True)
class DeclaredEdge:
    source: str
    target: str
    protocols: List[str]


# Protocols reflect what Phase 13's routing and Phase 15's protocol generator
# actually exercised against these exact edges, not guessed labels.
DECLARED_EDGES: List[DeclaredEdge] = [
    DeclaredEdge("client", "gateway", ["HTTP", "TCP"]),
    DeclaredEdge("client", "dns", ["DNS"]),
    DeclaredEdge("gateway", "load-balancer", ["HTTP", "TCP"]),
    DeclaredEdge("gateway", "load-balancer-2", ["HTTP", "TCP"]),
    DeclaredEdge("load-balancer", "api-1", ["HTTP", "TCP"]),
    DeclaredEdge("load-balancer", "api-2", ["HTTP", "TCP"]),
    DeclaredEdge("load-balancer-2", "api-1", ["HTTP", "TCP"]),
    DeclaredEdge("load-balancer-2", "api-2", ["HTTP", "TCP"]),
    DeclaredEdge("api-1", "redis", ["REDIS"]),
    DeclaredEdge("api-1", "database", ["POSTGRES"]),
    DeclaredEdge("api-1", "external-service", ["HTTP", "TLS"]),
    DeclaredEdge("api-2", "redis", ["REDIS"]),
    DeclaredEdge("api-2", "database", ["POSTGRES"]),
    DeclaredEdge("api-2", "external-service", ["HTTP", "TLS"]),
    DeclaredEdge("worker", "redis", ["REDIS"]),
    DeclaredEdge("worker", "database", ["POSTGRES"]),
]

# Representative source/target pairs to compute expected shortest paths for.
EXPECTED_PATH_PAIRS: List[Tuple[str, str]] = [
    ("client", "redis"),
    ("client", "database"),
    ("client", "external-service"),
]
