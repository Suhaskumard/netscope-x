"""Parametric generators for the 6 controlled network architectures required by spec Phase 18
("Generate multiple controlled network architectures. Examples: simple chain, star, multi-tier,
redundant, multi-path, dynamic service network").

Each function is pure and deterministic given its parameters (a `seed` for the one archetype
that's randomized) and returns `(roles, edges)` -- the same two-piece shape
`simulator/ground_truth/topology.py` hand-declares once for the fixed Phase 11 lab, generalized
here into something generated on demand for many different shapes. `simulator/tests/test_scenarios.py`
verifies each archetype's defining structural claim with real NetworkX computation (degree counts,
node connectivity, bridge-freeness, ...), not just by construction.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List

from backend.app.models import ServiceRole


@dataclass(frozen=True)
class ScenarioEdge:
    source: str
    target: str
    protocols: List[str]


def _http_edge(source: str, target: str) -> ScenarioEdge:
    # Every generated scenario is deployed (when it is deployed at all) using the generic
    # HTTP-over-TCP node image (simulator/scenarios/generic_node/), so this is what the edge's
    # protocols actually are, not a guessed label.
    return ScenarioEdge(source, target, ["HTTP", "TCP"])


def simple_chain(n: int) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """client -> api-1 -> api-2 -> ... -> database, a straight line of `n` nodes."""
    if n < 2:
        raise ValueError("simple_chain requires at least 2 nodes")
    names = [f"node-{i}" for i in range(1, n + 1)]
    roles: Dict[str, ServiceRole] = {names[0]: ServiceRole.CLIENT, names[-1]: ServiceRole.DATABASE}
    for name in names[1:-1]:
        roles[name] = ServiceRole.API
    edges = [_http_edge(names[i], names[i + 1]) for i in range(len(names) - 1)]
    return roles, edges


def star(n: int) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """One hub connected to `n` leaves, each leaf connected only to the hub."""
    if n < 2:
        raise ValueError("star requires at least 2 leaves")
    hub = "hub"
    leaves = [f"leaf-{i}" for i in range(1, n + 1)]
    roles: Dict[str, ServiceRole] = {hub: ServiceRole.GATEWAY}
    for leaf in leaves:
        roles[leaf] = ServiceRole.API
    edges = [_http_edge(hub, leaf) for leaf in leaves]
    return roles, edges


def multi_tier(tier_sizes: List[int]) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """Layered architecture: every node in tier i connects to every node in tier i+1
    (generalizes the real lab's client -> gateway -> load-balancer -> api -> data shape)."""
    if len(tier_sizes) < 2:
        raise ValueError("multi_tier requires at least 2 tiers")
    if any(size < 1 for size in tier_sizes):
        raise ValueError("every tier must have at least 1 node")

    tiers: List[List[str]] = []
    roles: Dict[str, ServiceRole] = {}
    for t, size in enumerate(tier_sizes):
        if t == 0:
            role = ServiceRole.CLIENT
        elif t == len(tier_sizes) - 1:
            role = ServiceRole.DATABASE
        else:
            role = ServiceRole.API
        names = [f"tier{t}-{i}" for i in range(1, size + 1)]
        for name in names:
            roles[name] = role
        tiers.append(names)

    edges: List[ScenarioEdge] = []
    for t in range(len(tiers) - 1):
        for source in tiers[t]:
            for target in tiers[t + 1]:
                edges.append(_http_edge(source, target))
    return roles, edges


def redundant(n: int) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """A chain with one extra skip-connection reintroducing a cycle, so the edges around the
    skip are never bridges (generalizes Phase 13's dual-load-balancer routing lab)."""
    if n < 3:
        raise ValueError("redundant requires at least 3 nodes")
    roles, edges = simple_chain(n)
    # Skip-connection from the first to the third node -- creates an alternate route around
    # node-2 without touching the rest of the chain's shape.
    edges.append(_http_edge("node-1", "node-3"))
    return roles, edges


def multi_path(k: int) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """A source and sink connected by `k` vertex-disjoint intermediate paths."""
    if k < 2:
        raise ValueError("multi_path requires at least 2 parallel paths")
    source, sink = "source", "sink"
    mids = [f"mid-{i}" for i in range(1, k + 1)]
    roles: Dict[str, ServiceRole] = {source: ServiceRole.CLIENT, sink: ServiceRole.DATABASE}
    for mid in mids:
        roles[mid] = ServiceRole.API
    edges: List[ScenarioEdge] = []
    for mid in mids:
        edges.append(_http_edge(source, mid))
        edges.append(_http_edge(mid, sink))
    return roles, edges


_DYNAMIC_ROLE_CHOICES = [ServiceRole.API, ServiceRole.CACHE, ServiceRole.DATABASE, ServiceRole.WORKER]


def dynamic_service_network(seed: int, n: int) -> tuple[Dict[str, ServiceRole], List[ScenarioEdge]]:
    """A seeded, reproducible random graph over `n` services -- stands in for a network whose
    service set and edges aren't a fixed hand-authored shape. Connectivity is guaranteed by
    building a random spanning structure first, then adding extra random edges on top."""
    if n < 3:
        raise ValueError("dynamic_service_network requires at least 3 nodes")
    rng = random.Random(seed)
    names = [f"svc-{i}" for i in range(1, n + 1)]

    roles: Dict[str, ServiceRole] = {names[0]: ServiceRole.CLIENT}
    for name in names[1:]:
        roles[name] = rng.choice(_DYNAMIC_ROLE_CHOICES)

    # Random spanning tree over the other n-1 nodes, rooted implicitly at names[0]: every
    # non-root node gets exactly one edge from an earlier, already-connected node, guaranteeing
    # the whole graph is connected regardless of what extra edges get added below.
    edges: List[ScenarioEdge] = []
    connected = [names[0]]
    for name in names[1:]:
        parent = rng.choice(connected)
        edges.append(_http_edge(parent, name))
        connected.append(name)

    # A handful of extra random edges on top, for realistic cross-links.
    extra_edge_count = max(0, n - 2)
    existing = {(e.source, e.target) for e in edges}
    attempts = 0
    added = 0
    while added < extra_edge_count and attempts < extra_edge_count * 10:
        attempts += 1
        a, b = rng.sample(names, 2)
        if (a, b) in existing or (b, a) in existing:
            continue
        edges.append(_http_edge(a, b))
        existing.add((a, b))
        added += 1

    return roles, edges
