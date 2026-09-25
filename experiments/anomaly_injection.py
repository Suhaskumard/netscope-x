"""Minimal synthetic anomaly-injection dataset (spec addendum Phase 76).

`experiments/metrics/anomaly_evaluation.py` (Phase 42) scores real `Anomaly` output against labeled
ground truth, but explicitly left the labeled dataset itself unbuilt. This is the smallest
honestly-scoped generator that makes `MetricContext.ANOMALY_DETECTION` scorable in the Phase 68 matrix
(RQ3: "injected known anomalies whose onset time and type are recorded as ground truth").

Timeline: fixed-length epochs of `EPOCH_SECONDS`. The first `BASELINE_EPOCHS` (>= 5, the Phase 38
`build_node_baseline` cold-start minimum) are normal traffic, giving every node a per-epoch behavioral
history. The next `TEST_EPOCHS` are scored: two carry one injected anomaly each, the rest stay clean so
false positives are measurable.

Normal traffic is the matrix's own `generate_packets_for_scenario` (same declared topology, ports and
protocols), re-seeded per epoch with a small per-epoch volume jitter so baselines have a real, non-zero
spread -- with identical epochs the MAD is 0 and any deviation would be an infinite z-score.

Two injected patterns, each a real packet-level change to the capture (nothing is annotated after the fact):
  - `volume_spike`: one node's existing outgoing edges carry `SPIKE_FACTOR`x their normal packets.
  - `new_destination_burst`: one node contacts up to `BURST_PEERS` nodes it has no edge with.
A pattern that cannot be built on a topology (e.g. no non-neighbour exists) is reported in `skipped`,
never faked.

Labels are derived by construction from the injected packets, never from what the detector fires:
`volume_spike` genuinely changes `TRAFFIC_VOLUME` on the actor and on every node receiving the spike;
`new_destination_burst` genuinely changes `DESTINATIONS` on the actor (that feature counts a node's own
outbound destinations, so the new peers' feature does not change). Side effects the detector may also
flag (e.g. the burst's extra bytes) are deliberately NOT labeled, so they score as false positives.
`onset_at` is the timestamp of the first injected packet.

Never imports detector code or `simulator.ground_truth`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.anomaly import AnomalyDimension
from backend.app.models.behavior import ServiceRole
from backend.app.models.packet import Packet
from experiments.synthetic_traffic import BASE_TIME, generate_packets_for_scenario
from simulator.scenarios.topologies import ScenarioEdge

EPOCH_SECONDS = 60.0
BASELINE_EPOCHS = 8
TEST_EPOCHS = 4
SPIKE_FACTOR = 5
BURST_PEERS = 3
VOLUME_JITTER = 2  # per-epoch packets_per_edge jitter, +/- this many pairs

VOLUME_SPIKE = "volume_spike"
NEW_DESTINATION_BURST = "new_destination_burst"
# Test-epoch offsets (from the first test epoch): 0 and 3 stay clean.
_PATTERN_TEST_EPOCH = {VOLUME_SPIKE: 1, NEW_DESTINATION_BURST: 2}


@dataclass(frozen=True)
class InjectedAnomaly:
    pattern: str
    actor: str
    epoch: int
    onset_at: datetime
    labels: Tuple[Tuple[str, AnomalyDimension], ...]  # (node name, dimension) genuinely changed
    detail: str


@dataclass
class AnomalyDataset:
    packets: List[Packet]
    injected: List[InjectedAnomaly]
    skipped: List[str] = field(default_factory=list)
    epoch_seconds: float = EPOCH_SECONDS
    baseline_epochs: int = BASELINE_EPOCHS
    test_epochs: int = TEST_EPOCHS

    @property
    def total_epochs(self) -> int:
        return self.baseline_epochs + self.test_epochs

    def epoch_start(self, epoch: int) -> datetime:
        return BASE_TIME + timedelta(seconds=epoch * self.epoch_seconds)

    def epoch_end(self, epoch: int) -> datetime:
        return self.epoch_start(epoch + 1)


def _shift(packets: Sequence[Packet], epoch: int, capture_id: str, tag: str, epoch_seconds: float) -> List[Packet]:
    offset = timedelta(seconds=epoch * epoch_seconds)
    return [
        p.model_copy(update={"timestamp": p.timestamp + offset, "packet_id": f"{capture_id}:{tag}{epoch}:p{i}"})
        for i, p in enumerate(packets)
    ]


def _neighbours(edges: Sequence[ScenarioEdge]) -> Dict[str, set]:
    result: Dict[str, set] = {}
    for e in edges:
        result.setdefault(e.source, set()).add(e.target)
        result.setdefault(e.target, set()).add(e.source)
    return result


def generate_anomaly_dataset(
    roles: Dict[str, ServiceRole],
    edges: List[ScenarioEdge],
    ip_by_name: Dict[str, str],
    capture_id: str,
    seed: int,
    packets_per_edge: int = 15,
) -> AnomalyDataset:
    """Builds the epoch timeline described in the module docstring, deterministic per `seed`."""
    rng = random.Random(seed * 7919 + 76)
    packets: List[Packet] = []

    for epoch in range(BASELINE_EPOCHS + TEST_EPOCHS):
        ppe = max(1, packets_per_edge + rng.randint(-VOLUME_JITTER, VOLUME_JITTER))
        normal = generate_packets_for_scenario(
            roles, edges, ip_by_name, capture_id, seed=seed * 1009 + epoch, packets_per_edge=ppe
        )
        packets.extend(_shift(normal, epoch, capture_id, "n", EPOCH_SECONDS))

    dataset = AnomalyDataset(packets=packets, injected=[])
    names = sorted(roles)
    neighbours = _neighbours(edges)
    first_test_epoch = BASELINE_EPOCHS

    def inject(pattern: str, actor: str, extra_edges: List[ScenarioEdge], per_edge: int, labels, detail: str) -> None:
        epoch = first_test_epoch + _PATTERN_TEST_EPOCH[pattern]
        extra = generate_packets_for_scenario(
            roles, extra_edges, ip_by_name, capture_id, seed=seed * 2003 + epoch, packets_per_edge=per_edge
        )
        shifted = _shift(extra, epoch, capture_id, "x", EPOCH_SECONDS)
        dataset.packets.extend(shifted)
        dataset.injected.append(
            InjectedAnomaly(
                pattern=pattern,
                actor=actor,
                epoch=epoch,
                onset_at=min(p.timestamp for p in shifted),
                labels=tuple(labels),
                detail=detail,
            )
        )

    # --- volume spike: an actor with outgoing edges sends SPIKE_FACTOR x its normal volume ---
    spike_actors = sorted({e.source for e in edges})
    spike_actor: Optional[str] = rng.choice(spike_actors) if spike_actors else None
    if spike_actor is None:
        dataset.skipped.append(f"{VOLUME_SPIKE}: topology has no outgoing edge")
    else:
        out_edges = [e for e in edges if e.source == spike_actor]
        touched = [spike_actor] + sorted({e.target for e in out_edges})
        inject(
            VOLUME_SPIKE,
            spike_actor,
            out_edges,
            (SPIKE_FACTOR - 1) * packets_per_edge,
            [(n, AnomalyDimension.TRAFFIC_VOLUME) for n in touched],
            f"{spike_actor} sends {SPIKE_FACTOR}x normal volume on {len(out_edges)} existing edge(s)",
        )

    # --- new-destination burst: an actor contacts nodes it has no edge with ---
    burst_options = {n: sorted(set(names) - neighbours.get(n, set()) - {n}) for n in names}
    burst_candidates = [n for n in names if burst_options[n]]
    if not burst_candidates:
        dataset.skipped.append(f"{NEW_DESTINATION_BURST}: every node pair already has an edge")
    else:
        preferred = [n for n in burst_candidates if n != spike_actor] or burst_candidates
        burst_actor = rng.choice(preferred)
        peers = rng.sample(burst_options[burst_actor], min(BURST_PEERS, len(burst_options[burst_actor])))
        peers.sort()
        new_edges = [ScenarioEdge(source=burst_actor, target=p, protocols=["tcp"]) for p in peers]
        inject(
            NEW_DESTINATION_BURST,
            burst_actor,
            new_edges,
            packets_per_edge,
            [(burst_actor, AnomalyDimension.DESTINATIONS)],
            f"{burst_actor} contacts {len(peers)} new destination(s): {', '.join(peers)}",
        )

    dataset.packets.sort(key=lambda p: p.timestamp)
    return dataset
