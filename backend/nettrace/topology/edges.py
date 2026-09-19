"""Edge discovery and probabilistic edge confidence (spec Phase 30-31, FR-1.9/FR-1.10).

Infers communication relationships exclusively from a capture's already-
reconstructed flows -- never from `simulator.ground_truth`
(`scripts/check_ground_truth_boundary.py` statically forbids this module
from importing it, spec §4's ground-truth rule).

Source: `flows.jsonl`, not raw packets. `Flow` (Phase 23-28) already
carries `protocol`, `first_seen`/`last_seen`, and `features.packet_count`
-- exactly what an `Edge`'s `protocols`/`first_observed`/`last_observed`/
`evidence` need, and only flow-level aggregation provides them. This is a
deliberate asymmetry with `backend.nettrace.topology.discovery.discover_nodes`
(which reads packets directly): ICMP/OTHER traffic, excluded from flow
reconstruction by `reconstruct_flows`'s own documented scope, can produce
*nodes* but never *edges* here. See `docs/architecture/node_discovery.md`
(which already commits to this design) and `docs/architecture/edge_discovery.md`.

Node-id resolution: `discover_edges` takes the caller's own
`discover_nodes(...)` output as a parameter rather than re-deriving nodes
internally, keeping this a pure function of its inputs. A flow whose
`src_ip`/`dst_ip` doesn't resolve against the supplied `nodes` is treated
as caller-misuse and silently skipped -- never raised, consistent with
`discover_nodes`'s own "never raise on bad/missing input" philosophy. A
flow whose `src_ip == dst_ip` (self-referential) is skipped too: an `Edge`
cannot self-loop (`Edge._no_self_loop`), and self-communication isn't a
relationship between two nodes.

Edges are undirected: `source_node_id`/`target_node_id` are assigned by
sorted `node_id` (a deterministic tie-break), not a best-effort initiator
guess. When multiple flows between a pair disagree on who initiated (e.g.
separate UDP sessions, different ports), there is no single honest "true"
initiator to report at the edge level -- each flow's own `src_ip`/
`direction` still captures real per-flow initiation; it is just not
collapsed into one edge-level claim.

Confidence (spec Phase 31) is a multi-signal, evidence-backed heuristic --
still provisional and uncalibrated (real calibration against ground truth
is Phase 32/68's job, off-limits here per spec §4/REPRO-4), but no longer
single-signal. Six independent terms are combined via noisy-OR:

    confidence = 1 - (1 - p_volume) * prod(1 - s * i_signal)

`p_volume = 1 - exp(-total_packet_count / packet_scale)` is Phase 30's
original packet-volume term. Each `i_signal` is a boolean (or, for
bidirectionality, a bounded continuous value) indicating whether a bucket
exhibits that signal on ANY of its flows; `s` (`edge_confidence_signal_
strength`) is one shared evidence-strength constant applied uniformly to
every signal, since nothing today justifies weighting one signal above
another -- asserting relative importance without evidence would itself be
the "arbitrary" confidence FR-1.10 forbids. Every term lies in `[0, 1)`, so
the product is always `> 0` and confidence always `< 1` -- bounded by
construction, and monotonic by construction (a new positive signal can
only shrink the product, never grow it, so more evidence never lowers
confidence). A signal that is structurally inapplicable to a bucket (e.g.
`tcp_state`/`tls_version` are always `None` for a UDP-only bucket)
contributes indicator `0`, i.e. a multiplicative identity factor of `1` --
never a penalty for evidence a bucket cannot structurally produce. See
`docs/architecture/edge_discovery.md` for the full justification, worked
numeric examples, and why this differs from Phase 30's deliberate decision
NOT to add a second weighted term for `observation_count` (that signal is
redundant with packet volume; these five are independent of it and of
each other).
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.app.models.flow import Flow, TCPState
from backend.app.models.topology import Edge, Node
from experiments.artifacts.io import read_jsonl
from experiments.artifacts.paths import flows_path

_DEFAULT_PACKET_SCALE = 20.0  # mirrors Settings.edge_confidence_packet_scale's own default
_DEFAULT_SIGNAL_STRENGTH = 0.3  # mirrors Settings.edge_confidence_signal_strength's own default


def _bidirectionality(ratio: float) -> float:
    """Maps a flow's forward_byte_ratio (0..1) to a bounded, parameter-free
    "genuine two-way traffic" strength: 0 at pure one-way traffic (ratio in
    {0, 1}), peaking at 1 for perfectly balanced traffic (ratio == 0.5)."""
    return 2 * min(ratio, 1 - ratio)


def _signal_indicators(bucket_flows: List[Flow]) -> Dict[str, float]:
    """The five Phase-31 signal terms for one node-pair bucket, each in
    [0, 1), computed by "any flow in the bucket exhibits this" existence
    semantics (not a fraction) -- required for monotonicity, since a
    fraction would shrink as more (unrelated) flows join the same bucket."""
    return {
        "established": 1.0 if any(f.tcp_state == TCPState.ESTABLISHED for f in bucket_flows) else 0.0,
        "fingerprinted": 1.0 if any(f.fingerprinted_protocol is not None for f in bucket_flows) else 0.0,
        "tls": 1.0 if any(f.tls_version is not None for f in bucket_flows) else 0.0,
        "persistent": 1.0 if any(f.features.is_persistent for f in bucket_flows) else 0.0,
        "bidirectional": max(
            (_bidirectionality(f.features.forward_byte_ratio) for f in bucket_flows), default=0.0
        ),
    }


def _confidence(
    bucket_flows: List[Flow],
    edge_confidence_packet_scale: float,
    edge_confidence_signal_strength: float,
) -> float:
    total_packet_count = sum(f.features.packet_count for f in bucket_flows)
    p_volume = 1 - math.exp(-total_packet_count / edge_confidence_packet_scale)

    s = edge_confidence_signal_strength
    indicators = _signal_indicators(bucket_flows)

    survival = 1 - p_volume
    for value in indicators.values():
        survival *= 1 - s * value
    return 1 - survival


def _evidence_line(flow: Flow) -> str:
    parts = [
        f"flow {flow.flow_id}: {flow.protocol.value} "
        f"{flow.src_ip}:{flow.src_port}->{flow.dst_ip}:{flow.dst_port}, "
        f"{flow.features.packet_count} packets, {flow.features.byte_count} bytes"
    ]
    if flow.tcp_state is not None:
        parts.append(f"tcp_state={flow.tcp_state.value}")
    if flow.fingerprinted_protocol is not None:
        parts.append(f"fingerprinted_protocol={flow.fingerprinted_protocol}")
    if flow.tls_version is not None:
        parts.append(f"tls_version={flow.tls_version}")
    if flow.features.is_persistent:
        parts.append("is_persistent=True")
    parts.append(f"forward_byte_ratio={flow.features.forward_byte_ratio:.3f}")
    return ", ".join(parts)


def _evidence_summary_line(
    bucket_flows: List[Flow], confidence: float, edge_confidence_signal_strength: float
) -> str:
    indicators = _signal_indicators(bucket_flows)
    return (
        "confidence signals: "
        f"established_handshake={'yes' if indicators['established'] else 'no'}, "
        f"fingerprinted_protocol={'yes' if indicators['fingerprinted'] else 'no'}, "
        f"tls={'yes' if indicators['tls'] else 'no'}, "
        f"persistent={'yes' if indicators['persistent'] else 'no'}, "
        f"bidirectional_strength={indicators['bidirectional']:.3f} "
        f"(signal_strength={edge_confidence_signal_strength}) -> confidence={confidence:.3f}"
    )


def bucket_flows_by_node_pair(
    root: Path,
    capture_id: str,
    nodes: List[Node],
    as_of: Optional[datetime] = None,
) -> Dict[Tuple[str, str], List[Flow]]:
    """Reads `flows_path(root, capture_id)` and groups TCP/UDP flows by unordered node-pair (sorted
    `node_id` tuple) -- the exact same grouping `discover_edges` itself builds one `Edge` per pair
    from. Extracted as its own function in Phase 51 (`backend/dependency/strength.py`) so dependency-
    strength estimation can reuse the identical buckets `discover_edges` computes (e.g. for
    directionality's `forward_byte_ratio`) rather than re-deriving flow-to-node-pair grouping a
    second time. `discover_edges` itself calls this function unchanged -- pure refactor, no behavior
    change.

    Same conventions as `discover_edges`: a flow whose `src_ip`/`dst_ip` doesn't resolve against
    `nodes`, or is self-referential, is silently skipped; `as_of` (spec Phase 43) filters to
    `flow.first_seen <= as_of`; returns `{}` for a missing/empty `flows.jsonl`, never an error.
    """
    ip_to_node_id: Dict[str, str] = {
        str(ip): node.node_id for node in nodes for ip in node.ip_addresses
    }

    path = flows_path(root, capture_id)
    if not path.is_file():
        return {}
    flows: List[Flow] = read_jsonl(path, Flow)
    if as_of is not None:
        flows = [f for f in flows if f.first_seen <= as_of]

    buckets: Dict[Tuple[str, str], List[Flow]] = defaultdict(list)
    for flow in flows:
        src_node_id = ip_to_node_id.get(str(flow.src_ip))
        dst_node_id = ip_to_node_id.get(str(flow.dst_ip))
        if src_node_id is None or dst_node_id is None or src_node_id == dst_node_id:
            continue
        key = tuple(sorted((src_node_id, dst_node_id)))
        buckets[key].append(flow)
    return buckets


def discover_edges(
    root: Path,
    capture_id: str,
    nodes: List[Node],
    edge_confidence_packet_scale: float = _DEFAULT_PACKET_SCALE,
    edge_confidence_signal_strength: float = _DEFAULT_SIGNAL_STRENGTH,
    as_of: Optional[datetime] = None,
) -> List[Edge]:
    """Reads `flows_path(root, capture_id)` and aggregates flows sharing a
    node pair into one `Edge` each. `nodes` must be (an equivalent IP
    coverage of) `discover_nodes(root, capture_id)`'s own output for the
    same capture -- when `as_of` is given, `nodes` should be that same
    `as_of`'s `discover_nodes` output, so both stay evidence-consistent.
    Returns `[]` for a missing/empty `flows.jsonl`, or a capture with no
    TCP/UDP flows (e.g. ICMP-only) -- never an error.

    `as_of` (spec Phase 43, FR-1.20): when given, only flows with
    `first_seen <= as_of` are considered -- the same inclusion rule
    `discover_nodes` applies to packets, so an edge and its endpoints agree
    on what "existed as of `as_of`" means. Confidence/evidence are
    genuinely recomputed from this narrower flow set, not filtered
    after the fact -- fewer contributing flows can only lower or match
    confidence, never overstate it (Phase 31's noisy-OR formula is
    monotonic in evidence). `None` (default) reproduces the original,
    whole-capture behavior exactly.
    """
    buckets = bucket_flows_by_node_pair(root, capture_id, nodes, as_of=as_of)

    aggregated = []
    for (source_node_id, target_node_id), bucket_flows in buckets.items():
        ordered_flows = sorted(bucket_flows, key=lambda f: (f.first_seen, f.flow_id))
        confidence = _confidence(
            bucket_flows, edge_confidence_packet_scale, edge_confidence_signal_strength
        )
        evidence = [_evidence_line(f) for f in ordered_flows]
        evidence.append(_evidence_summary_line(bucket_flows, confidence, edge_confidence_signal_strength))

        aggregated.append(
            {
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "confidence": confidence,
                "evidence": evidence,
                "observation_count": len(bucket_flows),
                "first_observed": min(f.first_seen for f in bucket_flows),
                "last_observed": max(f.last_seen for f in bucket_flows),
                "protocols": sorted({f.protocol.value for f in bucket_flows}),
            }
        )

    ordered = sorted(
        aggregated,
        key=lambda a: (a["first_observed"], a["source_node_id"], a["target_node_id"]),
    )

    return [
        Edge(edge_id=f"{capture_id}:edge:{index}", **fields)
        for index, fields in enumerate(ordered)
    ]
