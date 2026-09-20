"""Observation-completeness sampling (spec Phase 68, FR-1.40's
"topology complexity x observation-completeness sweep"; RQ1: "100% -> 90%
-> 75% -> 50% -> 25%, per spec Phase 68").

No mechanism anywhere in this repository sub-samples packets to simulate
degraded observability -- this is genuinely new, minimal plumbing, not a
duplicate of anything. Applied at exactly one point: after synthetic
packet generation, before the pipeline runs -- the same place a real
capture's packet loss would occur, so every downstream stage (flow
reconstruction, topology, behavior, dependencies) sees a consistently
degraded view, not a patchwork of full and partial evidence.

Deterministic and seeded (`random.Random(seed)`, never the `random`
module's global state) -- REPRO-2's "rerunnable... equivalent results
given the same inputs and seed" applies here exactly as it does to
`simulator/scenarios/topologies.py`'s own `dynamic_service_network`.
"""

from __future__ import annotations

import random
from typing import List

from backend.app.models.packet import Packet


def sample_packets(packets: List[Packet], completeness: float, seed: int) -> List[Packet]:
    """Returns the subset of `packets` an observer capturing `completeness`
    (in `[0, 1]`) of all traffic would have seen, preserving original
    order. `completeness=1.0` returns `packets` unchanged (identity, not a
    reshuffled copy) -- the "full observability" baseline must be exactly
    the input, not merely statistically close to it. `completeness=0.0`
    returns `[]`. Each packet is included independently with probability
    `completeness`, seeded by `(seed, packet index)` so the same
    `(packets, seed)` pair always yields the same subset regardless of
    `completeness`'s value (a lower completeness's sample is always a
    subset of a higher one's, not an independently-redrawn set).
    """
    if not 0.0 <= completeness <= 1.0:
        raise ValueError(f"completeness must be in [0, 1], got {completeness}")
    if completeness == 1.0:
        return packets
    if completeness == 0.0:
        return []

    rng = random.Random(seed)
    draws = [rng.random() for _ in packets]
    return [packet for packet, draw in zip(packets, draws) if draw < completeness]
