"""GET /topology. Backing implementation: spec Phase 32 (Probabilistic Topology Reconstruction).

Recomputes the topology graph fresh on every request -- normalizes
`raw.pcap`, reconstructs flows, then runs node/edge discovery -- and
persists the result via `write_json`. This is not a cache: the persisted
file is never read back by this route (there is nothing to serve stale),
it exists as a research artifact for `experiments/`-layer consumers. This
mirrors `GET /flows`'s own "recompute fresh, no cache" simplification
(`docs/architecture/flow_reconstruction.md`) one layer up -- `reconstruct_flows`
already writes `flows.jsonl`/`packets.jsonl` on every `/flows` call, so
this route's write-through is not a new pattern.

`graph_id` is the capture_id itself: a stable, non-timestamped,
non-content-hashed identity label (mirroring the ground-truth generator's
own constant `graph_id="lab-ground-truth"`), so re-running this route
against an unchanged capture always reports the same `graph_id` (NFR-3
determinism) regardless of `Settings` tuning or wall-clock time.
"""

from __future__ import annotations

from fastapi import Depends, APIRouter, Query

from backend.app.api.schemas import CAPTURE_ID_PATTERN
from backend.app.core.config import get_settings
from backend.app.tenancy.deps import TenantScope, get_tenant_scope
from backend.app.models import TopologyGraph
from backend.nettrace.capture.errors import CaptureNotFoundError
from backend.nettrace.capture.packets import ensure_packets
from backend.nettrace.reconstruct import reconstruct_flows
from backend.nettrace.topology.graph import build_topology_graph
from experiments.artifacts.io import write_json
from experiments.artifacts.paths import pcap_path, topology_path

router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=TopologyGraph)
def get_topology(
    capture_id: str = Query(
        ..., description="Capture session to reconstruct topology for.", pattern=CAPTURE_ID_PATTERN
    ),
    scope: TenantScope = Depends(get_tenant_scope),
) -> TopologyGraph:
    settings = get_settings()
    ensure_packets(scope.root, capture_id)
    reconstruct_flows(
        scope.root,
        capture_id,
        udp_session_idle_timeout_seconds=settings.udp_session_idle_timeout_seconds,
    )

    graph = build_topology_graph(
        scope.root,
        capture_id,
        graph_id=capture_id,
        edge_confidence_packet_scale=settings.edge_confidence_packet_scale,
        edge_confidence_signal_strength=settings.edge_confidence_signal_strength,
    )
    write_json(topology_path(scope.root, capture_id, graph.graph_id), graph)
    return graph
